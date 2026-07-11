"""--plan: fail-closed validation and argv-equivalent expansion.

The plan file is the typed launch contract (run_plan.schema.json). Disciplines
under test:
- A valid plan expands into exactly the flag surface a manual invocation would
  use, so both transports share every downstream validation and default.
- --plan is exclusive: any other config flag on argv is an error, so the two
  transports can never disagree about a knob's value.
- Anything invalid (unreadable file, broken JSON, contract violation, bad
  embedded snapshot) aborts at argument time — before any run state exists.
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from starbench.runner.cli import parse_args


def _minimal_snapshot() -> dict:
    return {
        "schema_version": 1,
        "captured_at": "2026-07-01T00:00:00+00:00",
        "profile": {"id": "hsw", "rev": 1, "name": "HSW sweep"},
        "contender": {"agent": "claude", "model": "claude-opus-4-8", "label": "Claude"},
        "roster": [{"agent": "claude", "model": "claude-opus-4-8"}],
        "instrument": {
            "evaluator_agent": "codex",
            "evaluator_model": "gpt-5.5",
            "evaluator_auth_mode": "env",
            "judge_mode": "single",
        },
        "execution": {
            "seed": 7,
            "batch_size": 1,
            "repeat": 5,
            "executor_backend": "local",
            "executor_auth_mode": "env",
        },
        "task_set": {"tasks_dir": "tasks", "task_ids": ["task_a"]},
    }


class RunPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_plan_"))

    def write_plan(self, **overrides) -> Path:
        plan = {
            "schema_version": 1,
            "run_id": "plan_run",
            "tasks_dir": str(self.tmp),
            "tasks": ["task_a", "task_b"],
            "executor_agent": "claude",
            "executor_model": "claude-opus-4-8",
            "evaluator_agent": "codex",
            "judge_mode": "single",
            "auth_mode": "env",
            "executor_backend": "local",
            "seed": 7,
            "repeat": 5,
        }
        plan.update(overrides)
        plan = {key: value for key, value in plan.items() if value is not None}
        path = self.tmp / "plan.json"
        path.write_text(json.dumps(plan) + "\n", encoding="utf-8")
        return path

    def parse_error(self, argv) -> str:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit):
                parse_args(argv)
        return stderr.getvalue()

    def test_plan_expands_to_the_same_validated_surface(self) -> None:
        path = self.write_plan()
        args = parse_args(["--plan", str(path), "--runs-dir", str(self.tmp)])
        self.assertEqual(args.run_id, "plan_run")
        self.assertEqual(args.task, ["task_a", "task_b"])
        self.assertEqual(args.executor_agent, "claude")
        self.assertEqual(args.executor_model, "claude-opus-4-8")
        self.assertEqual(args.judge_mode, "single")
        self.assertEqual(args.executor_backend, "local")
        self.assertEqual(args.seed, 7)
        self.assertEqual(args.repeat, 5)
        self.assertEqual(args.runs_dir, self.tmp.resolve())
        self.assertEqual(args.run_plan_data["run_id"], "plan_run")

    def test_plan_is_exclusive_with_config_flags(self) -> None:
        path = self.write_plan()
        message = self.parse_error(
            ["--plan", str(path), "--executor-agent", "codex"]
        )
        self.assertIn("--plan is exclusive", message)

    def test_unknown_plan_key_fails_closed(self) -> None:
        path = self.write_plan(api_key="sk-nope")
        message = self.parse_error(["--plan", str(path)])
        self.assertIn("run_plan contract", message)

    def test_wrong_type_fails_closed(self) -> None:
        path = self.write_plan(seed="7")
        message = self.parse_error(["--plan", str(path)])
        self.assertIn("run_plan contract", message)

    def test_missing_file_fails_closed(self) -> None:
        message = self.parse_error(["--plan", str(self.tmp / "absent.json")])
        self.assertIn("cannot read", message)

    def test_embedded_snapshot_lands_in_args(self) -> None:
        path = self.write_plan(profile_snapshot=_minimal_snapshot())
        args = parse_args(["--plan", str(path)])
        self.assertEqual(args.profile_snapshot_data["profile"]["id"], "hsw")

    def test_invalid_embedded_snapshot_fails_closed(self) -> None:
        snapshot = _minimal_snapshot()
        snapshot["contender"]["api_key"] = "sk-nope"
        path = self.write_plan(profile_snapshot=snapshot)
        message = self.parse_error(["--plan", str(path)])
        self.assertIn("profile_snapshot", message)


if __name__ == "__main__":
    unittest.main()
