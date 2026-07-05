"""Build and supervise `starbench-run` subprocesses launched from the console."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters import list_builtin
from ..runner.env_scope import EXECUTOR_ENV_PREFIX, JUDGE_ENV_PREFIX
from .data import SAFE_ID

# Built-in runtime ids come from the adapter registry (single source of truth).
AGENT_CHOICES = tuple(adapter.info.id for adapter in list_builtin())
JUDGE_MODES = ("both", "single", "parallel")
AUTH_MODES = ("env", "global", "copy-auth")
BACKENDS = ("local", "docker")
THINKING_EFFORTS = ("none", "low", "medium", "high")


class LaunchError(ValueError):
    pass


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


def build_run_argv(payload: Dict[str, Any], *, runs_dir: Path) -> List[str]:
    """Translate the launch form payload into a starbench-run argv.

    Raises LaunchError with a user-readable message for anything invalid.
    The returned argv always starts with `sys.executable -m ...` so it works
    inside the same environment that is serving the console.
    """
    run_id = str(payload.get("run_id") or "").strip()
    if not SAFE_ID.match(run_id):
        raise LaunchError(
            "Run id is required and may contain only letters, digits, dot, dash, underscore."
        )
    if (runs_dir / run_id).exists():
        raise LaunchError(f"Run id already exists in {runs_dir}: {run_id}")

    tasks_dir = str(payload.get("tasks_dir") or "").strip()
    if not tasks_dir:
        raise LaunchError("Tasks directory is required.")
    if not Path(tasks_dir).is_dir():
        raise LaunchError(f"Tasks directory not found: {tasks_dir}")

    argv: List[str] = [
        sys.executable,
        "-m",
        "starbench.runner.run_benchmark",
        "--runs-dir",
        str(runs_dir),
        "--run-id",
        run_id,
        "--tasks-dir",
        tasks_dir,
        "--no-progress",
    ]

    tasks = payload.get("tasks") or []
    if not isinstance(tasks, list) or not all(isinstance(item, str) for item in tasks):
        raise LaunchError("Tasks must be a list of task ids.")
    for task in tasks:
        argv += ["--task", task]

    # The subprocess must resolve custom:<id> specs from the same directory
    # the console validated them against.
    runtimes_dir_value = str(payload.get("runtimes_dir") or "").strip()
    if runtimes_dir_value:
        argv += ["--runtimes-dir", runtimes_dir_value]

    executor_agent = _require_agent(payload.get("executor_agent", "codex"), "Executor runtime")
    argv += ["--executor-agent", executor_agent]
    argv += ["--evaluator-agent", _require_agent(payload.get("evaluator_agent", "codex"), "Evaluator runtime")]
    argv += ["--judge-mode", _require_choice(payload.get("judge_mode", "single"), JUDGE_MODES, "Judge mode")]
    argv += ["--auth-mode", _require_choice(payload.get("auth_mode", "env"), AUTH_MODES, "Auth mode")]

    backend = _require_choice(payload.get("executor_backend", "local"), BACKENDS, "Executor backend")
    argv += ["--executor-backend", backend]
    docker_image = str(payload.get("docker_image") or "").strip()
    if backend == "docker":
        # Custom runtimes carry their image in the runtime spec's docker
        # section; --docker-image only applies to codex/claude.
        if docker_image:
            argv += ["--docker-image", docker_image]
        elif not executor_agent.startswith("custom:"):
            raise LaunchError("Docker image is required when the executor backend is docker.")

    for key, flag in (
        ("codex_bin", "--codex-bin"),
        ("executor_model", "--executor-model"),
        ("evaluator_model", "--evaluator-model"),
        ("executor_auth_mode", "--executor-auth-mode"),
        ("evaluator_auth_mode", "--evaluator-auth-mode"),
        ("opencode_provider", "--opencode-provider"),
        ("opencode_base_url", "--opencode-base-url"),
        ("opencode_api_key_env", "--opencode-api-key-env"),
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            if key.endswith("auth_mode"):
                value = _require_choice(value, AUTH_MODES, flag)
            argv += [flag, value]

    thinking = str(payload.get("claude_thinking_effort") or "").strip()
    if thinking and thinking != "none":
        argv += [
            "--claude-thinking-effort",
            _require_choice(thinking, THINKING_EFFORTS, "Claude thinking effort"),
        ]

    for key, flag, minimum in (
        ("seed", "--seed", 0),
        ("batch_size", "--batch-size", 1),
        ("repeat", "--repeat", 1),
        ("max_evaluator_parallel", "--max-evaluator-parallel", 1),
        ("claude_max_turns", "--claude-max-turns", 1),
        ("evaluator_timeout_seconds", "--evaluator-timeout-seconds", 1),
    ):
        number = _optional_int(payload.get(key), flag, minimum)
        if number is not None:
            argv += [flag, str(number)]

    # Executor skills: the console picks skills and groups by name; the runner
    # installs them into the executor's workspace. Groups are passed through as
    # groups (the runner expands them), so the console must not also list a
    # group's members individually or the runner rejects the duplicate.
    for skill_id in _string_list(payload.get("executor_skills"), "Executor skills"):
        argv += ["--executor-skill", skill_id]
    for group_id in _string_list(payload.get("executor_skill_groups"), "Executor skill groups"):
        argv += ["--executor-skill-group", group_id]
    skill_root = str(payload.get("executor_skill_root") or "").strip()
    if skill_root:
        argv += ["--executor-skill-root", skill_root]

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


class LaunchRegistry:
    """Tracks starbench-run subprocesses started from this console process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._launches: Dict[str, Dict[str, Any]] = {}

    def launch(
        self,
        run_id: str,
        argv: List[str],
        *,
        cwd: Path,
        log_path: Path,
        env_extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            existing = self._launches.get(run_id)
            if existing and existing["process"].poll() is None:
                raise LaunchError(f"Run {run_id} is already in flight.")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("ab")
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=str(cwd),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env={**os.environ, **env_extra} if env_extra else None,
                )
            finally:
                log_handle.close()
            record = {
                "run_id": run_id,
                "argv": argv,
                "pid": process.pid,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "log_path": str(log_path),
                "process": process,
            }
            self._launches[run_id] = record
            return self._public(record)

    def _public(self, record: Dict[str, Any]) -> Dict[str, Any]:
        process = record["process"]
        exit_code = process.poll()
        return {
            "run_id": record["run_id"],
            "argv": record["argv"],
            "pid": record["pid"],
            "started_at": record["started_at"],
            "log_path": record["log_path"],
            "running": exit_code is None,
            "exit_code": exit_code,
        }

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [self._public(record) for record in self._launches.values()]

    def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._launches.get(run_id)
            return self._public(record) if record else None

    def active_run_ids(self) -> set:
        with self._lock:
            return {
                run_id
                for run_id, record in self._launches.items()
                if record["process"].poll() is None
            }

    def stop(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._launches.get(run_id)
            if record is None:
                raise LaunchError(f"No console-launched run named {run_id}.")
            process = record["process"]
            if process.poll() is None:
                process.terminate()
            return self._public(record)
