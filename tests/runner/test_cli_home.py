"""CLI dir defaults resolve from STARBENCH_HOME; flags stay the top override."""
from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

from starbench.runner.cli import parse_args

_BASE = ["--executor-agent", "codex"]
_HOME = "/tmp/sb-home"
_ENV = {"STARBENCH_HOME": _HOME}


def _under_home(name: str) -> Path:
    # parse_args normalises every dir with Path.resolve(); expectations are
    # resolved the same way (on macOS /tmp is a symlink to /private/tmp).
    return (Path(_HOME) / name).resolve()


class CliHomeDefaultTests(unittest.TestCase):
    def test_omitted_dir_flags_resolve_under_home(self) -> None:
        args = parse_args(_BASE, environ=_ENV)
        self.assertEqual(args.tasks_dir, _under_home("tasks"))
        self.assertEqual(args.runs_dir, _under_home("runs"))
        self.assertEqual(args.executor_skill_root, _under_home("skills"))
        self.assertEqual(args.runtimes_dir, _under_home("runtimes"))

    def test_explicit_flag_beats_home(self) -> None:
        # Each of the four dir flags overrides its own home-derived default
        # without disturbing the other three, which still resolve under home.
        cases = [
            ("--tasks-dir", "tasks_dir", "tasks"),
            ("--runs-dir", "runs_dir", "runs"),
            ("--executor-skill-root", "executor_skill_root", "skills"),
            ("--runtimes-dir", "runtimes_dir", "runtimes"),
        ]
        for flag, attr, home_name in cases:
            with self.subTest(flag=flag):
                explicit = f"/elsewhere/{home_name}"
                args = parse_args([*_BASE, flag, explicit], environ=_ENV)
                self.assertEqual(getattr(args, attr), Path(explicit))
                for other_flag, other_attr, other_home_name in cases:
                    if other_attr == attr:
                        continue
                    self.assertEqual(getattr(args, other_attr), _under_home(other_home_name))

    def test_relative_home_is_a_parser_error(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            parse_args(_BASE, environ={"STARBENCH_HOME": "not/absolute"})
        self.assertIn("STARBENCH_HOME must be an absolute path", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
