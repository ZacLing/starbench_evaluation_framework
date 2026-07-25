"""Pure profile-deviation and immutable snapshot assembly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ...contracts import ARTIFACT_SCHEMA_VERSION
from ...domain import canonical_thinking_effort
from .errors import ExperimentError
from .planning_inputs import _resolve_selected_steps

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
    "evaluator_options": {},
}

def _normalized_shared_value(value: Any, default: Any) -> Any:
    """One shared key's comparison value: unset -> the runner default, numeric
    strings -> ints, other strings stripped, option boxes -> a sorted, value-
    normalized tuple. Representation differences ("5" vs 5, or a box's key
    order) must never read as measurement deviations."""
    if value is None or (isinstance(value, str) and not value.strip()):
        value = default
    if isinstance(value, dict):
        return tuple(
            sorted((str(k), _normalized_shared_value(v, None)) for k, v in value.items())
        )
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if value is None:
        return None
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
        canonical_thinking_effort(str(entry.get("thinking_effort") or "default")),
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
    # Judge-side option box (evaluator knobs plus gateway wiring) as it took
    # effect for this run; omitted when empty. Names are enforced at parse time.
    evaluator_options = launch_payload.get("evaluator_options") or {}
    if evaluator_options:
        execution["evaluator_options"] = dict(evaluator_options)
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
