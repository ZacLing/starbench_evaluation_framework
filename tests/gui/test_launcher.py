"""Launch argv construction and validation in ``starbench.gui.launcher``."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from starbench.gui.launcher import LaunchError, build_run_argv


class LauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_launch_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, **overrides):
        base = {
            "run_id": "gui_test",
            "tasks_dir": str(self.tasks_dir),
            "tasks": ["demo"],
            "executor_agent": "codex",
            "evaluator_agent": "claude",
            "judge_mode": "single",
            "auth_mode": "env",
            "executor_backend": "local",
            "executor_model": "gpt-5.5",
            "evaluator_model": "claude-opus-4-8",
            "seed": "7",
        }
        base.update(overrides)
        return base

    def test_builds_expected_argv(self) -> None:
        argv = build_run_argv(self.payload(), runs_dir=self.runs_dir)
        self.assertEqual(argv[0], sys.executable)
        self.assertIn("starbench.runner.run_benchmark", argv)
        self.assertIn("--no-progress", argv)
        joined = " ".join(argv)
        self.assertIn("--task demo", joined)
        self.assertIn("--executor-agent codex", joined)
        self.assertIn("--evaluator-agent claude", joined)
        self.assertIn("--seed 7", joined)
        self.assertNotIn("--docker-image", joined)

    def test_docker_backend_requires_image(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(
                self.payload(executor_backend="docker", docker_image=""),
                runs_dir=self.runs_dir,
            )
        argv = build_run_argv(
            self.payload(executor_backend="docker", docker_image="starbench-codex:latest"),
            runs_dir=self.runs_dir,
        )
        self.assertIn("starbench-codex:latest", argv)

    def test_rejects_bad_run_id_and_duplicates(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(run_id="../evil"), runs_dir=self.runs_dir)
        (self.runs_dir / "gui_test").mkdir()
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(), runs_dir=self.runs_dir)

    def test_rejects_unknown_choice(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(executor_agent="bash"), runs_dir=self.runs_dir)
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(judge_mode="triple"), runs_dir=self.runs_dir)

    def test_advanced_run_knobs_pass_through(self) -> None:
        argv = build_run_argv(
            self.payload(max_evaluator_parallel="8", claude_max_turns="30"),
            runs_dir=self.runs_dir,
        )
        joined = " ".join(argv)
        self.assertIn("--max-evaluator-parallel 8", joined)
        self.assertIn("--claude-max-turns 30", joined)

    def test_blank_claude_max_turns_is_omitted(self) -> None:
        argv = build_run_argv(self.payload(claude_max_turns=""), runs_dir=self.runs_dir)
        self.assertNotIn("--claude-max-turns", argv)

    def test_extra_args_are_split(self) -> None:
        argv = build_run_argv(
            self.payload(extra_args="--instruction-mode ablation --repeat 2"),
            runs_dir=self.runs_dir,
        )
        self.assertIn("--instruction-mode", argv)
        self.assertIn("ablation", argv)

    def test_missing_tasks_dir_rejected(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(
                self.payload(tasks_dir=str(self.tmp / "nope")), runs_dir=self.runs_dir
            )

    def test_instruction_none_passes_no_flag(self) -> None:
        argv = build_run_argv(
            self.payload(instruction_mode="none"), runs_dir=self.runs_dir
        )
        self.assertNotIn("--instruction-mode", argv)
        self.assertNotIn("--instruction-step", argv)

    def test_instruction_mode_and_steps_pass_through(self) -> None:
        argv = build_run_argv(
            self.payload(
                instruction_mode="select", instruction_steps=["H001", "H004"]
            ),
            runs_dir=self.runs_dir,
        )
        joined = " ".join(argv)
        self.assertIn("--instruction-mode select", joined)
        # Each id becomes its own repeated --instruction-step flag.
        self.assertEqual(argv.count("--instruction-step"), 2)
        self.assertIn("--instruction-step H001", joined)
        self.assertIn("--instruction-step H004", joined)

    def test_instruction_ablation_mode_passes_through(self) -> None:
        argv = build_run_argv(
            self.payload(instruction_mode="ablation"), runs_dir=self.runs_dir
        )
        self.assertIn("--instruction-mode ablation", " ".join(argv))

    def test_instruction_mode_rejects_unknown_value(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(
                self.payload(instruction_mode="bogus"), runs_dir=self.runs_dir
            )


if __name__ == "__main__":
    unittest.main()
