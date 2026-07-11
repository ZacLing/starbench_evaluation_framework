"""Persisted process-group supervision for console-launched runs.

The console owns exactly two files inside a run directory — run_state.json
(this module's ledger) and the .runner_claim reservation handshake; every run
artifact is written by the runner alone (see docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from ..fsio import atomic_write_json
from .errors import LaunchError


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
        atomic_write_json(path, payload, indent=2, sort_keys=True)

    # Flags whose value may be a console-created temp file, and the mkstemp
    # prefix proving it is ours to delete. Operator-provided paths never match.
    _LAUNCH_TEMP_FLAGS = {
        "--plan": "starbench-plan-",
        "--profile-snapshot": "starbench-profile-snapshot-",
    }

    @classmethod
    def _launch_temp_paths(cls, argv: Any) -> List[Path]:
        """Console-created temp files named on argv (plan / snapshot)."""
        if not isinstance(argv, list):
            return []
        paths: List[Path] = []
        for index, token in enumerate(argv[:-1]):
            prefix = cls._LAUNCH_TEMP_FLAGS.get(str(token))
            if prefix is None:
                continue
            candidate = Path(str(argv[index + 1]))
            if candidate.name.startswith(prefix):
                paths.append(candidate)
        return paths

    def _cleanup_snapshot(self, record: Dict[str, Any]) -> None:
        """Best-effort removal of the launch's temp files at terminal state —
        the runner has long since materialized them into the run root."""
        for path in self._launch_temp_paths(record.get("argv")):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

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
            actual = result.stdout.strip()
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0 or not actual:
            return False
        # Two realities of ps output shape this comparison:
        # - ps space-joins the argument vector without quoting, so an argv item
        #   containing a space (a tasks dir like "My Tasks") must be compared
        #   as a joined string; token-splitting the output would split that
        #   item in two and orphan a live run at reconcile.
        # - interpreters may rewrite argv[0] (macOS framework Python re-execs
        #   the venv stub as .../Python.app/Contents/MacOS/Python), so the
        #   first element cannot be compared literally.
        items = [str(item) for item in expected]
        tail = " ".join(items[1:])
        if tail:
            return actual == " ".join(items) or actual.endswith(" " + tail)
        return actual == items[0] or actual.rsplit("/", 1)[-1] == items[0].rsplit("/", 1)[-1]

    def _state_payload(self, record: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "run_id",
            "state",
            "batch",
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

    def _persist_best_effort(self, record: Dict[str, Any]) -> None:
        """Persist from a monitor thread: a transient disk error must not kill
        the thread, or the on-disk state freezes at "running" with a heartbeat
        nobody will ever refresh."""
        try:
            self._persist(record)
        except OSError:
            pass

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
                self._cleanup_snapshot(record)
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
                    self._cleanup_snapshot(record)

    def prepare(
        self,
        run_id: str,
        argv: List[str],
        *,
        cwd: Path,
        log_path: Path,
        env_extra: Optional[Dict[str, str]] = None,
        batch: Optional[str] = None,
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
                # The launch batch this run belongs to (runs launched together
                # share it). Purely descriptive: comparisons are stateless.
                "batch": batch,
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
        batch: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.prepare(
            run_id, argv, cwd=cwd, log_path=log_path, env_extra=env_extra, batch=batch
        )
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
                    self._persist_best_effort(record)
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
                self._persist_best_effort(record)
                self._cleanup_snapshot(record)
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
                # Identity, not just existence: once the adopted process dies,
                # its pgid can be recycled within one poll interval and would
                # otherwise be heartbeaten as ours forever.
                if not (
                    self._group_alive(record.get("pgid")) and self._process_matches(record)
                ):
                    record["state"] = (
                        "completed" if (record["run_root"] / "summary.json").is_file() else "exited"
                    )
                    record["ended_at"] = self._utc_now()
                    self._persist_best_effort(record)
                    self._cleanup_snapshot(record)
                    return
                record["heartbeat_at"] = self._utc_now()
                self._persist_best_effort(record)

    def _is_running(self, record: Dict[str, Any]) -> bool:
        # Terminal records keep their recorded pgid forever; the OS recycles
        # pids. Bare group existence must therefore never resurrect a run:
        # only active-state records count, and adopted records (no Popen
        # handle after a console restart) must also still match the launch
        # argv before their group is believed.
        if record.get("state") not in ACTIVE_RUN_STATES:
            return False
        process = record.get("process")
        if process is not None:
            return process.poll() is None
        return self._group_alive(record.get("pgid")) and self._process_matches(record)

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
            # Signals may only be aimed at a group we can prove is still ours.
            # A record without a live Popen handle (adopted after a console
            # restart, or long terminal) could name a pgid the OS has recycled
            # to an innocent process group — re-verify identity before TERM.
            process = record.get("process")
            owns_group = (
                process is not None and process.poll() is None
            ) or (self._group_alive(pgid) and self._process_matches(record))
            record["state"] = "stopping" if (pgid and owns_group) else final_state
            record["stop_requested_at"] = self._utc_now()
            self._persist(record)

        signal_errors: List[str] = []
        if owns_group and self._group_alive(pgid):
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
            # A recycled pgid that failed the ownership check is not "still
            # running" — the run's own processes are provably gone.
            still_running = owns_group and self._group_alive(pgid)
            record["state"] = "orphaned" if still_running else final_state
            record["ended_at"] = self._utc_now()
            record["docker_cleanup"] = docker_cleanup
            if still_running:
                signal_errors.append("Process group survived SIGTERM and SIGKILL.")
            if signal_errors:
                record["error"] = " ".join(signal_errors)
            self._persist(record)
            if not still_running:
                self._cleanup_snapshot(record)
            return self._public(record)

    def rollback(self, run_ids: List[str]) -> None:
        for run_id in reversed(run_ids):
            try:
                self.stop(run_id, final_state="rolled_back")
            except LaunchError:
                continue
            self._discard_unclaimed(run_id)

    def _discard_unclaimed(self, run_id: str) -> None:
        """Remove a rolled-back reservation directory the runner never claimed.

        A failed transaction would otherwise leave a run directory holding
        nothing but ``run_state.json`` — rendered forever as a phantom
        interrupted run and permanently burning the run id. Once the runner
        has claimed the directory (``.runner_claim``) or written anything
        else, the directory is evidence and stays. The in-memory launch
        record survives either way so /api/launches still explains why the
        transaction failed; the launch log lives outside the run directory."""
        with self._lock:
            record = self._launches.get(run_id)
            if record is None or record.get("state") != "rolled_back":
                return
            run_root = record.get("run_root")
            if not isinstance(run_root, Path):
                return
            try:
                leftovers = [path.name for path in run_root.iterdir()]
            except OSError:
                return
            if set(leftovers) - {RUN_STATE_FILENAME}:
                return
            try:
                (run_root / RUN_STATE_FILENAME).unlink(missing_ok=True)
                run_root.rmdir()
            except OSError:
                return

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
