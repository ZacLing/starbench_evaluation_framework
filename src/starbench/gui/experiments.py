"""Experiments: one configuration fanned out across multiple agent runtimes.

An experiment is the console's unit of comparison: a fixed task set, one shared
judge and shared parameters (the controls), and M contenders (runtime + model,
the variable). The console orchestrates one `starbench-run` per contender and
records the grouping in `<runs-dir>/experiments/<id>.json`; the runs themselves
stay plain runs that the CLI fully owns.

Profiles live in `<runs-dir>/profiles.json`: named bundles of the shared
configuration plus a declaration of which fields each contender fills in
individually. A profile may additionally declare a `roster` (the contender
columns its coverage matrix measures) and a `task_set`; launching from such a
profile hands every contender's run a self-contained, credential-free
`profile_snapshot.json` (snapshot-on-use — the runner validates and writes it).
The payload is the effective configuration and the profile is the comparison
baseline: an ad-hoc launch may deviate from the profile without persisting an
edit, and the snapshot then records the actual values plus a backend-computed
`modified`/`modified_fields` annotation naming the deviating dimensions.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..adapters import DEFAULT_DOCKER_IMAGES, list_builtin
from ..contracts import ARTIFACT_SCHEMA_VERSION, ContractValidationError, validate_payload
from . import injection, providers as providers_module, skills as skills_module
from .agents import DEFAULT_RUNTIMES_DIR, get_custom_agent
from .data import SAFE_ID, _read_json, read_human_reference_steps, read_rigors, run_overview
from .launcher import LaunchError, build_run_argv
from .skills import DEFAULT_SKILLS_DIR, SkillError

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

# Effort levels each built-in runtime's CLI actually accepts; custom runtimes
# take the prompt tiers. Plans reject a level outside the runtime's set.
THINKING_EFFORTS_BY_AGENT = {info.id: info.thinking_efforts for info in _BUILTIN_INFO.values()}
PROMPT_THINKING_EFFORTS = ("none", "low", "medium", "high")


def _validated_thinking_effort(agent: str, contender: Dict[str, Any], label: str) -> str:
    effort = str(contender.get("thinking_effort") or "none")
    supported = THINKING_EFFORTS_BY_AGENT.get(agent, PROMPT_THINKING_EFFORTS)
    if effort not in supported:
        raise ExperimentError(
            f"Contender {label}: thinking effort {effort} is not supported by "
            f"{agent} (supported: {', '.join(supported)})."
        )
    return effort

PER_CONTENDER_FIELD_CHOICES = ["model", "credentials", "gateway", "thinking_effort"]

# Fields a profile roster entry may carry: the reference shape the wizard
# collects per contender (runtime + provider reference + model). Credentials
# never belong in a profile — providers are referenced by id, and the launch
# snapshot inlines only endpoint values and env-var NAMES.
ROSTER_ENTRY_FIELDS = {"agent", "model", "label", "provider_id", "thinking_effort"}
TASK_SET_FIELDS = {"tasks_dir", "task_ids"}

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

# HSW measurement-contract template: same instrument as "standard" but five
# repeats per cell (a single execution is a sample, not a score). The roster is
# deliberately an empty placeholder — which contender columns are worth
# measuring is a human judgment the operator fills in, not a default we invent.
BUILTIN_PROFILE_HSW_FRONTIER = {
    "id": "hsw-frontier",
    "name": "HSW frontier sweep",
    "shared": {**BUILTIN_PROFILE["shared"], "repeat": 5},
    "per_contender_fields": ["model", "credentials", "gateway"],
    "roster": [],
}

BUILTIN_PROFILES = [BUILTIN_PROFILE, BUILTIN_PROFILE_HSW_FRONTIER]


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
            "profiles": list(BUILTIN_PROFILES),
            "persisted": False,
        }
    payload.setdefault("default_profile_id", None)
    payload["persisted"] = True
    return payload


def _validate_profile_roster(profile_id: str, roster: Any) -> None:
    """Roster entries follow the wizard's reference shape; unknown keys are
    rejected so credential-shaped fields can never enter profiles.json."""
    if not isinstance(roster, list):
        raise ExperimentError(f"Profile {profile_id} roster must be a list of contender specs.")
    for index, entry in enumerate(roster):
        if not isinstance(entry, dict):
            raise ExperimentError(f"Profile {profile_id} roster[{index}] must be an object.")
        unknown = set(entry) - ROSTER_ENTRY_FIELDS
        if unknown:
            raise ExperimentError(
                f"Profile {profile_id} roster[{index}] has unsupported field(s) "
                f"{sorted(unknown)}; allowed: {sorted(ROSTER_ENTRY_FIELDS)}. Credentials "
                "never belong in a profile — reference a provider by id instead."
            )
        if not isinstance(entry.get("agent"), str) or not entry.get("agent"):
            raise ExperimentError(f"Profile {profile_id} roster[{index}] needs an `agent` string.")
        for field in ("model", "label", "provider_id", "thinking_effort"):
            if field in entry and not isinstance(entry[field], str):
                raise ExperimentError(
                    f"Profile {profile_id} roster[{index}].{field} must be a string."
                )


def _validate_profile_task_set(profile_id: str, task_set: Any) -> None:
    if not isinstance(task_set, dict):
        raise ExperimentError(f"Profile {profile_id} task_set must be an object.")
    unknown = set(task_set) - TASK_SET_FIELDS
    if unknown:
        raise ExperimentError(
            f"Profile {profile_id} task_set has unsupported field(s) {sorted(unknown)}; "
            f"allowed: {sorted(TASK_SET_FIELDS)}."
        )
    if not isinstance(task_set.get("tasks_dir"), str) or not task_set.get("tasks_dir"):
        raise ExperimentError(f"Profile {profile_id} task_set needs a non-empty `tasks_dir`.")
    task_ids = task_set.get("task_ids")
    if not isinstance(task_ids, list) or not all(isinstance(item, str) for item in task_ids):
        raise ExperimentError(
            f"Profile {profile_id} task_set.task_ids must be a list of task ids "
            "(empty means every task in the directory)."
        )


def _profile_content(profile: Dict[str, Any]) -> Dict[str, Any]:
    """A profile minus its revision counter — the content `rev` versions."""
    return {key: value for key, value in profile.items() if key != "rev"}


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
        if "roster" in profile:
            _validate_profile_roster(profile_id, profile.get("roster"))
        if "task_set" in profile:
            _validate_profile_task_set(profile_id, profile.get("task_set"))
    default_id = payload.get("default_profile_id")
    if default_id is not None and default_id not in seen:
        raise ExperimentError(f"default_profile_id {default_id!r} matches no profile.")

    # Revision counter: server-assigned, never trusted from the client. A new
    # profile starts at 1; content changes bump the stored rev; an identical
    # save keeps it. Snapshots cite this rev to pin "the contract as of launch".
    previous = _read_json(profiles_path(runs_dir))
    previous_by_id: Dict[str, Dict[str, Any]] = {}
    if isinstance(previous, dict) and isinstance(previous.get("profiles"), list):
        previous_by_id = {
            str(entry.get("id")): entry
            for entry in previous["profiles"]
            if isinstance(entry, dict)
        }
    revised: List[Dict[str, Any]] = []
    for profile in profiles:
        profile_id = str(profile.get("id") or "")
        stored_profile = dict(profile)
        old = previous_by_id.get(profile_id)
        if old is None:
            stored_profile["rev"] = 1
        elif _profile_content(old) == _profile_content(stored_profile):
            stored_profile["rev"] = int(old.get("rev") or 1)
        else:
            stored_profile["rev"] = int(old.get("rev") or 1) + 1
        revised.append(stored_profile)

    stored = {"default_profile_id": default_id, "profiles": revised}
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


# ---------------------------------------------------------------------------
# Instruction ablation: plan-time step resolution and execution estimate
# ---------------------------------------------------------------------------

INSTRUCTION_MODES = ("none", "traverse", "select", "ablation")
RIGOR_MODES = ("none", "select")


def _resolve_selected_rigors(
    tasks_dir_value: Any, task_selectors: Any
) -> List[Tuple[str, List[str]]]:
    """Resolve the tasks that will run to their public rigor ids.

    Same selector/order contract as ``_resolve_selected_steps``: one
    ``(task_id, [rigor_id, ...])`` pair per task in directory order, matching a
    selector by task id or directory name, with an empty selector list meaning
    "every task". Rigor content is fully public, so this reads all rigor ids.
    """
    tasks_dir = Path(str(tasks_dir_value)) if tasks_dir_value else None
    if tasks_dir is None or not tasks_dir.is_dir():
        return []
    ordered: List[Tuple[str, List[str]]] = []
    by_selector: Dict[str, Tuple[str, List[str]]] = {}
    for entry in sorted(tasks_dir.iterdir()):
        task_json = entry / "task.json"
        if not entry.is_dir() or not task_json.exists():
            continue
        spec = _read_json(task_json)
        if not isinstance(spec, dict):
            continue
        rigor_ids = [rigor["id"] for rigor in read_rigors(entry, spec)]
        record = (str(spec.get("id", entry.name)), rigor_ids)
        by_selector[record[0]] = record
        by_selector[entry.name] = record
        ordered.append(record)
    selectors = [str(item) for item in (task_selectors or []) if isinstance(item, str)]
    if not selectors:
        return ordered
    return [by_selector[selector] for selector in selectors if selector in by_selector]


def _resolve_selected_steps(
    tasks_dir_value: Any, task_selectors: Any
) -> List[Tuple[str, List[str]]]:
    """Resolve the tasks that will run to their public expert-step ids.

    Returns one ``(task_id, [step_id, ...])`` pair per task, in directory order.
    A selector matches by either task id or directory name (the runner accepts
    both for ``--task``). An empty selector list means "every task in the
    directory", mirroring the runner discovering all tasks when no ``--task`` is
    passed. Only public step ids are read here — never the private ``reasoning``.
    """
    tasks_dir = Path(str(tasks_dir_value)) if tasks_dir_value else None
    if tasks_dir is None or not tasks_dir.is_dir():
        return []
    ordered: List[Tuple[str, List[str]]] = []
    by_selector: Dict[str, Tuple[str, List[str]]] = {}
    for entry in sorted(tasks_dir.iterdir()):
        task_json = entry / "task.json"
        if not entry.is_dir() or not task_json.exists():
            continue
        spec = _read_json(task_json)
        if not isinstance(spec, dict):
            continue
        step_ids = [step["step_id"] for step in read_human_reference_steps(entry, spec)]
        record = (str(spec.get("id", entry.name)), step_ids)
        by_selector[record[0]] = record
        by_selector[entry.name] = record
        ordered.append(record)
    selectors = [str(item) for item in (task_selectors or []) if isinstance(item, str)]
    if not selectors:
        return ordered
    return [by_selector[selector] for selector in selectors if selector in by_selector]


def _instruction_variants_for_task(mode: str, step_count: int) -> int:
    """Executor variants the runner expands for one task under an instruction mode.

    Faithful to ``runner.task_loader.build_task_runs``:
    - ``none`` / ``select`` -> exactly one run per task.
    - ``traverse`` -> one run per expert step (0 when the task ships none, which
      the runner rejects rather than running as a baseline).
    - ``ablation`` -> baseline + one run per step + one combined ``all_instructions``
      run (the combined run exists only when the task has more than one step);
      0 when the task ships no steps (the runner rejects it).
    """
    if mode in ("none", "select"):
        return 1
    if mode == "traverse":
        return step_count
    if mode == "ablation":
        if step_count == 0:
            return 0
        return 1 + step_count + (1 if step_count > 1 else 0)
    return 1


def _instruction_execution_estimate(
    resolved_steps: List[Tuple[str, List[str]]],
    *,
    mode: str,
    repeat: int,
    contender_count: int,
) -> Dict[str, Any]:
    """How many executor variants each contender (and the whole experiment) runs.

    ``per_contender`` = Σ over selected tasks of the mode's variant count × repeat;
    ``total`` = ``per_contender`` × the number of contenders. Tasks that ship no
    expert steps contribute nothing in the step-requiring modes because the
    runner rejects them there (the honest count, not a silent baseline).
    """
    step_counts = [len(step_ids) for _, step_ids in resolved_steps]
    variants_per_contender = sum(_instruction_variants_for_task(mode, count) for count in step_counts)
    per_contender = variants_per_contender * repeat
    stepless = sum(1 for count in step_counts if count == 0)
    repeat_suffix = f" × {repeat} repeat(s)" if repeat > 1 else ""

    if mode == "none":
        note = f"Baseline: one run per task{repeat_suffix}."
    elif mode == "select":
        note = f"One combined-instruction run per task{repeat_suffix}."
    elif mode == "traverse":
        note = f"One run per expert step, summed across tasks{repeat_suffix}."
    elif mode == "ablation":
        note = (
            "Per task: baseline + one run per step + a combined all-steps run "
            f"(the combined run only when a task has more than one step){repeat_suffix}."
        )
    else:  # pragma: no cover - guarded earlier
        note = ""

    if stepless and mode in ("select", "traverse", "ablation"):
        note += (
            f" {stepless} selected task(s) ship no expert steps; the runner "
            f"rejects those in {mode} mode rather than running a baseline."
        )

    return {
        "per_contender": per_contender,
        "total": per_contender * contender_count,
        "mode": mode,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Profile snapshot (snapshot-on-use): the measurement contract each run carries
#
# The payload is the effective configuration (the wizard may have edited it
# after loading a profile); the profile is the comparison baseline. The
# backend diffs the two itself — it never trusts a client-declared "modified"
# flag — and annotates any deviation in the snapshot (`modified` +
# `modified_fields`), so an ad-hoc test can launch without persisting a
# profile edit while the record stays honest.
# ---------------------------------------------------------------------------

# Shared keys that are part of the measurement contract (they feed the
# snapshot's instrument/execution sections), mapped to the effective default
# the runner applies when the key is unset. The deviation diff normalizes the
# payload and the profile with the SAME defaults, so an omitted key and an
# explicitly-spelled default never read as a deviation.
_SHARED_CONTRACT_DEFAULTS: Dict[str, Any] = {
    "evaluator_agent": "codex",
    "evaluator_model": None,
    "evaluator_auth_mode": None,
    "judge_mode": "single",
    "evaluator_timeout_seconds": 900,
    "seed": 123,
    "batch_size": 1,
    "repeat": 1,
    "executor_backend": "local",
    "executor_auth_mode": "env",
    "max_evaluator_parallel": 4,
    "web_search_mode": "task",
    "claude_max_turns": None,
}


def _normalized_shared_value(value: Any, default: Any) -> Any:
    """One shared key's comparison value: unset -> the runner default, numeric
    strings -> ints, other strings stripped. Representation differences
    ("5" vs 5) must never read as measurement deviations."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    try:
        return int(text)
    except ValueError:
        return text


def _shared_deviations(
    payload_shared: Dict[str, Any], profile_shared: Dict[str, Any]
) -> List[str]:
    """Shared-configuration keys whose effective value deviates from the
    profile baseline, sorted. Only measurement-contract keys are compared:
    keys with no bearing on the snapshot (display/orchestration knobs) cannot
    mark a launch as modified."""
    deviations = []
    for key, default in _SHARED_CONTRACT_DEFAULTS.items():
        effective = _normalized_shared_value(payload_shared.get(key), default)
        baseline = _normalized_shared_value(profile_shared.get(key), default)
        if effective != baseline:
            deviations.append(key)
    return sorted(deviations)


def _roster_comparison_key(entry: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """The measurement-relevant identity of one roster entry. ``label`` is
    display-only and deliberately excluded: renaming a contender does not
    change what is being measured."""
    return (
        str(entry.get("agent") or ""),
        str(entry.get("model") or "").strip(),
        str(entry.get("provider_id") or ""),
        str(entry.get("thinking_effort") or "none"),
    )


def _roster_deviates(contenders: List[Any], profile_roster: List[Any]) -> bool:
    """True when the launched contender set differs from the profile's declared
    roster as a multiset (order is presentation, not measurement)."""
    launched = sorted(
        _roster_comparison_key(entry) for entry in contenders if isinstance(entry, dict)
    )
    declared = sorted(
        _roster_comparison_key(entry) for entry in profile_roster if isinstance(entry, dict)
    )
    return launched != declared


def _task_set_deviates(
    payload: Dict[str, Any], profile_task_set: Any, resolved_task_ids: List[str]
) -> bool:
    """True when the launch's resolved task selection differs from what the
    profile's task_set resolves to right now. Comparison happens at the
    resolved level so "empty selectors = every task" equals an explicit list
    naming every task. A profile without a task_set declares no baseline, so
    nothing can deviate from it."""
    if not isinstance(profile_task_set, dict):
        return False
    if str(payload.get("tasks_dir") or "") != str(profile_task_set.get("tasks_dir") or ""):
        return True
    baseline_task_ids = [
        task_id
        for task_id, _ in _resolve_selected_steps(
            profile_task_set.get("tasks_dir"), profile_task_set.get("task_ids")
        )
    ]
    return sorted(resolved_task_ids) != sorted(baseline_task_ids)


def _int_or_default(value: Any, default: int) -> int:
    """Effective integer a launch will use: the runner's default when unset.

    Snapshots inline effective values (self-containment), never blanks. Values
    were already validated by ``build_run_argv`` before assembly runs.
    """
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _snapshot_contender_spec(
    entry: Dict[str, Any],
    provider_by_id: Dict[str, Any],
    *,
    context: str,
) -> Dict[str, Any]:
    """One contender/roster entry in the snapshot's self-contained shape.

    Provider references resolve to inline values here — the endpoint URL and
    the NAME of the API-key environment variable — so the snapshot survives
    provider edits/deletions without dangling ids. Secrets never enter a
    snapshot: only env-var names travel, and the contract schema rejects any
    field that could carry key material.
    """
    spec: Dict[str, Any] = {
        "agent": str(entry.get("agent") or ""),
        "model": str(entry.get("model") or ""),
    }
    for field in ("label", "thinking_effort", "auth_mode"):
        value = str(entry.get(field) or "")
        if value:
            spec[field] = value
    provider_id = str(entry.get("provider_id") or "")
    if provider_id:
        provider = provider_by_id.get(provider_id)
        if provider is None:
            raise ExperimentError(
                f"{context}: provider {provider_id!r} is not a configured AI provider; "
                "a snapshot must not carry a dangling reference."
            )
        spec["provider_id"] = provider_id
        base_url = str(provider.get("base_url") or "")
        if base_url:
            spec["base_url"] = base_url
        api_key_env = str(provider.get("api_key_env") or "")
        if api_key_env:
            spec["api_key_env"] = api_key_env
    return spec


def _assemble_profile_snapshot(
    *,
    profile: Dict[str, Any],
    contender_spec: Dict[str, Any],
    roster: List[Dict[str, Any]],
    shared: Dict[str, Any],
    evaluator_agent: str,
    launch_payload: Dict[str, Any],
    effective_backend: str,
    tasks_dir: str,
    task_ids: List[str],
    modified_fields: List[str],
) -> Dict[str, Any]:
    """The full measurement contract for one contender's run, as of launch.

    Every value here is the EFFECTIVE one (assembled from the launch payload);
    ``profile`` cites the comparison baseline, and a launch that deviated from
    it carries ``modified``/``modified_fields`` so the deviation is on the
    record without forcing a profile edit."""
    profile_id = str(profile.get("id") or "")
    contender_auth = str(launch_payload.get("auth_mode") or "env")
    instrument = {
        "evaluator_agent": evaluator_agent,
        "evaluator_model": str(shared.get("evaluator_model") or ""),
        # The runner defaults --evaluator-auth-mode to --auth-mode (this
        # contender's), so the effective value is what gets pinned here.
        "evaluator_auth_mode": str(shared.get("evaluator_auth_mode") or "") or contender_auth,
        "judge_mode": str(shared.get("judge_mode") or "single"),
        "evaluator_timeout_seconds": _int_or_default(
            shared.get("evaluator_timeout_seconds"), 900
        ),
    }
    execution = {
        "seed": _int_or_default(shared.get("seed"), 123),
        "batch_size": _int_or_default(shared.get("batch_size"), 1),
        "repeat": _int_or_default(shared.get("repeat"), 1),
        "executor_backend": effective_backend,
        "executor_auth_mode": contender_auth,
        "max_evaluator_parallel": _int_or_default(shared.get("max_evaluator_parallel"), 4),
        "web_search": str(launch_payload.get("web_search") or "task"),
    }
    claude_max_turns = shared.get("claude_max_turns")
    if claude_max_turns not in (None, ""):
        execution["claude_max_turns"] = int(claude_max_turns)
    snapshot = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "id": profile_id,
            # Hand-edited profiles.json may predate the revision counter; the
            # first revision is the honest floor, matching what save assigns.
            # When the launch deviated, this rev pins the BASELINE compared
            # against, never the deviating values.
            "rev": int(profile.get("rev") or 1),
            "name": str(profile.get("name") or profile_id),
        },
        "contender": contender_spec,
        "roster": list(roster),
        "instrument": instrument,
        "execution": execution,
        "task_set": {"tasks_dir": tasks_dir, "task_ids": list(task_ids)},
    }
    if modified_fields:
        snapshot["modified"] = True
        snapshot["modified_fields"] = list(modified_fields)
    return snapshot


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
    resolved_steps = _resolve_selected_steps(payload.get("tasks_dir"), payload.get("tasks"))
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
        resolved_rigors = _resolve_selected_rigors(payload.get("tasks_dir"), payload.get("tasks"))
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
            "codex_bin": contender.get("codex_bin"),
            "opencode_provider": gateway.get("opencode_provider"),
            "opencode_base_url": gateway.get("opencode_base_url"),
            "opencode_api_key_env": gateway.get("opencode_api_key_env"),
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
            fd, snapshot_path = tempfile.mkstemp(
                prefix=f"starbench-profile-snapshot-{run_id}-", suffix=".json"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
            argv += ["--profile-snapshot", snapshot_path]

        executor_env_spec = contender.get("env") if isinstance(contender.get("env"), dict) else {}

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
                # Auth mode the launch will use; the review-step preflight
                # passes it through so credential checks match reality.
                "executor_auth_mode": launch_payload["auth_mode"],
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
    }


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
