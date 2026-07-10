from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from starbench.domain import RUN_LAUNCH_TOKEN_ENV, RUN_STATE_FILENAME
from starbench.execution.docker import build_docker_agent_command
from starbench.gui.launcher import LaunchError, LaunchRegistry, launch_transaction
from starbench.runner.orchestrator import claim_run_root


class SupervisorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_supervisor_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.worker = self.tmp / "worker.py"
        self.worker.write_text(
            textwrap.dedent(
                """
                import subprocess
                import sys
                import time
                from pathlib import Path

                child = subprocess.Popen(
                    [sys.executable, "-c", "import time; time.sleep(60)"]
                )
                Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
                time.sleep(60)
                """
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _pid_running(pid: int) -> bool:
        try:
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "stat="],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        state = result.stdout.strip()
        return result.returncode == 0 and bool(state) and not state.startswith("Z")

    def _wait_for_file(self, path: Path) -> None:
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(path.exists(), f"Timed out waiting for {path}")

    def _worker_argv(self, child_pid_path: Path) -> list[str]:
        return [
            sys.executable,
            str(self.worker),
            str(child_pid_path),
            "--executor-backend",
            "local",
        ]

    def test_stop_terminates_the_complete_process_group(self) -> None:
        child_pid_path = self.tmp / "child.pid"
        registry = LaunchRegistry(self.runs_dir, stop_timeout_seconds=1)
        launch = registry.launch(
            "tree_run",
            self._worker_argv(child_pid_path),
            cwd=self.tmp,
            log_path=self.runs_dir / "tree_run.launch.log",
        )
        self._wait_for_file(child_pid_path)
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))
        self.assertTrue(self._pid_running(launch["pid"]))
        self.assertTrue(self._pid_running(child_pid))

        stopped = registry.stop("tree_run")

        self.assertFalse(stopped["running"])
        self.assertEqual(stopped["state"], "stopped")
        self.assertFalse(self._pid_running(launch["pid"]))
        self.assertFalse(self._pid_running(child_pid))
        state = json.loads(
            (self.runs_dir / "tree_run" / RUN_STATE_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(state["state"], "stopped")
        self.assertEqual(state["pgid"], launch["pgid"])

    def test_reconcile_recovers_control_after_console_restart(self) -> None:
        child_pid_path = self.tmp / "recovered-child.pid"
        original = LaunchRegistry(self.runs_dir, stop_timeout_seconds=1)
        original._start_process_monitor = lambda *_args: None
        launch = original.launch(
            "recover_run",
            self._worker_argv(child_pid_path),
            cwd=self.tmp,
            log_path=self.runs_dir / "recover_run.launch.log",
        )
        self._wait_for_file(child_pid_path)

        recovered = LaunchRegistry(self.runs_dir, stop_timeout_seconds=1)
        self.assertIn("recover_run", recovered.active_run_ids())
        self.assertEqual(recovered.get("recover_run")["pgid"], launch["pgid"])

        stopped = recovered.stop("recover_run")
        original._launches["recover_run"]["process"].wait(timeout=2)
        self.assertEqual(stopped["state"], "stopped")
        self.assertFalse(stopped["running"])

    def test_reconcile_preserves_explicit_stop_state_when_summary_exists(self) -> None:
        run_root = self.runs_dir / "stopped_run"
        run_root.mkdir()
        (run_root / "summary.json").write_text("{}\n", encoding="utf-8")
        (run_root / RUN_STATE_FILENAME).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "stopped_run",
                    "state": "stopped",
                    "argv": [sys.executable, "-c", "pass"],
                    "updated_at": "2026-01-01T00:00:00+00:00",
                    "log_path": str(self.runs_dir / "stopped_run.launch.log"),
                    "reservation_token": "a" * 32,
                }
            ),
            encoding="utf-8",
        )

        recovered = LaunchRegistry(self.runs_dir)

        self.assertEqual(recovered.get("stopped_run")["state"], "stopped")

    def test_transaction_rolls_back_an_already_started_run(self) -> None:
        child_pid_path = self.tmp / "transaction-child.pid"
        registry = LaunchRegistry(self.runs_dir, stop_timeout_seconds=1)
        launches = [
            {
                "run_id": "first_run",
                "argv": self._worker_argv(child_pid_path),
                "cwd": self.tmp,
                "log_path": self.runs_dir / "first_run.launch.log",
            },
            {
                "run_id": "second_run",
                "argv": [str(self.tmp / "missing-executable")],
                "cwd": self.tmp,
                "log_path": self.runs_dir / "second_run.launch.log",
            },
        ]

        with self.assertRaisesRegex(LaunchError, "Could not launch run second_run"):
            launch_transaction(registry, launches)

        first = registry.get("first_run")
        second = registry.get("second_run")
        self.assertFalse(first["running"])
        self.assertEqual(first["state"], "rolled_back")
        self.assertEqual(second["state"], "rolled_back")

    def test_runner_only_adopts_the_matching_reservation(self) -> None:
        registry = LaunchRegistry(self.runs_dir)
        registry.prepare(
            "reserved_run",
            [sys.executable, "-c", "pass"],
            cwd=self.tmp,
            log_path=self.runs_dir / "reserved_run.launch.log",
        )
        state = json.loads(
            (self.runs_dir / "reserved_run" / RUN_STATE_FILENAME).read_text(encoding="utf-8")
        )
        with mock.patch.dict(
            os.environ, {RUN_LAUNCH_TOKEN_ENV: state["reservation_token"]}, clear=False
        ):
            claimed = claim_run_root(self.runs_dir, "reserved_run")
        self.assertEqual(claimed, self.runs_dir / "reserved_run")

        with mock.patch.dict(
            os.environ, {RUN_LAUNCH_TOKEN_ENV: state["reservation_token"]}, clear=False
        ):
            with self.assertRaisesRegex(SystemExit, "already been claimed"):
                claim_run_root(self.runs_dir, "reserved_run")

        with mock.patch.dict(os.environ, {RUN_LAUNCH_TOKEN_ENV: "wrong"}, clear=False):
            with self.assertRaises(SystemExit):
                claim_run_root(self.runs_dir, "reserved_run")

    def test_reconcile_ignores_malformed_persisted_state(self) -> None:
        run_root = self.runs_dir / "malformed"
        run_root.mkdir()
        (run_root / RUN_STATE_FILENAME).write_text(
            json.dumps({"run_id": "malformed", "state": "running"}),
            encoding="utf-8",
        )

        registry = LaunchRegistry(self.runs_dir)

        self.assertIsNone(registry.get("malformed"))

    def test_stop_all_closes_a_prepared_reservation(self) -> None:
        registry = LaunchRegistry(self.runs_dir)
        registry.prepare(
            "prepared_run",
            [sys.executable, "-c", "pass"],
            cwd=self.tmp,
            log_path=self.runs_dir / "prepared_run.launch.log",
        )

        stopped = registry.stop_all()

        self.assertEqual([item["run_id"] for item in stopped], ["prepared_run"])
        self.assertEqual(registry.get("prepared_run")["state"], "stopped")

    def test_prepare_removes_reservation_when_state_persistence_fails(self) -> None:
        registry = LaunchRegistry(self.runs_dir)
        with mock.patch.object(registry, "_persist", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                registry.prepare(
                    "failed_prepare",
                    [sys.executable, "-c", "pass"],
                    cwd=self.tmp,
                    log_path=self.runs_dir / "failed_prepare.launch.log",
                )

        self.assertIsNone(registry.get("failed_prepare"))
        self.assertFalse((self.runs_dir / "failed_prepare").exists())

    def test_docker_commands_are_labeled_for_supervisor_cleanup(self) -> None:
        command = build_docker_agent_command(
            docker_bin="docker",
            docker_image="image:latest",
            workspace=self.tmp / "workspace",
            inner_command=["agent"],
            env_whitelist=[],
            auth_env={"STARBENCH_RUN_ID": "labeled_run"},
        )
        joined = " ".join(command)
        self.assertIn("--label starbench.managed=true", joined)
        self.assertIn("--label starbench.run_id=labeled_run", joined)

    def test_docker_cleanup_stops_then_kills_only_survivors(self) -> None:
        registry = LaunchRegistry(self.runs_dir, stop_timeout_seconds=1)
        registry.prepare(
            "docker_run",
            [
                sys.executable,
                "-c",
                "pass",
                "--executor-backend",
                "docker",
            ],
            cwd=self.tmp,
            log_path=self.runs_dir / "docker_run.launch.log",
        )
        completed = subprocess.CompletedProcess
        responses = [
            completed([], 0, stdout="container-a\ncontainer-b\n", stderr=""),
            completed([], 0, stdout="", stderr=""),
            completed([], 0, stdout="container-b\n", stderr=""),
            completed([], 0, stdout="", stderr=""),
        ]
        with mock.patch(
            "starbench.gui.launcher.subprocess.run", side_effect=responses
        ) as run:
            stopped = registry.stop("docker_run")

        self.assertEqual(
            stopped["docker_cleanup"],
            {
                "matched": ["container-a", "container-b"],
                "stopped": ["container-a"],
                "killed": ["container-b"],
                "errors": [],
            },
        )
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn("stop", commands[1])
        self.assertEqual(commands[3][-2:], ["kill", "container-b"])


if __name__ == "__main__":
    unittest.main()
