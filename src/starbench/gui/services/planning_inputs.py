"""Runtime/provider resolution and execution-count planning helpers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...adapters import list_builtin
from ...domain import INSTRUCTION_MODES, RIGOR_MODES
from .. import injection
from ..agents import get_custom_agent
from ..read_models.base import _read_json
from ..read_models.tasks import read_human_reference_steps, read_rigors
from .errors import ExperimentError

_BUILTIN_INFO = {adapter.info.id: adapter.info for adapter in list_builtin()}
DOCKER_CAPABLE_AGENTS = {info.id for info in _BUILTIN_INFO.values() if info.docker_capable}
JUDGE_ENV_SENSITIVE = {info.id: info.judge_sensitive_env for info in _BUILTIN_INFO.values()}
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


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "contender"


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


def _credential_source_names(
    env_spec: Dict[str, Any],
    *,
    api_key_env: Any = None,
    provider: Optional[Dict[str, Any]] = None,
    auth_mode: str = "env",
) -> List[str]:
    """Return source env names needed to materialize one role's credentials."""

    if auth_mode != "env":
        return []
    names = {
        str(entry.get("from_env") or "").strip()
        for entry in env_spec.values()
        if isinstance(entry, dict) and entry.get("from_env")
    }
    explicit = str(api_key_env or "").strip()
    if explicit:
        names.add(explicit)
    if provider is not None:
        source = str(provider.get("api_key_env") or "").strip()
        if source:
            names.add(source)
    return sorted(name for name in names if name)


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
    updated["evaluator_bin"] = settings.get("codex_bin")
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
