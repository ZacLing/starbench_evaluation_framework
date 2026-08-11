"""Tests for the Pi runtime adapter (command shape, env isolation, registry)."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.adapters.pi import (
    PiAdapter,
    build_pi_command,
    build_pi_docker_command,
    prepare_pi_env,
)
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
    def tempdir(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="starbench_pi_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def test_env_mode_isolates_home_and_forces_offline(self):
        # Hostile base env: every var the adapter hard-sets arrives pre-set to a
        # value that would break isolation. All four must be overridden, so a
        # regression to setdefault on any one of them fails here.
        home = self.tempdir() / "pi_executor"
        env = prepare_pi_env(
            home,
            "env",
            base_env={
                "PATH": "/bin",
                "PI_OFFLINE": "0",
                "PI_CODING_AGENT_DIR": "/home/attacker/.pi",
                "PI_CODING_AGENT_SESSION_DIR": "/home/attacker/sessions",
                "PI_SKIP_VERSION_CHECK": "0",
            },
        )
        self.assertEqual(env["PI_CODING_AGENT_DIR"], str(home))
        self.assertEqual(env["PI_CODING_AGENT_SESSION_DIR"], str(home / "sessions"))
        self.assertEqual(env["PI_OFFLINE"], "1")
        self.assertEqual(env["PI_SKIP_VERSION_CHECK"], "1")
        self.assertEqual(env["PATH"], "/bin")
        self.assertTrue(home.exists())

    def test_global_and_copy_auth_are_rejected(self):
        home = self.tempdir() / "pi_home"
        for mode in ("global", "copy-auth"):
            with self.assertRaises(ValueError):
                prepare_pi_env(home, mode, base_env={})


class PiJudgeTests(unittest.TestCase):
    """run_judge's invariants, tested at their seams (it spawns a process)."""

    def tempdir(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="starbench_pi_judge_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def test_judge_command_installs_no_skills(self):
        # run_judge calls build_pi_command without skill_paths: the judge reads
        # evidence, it must not inherit the executor's installed skills, and
        # --no-skills keeps pi's own discovery off.
        command = build_pi_command(
            "pi", provider="anthropic", model="claude-opus-4-8", thinking="high"
        )
        self.assertNotIn("--skill", command)
        self.assertIn("--no-skills", command)

    def test_judge_home_is_isolated_from_the_executor_home(self):
        # The judge home run_judge derives (`<judge_home_base>_pi`) is a sibling
        # of the executor's, never the same directory: a contender that poisoned
        # the executor's pi config cannot reach the judge through it.
        run_dir = self.tempdir()
        judge_home_base = run_dir / "agent_home" / "judge"
        judge_home = judge_home_base.parent / f"{judge_home_base.name}_pi"
        judge_env = prepare_pi_env(judge_home, "env", base_env={})
        executor_env = prepare_pi_env(
            run_dir / "agent_home" / "pi_executor", "env", base_env={}
        )
        self.assertEqual(judge_env["PI_CODING_AGENT_DIR"], str(judge_home))
        self.assertTrue(judge_home.name.endswith("_pi"))
        self.assertNotEqual(
            judge_env["PI_CODING_AGENT_DIR"], executor_env["PI_CODING_AGENT_DIR"]
        )
        self.assertTrue(judge_home.is_dir())


class PiDockerCommandTests(unittest.TestCase):
    def _command(self, **kwargs):
        defaults = dict(
            pi_bin="pi",
            docker_bin="docker",
            docker_image="starbench-pi:latest",
            workspace=Path("/tmp/ws"),
            auth_env={"ANTHROPIC_API_KEY": "k", "STARBENCH_RUN_ID": "run1"},
        )
        defaults.update(kwargs)
        return build_pi_docker_command(**defaults)

    def test_wraps_headless_pi_in_the_shared_docker_harness(self):
        command = self._command(provider="anthropic", model="m", thinking="high")
        self.assertEqual(command[:2], ["docker", "run"])
        self.assertIn("starbench-pi:latest", command)
        # Inner command tail keeps the exact host shape.
        image_at = command.index("starbench-pi:latest")
        inner = command[image_at + 1 :]
        self.assertEqual(inner[:3], ["pi", "--mode", "json"])
        self.assertIn("--no-skills", inner)
        self.assertEqual(inner[inner.index("--thinking") + 1], "high")

    def test_isolation_env_lands_inside_the_workspace_mount(self):
        command = self._command()
        pairs = [command[i + 1] for i, a in enumerate(command) if a == "-e"]
        self.assertIn("HOME=/workspace/.runner/pi_home", pairs)
        self.assertIn("PI_CODING_AGENT_DIR=/workspace/.runner/pi_home/agent", pairs)
        self.assertIn(
            "PI_CODING_AGENT_SESSION_DIR=/workspace/.runner/pi_home/agent/sessions", pairs
        )
        self.assertIn("PI_OFFLINE=1", pairs)
        self.assertIn("PI_SKIP_VERSION_CHECK=1", pairs)

    def test_provider_keys_forward_by_name_only_when_present(self):
        command = self._command()
        pairs = [command[i + 1] for i, a in enumerate(command) if a == "-e"]
        # Present key is whitelisted by NAME (value never on argv); absent keys are not.
        self.assertIn("ANTHROPIC_API_KEY", pairs)
        self.assertNotIn("OPENAI_API_KEY", pairs)
        self.assertFalse(any("=k" in p for p in pairs))

    def test_skill_paths_are_container_side(self):
        from pathlib import PurePosixPath

        command = self._command(
            skill_paths=(PurePosixPath("/workspace/.starbench/executor_skills/s1"),)
        )
        self.assertEqual(
            command[command.index("--skill") + 1], "/workspace/.starbench/executor_skills/s1"
        )


class PiInfoTests(unittest.TestCase):
    def test_registered_as_builtin_with_expected_facts(self):
        adapter = get_builtin("pi")
        info = adapter.info
        self.assertEqual(info.id, "pi")
        self.assertEqual(info.docker_image, "starbench-pi:latest")
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
