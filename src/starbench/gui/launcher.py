"""Assemble validated `starbench-run` argv and launch env from a request.

Process supervision lives in starbench.lifecycle; this module never spawns
anything.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters import list_builtin
from ..domain import INSTRUCTION_MODES, RIGOR_MODES
from ..lifecycle import LaunchError
from ..contracts import ContractValidationError, validate_payload
from ..runner.cli import PLAN_LIST_FLAGS
from ..runner.env_scope import EXECUTOR_ENV_PREFIX, JUDGE_ENV_PREFIX
from .read_models.base import SAFE_ID

# Built-in runtime ids come from the adapter registry (single source of truth).
AGENT_CHOICES = tuple(adapter.info.id for adapter in list_builtin())
JUDGE_MODES = ("both", "single", "parallel")
AUTH_MODES = ("env", "global", "copy-auth")
BACKENDS = ("local", "docker")
THINKING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
WEB_SEARCH_MODES = ("task", "allow", "deny")


def _require_choice(value: Any, choices: tuple, label: str) -> str:
    text = str(value)
    if text not in choices:
        raise LaunchError(f"{label} must be one of {', '.join(choices)}.")
    return text


def _require_agent(value: Any, label: str) -> str:
    """Built-in runtime name or custom:<id> (resolved by the CLI itself)."""
    text = str(value)
    if text in AGENT_CHOICES:
        return text
    if text.startswith("custom:") and SAFE_ID.match(text.split(":", 1)[1] or ""):
        return text
    raise LaunchError(
        f"{label} must be one of {', '.join(AGENT_CHOICES)} or custom:<id>."
    )


def _optional_int(value: Any, label: str, minimum: int = 1) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise LaunchError(f"{label} must be an integer.")
    if number < minimum:
        raise LaunchError(f"{label} must be at least {minimum}.")
    return number


def _string_list(value: Any, label: str) -> List[str]:
    """Coerce a payload value into a clean list of non-empty strings."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise LaunchError(f"{label} must be a list of names.")
    cleaned: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise LaunchError(f"{label} must be a list of names.")
        text = item.strip()
        if text:
            cleaned.append(text)
    return cleaned


def _normalized_launch(payload: Dict[str, Any], *, runs_dir: Path) -> Dict[str, Any]:
    """Validate the launch form payload into the flat run_plan key space.

    One validation path feeds both transports: build_run_plan wraps this dict
    as the typed contract, build_run_argv renders it into flags. Raises
    LaunchError with a user-readable message for anything invalid.
    """
    plan: Dict[str, Any] = {}

    run_id = str(payload.get("run_id") or "").strip()
    if not SAFE_ID.match(run_id):
        raise LaunchError(
            "Run id is required and may contain only letters, digits, dot, dash, underscore."
        )
    if (runs_dir / run_id).exists():
        raise LaunchError(f"Run id already exists in {runs_dir}: {run_id}")
    plan["run_id"] = run_id

    tasks_dir = str(payload.get("tasks_dir") or "").strip()
    if not tasks_dir:
        raise LaunchError("Tasks directory is required.")
    if not Path(tasks_dir).is_dir():
        raise LaunchError(f"Tasks directory not found: {tasks_dir}")
    plan["tasks_dir"] = tasks_dir

    tasks = payload.get("tasks") or []
    if not isinstance(tasks, list) or not all(isinstance(item, str) for item in tasks):
        raise LaunchError("Tasks must be a list of task ids.")
    if tasks:
        plan["tasks"] = list(tasks)

    # The subprocess must resolve custom:<id> specs from the same directory
    # the console validated them against.
    runtimes_dir_value = str(payload.get("runtimes_dir") or "").strip()
    if runtimes_dir_value:
        plan["runtimes_dir"] = runtimes_dir_value

    executor_agent = _require_agent(payload.get("executor_agent", "codex"), "Executor runtime")
    plan["executor_agent"] = executor_agent
    plan["evaluator_agent"] = _require_agent(
        payload.get("evaluator_agent", "codex"), "Evaluator runtime"
    )
    plan["judge_mode"] = _require_choice(
        payload.get("judge_mode", "single"), JUDGE_MODES, "Judge mode"
    )
    plan["auth_mode"] = _require_choice(payload.get("auth_mode", "env"), AUTH_MODES, "Auth mode")

    backend = _require_choice(payload.get("executor_backend", "local"), BACKENDS, "Executor backend")
    plan["executor_backend"] = backend
    docker_image = str(payload.get("docker_image") or "").strip()
    if backend == "docker":
        # Custom runtimes carry their image in the runtime spec's docker
        # section; --docker-image only applies to the builtin runtimes.
        if docker_image:
            plan["docker_image"] = docker_image
        elif not executor_agent.startswith("custom:"):
            raise LaunchError("Docker image is required when the executor backend is docker.")

    for key in (
        "codex_bin",
        "executor_bin",
        "evaluator_bin",
        "executor_model",
        "evaluator_model",
        "executor_auth_mode",
        "evaluator_auth_mode",
        "opencode_provider",
        "opencode_base_url",
        "opencode_api_key_env",
        "executor_opencode_provider",
        "executor_opencode_base_url",
        "executor_opencode_api_key_env",
        "evaluator_opencode_provider",
        "evaluator_opencode_base_url",
        "evaluator_opencode_api_key_env",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            if key.endswith("auth_mode"):
                value = _require_choice(value, AUTH_MODES, key)
            plan[key] = value

    thinking = str(payload.get("thinking_effort") or "").strip()
    if thinking and thinking != "none":
        plan["thinking_effort"] = _require_choice(thinking, THINKING_EFFORTS, "thinking effort")

    web_search = str(payload.get("web_search") or "").strip()
    if web_search and web_search != "task":
        plan["web_search"] = _require_choice(web_search, WEB_SEARCH_MODES, "web search mode")

    for key, minimum in (
        ("seed", 0),
        ("batch_size", 1),
        ("repeat", 1),
        ("max_evaluator_parallel", 1),
        ("claude_max_turns", 1),
        ("evaluator_timeout_seconds", 1),
    ):
        number = _optional_int(payload.get(key), key, minimum)
        if number is not None:
            plan[key] = number

    # Executor skills: the console picks skills and groups by name; the runner
    # installs them into the executor's workspace. Groups are passed through as
    # groups (the runner expands them), so the console must not also list a
    # group's members individually or the runner rejects the duplicate.
    skills = _string_list(payload.get("executor_skills"), "Executor skills")
    if skills:
        plan["executor_skills"] = skills
    skill_groups = _string_list(payload.get("executor_skill_groups"), "Executor skill groups")
    if skill_groups:
        plan["executor_skill_groups"] = skill_groups
    skill_root = str(payload.get("executor_skill_root") or "").strip()
    if skill_root:
        plan["executor_skill_root"] = skill_root

    # Instruction ablation: a research sweep over a task's human_reference expert
    # steps. `none` is the baseline and adds nothing; the other modes append the
    # expert instructions to the executor prompt (never the private `reasoning`).
    instruction_mode = str(payload.get("instruction_mode") or "none").strip()
    if instruction_mode and instruction_mode != "none":
        plan["instruction_mode"] = _require_choice(
            instruction_mode, INSTRUCTION_MODES, "Instruction mode"
        )
    steps = _string_list(payload.get("instruction_steps"), "Instruction steps")
    if steps:
        plan["instruction_steps"] = steps

    # Rigor injection: restate selected rubric-level requirements as hard
    # requirements in the executor prompt. `none` adds nothing; the runner also
    # infers select mode from any rigor id, but the mode is kept explicit.
    rigor_mode = str(payload.get("rigor_mode") or "none").strip()
    if rigor_mode and rigor_mode != "none":
        plan["rigor_mode"] = _require_choice(rigor_mode, RIGOR_MODES, "Rigor mode")
    rigors = _string_list(payload.get("rigors"), "Rigors")
    if rigors:
        plan["rigors"] = rigors

    return plan


def build_run_plan(payload: Dict[str, Any], *, runs_dir: Path) -> Dict[str, Any]:
    """Typed run_plan document for `starbench-run --plan` (the preferred
    transport). Free-form extra_args cannot ride a typed contract — callers
    with extra flags fall back to build_run_argv."""
    if str(payload.get("extra_args") or "").strip():
        raise LaunchError(
            "Extra CLI flags cannot ride a typed run plan; launch via argv instead."
        )
    plan = {"schema_version": 1, **_normalized_launch(payload, runs_dir=runs_dir)}
    # Belt and braces: the runner re-validates fail-closed, but an assembly bug
    # should surface here as a form error, not at launch.
    try:
        validate_payload("run_plan.schema.json", plan)
    except ContractValidationError as error:
        raise LaunchError(f"Assembled run plan violates its contract: {error}")
    return plan


def build_run_argv(payload: Dict[str, Any], *, runs_dir: Path) -> List[str]:
    """Translate the launch form payload into a starbench-run argv.

    Kept for launches that need free-form extra_args; plan-based launches use
    build_run_plan. The returned argv always starts with `sys.executable -m ...`
    so it works inside the same environment that is serving the console.
    """
    plan = _normalized_launch(payload, runs_dir=runs_dir)
    argv: List[str] = [
        sys.executable,
        "-m",
        "starbench.runner.run_benchmark",
        "--runs-dir",
        str(runs_dir),
        "--no-progress",
    ]
    for key, value in plan.items():
        if key in PLAN_LIST_FLAGS:
            for item in value:
                argv += [PLAN_LIST_FLAGS[key], str(item)]
            continue
        argv += ["--" + key.replace("_", "-"), str(value)]

    extra = str(payload.get("extra_args") or "").strip()
    if extra:
        try:
            argv += shlex.split(extra)
        except ValueError as error:
            raise LaunchError(f"Extra CLI flags are not parseable: {error}")

    return argv


def resolve_env_spec(spec: Any) -> Dict[str, str]:
    """Resolve {"VAR": {"value": "..."} | {"from_env": "SRC"}} into concrete
    values from the console's environment. Secrets never travel through the
    browser; only env-var names do."""
    resolved: Dict[str, str] = {}
    if not isinstance(spec, dict):
        return resolved
    for name, entry in spec.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            continue
        if "value" in entry:
            resolved[name] = str(entry["value"])
        elif "from_env" in entry:
            source = str(entry["from_env"] or "")
            value = os.environ.get(source, "")
            if value:
                resolved[name] = value
    return resolved


def scoped_launch_env(executor_spec: Any, judge_spec: Any) -> Dict[str, str]:
    """Namespace the executor and judge env specs under their scope prefixes.

    Each spec is resolved to concrete values (``resolve_env_spec``) and then
    prefixed with ``STARBENCH_EXECUTOR_ENV_`` / ``STARBENCH_JUDGE_ENV_`` so the
    runner can fold them into isolated executor/judge base envs (see
    ``runner.env_scope``). This keeps a contender's injected endpoint/credentials
    out of the judge's environment without ever putting a secret on argv (ps
    visible) or in a plaintext file — only values in the subprocess env travel.
    """
    env_extra: Dict[str, str] = {}
    for name, value in resolve_env_spec(executor_spec).items():
        env_extra[f"{EXECUTOR_ENV_PREFIX}{name}"] = value
    for name, value in resolve_env_spec(judge_spec).items():
        env_extra[f"{JUDGE_ENV_PREFIX}{name}"] = value
    return env_extra
