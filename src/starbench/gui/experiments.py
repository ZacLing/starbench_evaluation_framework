"""Experiments: one configuration fanned out across multiple agent runtimes.

An experiment is the console's unit of comparison: a fixed task set, one shared
judge and shared parameters (the controls), and M contenders (runtime + model,
the variable). The console orchestrates one `starbench-run` per contender and
records the grouping in `<runs-dir>/experiments/<id>.json`; the runs themselves
stay plain runs that the CLI fully owns.

Profiles live in `<runs-dir>/profiles.json`: named bundles of the shared
configuration plus a declaration of which fields each contender fills in
individually.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters import DEFAULT_DOCKER_IMAGES, list_builtin
from . import injection, providers as providers_module
from .agents import DEFAULT_RUNTIMES_DIR, get_custom_agent
from .data import SAFE_ID, _read_json, run_overview
from .launcher import LaunchError, build_run_argv

# All per-runtime facts below derive from the adapter registry (single source
# of truth); the GUI keeps no hand-maintained copies.
_BUILTIN_INFO = {adapter.info.id: adapter.info for adapter in list_builtin()}

# Every built-in runtime runs in Docker isolation (each in its own image);
# custom runtimes need a docker section in their spec.
DOCKER_CAPABLE_AGENTS = {info.id for info in _BUILTIN_INFO.values() if info.docker_capable}

# Environment variables each built-in judge reads for routing/credentials.
# The environment is process-wide per run: a contender that injects one of
# these would silently reroute the judge in the same subprocess.
JUDGE_ENV_SENSITIVE = {info.id: info.judge_sensitive_env for info in _BUILTIN_INFO.values()}

PER_CONTENDER_FIELD_CHOICES = ["model", "credentials", "gateway", "thinking_effort"]

BUILTIN_PROFILE = {
    "id": "standard",
    "name": "Standard evaluation",
    "shared": {
        "evaluator_agent": "codex",
        "evaluator_model": "gpt-5.5",
        "evaluator_auth_mode": "env",
        "judge_mode": "single",
        "evaluator_timeout_seconds": 900,
        "executor_backend": "local",
        "executor_auth_mode": "env",
        "seed": 123,
        "batch_size": 1,
        "repeat": 1,
    },
    "per_contender_fields": ["model", "credentials", "gateway"],
}


class ExperimentError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def profiles_path(runs_dir: Path) -> Path:
    return runs_dir / "profiles.json"


def load_profiles(runs_dir: Path) -> Dict[str, Any]:
    payload = _read_json(profiles_path(runs_dir))
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        return {
            "default_profile_id": BUILTIN_PROFILE["id"],
            "profiles": [BUILTIN_PROFILE],
            "persisted": False,
        }
    payload.setdefault("default_profile_id", None)
    payload["persisted"] = True
    return payload


def save_profiles(runs_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ExperimentError("`profiles` must be a non-empty list.")
    seen = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ExperimentError("Each profile must be an object.")
        profile_id = str(profile.get("id") or "")
        if not SAFE_ID.match(profile_id):
            raise ExperimentError(f"Profile id is invalid: {profile_id!r}")
        if profile_id in seen:
            raise ExperimentError(f"Duplicate profile id: {profile_id}")
        seen.add(profile_id)
        if not isinstance(profile.get("shared"), dict):
            raise ExperimentError(f"Profile {profile_id} needs a `shared` object.")
        fields = profile.get("per_contender_fields")
        if not isinstance(fields, list) or not all(
            field in PER_CONTENDER_FIELD_CHOICES for field in fields
        ):
            raise ExperimentError(
                f"Profile {profile_id} per_contender_fields must be a subset of "
                f"{PER_CONTENDER_FIELD_CHOICES}."
            )
    default_id = payload.get("default_profile_id")
    if default_id is not None and default_id not in seen:
        raise ExperimentError(f"default_profile_id {default_id!r} matches no profile.")

    stored = {"default_profile_id": default_id, "profiles": profiles}
    runs_dir.mkdir(parents=True, exist_ok=True)
    profiles_path(runs_dir).write_text(
        json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    stored["persisted"] = True
    return stored


# ---------------------------------------------------------------------------
# Experiment orchestration
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "contender"


def experiments_dir(runs_dir: Path) -> Path:
    return runs_dir / "experiments"


def _experiment_path(runs_dir: Path, experiment_id: str) -> Path:
    if not SAFE_ID.match(experiment_id):
        raise ExperimentError(f"Invalid experiment id: {experiment_id!r}")
    return experiments_dir(runs_dir) / f"{experiment_id}.json"


def _judge_sensitive_vars(evaluator_agent: str, runtimes_dir: Path) -> set:
    if evaluator_agent.startswith("custom:"):
        meta = get_custom_agent(runtimes_dir, evaluator_agent.split(":", 1)[1])
        if meta is None:
            return set()
        sensitive = set(meta.get("env") or {})
        for field in ("base_url_env", "api_key_env"):
            if meta.get(field):
                sensitive.add(meta[field])
        return sensitive
    return set(JUDGE_ENV_SENSITIVE.get(evaluator_agent, ()))


def _resolve_judge_reference(
    shared: Dict[str, Any],
    evaluator_agent: str,
    provider_by_id: Dict[str, Any],
    runtimes_dir: Path,
) -> Dict[str, Any]:
    """Resolve a judge provider reference (``evaluator_provider_id``) into the
    explicit ``evaluator_auth_mode`` / ``evaluator_gateway`` / ``judge_env``
    fields the rest of this module already understands.

    The reference shape and the legacy explicit shape converge here: given the
    same provider, the computed fields equal what the old frontend sent. A
    ``shared`` without ``evaluator_provider_id`` passes through untouched.
    """
    provider_id = str(shared.get("evaluator_provider_id") or "")
    if not provider_id:
        return shared
    provider = provider_by_id.get(provider_id)
    if provider is None:
        raise ExperimentError(f"Judge provider {provider_id!r} is not a configured AI provider.")
    info = None
    custom_meta = None
    if evaluator_agent.startswith("custom:"):
        custom_meta = get_custom_agent(runtimes_dir, evaluator_agent.split(":", 1)[1])
        if custom_meta is None:
            return shared  # the explicit validation below raises the precise error
    elif evaluator_agent in _BUILTIN_INFO:
        info = _BUILTIN_INFO[evaluator_agent]
    else:
        return shared  # unknown runtime; build_run_argv rejects it later
    settings = injection.settings_for(provider, info=info, custom_meta=custom_meta)
    updated = dict(shared)
    updated["evaluator_auth_mode"] = settings["auth_mode"]
    gateway = settings.get("gateway") or {}
    updated["evaluator_gateway"] = gateway or None
    updated["judge_env"] = settings.get("env")
    return updated


def _resolve_contender_reference(
    contender: Dict[str, Any],
    provider_by_id: Dict[str, Any],
    custom_meta: Optional[Dict[str, Any]],
    info: Any,
) -> Dict[str, Any]:
    """Resolve a contender provider reference (``provider_id``) into the explicit
    contender shape (``auth_mode`` / ``codex_bin`` / ``opencode_*`` / ``env``).

    A contender without ``provider_id`` (legacy explicit shape) passes through.
    """
    if "provider_id" not in contender:
        return contender
    provider_id = str(contender.get("provider_id") or "")
    provider = provider_by_id.get(provider_id) if provider_id else None
    if provider is None:
        if provider_id:
            raise ExperimentError(
                f"Contender provider {provider_id!r} is not a configured AI provider."
            )
        # Providerless (a custom runtime with protocol "none"): the CLI uses its
        # own login/config.
        settings = dict(injection.PROVIDERLESS_SETTINGS)
    else:
        settings = injection.settings_for(provider, info=info, custom_meta=custom_meta)
    model = str(contender.get("model") or "").strip()
    if custom_meta is not None and not custom_meta.get("model_flag"):
        model = ""
    resolved: Dict[str, Any] = {
        "label": contender.get("label"),
        "agent": contender.get("agent"),
        "model": model,
        "auth_mode": settings["auth_mode"],
        "thinking_effort": contender.get("thinking_effort"),
        "codex_bin": settings.get("codex_bin"),
        "env": settings.get("env"),
    }
    resolved.update(settings.get("gateway") or {})
    return resolved


def plan_experiment(
    payload: Dict[str, Any], *, runs_dir: Path, runtimes_dir: Path = DEFAULT_RUNTIMES_DIR
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

    # Resolve provider references (the reference shape) into the explicit fields
    # the rest of this function consumes. Providers live in <runs-dir>/providers.
    provider_by_id = {
        provider["id"]: provider
        for provider in providers_module.load_providers(runs_dir)["providers"]
    }

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
    plans: List[Dict[str, Any]] = []
    used_run_ids = set()
    for index, contender in enumerate(contenders):
        if not isinstance(contender, dict):
            raise ExperimentError("Each contender must be an object.")
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

        # The codex binary config is process-global: rerouting a Codex
        # contender through a gateway would silently reroute a Codex judge in
        # the same run.
        if contender.get("codex_bin") and evaluator_agent == "codex":
            raise ExperimentError(
                f"Contender {label}: routing Codex through a gateway also reroutes the "
                "Codex judge (the CLI shares one codex configuration per run). Pick a "
                "non-Codex judge or use the official OpenAI provider for this contender."
            )

        # OpenCode gateway flags are process-global in the CLI: a contender and
        # an OpenCode judge must agree on them, and an OpenCode judge supplies
        # them when the contender does not use OpenCode at all.
        gateway = {
            "opencode_provider": contender.get("opencode_provider"),
            "opencode_base_url": contender.get("opencode_base_url"),
            "opencode_api_key_env": contender.get("opencode_api_key_env"),
        }
        if evaluator_agent == "opencode" and evaluator_gateway:
            if agent == "opencode":
                for key in gateway:
                    contender_value = str(gateway.get(key) or "")
                    judge_value = str(evaluator_gateway.get(key) or "")
                    if contender_value and judge_value and contender_value != judge_value:
                        raise ExperimentError(
                            f"Contender {label}: its OpenCode gateway conflicts with the "
                            "judge's gateway; the CLI supports only one OpenCode gateway "
                            "per run."
                        )
            else:
                gateway = dict(evaluator_gateway)

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
            "claude_thinking_effort": str(contender.get("thinking_effort") or "none"),
            "evaluator_agent": str(shared.get("evaluator_agent") or "codex"),
            "evaluator_model": str(shared.get("evaluator_model") or "").strip(),
            "evaluator_auth_mode": str(shared.get("evaluator_auth_mode") or "") or None,
            "judge_mode": str(shared.get("judge_mode") or "single"),
            "evaluator_timeout_seconds": shared.get("evaluator_timeout_seconds"),
            "seed": shared.get("seed"),
            "batch_size": shared.get("batch_size"),
            "repeat": shared.get("repeat"),
            "codex_bin": contender.get("codex_bin"),
            "opencode_provider": gateway.get("opencode_provider"),
            "opencode_base_url": gateway.get("opencode_base_url"),
            "opencode_api_key_env": gateway.get("opencode_api_key_env"),
            "extra_args": str(shared.get("extra_args") or ""),
        }
        try:
            argv = build_run_argv(launch_payload, runs_dir=runs_dir)
        except LaunchError as error:
            raise ExperimentError(f"Contender {label}: {error}")
        executor_env_spec = contender.get("env") if isinstance(contender.get("env"), dict) else {}

        # The runner now scopes executor and judge env separately (the console
        # ships each side's variables under STARBENCH_EXECUTOR_ENV_* /
        # STARBENCH_JUDGE_ENV_* prefixes, which the runner unpacks into isolated
        # base envs). A contender injecting a judge-sensitive variable therefore
        # no longer reroutes the judge — what used to be a hard rejection is now
        # an advisory warning surfaced in the plan.
        warnings: List[str] = []
        for key in executor_env_spec:
            if key in judge_sensitive and judge_env.get(key) != executor_env_spec[key]:
                warnings.append(
                    f"Contender {label}: {key} is injected for the contender and is "
                    f"also read by the {evaluator_agent} judge. Executor and judge run "
                    "under isolated env scopes, so the judge keeps its own routing."
                )
        # `merged_env` (and the legacy env_spec/env_keys fields) is kept only for
        # display/back-compat; the two scopes are shipped separately below. A
        # judge that sets a variable the contender also sets to a *different*
        # value is still surfaced as an error since the merged view cannot show
        # both.
        merged_env = dict(executor_env_spec)
        for key, entry in judge_env.items():
            if key in merged_env and merged_env[key] != entry:
                raise ExperimentError(
                    f"Contender {label}: it sets {key} differently from the judge; "
                    "the environment is process-wide per run, so the two cannot "
                    "disagree. Align the providers or pick another judge."
                )
            merged_env[key] = entry

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
                # Legacy merged view (kept for display/back-compat).
                "env_spec": merged_env,
                "env_keys": sorted(merged_env.keys()),
                # Scoped views the server ships as STARBENCH_{EXECUTOR,JUDGE}_ENV_*.
                "executor_env_spec": executor_env_spec,
                "judge_env_spec": judge_env,
                "warnings": warnings,
                "argv": argv,
            }
        )
    return {"name": name, "shared": shared, "plans": plans}


def record_experiment(
    runs_dir: Path,
    *,
    name: str,
    payload: Dict[str, Any],
    plans: List[Dict[str, Any]],
) -> Dict[str, Any]:
    record = {
        "id": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tasks_dir": payload.get("tasks_dir"),
        "tasks": payload.get("tasks") or [],
        "shared": payload.get("shared"),
        "contenders": [
            {
                "label": plan["label"],
                "agent": plan["agent"],
                "agent_label": plan.get("agent_label") or plan["agent"],
                "model": plan["model"],
                "run_id": plan["run_id"],
                "backend": plan["backend"],
                "backend_downgraded": plan["backend_downgraded"],
            }
            for plan in plans
        ],
        "run_ids": [plan["run_id"] for plan in plans],
    }
    directory = experiments_dir(runs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _experiment_path(runs_dir, name).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def list_experiments(runs_dir: Path, active_run_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    directory = experiments_dir(runs_dir)
    if not directory.is_dir():
        return []
    records: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        record = _read_json(path)
        if not isinstance(record, dict) or not isinstance(record.get("run_ids"), list):
            continue
        summary = dict(record)
        summary["runs"] = []
        for run_id in record["run_ids"]:
            run_root = runs_dir / str(run_id)
            if run_root.is_dir():
                summary["runs"].append(run_overview(run_root, active_run_ids))
            else:
                summary["runs"].append({"run_id": run_id, "status": "missing"})
        records.append(summary)
    return records


def experiment_detail(
    runs_dir: Path, experiment_id: str, active_run_ids: Optional[set] = None
) -> Dict[str, Any]:
    path = _experiment_path(runs_dir, experiment_id)
    record = _read_json(path)
    if not isinstance(record, dict):
        raise ExperimentError(f"No experiment named {experiment_id}.")

    contenders = record.get("contenders") or []
    runs: List[Dict[str, Any]] = []
    for contender in contenders:
        run_id = str(contender.get("run_id") or "")
        run_root = runs_dir / run_id
        entry = dict(contender)
        entry["run"] = run_overview(run_root, active_run_ids) if run_root.is_dir() else None
        runs.append(entry)

    matrix = _build_matrix(runs_dir, contenders)
    return {**record, "contenders": runs, "matrix": matrix}


def _build_matrix(runs_dir: Path, contenders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """rubric x contender pass matrix, grouped by task, from single-judge results."""
    questions: Dict[str, Dict[str, str]] = {}
    cells: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}
    task_order: List[str] = []

    for contender in contenders:
        run_id = str(contender.get("run_id") or "")
        run_root = runs_dir / run_id
        if not run_root.is_dir():
            continue
        for task_root in sorted(run_root.iterdir()):
            if not task_root.is_dir() or not (task_root / "logs").is_dir():
                continue
            manifest = _read_json(task_root / "manifest.json")
            task_id = (
                str(manifest.get("task_id"))
                if isinstance(manifest, dict) and manifest.get("task_id")
                else task_root.name
            )
            if task_id not in cells:
                cells[task_id] = {}
                questions.setdefault(task_id, {})
                task_order.append(task_id)
            if isinstance(manifest, dict):
                for rubric in manifest.get("rubrics") or []:
                    if isinstance(rubric, dict) and rubric.get("id"):
                        questions[task_id].setdefault(
                            str(rubric["id"]), str(rubric.get("question", ""))
                        )
            aggregate = _read_json(task_root / "judges" / "single_aggregate.json")
            if not isinstance(aggregate, dict):
                continue
            for row in aggregate.get("results") or []:
                rubric_id = str(row.get("rubric_id") or "")
                if not rubric_id:
                    continue
                bucket = cells[task_id].setdefault(rubric_id, {})
                stats = bucket.setdefault(run_id, {"passed": 0, "total": 0})
                stats["total"] += 1
                if row.get("passed"):
                    stats["passed"] += 1

    matrix = []
    for task_id in task_order:
        rubric_ids = sorted(cells[task_id].keys())
        matrix.append(
            {
                "task_id": task_id,
                "rubrics": [
                    {
                        "id": rubric_id,
                        "question": questions[task_id].get(rubric_id, ""),
                        "cells": cells[task_id][rubric_id],
                    }
                    for rubric_id in rubric_ids
                ],
            }
        )
    return matrix
