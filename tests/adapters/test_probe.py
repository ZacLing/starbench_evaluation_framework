"""Shared CLI probe primitives in ``starbench.execution.probe``."""
from __future__ import annotations

import subprocess
import unittest
from unittest import mock

from starbench.execution import probe


class RunProbeEnvTest(unittest.TestCase):
    def run_and_capture_env(self, **kwargs):
        captured = {}

        def fake_run(command, **run_kwargs):
            captured["command"] = list(command)
            captured["env"] = run_kwargs["env"]
            captured["timeout"] = run_kwargs["timeout"]
            return subprocess.CompletedProcess(command, 0, "tool 1.2.3\n", "")

        with mock.patch.object(probe.subprocess, "run", fake_run):
            probe.run_probe(["tool", "--version"], timeout=3, **kwargs)
        return captured

    def test_forces_term_and_no_color_over_inherited_terminal(self) -> None:
        # A server launched from a real terminal inherits TERM; the probe
        # must override it (assignment, not setdefault) or CLIs emit ANSI
        # escapes that break string matching downstream.
        with mock.patch.dict(
            probe.os.environ, {"TERM": "xterm-256color", "NO_COLOR": ""}
        ):
            captured = self.run_and_capture_env()
        self.assertEqual(captured["env"]["TERM"], "dumb")
        self.assertEqual(captured["env"]["NO_COLOR"], "1")

    def test_forces_term_on_caller_supplied_env_without_mutating_it(self) -> None:
        base = {"PATH": "/bin", "TERM": "xterm-256color", "NO_COLOR": ""}
        captured = self.run_and_capture_env(env=base)
        self.assertEqual(captured["env"]["TERM"], "dumb")
        self.assertEqual(captured["env"]["NO_COLOR"], "1")
        self.assertEqual(captured["env"]["PATH"], "/bin")
        # The caller's dict must stay untouched.
        self.assertEqual(base["TERM"], "xterm-256color")
        self.assertEqual(base["NO_COLOR"], "")


class VersionHelpersTest(unittest.TestCase):
    def test_extract_version_prefers_full_semver_with_prerelease(self) -> None:
        self.assertEqual(probe.extract_version("codex 0.141.0"), "0.141.0")
        self.assertEqual(probe.extract_version("v1.2.3-rc1 (build 7)"), "1.2.3-rc1")
        self.assertEqual(probe.extract_version("tool 2.5"), "2.5")
        self.assertIsNone(probe.extract_version("no version here"))

    def test_tail_keeps_last_limit_characters(self) -> None:
        self.assertEqual(probe.tail("  short  "), "short")
        self.assertEqual(probe.tail("abcdef", limit=3), "def")


if __name__ == "__main__":
    unittest.main()
