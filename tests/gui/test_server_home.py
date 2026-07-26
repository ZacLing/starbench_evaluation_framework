"""build_state fills every omitted location from STARBENCH_HOME."""
from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starbench.gui.server import build_state, main


def _resolved(root: str, *parts: str) -> Path:
    # build_state normalises every dir with Path.resolve(); expectations are
    # resolved the same way (on macOS the temp root sits under a symlink).
    return Path(root, *parts).resolve()


class BuildStateHomeTests(unittest.TestCase):
    def test_omitted_dirs_fill_from_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = build_state(environ={"STARBENCH_HOME": tmp})
            self.assertEqual(state.runs_dir, _resolved(tmp, "runs"))
            self.assertEqual(state.tasks_dirs, [_resolved(tmp, "tasks")])
            self.assertEqual(state.runtimes_dir, _resolved(tmp, "runtimes"))
            self.assertEqual(state.skills_dir, _resolved(tmp, "skills"))

    def test_explicit_dirs_beat_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "elsewhere-runs"
            state = build_state(runs_dir=explicit, environ={"STARBENCH_HOME": tmp})
            self.assertEqual(state.runs_dir, explicit.resolve())
            self.assertEqual(state.tasks_dirs, [_resolved(tmp, "tasks")])

    def test_home_derived_and_flag_derived_dirs_normalise_alike(self) -> None:
        # A flag naming the same directory by an unnormalised route must land on
        # the same Path as the home-derived default, or the console and the
        # runner disagree about run identity.
        with tempfile.TemporaryDirectory() as tmp:
            from_home = build_state(environ={"STARBENCH_HOME": tmp})
            from_flag = build_state(
                runs_dir=Path(tmp) / "nested" / ".." / "runs",
                tasks_dirs=[Path(tmp) / "nested" / ".." / "tasks"],
                runtimes_dir=Path(tmp) / "nested" / ".." / "runtimes",
                skills_dir=Path(tmp) / "nested" / ".." / "skills",
                environ={"STARBENCH_HOME": tmp},
            )
            self.assertEqual(from_flag.runs_dir, from_home.runs_dir)
            self.assertEqual(from_flag.tasks_dirs, from_home.tasks_dirs)
            self.assertEqual(from_flag.runtimes_dir, from_home.runtimes_dir)
            self.assertEqual(from_flag.skills_dir, from_home.skills_dir)


class MainHomeErrorTests(unittest.TestCase):
    def test_relative_home_is_a_parser_error(self) -> None:
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {"STARBENCH_HOME": "not/absolute"}):
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                main(["--no-browser"])
        self.assertIn("STARBENCH_HOME must be an absolute path", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
