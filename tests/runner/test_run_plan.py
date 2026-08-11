"""--plan: fail-closed validation and argv-equivalent expansion.

The plan file is the typed launch contract (run_plan.schema.json). Disciplines
under test:
- A valid plan expands into exactly the flag surface a manual invocation would
  use, so both transports share every downstream validation and default.
- --plan is exclusive: any other config flag on argv is an error, so the two
  transports can never disagree about a knob's value.
- Anything invalid (unreadable file, broken JSON, contract violation, bad
  embedded snapshot) aborts at argument time — before any run state exists.
- --thinking-effort parses against the shared tier vocabulary and is narrowed
  to the executor's own declared level set at launch, before any executor runs.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import DEMO_TASK
from starbench.runner.cli import _expand_plan_argv, parse_args
from starbench.runner.run_benchmark import run_benchmark


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
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write_plan(self, **overrides) -> Path:
        plan = {
            "schema_version": 2,
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

    def test_required_executor_skills_expand_from_plan(self) -> None:
        path = self.write_plan(required_executor_skills=["skill-a", "skill-b"])
        args = parse_args(["--plan", str(path), "--runs-dir", str(self.tmp)])
        self.assertEqual(args.required_executor_skill, ["skill-a", "skill-b"])
        self.assertEqual(
            args.run_plan_data["required_executor_skills"],
            ["skill-a", "skill-b"],
        )

    def test_batch_label_rides_the_plan_into_args(self) -> None:
        # The batch label is a measurement fact the runner records, so it must
        # survive the plan transport: the contract accepts it and the generic
        # scalar expansion renders it as --batch <value>.
        path = self.write_plan(batch="exp_a")
        expanded, _plan = _expand_plan_argv(
            ["--plan", str(path), "--runs-dir", str(self.tmp)],
            argparse.ArgumentParser(),
        )
        self.assertEqual(expanded[expanded.index("--batch") + 1], "exp_a")
        args = parse_args(["--plan", str(path), "--runs-dir", str(self.tmp)])
        self.assertEqual(args.batch, "exp_a")
        self.assertEqual(args.run_plan_data["batch"], "exp_a")

    def test_unsafe_batch_label_fails_closed(self) -> None:
        path = self.write_plan(batch="../escape")
        message = self.parse_error(["--plan", str(path), "--runs-dir", str(self.tmp)])
        self.assertIn("run_plan contract", message)

    def test_unsafe_batch_label_on_argv_fails_closed(self) -> None:
        # Same guard, exercised on the direct-argv transport: --batch runs
        # through parse_safe_id inside parse_args, so an unsafe label is
        # rejected at parse time regardless of whether it arrived via --plan
        # or a bare flag.
        message = self.parse_error(
            [
                "--tasks-dir",
                str(self.tmp),
                "--runs-dir",
                str(self.tmp),
                "--batch",
                "../escape",
            ]
        )
        self.assertIn("Invalid batch label", message)

    def test_legacy_none_thinking_effort_canonicalizes_to_default(self) -> None:
        # Old plans and scripts spell the do-nothing tier "none"; the parser
        # folds it so everything downstream sees only "default".
        path = self.write_plan(thinking_effort="none")
        args = parse_args(["--plan", str(path), "--runs-dir", str(self.tmp)])
        self.assertEqual(args.thinking_effort, "default")
        argv_args = parse_args(
            ["--tasks-dir", str(self.tmp), "--thinking-effort", "none"]
        )
        self.assertEqual(argv_args.thinking_effort, "default")

    def test_model_dependent_upper_tiers_parse(self) -> None:
        args = parse_args(
            ["--tasks-dir", str(self.tmp), "--thinking-effort", "ultra"]
        )
        self.assertEqual(args.thinking_effort, "ultra")

    def test_off_tier_reaches_pi_through_both_transports(self) -> None:
        # "off" is pi's explicit disable-reasoning level (--thinking off), a
        # real tier distinct from "default" (pass no switch at all). Both
        # transports must carry it: argparse choices and the plan contract
        # enum. Registering a runtime that declares a tier the shared
        # vocabulary lacks would leave the console offering a level the
        # launch then refuses.
        argv_args = parse_args(
            ["--tasks-dir", str(self.tmp), "--thinking-effort", "off"]
        )
        self.assertEqual(argv_args.thinking_effort, "off")
        path = self.write_plan(
            executor_agent="pi", executor_model="claude-sonnet-4-5", thinking_effort="off"
        )
        plan_args = parse_args(["--plan", str(path), "--runs-dir", str(self.tmp)])
        self.assertEqual(plan_args.thinking_effort, "off")
        self.assertEqual(plan_args.executor_agent, "pi")
        # "off" is not folded away the way the legacy "none" spelling is.
        self.assertNotEqual(plan_args.thinking_effort, "default")

    def test_off_tier_is_rejected_for_an_executor_that_lacks_it(self) -> None:
        # The shared vocabulary carries "off" so pi can reach its real tier, but
        # the level set a launch is measured against is the executor's own.
        # Claude Code has no "off", so the run aborts at the orchestrator's
        # narrowing — before any executor starts, not silently coerced to
        # something else that would skew the comparison.
        tasks_dir = self.tmp / "tasks"
        shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
        args = parse_args(
            [
                "--tasks-dir",
                str(tasks_dir),
                "--runs-dir",
                str(self.tmp / "runs"),
                "--executor-skill-root",
                str(self.tmp / "skills"),
                "--runtimes-dir",
                str(self.tmp / "runtimes"),
                "--executor-agent",
                "claude",
                "--thinking-effort",
                "off",
            ]
        )
        self.assertEqual(args.thinking_effort, "off")
        with self.assertRaises(SystemExit) as context:
            asyncio.run(run_benchmark(args))
        self.assertIn("--thinking-effort off is not supported by claude", str(context.exception))

    def test_v1_plan_gets_a_friendly_migration_error(self) -> None:
        # A schema_version 1 document is rejected before the raw schema check,
        # with a message that names the new box keys and how to migrate.
        path = self.write_plan(schema_version=1)
        message = self.parse_error(["--plan", str(path)])
        self.assertIn("schema_version 1 is no longer accepted", message)
        self.assertIn('"executor_options": {"max_turns": ...}', message)
        self.assertNotIn("run_plan contract", message)

    def test_v2_plan_with_option_boxes_expands(self) -> None:
        # claude executor declares max_turns; an opencode judge declares the
        # gateway wiring options (api_key_env is default-filled by the resolver).
        path = self.write_plan(
            evaluator_agent="opencode",
            executor_options={"max_turns": 40},
            evaluator_options={"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1"},
        )
        args = parse_args(["--plan", str(path), "--runs-dir", str(self.tmp)])
        self.assertEqual(args.executor_options, {"max_turns": 40})
        self.assertEqual(
            args.evaluator_options,
            {
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENAI_API_KEY",
            },
        )

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
