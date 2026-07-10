"""Build and supervise `starbench-run` subprocesses launched from the console."""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..adapters import list_builtin
from ..contracts import (
    ARTIFACT_SCHEMA_VERSION,
    ContractValidationError,
    validate_payload,
)
from ..domain import (
    ACTIVE_RUN_STATES,
    RUN_ID_ENV,
    RUN_LAUNCH_TOKEN_ENV,
    RUN_STATE_FILENAME,
    safe_child,
)
from ..execution.process import split_command
from ..runner.env_scope import EXECUTOR_ENV_PREFIX, JUDGE_ENV_PREFIX
from .data import SAFE_ID

# Built-in runtime ids come from the adapter registry (single source of truth).
AGENT_CHOICES = tuple(adapter.info.id for adapter in list_builtin())
JUDGE_MODES = ("both", "single", "parallel")
AUTH_MODES = ("env", "global", "copy-auth")
BACKENDS = ("local", "docker")
THINKING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
WEB_SEARCH_MODES = ("task", "allow", "deny")
INSTRUCTION_MODES = ("none", "traverse", "select", "ablation")
RIGOR_MODES = ("none", "select")


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
        ("executor_bin", "--executor-bin"),
        ("evaluator_bin", "--evaluator-bin"),
        ("executor_model", "--executor-model"),
        ("evaluator_model", "--evaluator-model"),
        ("executor_auth_mode", "--executor-auth-mode"),
        ("evaluator_auth_mode", "--evaluator-auth-mode"),
        ("opencode_provider", "--opencode-provider"),
        ("opencode_base_url", "--opencode-base-url"),
        ("opencode_api_key_env", "--opencode-api-key-env"),
        ("executor_opencode_provider", "--executor-opencode-provider"),
        ("executor_opencode_base_url", "--executor-opencode-base-url"),
        ("executor_opencode_api_key_env", "--executor-opencode-api-key-env"),
        ("evaluator_opencode_provider", "--evaluator-opencode-provider"),
        ("evaluator_opencode_base_url", "--evaluator-opencode-base-url"),
        ("evaluator_opencode_api_key_env", "--evaluator-opencode-api-key-env"),
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            if key.endswith("auth_mode"):
                value = _require_choice(value, AUTH_MODES, flag)
            argv += [flag, value]

    thinking = str(payload.get("thinking_effort") or "").strip()
    if thinking and thinking != "none":
        argv += [
            "--thinking-effort",
            _require_choice(thinking, THINKING_EFFORTS, "thinking effort"),
        ]

    web_search = str(payload.get("web_search") or "").strip()
    if web_search and web_search != "task":
        argv += [
            "--web-search",
            _require_choice(web_search, WEB_SEARCH_MODES, "web search mode"),
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

    # Instruction ablation: a research sweep over a task's human_reference expert
    # steps. `none` is the baseline and passes no flag; the other modes append
    # the expert instructions to the executor prompt (never the private
    # `reasoning`). `--instruction-step` ids are repeated — they bundle the
    # chosen steps in `select` mode and narrow the sweep in `ablation` mode.
    instruction_mode = str(payload.get("instruction_mode") or "none").strip()
    if instruction_mode and instruction_mode != "none":
        argv += [
            "--instruction-mode",
            _require_choice(instruction_mode, INSTRUCTION_MODES, "Instruction mode"),
        ]
    for step_id in _string_list(payload.get("instruction_steps"), "Instruction steps"):
        argv += ["--instruction-step", step_id]

    # Rigor injection: a research knob that restates selected rubric-level
    # requirements as hard requirements in the executor prompt. `none` is the
    # default and passes no flag; `select` appends one `--rigor` per chosen id
    # (the runner also infers select mode from any `--rigor`, but we pass the
    # mode explicitly so the argv reads unambiguously).
    rigor_mode = str(payload.get("rigor_mode") or "none").strip()
    if rigor_mode and rigor_mode != "none":
        argv += ["--rigor-mode", _require_choice(rigor_mode, RIGOR_MODES, "Rigor mode")]
    for rigor_id in _string_list(payload.get("rigors"), "Rigors"):
        argv += ["--rigor", rigor_id]

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
    """Persisted process-group supervisor for console-launched runs."""

    def __init__(self, runs_dir: Path, *, stop_timeout_seconds: float = 3.0) -> None:
        self.runs_dir = runs_dir.resolve()
        self.stop_timeout_seconds = stop_timeout_seconds
        self._lock = threading.RLock()
        self._launches: Dict[str, Dict[str, Any]] = {}
        self._reconcile()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            os.replace(tmp_name, path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    @staticmethod
    def _group_alive(pgid: Any) -> bool:
        if not isinstance(pgid, int) or pgid <= 0 or pgid == os.getpgrp():
            return False
        try:
            result = subprocess.run(
                ["ps", "-ax", "-o", "pgid=,stat="],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    fields = line.split()
                    if len(fields) >= 2 and fields[0].isdigit():
                        if int(fields[0]) == pgid and not fields[1].startswith("Z"):
                            return True
                return False
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def _process_matches(record: Dict[str, Any]) -> bool:
        """Reject stale/PID-reused state before adopting a process group."""

        pid = record.get("pid")
        expected = record.get("argv")
        if not isinstance(pid, int) or not isinstance(expected, list) or not expected:
            return False
        try:
            result = subprocess.run(
                ["ps", "-ww", "-p", str(pid), "-o", "command="],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
            actual = shlex.split(result.stdout.strip())
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        expected = [str(item) for item in expected]
        return result.returncode == 0 and actual[: len(expected)] == expected

    def _state_payload(self, record: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "run_id",
            "state",
            "argv",
            "pid",
            "pgid",
            "started_at",
            "updated_at",
            "heartbeat_at",
            "ended_at",
            "exit_code",
            "log_path",
            "reservation_token",
            "stop_requested_at",
            "error",
            "docker_cleanup",
        )
        return {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            **{key: record.get(key) for key in keys if record.get(key) is not None},
        }

    def _persist(self, record: Dict[str, Any]) -> None:
        record["updated_at"] = self._utc_now()
        self._atomic_write_json(record["state_path"], self._state_payload(record))

    def _reconcile(self) -> None:
        if not self.runs_dir.is_dir():
            return
        for run_root in self.runs_dir.iterdir():
            state_path = run_root / RUN_STATE_FILENAME
            if not run_root.is_dir() or not state_path.is_file():
                continue
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                validate_payload("run_state.schema.json", payload)
            except (OSError, ValueError, ContractValidationError):
                continue
            if not isinstance(payload, dict) or payload.get("run_id") != run_root.name:
                continue
            record = {
                **payload,
                "state_path": state_path,
                "run_root": run_root,
                "process": None,
                "env_extra": None,
            }
            self._launches[run_root.name] = record
            # A completed artifact may race with a stop/rollback request.  The
            # explicit operator/transaction terminal state wins on restart;
            # otherwise a normal process exit with a summary is completed.
            if (
                (run_root / "summary.json").is_file()
                and record.get("state")
                not in {"stopped", "rolled_back", "launch_failed", "orphaned"}
            ):
                record["state"] = "completed"
                self._persist(record)
            elif record.get("state") in ACTIVE_RUN_STATES:
                if self._group_alive(record.get("pgid")) and self._process_matches(record):
                    record["state"] = "running"
                    record["heartbeat_at"] = self._utc_now()
                    self._persist(record)
                    self._start_reconciled_monitor(run_root.name)
                else:
                    record["state"] = "orphaned"
                    record["ended_at"] = self._utc_now()
                    record["error"] = (
                        "Recorded process group no longer exists or its process identity changed."
                    )
                    self._persist(record)

    def prepare(
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
            if existing and self._is_running(existing):
                raise LaunchError(f"Run {run_id} is already in flight.")
            run_root = safe_child(self.runs_dir, run_id, kind="run id")
            try:
                run_root.mkdir(parents=True, exist_ok=False)
            except FileExistsError as error:
                raise LaunchError(f"Run id already exists in {self.runs_dir}: {run_id}") from error
            now = self._utc_now()
            record = {
                "run_id": run_id,
                "state": "prepared",
                "argv": list(argv),
                "pid": None,
                "pgid": None,
                "started_at": None,
                "updated_at": now,
                "heartbeat_at": now,
                "ended_at": None,
                "exit_code": None,
                "log_path": str(log_path),
                "reservation_token": uuid.uuid4().hex,
                "state_path": run_root / RUN_STATE_FILENAME,
                "run_root": run_root,
                "cwd": cwd,
                "env_extra": dict(env_extra or {}),
                "process": None,
            }
            self._launches[run_id] = record
            try:
                self._persist(record)
            except Exception:
                self._launches.pop(run_id, None)
                try:
                    run_root.rmdir()
                except OSError:
                    pass
                raise
            return self._public(record)

    def commit(self, run_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._launches.get(run_id)
            if record is None or record.get("state") != "prepared":
                raise LaunchError(f"Run {run_id} has not been prepared.")
            record["state"] = "starting"
            self._persist(record)
            log_path = Path(record["log_path"])
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("ab")
            env = {
                **os.environ,
                **(record.get("env_extra") or {}),
                RUN_LAUNCH_TOKEN_ENV: record["reservation_token"],
                RUN_ID_ENV: run_id,
            }
            try:
                process = subprocess.Popen(
                    record["argv"],
                    cwd=str(record["cwd"]),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                )
            except Exception as error:
                record["state"] = "launch_failed"
                record["ended_at"] = self._utc_now()
                record["error"] = f"{type(error).__name__}: {error}"
                self._persist(record)
                raise LaunchError(f"Could not launch run {run_id}: {error}") from error
            finally:
                log_handle.close()
            record["process"] = process
            record["pid"] = process.pid
            record["pgid"] = process.pid
            record["started_at"] = self._utc_now()
            record["heartbeat_at"] = record["started_at"]
            record["state"] = "running"
            self._persist(record)
            self._start_process_monitor(run_id, process)
            return self._public(record)

    def launch(
        self,
        run_id: str,
        argv: List[str],
        *,
        cwd: Path,
        log_path: Path,
        env_extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        self.prepare(run_id, argv, cwd=cwd, log_path=log_path, env_extra=env_extra)
        try:
            return self.commit(run_id)
        except Exception:
            self.rollback([run_id])
            raise

    def _start_process_monitor(self, run_id: str, process: subprocess.Popen) -> None:
        thread = threading.Thread(
            target=self._monitor_process,
            args=(run_id, process),
            daemon=True,
            name=f"starbench-run-{run_id}",
        )
        thread.start()

    def _monitor_process(self, run_id: str, process: subprocess.Popen) -> None:
        while True:
            try:
                exit_code = process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                with self._lock:
                    record = self._launches.get(run_id)
                    if record is None or record.get("process") is not process:
                        return
                    record["heartbeat_at"] = self._utc_now()
                    self._persist(record)
                continue
            with self._lock:
                record = self._launches.get(run_id)
                if record is None or record.get("process") is not process:
                    return
                if record.get("state") not in {"stopped", "rolled_back", "orphaned"}:
                    record["state"] = (
                        "completed" if (record["run_root"] / "summary.json").is_file() else "exited"
                    )
                record["exit_code"] = exit_code
                record["ended_at"] = record.get("ended_at") or self._utc_now()
                self._persist(record)
            return

    def _start_reconciled_monitor(self, run_id: str) -> None:
        thread = threading.Thread(
            target=self._monitor_reconciled,
            args=(run_id,),
            daemon=True,
            name=f"starbench-reconcile-{run_id}",
        )
        thread.start()

    def _monitor_reconciled(self, run_id: str) -> None:
        while True:
            time.sleep(1.0)
            with self._lock:
                record = self._launches.get(run_id)
                if record is None or record.get("state") not in ACTIVE_RUN_STATES:
                    return
                if not self._group_alive(record.get("pgid")):
                    record["state"] = (
                        "completed" if (record["run_root"] / "summary.json").is_file() else "exited"
                    )
                    record["ended_at"] = self._utc_now()
                    self._persist(record)
                    return
                record["heartbeat_at"] = self._utc_now()
                self._persist(record)

    def _is_running(self, record: Dict[str, Any]) -> bool:
        return self._group_alive(record.get("pgid"))

    def _public(self, record: Dict[str, Any]) -> Dict[str, Any]:
        process = record.get("process")
        exit_code = process.poll() if process is not None else record.get("exit_code")
        return {
            "run_id": record["run_id"],
            "state": record.get("state"),
            "argv": record["argv"],
            "pid": record.get("pid"),
            "pgid": record.get("pgid"),
            "started_at": record.get("started_at"),
            "log_path": record["log_path"],
            "running": self._is_running(record),
            "exit_code": exit_code,
            "docker_cleanup": record.get("docker_cleanup"),
            "error": record.get("error"),
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
                if self._is_running(record)
            }

    @staticmethod
    def _docker_bin(argv: List[str]) -> str:
        if "--docker-bin" in argv:
            index = argv.index("--docker-bin")
            if index + 1 < len(argv):
                return argv[index + 1]
        return "docker"

    def _stop_docker_containers(self, record: Dict[str, Any]) -> Dict[str, Any]:
        cleanup: Dict[str, Any] = {
            "matched": [],
            "stopped": [],
            "killed": [],
            "errors": [],
        }
        argv = record.get("argv") or []
        if "--executor-backend" not in argv:
            return cleanup
        backend_index = argv.index("--executor-backend")
        if backend_index + 1 >= len(argv) or argv[backend_index + 1] != "docker":
            return cleanup
        try:
            docker = split_command(self._docker_bin(record.get("argv") or []))
        except ValueError as error:
            cleanup["errors"].append(f"Invalid docker command: {error}")
            return cleanup

        list_command = docker + [
            "ps",
            "-q",
            "--filter",
            "label=starbench.managed=true",
            "--filter",
            f"label=starbench.run_id={record['run_id']}",
        ]

        def list_running() -> List[str]:
            listed = subprocess.run(
                list_command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if listed.returncode != 0:
                detail = listed.stderr.strip() or f"exit {listed.returncode}"
                raise RuntimeError(f"docker ps failed: {detail}")
            return listed.stdout.split()

        try:
            container_ids = list_running()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            cleanup["errors"].append(str(error))
            return cleanup
        cleanup["matched"] = container_ids
        if not container_ids:
            return cleanup

        grace_seconds = str(max(1, int(self.stop_timeout_seconds)))
        try:
            stopped = subprocess.run(
                docker + ["stop", "--time", grace_seconds, *container_ids],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.stop_timeout_seconds + 5,
            )
            if stopped.returncode != 0:
                detail = stopped.stderr.strip() or f"exit {stopped.returncode}"
                cleanup["errors"].append(f"docker stop failed: {detail}")
        except (OSError, subprocess.TimeoutExpired) as error:
            cleanup["errors"].append(f"docker stop failed: {error}")

        try:
            survivors = list_running()
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            cleanup["errors"].append(str(error))
            survivors = list(container_ids)
        cleanup["stopped"] = [item for item in container_ids if item not in survivors]

        if survivors:
            try:
                killed = subprocess.run(
                    docker + ["kill", *survivors],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if killed.returncode == 0:
                    cleanup["killed"] = survivors
                else:
                    detail = killed.stderr.strip() or f"exit {killed.returncode}"
                    cleanup["errors"].append(f"docker kill failed: {detail}")
            except (OSError, subprocess.TimeoutExpired) as error:
                cleanup["errors"].append(f"docker kill failed: {error}")
        return cleanup

    def stop(self, run_id: str, *, final_state: str = "stopped") -> Dict[str, Any]:
        with self._lock:
            record = self._launches.get(run_id)
            if record is None:
                raise LaunchError(f"No console-launched run named {run_id}.")
            pgid = record.get("pgid")
            record["state"] = "stopping" if pgid else final_state
            record["stop_requested_at"] = self._utc_now()
            self._persist(record)

        signal_errors: List[str] = []
        if self._group_alive(pgid):
            try:
                os.killpg(pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                signal_errors.append(f"SIGTERM denied for process group {pgid}: {error}")
            deadline = time.monotonic() + self.stop_timeout_seconds
            while self._group_alive(pgid) and time.monotonic() < deadline:
                process = record.get("process")
                if process is not None:
                    process.poll()
                time.sleep(0.05)
            if self._group_alive(pgid):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError as error:
                    signal_errors.append(f"SIGKILL denied for process group {pgid}: {error}")
                deadline = time.monotonic() + self.stop_timeout_seconds
                while self._group_alive(pgid) and time.monotonic() < deadline:
                    process = record.get("process")
                    if process is not None:
                        process.poll()
                    time.sleep(0.05)

        docker_cleanup = self._stop_docker_containers(record)
        with self._lock:
            process = record.get("process")
            if process is not None:
                try:
                    record["exit_code"] = process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    record["exit_code"] = process.poll()
            still_running = self._group_alive(pgid)
            record["state"] = "orphaned" if still_running else final_state
            record["ended_at"] = self._utc_now()
            record["docker_cleanup"] = docker_cleanup
            if still_running:
                signal_errors.append("Process group survived SIGTERM and SIGKILL.")
            if signal_errors:
                record["error"] = " ".join(signal_errors)
            self._persist(record)
            return self._public(record)

    def rollback(self, run_ids: List[str]) -> None:
        for run_id in reversed(run_ids):
            try:
                self.stop(run_id, final_state="rolled_back")
            except LaunchError:
                continue

    def stop_all(self) -> List[Dict[str, Any]]:
        stopped: List[Dict[str, Any]] = []
        with self._lock:
            run_ids = sorted(
                run_id
                for run_id, record in self._launches.items()
                if record.get("state") in ACTIVE_RUN_STATES
            )
        for run_id in run_ids:
            try:
                stopped.append(self.stop(run_id))
            except LaunchError:
                continue
        return stopped


def launch_transaction(
    registry: LaunchRegistry, launches: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Reserve every run before starting any, then rollback all on failure."""

    prepared: List[str] = []
    try:
        for launch in launches:
            registry.prepare(**launch)
            prepared.append(launch["run_id"])
        return [registry.commit(run_id) for run_id in prepared]
    except Exception:
        registry.rollback(prepared)
        raise
