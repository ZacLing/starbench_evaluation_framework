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

    def test_registry_declares_each_clis_real_effort_levels(self) -> None:
        # Claude Code: `claude --help` lists low, medium, high, xhigh, max.
        self.assertEqual(
            get_builtin("claude").info.thinking_efforts,
            ("default", "low", "medium", "high", "xhigh", "max"),
        )
        # Codex config reference: minimal..xhigh everywhere; max/ultra are
        # model-dependent tiers (gpt-5.6+) that Codex coerces down elsewhere.
        self.assertEqual(
            get_builtin("codex").info.thinking_efforts,
            ("default", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
        )
        # OpenCode --variant: union of the built-in provider variants.
        self.assertIn("max", get_builtin("opencode").info.thinking_efforts)
        # Prompt runtimes carry only the three instruction tiers.
        for agent in ("gemini", "grok"):
            self.assertEqual(
                get_builtin(agent).info.thinking_efforts,
                ("default", "low", "medium", "high"),
            )

    def test_claude_command_carries_native_effort_flag(self) -> None:
        command = build_claude_print_command(
            "claude", cwd=Path("/tmp/ws"), effort="high"
        )
        joined = " ".join(command)
        self.assertIn("--effort high", joined)
        for spelling in ("default", "none"):  # "none" is the legacy spelling
            quiet_command = build_claude_print_command(
                "claude", cwd=Path("/tmp/ws"), effort=spelling
            )
            self.assertNotIn("--effort", quiet_command)

    def test_opencode_command_carries_native_variant_flag(self) -> None:
        command = build_opencode_run_command(
            "opencode", cwd=Path("/tmp/ws"), variant="medium"
        )
        joined = " ".join(command)
        self.assertIn("--variant medium", joined)
        for spelling in ("default", "none"):
            quiet_command = build_opencode_run_command(
                "opencode", cwd=Path("/tmp/ws"), variant=spelling
            )
            self.assertNotIn("--variant", quiet_command)

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

    def test_codex_command_leaves_default_reasoning_alone(self) -> None:
        for spelling in ("default", "none"):
            command = build_codex_exec_command(
                "codex",
                cwd=Path("/tmp/ws"),
                final_path=Path("/tmp/final.md"),
                sandbox="workspace-write",
                reasoning_effort=spelling,
            )
            self.assertNotIn("model_reasoning_effort", " ".join(command))

    def test_codex_passes_model_dependent_upper_tiers_through(self) -> None:
        # gpt-5.6 ships max/ultra; the CLI coerces them down on older models,
        # so the adapter's job is only to pass the tier through verbatim.
        command = build_codex_exec_command(
            "codex",
            cwd=Path("/tmp/ws"),
            final_path=Path("/tmp/final.md"),
            sandbox="workspace-write",
            reasoning_effort="ultra",
        )
        self.assertIn('model_reasoning_effort="ultra"', " ".join(command))

    def test_prompt_instruction_is_appended_only_when_effort_set(self) -> None:
        self.assertEqual(append_thinking_instruction("base", "default"), "base")
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
