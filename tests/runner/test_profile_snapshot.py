"""--profile-snapshot: fail-closed validation and atomic delivery into the run root.

Two disciplines under test:
- A valid snapshot lands as ``<run-root>/profile_snapshot.json`` byte-equal in
  content to what was passed (the runner alone writes run artifacts; the
  console supervisor owns only ``run_state.json`` and ``.runner_claim``).
- Anything invalid (unreadable file, broken JSON, contract violation) aborts
  the start before a run directory exists — never a silent drop, never half a
  run on disk.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from contracts.test_artifact_schemas import fake_codex_script
from contracts.test_profile_snapshot_contract import valid_snapshot
from helpers import DEMO_TASK, ROOT

from starbench.contracts import validate_payload
from starbench.runner.cli import parse_args


class ProfileSnapshotCliValidationTests(unittest.TestCase):
    """parse_args validates the snapshot before any run directory exists."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_profile_snapshot_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runs_dir = self.tmp / "runs"

    def argv(self, snapshot_path: Path) -> list:
        return [
            "--tasks-dir",
            str(DEMO_TASK.parent),
            "--runs-dir",
            str(self.runs_dir),
            "--run-id",
            "snapshot_run",
            "--profile-snapshot",
            str(snapshot_path),
        ]

    def parse_expecting_error(self, snapshot_path: Path) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                parse_args(self.argv(snapshot_path))
        self.assertNotEqual(ctx.exception.code, 0)
        # Fail closed means fail early: nothing was created under runs/.
        self.assertFalse(self.runs_dir.exists())
        return stderr.getvalue()

    def test_valid_snapshot_is_parsed_and_kept(self) -> None:
        path = self.tmp / "snapshot.json"
        path.write_text(json.dumps(valid_snapshot()), encoding="utf-8")
        args = parse_args(self.argv(path))
        self.assertEqual(args.profile_snapshot_data, valid_snapshot())

    def test_absent_flag_keeps_data_none(self) -> None:
        args = parse_args(self.argv(self.tmp / "unused.json")[:-2])
        self.assertIsNone(args.profile_snapshot_data)

    def test_missing_file_aborts_start(self) -> None:
        message = self.parse_expecting_error(self.tmp / "ghost.json")
        self.assertIn("cannot read", message)

    def test_invalid_json_aborts_start(self) -> None:
        path = self.tmp / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        message = self.parse_expecting_error(path)
        self.assertIn("not valid JSON", message)

    def test_contract_violation_aborts_start(self) -> None:
        snapshot = valid_snapshot()
        snapshot["contender"]["api_key"] = "sk-super-secret"
        path = self.tmp / "contaminated.json"
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        message = self.parse_expecting_error(path)
        self.assertIn("profile_snapshot contract", message)

    def test_missing_required_key_aborts_start(self) -> None:
        snapshot = valid_snapshot()
        del snapshot["roster"]
        path = self.tmp / "incomplete.json"
        path.write_text(json.dumps(snapshot), encoding="utf-8")
        message = self.parse_expecting_error(path)
        self.assertIn("roster", message)


class ProfileSnapshotClosedLoopTests(unittest.TestCase):
    """Full subprocess runs against the fake codex runtime."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_profile_snapshot_run_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tasks_dir = self.tmp / "tasks"
        self.runs_dir = self.tmp / "runs"
        shutil.copytree(DEMO_TASK, self.tasks_dir / DEMO_TASK.name)
        self.fake_codex = self.tmp / "fake_codex.py"
        fake_codex_script(self.fake_codex)

    def run_cli(self, extra: list) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ROOT / "src"), env["PYTHONPATH"]]
            if env.get("PYTHONPATH")
            else [str(ROOT / "src")]
        )
        cmd = [
            sys.executable,
            "-m",
            "starbench.runner.run_benchmark",
            "--tasks-dir",
            str(self.tasks_dir),
            "--runs-dir",
            str(self.runs_dir),
            "--run-id",
            "snapshot_run",
            "--judge-mode",
            "single",
            "--auth-mode",
            "global",
            "--executor-backend",
            "local",
            "--codex-bin",
            f"{sys.executable} {self.fake_codex}",
            "--no-progress",
        ] + extra
        return subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_valid_snapshot_lands_in_run_root(self) -> None:
        snapshot = valid_snapshot()
        source = self.tmp / "snapshot.json"
        source.write_text(json.dumps(snapshot), encoding="utf-8")
        completed = self.run_cli(["--profile-snapshot", str(source)])
        self.assertEqual(completed.returncode, 0, msg=completed.stderr)

        written = json.loads(
            (self.runs_dir / "snapshot_run" / "profile_snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(written, snapshot)
        # The delivered artifact honours the public contract it was checked
        # against at start (no rewriting on the way to disk).
        validate_payload("profile_snapshot.schema.json", written)
        # No temp residue from the atomic write.
        leftovers = list((self.runs_dir / "snapshot_run").glob(".profile_snapshot-*"))
        self.assertEqual(leftovers, [])

    def test_invalid_snapshot_leaves_no_run_artifacts(self) -> None:
        snapshot = valid_snapshot()
        snapshot["execution"]["executor_backend"] = "kubernetes"
        source = self.tmp / "bad.json"
        source.write_text(json.dumps(snapshot), encoding="utf-8")
        completed = self.run_cli(["--profile-snapshot", str(source)])
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("profile_snapshot contract", completed.stderr)
        # Fail closed before any writer runs: no run directory, no half a run.
        self.assertFalse((self.runs_dir / "snapshot_run").exists())


if __name__ == "__main__":
    unittest.main()
