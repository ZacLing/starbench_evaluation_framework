"""STARBENCH_HOME resolution: env decides where data lives, never the cwd."""
from __future__ import annotations

import unittest
from pathlib import Path

from starbench.home import ENV_VAR, HomeLayout, resolve_home


class ResolveHomeTests(unittest.TestCase):
    def test_default_is_dot_starbench_under_user_home(self) -> None:
        self.assertEqual(resolve_home(environ={}), Path.home() / ".starbench")

    def test_env_var_relocates_home(self) -> None:
        self.assertEqual(
            resolve_home(environ={ENV_VAR: "/tmp/sb-exp"}), Path("/tmp/sb-exp")
        )

    def test_tilde_is_expanded(self) -> None:
        self.assertEqual(
            resolve_home(environ={ENV_VAR: "~/bench-home"}),
            Path.home() / "bench-home",
        )

    def test_blank_env_value_falls_back_to_default(self) -> None:
        self.assertEqual(resolve_home(environ={ENV_VAR: "  "}), Path.home() / ".starbench")

    def test_relative_env_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_home(environ={ENV_VAR: "relative/home"})


class HomeLayoutTests(unittest.TestCase):
    def test_layout_paths(self) -> None:
        layout = HomeLayout(Path("/data/sb"))
        self.assertEqual(layout.tasks, Path("/data/sb/tasks"))
        self.assertEqual(layout.runs, Path("/data/sb/runs"))
        self.assertEqual(layout.runtimes, Path("/data/sb/runtimes"))
        self.assertEqual(layout.skills, Path("/data/sb/skills"))


if __name__ == "__main__":
    unittest.main()
