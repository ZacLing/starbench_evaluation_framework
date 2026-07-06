"""Thinking-effort channels and the run-level web-search override.

--thinking-effort must reach each runtime through its native switch where one
exists (Claude: --effort, Codex: model_reasoning_effort, OpenCode: --variant;
all verified against the installed CLIs' --help) and as a prompt instruction
elsewhere; --web-search must override the task flag only where the runner
actually enforces web access.
"""
from __future__ import annotations

import unittest

from starbench.adapters import get_builtin
from starbench.adapters.base import effective_web_search
from starbench.adapters.claude import build_claude_print_command
from starbench.adapters.codex import build_codex_exec_command
from starbench.adapters.opencode import build_opencode_run_command
from starbench.runner.prompts import append_thinking_instruction
from pathlib import Path


class ThinkingChannelTests(unittest.TestCase):
    def test_registry_declares_native_channels(self) -> None:
        for agent in ("claude", "codex", "opencode"):
            self.assertEqual(get_builtin(agent).info.thinking_channel, "native_config")
        # Gemini's thinking knobs live in settings.json only, and Grok Build's
        # CLI switch is unverified — both stay honest prompt-level requests.
        for agent in ("gemini", "grok"):
            self.assertEqual(get_builtin(agent).info.thinking_channel, "prompt")

    def test_claude_command_carries_native_effort_flag(self) -> None:
        command = build_claude_print_command(
            "claude", cwd=Path("/tmp/ws"), effort="high"
        )
        joined = " ".join(command)
        self.assertIn("--effort high", joined)
        none_command = build_claude_print_command(
            "claude", cwd=Path("/tmp/ws"), effort="none"
        )
        self.assertNotIn("--effort", none_command)

    def test_opencode_command_carries_native_variant_flag(self) -> None:
        command = build_opencode_run_command(
            "opencode", cwd=Path("/tmp/ws"), variant="medium"
        )
        joined = " ".join(command)
        self.assertIn("--variant medium", joined)
        none_command = build_opencode_run_command(
            "opencode", cwd=Path("/tmp/ws"), variant="none"
        )
        self.assertNotIn("--variant", none_command)

    def test_codex_command_carries_native_reasoning_effort(self) -> None:
        command = build_codex_exec_command(
            "codex",
            cwd=Path("/tmp/ws"),
            final_path=Path("/tmp/final.md"),
            sandbox="workspace-write",
            reasoning_effort="high",
        )
        joined = " ".join(command)
        self.assertIn('model_reasoning_effort="high"', joined)

    def test_codex_command_leaves_default_reasoning_alone_for_none(self) -> None:
        command = build_codex_exec_command(
            "codex",
            cwd=Path("/tmp/ws"),
            final_path=Path("/tmp/final.md"),
            sandbox="workspace-write",
            reasoning_effort="none",
        )
        self.assertNotIn("model_reasoning_effort", " ".join(command))

    def test_prompt_instruction_is_appended_only_when_effort_set(self) -> None:
        self.assertEqual(append_thinking_instruction("base", "none"), "base")
        out = append_thinking_instruction("base", "high")
        self.assertIn("Thinking effort instruction:", out)
        self.assertTrue(out.startswith("base"))


class WebSearchOverrideTests(unittest.TestCase):
    def test_task_mode_defers_to_the_task_flag(self) -> None:
        self.assertTrue(effective_web_search("task", True))
        self.assertFalse(effective_web_search("task", False))

    def test_allow_and_deny_override_the_task_flag(self) -> None:
        self.assertTrue(effective_web_search("allow", False))
        self.assertFalse(effective_web_search("deny", True))

    def test_codex_search_flag_follows_the_effective_value(self) -> None:
        on = build_codex_exec_command(
            "codex",
            cwd=Path("/tmp/ws"),
            final_path=Path("/tmp/final.md"),
            sandbox="workspace-write",
            allow_web_search=effective_web_search("allow", False),
        )
        off = build_codex_exec_command(
            "codex",
            cwd=Path("/tmp/ws"),
            final_path=Path("/tmp/final.md"),
            sandbox="workspace-write",
            allow_web_search=effective_web_search("deny", True),
        )
        self.assertIn("--search", on)
        self.assertNotIn("--search", off)


if __name__ == "__main__":
    unittest.main()
