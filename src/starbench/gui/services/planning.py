"""Experiment application service: request to validated launch plans."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from ...adapters import DEFAULT_DOCKER_IMAGES
from ...contracts import ContractValidationError, validate_payload
from ...runner.task_loader import discover_tasks
from .. import providers as providers_module, skills as skills_module
from ..agents import DEFAULT_RUNTIMES_DIR, get_custom_agent
from ..data import SAFE_ID
from ..launcher import LaunchError, build_run_argv
from ..skills import DEFAULT_SKILLS_DIR, SkillError
from .errors import ExperimentError
from .planning_inputs import (
    DOCKER_CAPABLE_AGENTS, INSTRUCTION_MODES, RIGOR_MODES, _BUILTIN_INFO,
    _credential_source_names,
    _instruction_execution_estimate, _judge_sensitive_vars, _resolve_contender_reference,
    _resolve_judge_reference, _slug, _validated_thinking_effort,
)
from .profile_snapshots import (
    _assemble_profile_snapshot, _roster_deviates, _shared_deviations,
    _snapshot_contender_spec, _task_set_deviates,
)
from .profiles import load_profiles
from .records import _experiment_path

def plan_experiment(
    payload: Dict[str, Any],
    *,
    runs_dir: Path,
    runtimes_dir: Path = DEFAULT_RUNTIMES_DIR,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
) -> Dict[str, Any]:
    """Validate an experiment request and build one launch plan per contender."""
    name = str(payload.get("name") or "").strip()
    if not SAFE_ID.match(name):
        raise ExperimentError(
            "Experiment name is required (letters, digits, dot, dash, underscore)."
        )
    if _experiment_path(runs_dir, name).exists():
        raise ExperimentError(f"An experiment named {name} already exists.")

    shared = payload.get("shared")
    if not isinstance(shared, dict):
        raise ExperimentError("`shared` configuration object is required.")
    contenders = payload.get("contenders")
    if not isinstance(contenders, list) or not contenders:
        raise ExperimentError("At least one contender runtime is required.")
    if len(contenders) > 12:
        raise ExperimentError("At most 12 contenders per experiment.")

    tasks_dir_value = payload.get("tasks_dir")
    task_selectors = payload.get("tasks")
    if not isinstance(tasks_dir_value, str) or not tasks_dir_value:
        raise ExperimentError("invalid_task: a task folder is required.")
    if not isinstance(task_selectors, list) or not all(
        isinstance(item, str) for item in task_selectors
    ):
        raise ExperimentError("invalid_task: tasks must be a list of task ids.")
    try:
        selected_tasks = discover_tasks(Path(tasks_dir_value), task_selectors)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        raise ExperimentError(f"invalid_task: {error}") from error

    # Executor skills are shared across contenders (a controlled comparison, like
    # the shared judge). Validate the selection now — an unknown skill or group
    # is a plan-time error — and keep the group-expanded id list for the summary.
    executor_skill_ids = shared.get("executor_skills")
    executor_skill_group_ids = shared.get("executor_skill_groups")
    try:
        expanded_skill_ids = skills_module.validate_selection(
            skills_dir, executor_skill_ids, executor_skill_group_ids
        )
    except SkillError as error:
        raise ExperimentError(str(error))

    # Instruction ablation is shared across contenders (a controlled comparison,
    # like the shared judge and skills). Resolve the selected tasks' public expert
    # steps once so we can validate the step choice and estimate how many executor
    # variants each contender expands into. Only public step ids are read here —
    # never the private `reasoning`.
    instruction_mode = str(shared.get("instruction_mode") or "none").strip() or "none"
    if instruction_mode not in INSTRUCTION_MODES:
        raise ExperimentError(
            f"Instruction mode must be one of {', '.join(INSTRUCTION_MODES)}."
        )
    instruction_steps = [
        str(step).strip()
        for step in (shared.get("instruction_steps") or [])
        if isinstance(step, str) and str(step).strip()
    ]
    resolved_steps = [
        (task.id, [step.step_id for step in task.human_reference_steps])
        for task in selected_tasks
    ]
    if instruction_mode in ("traverse", "ablation"):
        # The runner rejects the WHOLE run when any selected task lacks expert
        # steps in these modes (verified semantics, not a baseline fallback).
        # Launching a plan that is known to die is a false green light.
        stepless_tasks = [task_id for task_id, step_ids in resolved_steps if not step_ids]
        if stepless_tasks:
            raise ExperimentError(
                f"{instruction_mode.capitalize()} mode needs expert steps in every "
                f"selected task; the runner rejects the whole run otherwise. "
                f"Without steps: {', '.join(stepless_tasks)}. Deselect them or pick "
                "tasks that ship a human reference."
            )
    if instruction_mode == "select":
        if not instruction_steps:
            raise ExperimentError(
                "Selected-steps mode needs at least one expert step chosen."
            )
        known_step_ids = {
            step_id for _, step_ids in resolved_steps for step_id in step_ids
        }
        # Plan-time guard catches the gross error (a step that no selected task
        # ships). The runner enforces the stricter rule — every chosen step must
        # exist in EVERY selected task, or it rejects the run naming the task.
        unknown_steps = [step for step in instruction_steps if step not in known_step_ids]
        if unknown_steps:
            raise ExperimentError(
                "These expert steps exist in none of the selected tasks: "
                f"{', '.join(unknown_steps)}. Pick steps at least one selected task ships."
            )

    # Rigor injection is shared across contenders too (a controlled comparison,
    # like the shared judge, skills and instructions). It restates selected
    # rubric-level requirements as hard requirements in the prompt; it does NOT
    # expand executor variants (the runner injects them into whatever variant the
    # instruction mode produces), so the execution estimate is unaffected. All
    # rigor content is public.
    rigor_mode = str(shared.get("rigor_mode") or "none").strip() or "none"
    if rigor_mode not in RIGOR_MODES:
        raise ExperimentError(f"Rigor mode must be one of {', '.join(RIGOR_MODES)}.")
    rigor_ids = [
        str(rigor).strip()
        for rigor in (shared.get("rigors") or [])
        if isinstance(rigor, str) and str(rigor).strip()
    ]
    if rigor_mode == "select":
        if not rigor_ids:
            raise ExperimentError("Rigor mode select needs at least one rigor requirement chosen.")
        resolved_rigors = [
            (task.id, [rigor.id for rigor in task.rigors]) for task in selected_tasks
        ]
        known_rigor_ids = {
            rigor_id for _, rigor_id_list in resolved_rigors for rigor_id in rigor_id_list
        }
        # Plan-time guard catches the gross error (a rigor that no selected task
        # ships). The runner enforces the stricter rule — every chosen rigor must
        # exist in EVERY selected task, or it rejects the run naming the task.
        unknown_rigors = [rigor for rigor in rigor_ids if rigor not in known_rigor_ids]
        if unknown_rigors:
            raise ExperimentError(
                "These rigor requirements exist in none of the selected tasks: "
                f"{', '.join(unknown_rigors)}. Pick rigors at least one selected task ships."
            )
    else:
        rigor_ids = []

    # Resolve provider references (the reference shape) into the explicit fields
    # the rest of this function consumes. Providers live in <runs-dir>/providers.
    provider_by_id = {
        provider["id"]: provider
        for provider in providers_module.load_providers(runs_dir)["providers"]
    }

    # Test-profile launch link (snapshot-on-use): a payload naming a profile
    # with a non-empty roster gets one measurement-contract snapshot per
    # contender, handed to the runner via --profile-snapshot. The PAYLOAD is
    # the effective configuration (the wizard may have edited it after loading
    # the profile); the profile is the comparison baseline, and any deviation
    # is diffed here in the backend and annotated in the snapshot. No profile,
    # or a profile without a roster, launches bare — legal, just not a
    # coverage-matrix column filler.
    profile_id = str(payload.get("profile_id") or "")
    snapshot_profile: Optional[Dict[str, Any]] = None
    if profile_id:
        profile_by_id = {
            str(profile.get("id")): profile
            for profile in load_profiles(runs_dir)["profiles"]
            if isinstance(profile, dict)
        }
        launch_profile = profile_by_id.get(profile_id)
        if launch_profile is None:
            raise ExperimentError(f"Profile {profile_id!r} does not exist in profiles.json.")
        profile_roster = launch_profile.get("roster")
        if isinstance(profile_roster, list) and profile_roster:
            snapshot_profile = launch_profile

    backend = str(shared.get("executor_backend") or "local")
    evaluator_agent = str(shared.get("evaluator_agent") or "codex")
    shared = _resolve_judge_reference(shared, evaluator_agent, provider_by_id, runtimes_dir)
    evaluator_gateway = (
        shared.get("evaluator_gateway")
        if isinstance(shared.get("evaluator_gateway"), dict)
        else None
    )
    judge_env = (
        shared.get("judge_env") if isinstance(shared.get("judge_env"), dict) else {}
    )
    if evaluator_agent.startswith("custom:"):
        judge_meta = get_custom_agent(runtimes_dir, evaluator_agent.split(":", 1)[1])
        if judge_meta is None:
            raise ExperimentError(
                f"Judge runtime {evaluator_agent} is not a valid custom runtime "
                f"in {runtimes_dir}."
            )
    judge_sensitive = _judge_sensitive_vars(evaluator_agent, runtimes_dir)

    # Ad-hoc deviation record: diff the payload's effective configuration
    # against the profile baseline (computed HERE, never trusted from the
    # client). One list serves every contender — the deviating dimensions are
    # shared configuration, so each contender's snapshot carries the same
    # annotation. Dimension markers first, then the deviating shared keys.
    snapshot_modified_fields: List[str] = []
    snapshot_roster: List[Dict[str, Any]] = []
    if snapshot_profile is not None:
        if _roster_deviates(contenders, snapshot_profile.get("roster") or []):
            snapshot_modified_fields.append("roster")
        if _task_set_deviates(
            payload,
            snapshot_profile.get("task_set"),
            [task_id for task_id, _ in resolved_steps],
        ):
            snapshot_modified_fields.append("task_set")
        snapshot_modified_fields += _shared_deviations(
            shared, snapshot_profile.get("shared") or {}
        )
        # The roster the snapshots record is the one that actually launched
        # (the payload's contenders in their reference shape), resolved to
        # inline provider values like every other snapshot entry.
        for index, entry in enumerate(contenders):
            if not isinstance(entry, dict):
                continue  # the per-contender loop below rejects this payload
            entry_label = str(entry.get("label") or "") or (
                f"{entry.get('agent') or ''}-{entry.get('model') or index + 1}"
            )
            snapshot_roster.append(
                _snapshot_contender_spec(
                    {
                        "agent": entry.get("agent"),
                        "model": entry.get("model"),
                        "label": entry.get("label"),
                        "thinking_effort": entry.get("thinking_effort"),
                        "provider_id": entry.get("provider_id"),
                    },
                    provider_by_id,
                    context=f"Contender {entry_label}",
                )
            )
    plans: List[Dict[str, Any]] = []
    used_run_ids = set()
    for index, contender in enumerate(contenders):
        if not isinstance(contender, dict):
            raise ExperimentError("Each contender must be an object.")
        # The reference-shaped original: the snapshot needs its provider_id,
        # which _resolve_contender_reference drops from the resolved shape.
        requested_contender = contender
        agent = str(contender.get("agent") or "")
        custom_meta = None
        if agent.startswith("custom:"):
            custom_meta = get_custom_agent(runtimes_dir, agent.split(":", 1)[1])
            if custom_meta is None:
                raise ExperimentError(
                    f"Contender runtime {agent} is not a valid custom runtime "
                    f"in {runtimes_dir}."
                )
        contender = _resolve_contender_reference(
            contender, provider_by_id, custom_meta, _BUILTIN_INFO.get(agent)
        )
        label = str(contender.get("label") or "") or f"{agent}-{contender.get('model') or index + 1}"
        slug = _slug(label)
        run_id = f"{name}__{slug}"
        suffix = 2
        while run_id in used_run_ids:
            run_id = f"{name}__{slug}-{suffix}"
            suffix += 1
        used_run_ids.add(run_id)

        docker_capable = (
            agent in DOCKER_CAPABLE_AGENTS
            if custom_meta is None
            else bool(custom_meta.get("docker_capable"))
        )
        effective_backend = backend if docker_capable else "local"

        # Executor and Judge own independent OpenCode gateway configurations.
        gateway = {
            "opencode_provider": contender.get("opencode_provider"),
            "opencode_base_url": contender.get("opencode_base_url"),
            "opencode_api_key_env": contender.get("opencode_api_key_env"),
        }
        evaluator_gateway = evaluator_gateway or {}

        launch_payload = {
            "run_id": run_id,
            "tasks_dir": payload.get("tasks_dir"),
            "tasks": payload.get("tasks") or [],
            "runtimes_dir": str(runtimes_dir),
            "executor_agent": agent,
            "executor_model": str(contender.get("model") or "").strip(),
            "executor_backend": effective_backend,
            # Each runtime gets its own image; custom runtimes carry theirs
            # in the spec, so no --docker-image is passed for them.
            "docker_image": (
                DEFAULT_DOCKER_IMAGES.get(agent, "") if effective_backend == "docker" else ""
            ),
            "auth_mode": str(contender.get("auth_mode") or "env"),
            "thinking_effort": _validated_thinking_effort(agent, contender, label),
            "web_search": str(shared.get("web_search_mode") or "task"),
            "claude_max_turns": shared.get("claude_max_turns"),
            "evaluator_agent": str(shared.get("evaluator_agent") or "codex"),
            "evaluator_model": str(shared.get("evaluator_model") or "").strip(),
            "evaluator_auth_mode": str(shared.get("evaluator_auth_mode") or "") or None,
            "judge_mode": str(shared.get("judge_mode") or "single"),
            "evaluator_timeout_seconds": shared.get("evaluator_timeout_seconds"),
            "max_evaluator_parallel": shared.get("max_evaluator_parallel"),
            "seed": shared.get("seed"),
            "batch_size": shared.get("batch_size"),
            "repeat": shared.get("repeat"),
            "executor_bin": contender.get("codex_bin"),
            "evaluator_bin": shared.get("evaluator_bin"),
            "executor_opencode_provider": gateway.get("opencode_provider"),
            "executor_opencode_base_url": gateway.get("opencode_base_url"),
            "executor_opencode_api_key_env": gateway.get("opencode_api_key_env"),
            "evaluator_opencode_provider": evaluator_gateway.get("opencode_provider"),
            "evaluator_opencode_base_url": evaluator_gateway.get("opencode_base_url"),
            "evaluator_opencode_api_key_env": evaluator_gateway.get("opencode_api_key_env"),
            "extra_args": str(shared.get("extra_args") or ""),
            # Shared instruction ablation: same mode/steps for every contender.
            "instruction_mode": instruction_mode,
            "instruction_steps": instruction_steps,
            # Shared rigor injection: same mode/ids for every contender.
            "rigor_mode": rigor_mode,
            "rigors": rigor_ids,
            # Shared executor skills: forward ids and groups as-is (the runner
            # expands groups) plus the library root the console validated against.
            "executor_skills": executor_skill_ids or [],
            "executor_skill_groups": executor_skill_group_ids or [],
            "executor_skill_root": str(skills_dir) if expanded_skill_ids else "",
        }
        try:
            argv = build_run_argv(launch_payload, runs_dir=runs_dir)
        except LaunchError as error:
            raise ExperimentError(f"Contender {label}: {error}")

        if snapshot_profile is not None:
            contender_spec = _snapshot_contender_spec(
                {
                    "agent": agent,
                    "model": launch_payload["executor_model"],
                    "label": label,
                    "thinking_effort": launch_payload["thinking_effort"],
                    "auth_mode": launch_payload["auth_mode"],
                    "provider_id": str(requested_contender.get("provider_id") or ""),
                },
                provider_by_id,
                context=f"Contender {label}",
            )
            snapshot = _assemble_profile_snapshot(
                profile=snapshot_profile,
                contender_spec=contender_spec,
                roster=snapshot_roster,
                shared=shared,
                evaluator_agent=evaluator_agent,
                launch_payload=launch_payload,
                effective_backend=effective_backend,
                tasks_dir=str(payload.get("tasks_dir") or ""),
                task_ids=[task_id for task_id, _ in resolved_steps],
                modified_fields=snapshot_modified_fields,
            )
            # Belt and braces: the runner re-validates and fails closed, but an
            # assembly bug should surface as a plan-time error, not at launch.
            try:
                validate_payload("profile_snapshot.schema.json", snapshot)
            except ContractValidationError as error:
                raise ExperimentError(
                    f"Contender {label}: assembled profile snapshot violates its "
                    f"contract: {error}"
                )
            if payload.get("dry_run"):
                # Plan previews are read-only and may run on every form edit.
                # Show the transport in argv without leaking one temp file per
                # preview; the non-dry launch request materializes the snapshot.
                snapshot_path = "<generated-at-launch>"
            else:
                fd, snapshot_path = tempfile.mkstemp(
                    prefix=f"starbench-profile-snapshot-{run_id}-", suffix=".json"
                )
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
            argv += ["--profile-snapshot", snapshot_path]

        executor_env_spec = contender.get("env") if isinstance(contender.get("env"), dict) else {}
        executor_provider = provider_by_id.get(
            str(requested_contender.get("provider_id") or "")
        )
        judge_provider = provider_by_id.get(str(shared.get("evaluator_provider_id") or ""))
        executor_credential_env_keys = _credential_source_names(
            executor_env_spec,
            api_key_env=launch_payload.get("executor_opencode_api_key_env"),
            provider=executor_provider,
            auth_mode=launch_payload["auth_mode"],
        )
        evaluator_credential_env_keys = _credential_source_names(
            judge_env,
            api_key_env=launch_payload.get("evaluator_opencode_api_key_env"),
            provider=judge_provider,
            auth_mode=str(launch_payload.get("evaluator_auth_mode") or "env"),
        )

        # The runner now scopes executor and judge env separately (the console
        # ships each side's variables under STARBENCH_EXECUTOR_ENV_* /
        # STARBENCH_JUDGE_ENV_* prefixes, which the runner unpacks into isolated
        # base envs). A contender injecting a judge-sensitive variable therefore
        # no longer reroutes the judge — what used to be a hard rejection is now
        # an advisory warning surfaced in the plan.
        warnings: List[str] = []
        # The web-search override is only enforceable where the runner controls
        # web access (Claude's tool allowlist, Codex's --search flag). Say so
        # instead of letting the override look global.
        web_search_mode = str(shared.get("web_search_mode") or "task")
        if web_search_mode != "task" and agent not in ("claude", "codex"):
            warnings.append(
                f"Contender {label}: the web-search override ({web_search_mode}) is not "
                f"enforceable for {agent} — its own tooling decides web access. Only "
                "Claude Code and Codex enforce it."
            )
        for key in executor_env_spec:
            if key in judge_sensitive and judge_env.get(key) != executor_env_spec[key]:
                warnings.append(
                    f"Contender {label}: {key} is injected for the contender and is "
                    f"also read by the {evaluator_agent} judge. Executor and judge run "
                    "under isolated env scopes, so the judge keeps its own routing."
                )
        # `merged_env` is display/back-compat only. Conflicting values remain in
        # their role-scoped maps; the merged view keeps the executor value.
        merged_env = dict(executor_env_spec)
        for key, entry in judge_env.items():
            merged_env.setdefault(key, entry)

        docker_image = ""
        if effective_backend == "docker":
            docker_image = (
                str(custom_meta.get("docker_image") or "")
                if custom_meta
                else DEFAULT_DOCKER_IMAGES.get(agent, "")
            )
        plans.append(
            {
                "label": label,
                "agent": agent,
                "agent_label": custom_meta["label"] if custom_meta else agent,
                "model": launch_payload["executor_model"],
                "run_id": run_id,
                "backend": effective_backend,
                "backend_downgraded": backend == "docker" and effective_backend == "local",
                "docker_image": docker_image,
                # Auth mode the launch will use; the review-step preflight
                # passes it through so credential checks match reality.
                "executor_auth_mode": launch_payload["auth_mode"],
                "evaluator_agent": launch_payload["evaluator_agent"],
                "evaluator_auth_mode": str(
                    launch_payload.get("evaluator_auth_mode") or "env"
                ),
                "executor_bin": str(launch_payload.get("executor_bin") or ""),
                "evaluator_bin": str(launch_payload.get("evaluator_bin") or ""),
                "executor_opencode_api_key_env": str(
                    launch_payload.get("executor_opencode_api_key_env") or ""
                ),
                "evaluator_opencode_api_key_env": str(
                    launch_payload.get("evaluator_opencode_api_key_env") or ""
                ),
                "executor_credential_env_keys": executor_credential_env_keys,
                "evaluator_credential_env_keys": evaluator_credential_env_keys,
                # Legacy merged view (kept for display/back-compat).
                "env_spec": merged_env,
                "env_keys": sorted(merged_env.keys()),
                # Scoped views the server ships as STARBENCH_{EXECUTOR,JUDGE}_ENV_*.
                "executor_env_spec": executor_env_spec,
                "judge_env_spec": judge_env,
                # Group-expanded skill ids injected into this contender (shared
                # across contenders); surfaced in the Review summary.
                "executor_skills": expanded_skill_ids,
                "warnings": warnings,
                "argv": argv,
            }
        )

    try:
        repeat = int(shared.get("repeat") or 1)
    except (TypeError, ValueError):
        repeat = 1
    repeat = max(repeat, 1)
    execution_estimate = _instruction_execution_estimate(
        resolved_steps,
        mode=instruction_mode,
        repeat=repeat,
        contender_count=len(plans),
    )
    return {
        "name": name,
        "shared": shared,
        "plans": plans,
        "execution_estimate": execution_estimate,
        "profile_modified": bool(snapshot_modified_fields),
        "profile_modified_fields": snapshot_modified_fields,
    }
