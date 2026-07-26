"""Tests for the Pi runtime adapter (command shape, env isolation, registry)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starbench.adapters.pi import PiAdapter, build_pi_command, prepare_pi_env
from starbench.adapters.registry import get_builtin, list_builtin


class PiCommandTests(unittest.TestCase):
    def test_minimal_command_is_headless_json_and_skill_less(self):
        command = build_pi_command("pi")
        self.assertEqual(command[:3], ["pi", "--mode", "json"])
        self.assertIn("--no-skills", command)
        self.assertNotIn("--skill", command)
        self.assertNotIn("--thinking", command)

    def test_provider_model_thinking_and_skills(self):
        command = build_pi_command(
            "pi",
            provider="anthropic",
            model="claude-sonnet-4-5",
            thinking="high",
            skill_paths=(Path("/w/.starbench/executor_skills/s1"),),
        )
        self.assertIn("--provider", command)
        self.assertEqual(command[command.index("--provider") + 1], "anthropic")
        self.assertEqual(command[command.index("--model") + 1], "claude-sonnet-4-5")
        self.assertEqual(command[command.index("--thinking") + 1], "high")
        self.assertEqual(
            command[command.index("--skill") + 1], "/w/.starbench/executor_skills/s1"
        )

    def test_default_thinking_omits_flag(self):
        for level in ("default", "none"):
            command = build_pi_command("pi", thinking=level)
            self.assertNotIn("--thinking", command)


class PiEnvTests(unittest.TestCase):
    def test_env_mode_isolates_home_and_forces_offline(self):
        home = Path(tempfile.mkdtemp()) / "pi_executor"
        env = prepare_pi_env(home, "env", base_env={"PATH": "/bin", "PI_OFFLINE": "0"})
        self.assertEqual(env["PI_CODING_AGENT_DIR"], str(home))
        self.assertEqual(env["PI_OFFLINE"], "1")
        self.assertEqual(env["PI_SKIP_VERSION_CHECK"], "1")
        self.assertEqual(env["PATH"], "/bin")
        self.assertTrue(home.exists())

    def test_global_and_copy_auth_are_rejected(self):
        home = Path(tempfile.mkdtemp()) / "pi_home"
        for mode in ("global", "copy-auth"):
            with self.assertRaises(ValueError):
                prepare_pi_env(home, mode, base_env={})


class PiInfoTests(unittest.TestCase):
    def test_registered_as_builtin_with_expected_facts(self):
        adapter = get_builtin("pi")
        info = adapter.info
        self.assertEqual(info.id, "pi")
        self.assertIsNone(info.docker_image)
        self.assertEqual(info.injection.kind, "pi_gateway")
        self.assertEqual(info.provider_filter.kinds, ("anthropic", "openai", "google", "xai"))
        self.assertEqual(info.thinking_channel, "native_config")
        self.assertIn("xhigh", info.thinking_efforts)
        self.assertIn("PI_CODING_AGENT_DIR", info.judge_sensitive_env)
        self.assertIn("pi", [a.info.id for a in list_builtin()])
        self.assertEqual([o.name for o in info.options], ["provider"])
        self.assertFalse(info.enforces_web_search)
        self.assertIsInstance(adapter, PiAdapter)


if __name__ == "__main__":
    unittest.main()
