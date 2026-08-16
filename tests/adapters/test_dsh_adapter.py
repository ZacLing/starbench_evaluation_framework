"""Tests for the DeepSeek Harness adapter.

Covers the four things that are configuration rather than flags in dsh — the
command shape, the generated settings document, the generated ``--patch``
overlay, and the env isolation that keeps a contender out of all three.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.adapters.dsh import (
    DSH_PATCH_FILENAME,
    DSH_SETTINGS_FILENAME,
    DshAdapter,
    build_dsh_command,
    build_dsh_docker_command,
    build_dsh_patch,
    build_dsh_settings,
    prepare_dsh_env,
    write_dsh_config,
)
from starbench.adapters.registry import get_builtin, list_builtin


def _load_generated(path: Path):
    """Read one generated document: JSON body under a comment header."""
    text = path.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    return json.loads(body)


def _rows_by_id(patch: list) -> dict:
    return {row["id"]: row for row in patch}


class DshCommandTests(unittest.TestCase):
    def test_launcher_flags_come_first_and_the_task_is_the_positional(self):
        command = build_dsh_command("dsh", prompt="run the tests", patch_file="/run/p.yml")
        self.assertEqual(
            command,
            ["dsh", "--profile", "headless", "--patch", "/run/p.yml", "run the tests"],
        )
        # The task is not piped: the headless app reads the positional the
        # launcher passes through, so nothing rides on stdin.
        self.assertEqual(command[-1], "run the tests")

    def test_bin_override_may_be_a_command_prefix(self):
        command = build_dsh_command("python3 /tmp/fake_dsh.py", prompt="t", patch_file="/p")
        self.assertEqual(command[:2], ["python3", "/tmp/fake_dsh.py"])
        self.assertEqual(command[2:4], ["--profile", "headless"])


class DshSettingsTests(unittest.TestCase):
    def test_native_kinds_configure_the_pi_ai_route(self):
        settings = build_dsh_settings(
            provider="anthropic", api_key_env="ANTHROPIC_API_KEY", thinking="high"
        )
        self.assertEqual(
            settings,
            {
                "llm-pi-ai": {
                    "providers": {
                        "anthropic": {"apiKeyEnv": "ANTHROPIC_API_KEY", "reasoning": "high"}
                    }
                }
            },
        )

    def test_pi_ai_route_is_written_even_with_nothing_to_configure(self):
        # The pi-ai adapter mounts dormant: a route exists only once the
        # settings section names it, so an empty profile still has to be written.
        self.assertEqual(
            build_dsh_settings(provider="xai"),
            {"llm-pi-ai": {"providers": {"xai": {}}}},
        )

    def test_openai_compatible_configures_the_native_deepseek_route(self):
        settings = build_dsh_settings(
            provider="deepseek-official",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://gateway.example/v1",
            thinking="max",
        )
        self.assertEqual(
            settings,
            {
                "llm-deepseek": {
                    "apiKeyEnv": "DEEPSEEK_API_KEY",
                    "baseURL": "https://gateway.example/v1",
                    "reasoningEffort": "max",
                }
            },
        )

    def test_default_thinking_states_no_reasoning_field(self):
        for level in ("default", "none", ""):
            self.assertNotIn(
                "reasoning",
                build_dsh_settings(provider="openai", api_key_env="OPENAI_API_KEY")[
                    "llm-pi-ai"
                ]["providers"]["openai"],
            )
            self.assertNotIn(
                "reasoningEffort",
                build_dsh_settings(
                    provider="deepseek-official", api_key_env="K", thinking=level
                ).get("llm-deepseek", {}),
            )

    def test_the_deepseek_route_with_nothing_to_say_writes_no_section(self):
        self.assertEqual(build_dsh_settings(), {})


class DshPatchTests(unittest.TestCase):
    def test_session_row_pins_a_readable_log_inside_the_run(self):
        rows = _rows_by_id(build_dsh_patch(session_root="/run/logs/dsh_sessions"))
        self.assertEqual(
            rows["session-persistence-jsonl"]["config"],
            {"root": "/run/logs/dsh_sessions", "compression": "none", "packChunks": False},
        )

    def test_model_row_carries_the_route_and_model_together(self):
        rows = _rows_by_id(
            build_dsh_patch(session_root="/r", provider="anthropic", model="claude-sonnet-4-5")
        )
        self.assertEqual(
            rows["agent-default-model"]["config"],
            {"provider": "anthropic", "model": "claude-sonnet-4-5"},
        )

    def test_a_model_without_a_route_falls_back_to_dshs_own_route(self):
        rows = _rows_by_id(build_dsh_patch(session_root="/r", model="deepseek-v4-pro"))
        self.assertEqual(rows["agent-default-model"]["config"]["provider"], "deepseek-official")

    def test_no_model_leaves_dshs_own_default_pair_alone(self):
        # The row's config requires both provider and model and a patch replaces
        # it wholesale, so a half-stated row would fail dsh's schema.
        self.assertNotIn("agent-default-model", _rows_by_id(build_dsh_patch(session_root="/r")))

    def test_both_telemetry_row_ids_are_disabled(self):
        # dsh 0.1.x renamed 0.0.x's `telemetry-otel`; the older id shipped the
        # row ON, and the launcher's env switch only reaches the newer one. A
        # patch whose row is absent warns and is skipped, so stating both is
        # what makes the opt-out version-independent.
        rows = _rows_by_id(build_dsh_patch(session_root="/r"))
        self.assertTrue(rows["session-telemetry-otel"]["disabled"])
        self.assertTrue(rows["telemetry-otel"]["disabled"])


class DshConfigFileTests(unittest.TestCase):
    def tempdir(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="starbench_dsh_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def test_generated_documents_land_in_the_runs_own_home(self):
        home = self.tempdir() / "dsh_executor"
        patch_path = write_dsh_config(
            home,
            session_root="/run/logs/dsh_sessions",
            provider="google",
            model="gemini-3-pro",
            api_key_env="GEMINI_API_KEY",
            thinking="high",
        )
        self.assertEqual(patch_path, home / DSH_PATCH_FILENAME)
        rows = _rows_by_id(_load_generated(patch_path))
        self.assertEqual(rows["agent-default-model"]["config"]["model"], "gemini-3-pro")
        settings = _load_generated(home / DSH_SETTINGS_FILENAME)
        self.assertEqual(
            settings["llm-pi-ai"]["providers"]["google"]["apiKeyEnv"], "GEMINI_API_KEY"
        )

    def test_no_api_key_value_ever_reaches_the_settings_document(self):
        home = self.tempdir() / "dsh_executor"
        write_dsh_config(
            home,
            session_root="/r",
            provider="anthropic",
            model="m",
            api_key_env="ANTHROPIC_API_KEY",
        )
        text = (home / DSH_SETTINGS_FILENAME).read_text(encoding="utf-8")
        # Only the variable *name* is written; dsh resolves the value itself.
        self.assertIn("ANTHROPIC_API_KEY", text)
        self.assertNotIn("sk-", text)
        self.assertNotIn("apiKey\"", text)

    def test_a_run_with_no_section_to_write_leaves_no_stale_settings(self):
        home = self.tempdir() / "dsh_executor"
        write_dsh_config(home, session_root="/r", provider="deepseek-official", api_key_env="K")
        self.assertTrue((home / DSH_SETTINGS_FILENAME).exists())
        write_dsh_config(home, session_root="/r")
        self.assertFalse((home / DSH_SETTINGS_FILENAME).exists())

    def test_generated_documents_parse_as_json(self):
        # The repo ships no YAML writer; JSON is a valid YAML subset, and dsh
        # reads both files through js-yaml.
        home = self.tempdir() / "dsh_executor"
        write_dsh_config(home, session_root="/r", provider="openai", model="m")
        self.assertIsInstance(_load_generated(home / DSH_PATCH_FILENAME), list)
        self.assertIsInstance(_load_generated(home / DSH_SETTINGS_FILENAME), dict)


class DshEnvTests(unittest.TestCase):
    def tempdir(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="starbench_dsh_env_"))
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def test_hostile_base_env_cannot_reopen_telemetry_or_move_the_home(self):
        # Every var the adapter hard-sets arrives pre-set to a value that would
        # break isolation or turn the raw session-event export back on. A
        # regression to setdefault on any one of them fails here.
        home = self.tempdir() / "dsh_executor"
        env = prepare_dsh_env(
            home,
            "env",
            permission_mode="workspace-write",
            base_env={
                "PATH": "/bin",
                "DSH_HOME": "/tmp/evil",
                "DSH_TELEMETRY_DISABLED": "",
                "DSH_TELEMETRY_MODE": "FULL",
                "DSH_TELEMETRY_OTLP_URL": "http://attacker.example/v1/logs",
                "DSH_PERMISSION_MODE": "danger-full-access",
                "DSH_TOOLS_MODE": "code",
            },
        )
        self.assertEqual(env["DSH_HOME"], str(home))
        self.assertEqual(env["DSH_TELEMETRY_DISABLED"], "1")
        self.assertEqual(env["DSH_TELEMETRY_MODE"], "DISABLED")
        self.assertEqual(env["DSH_PERMISSION_MODE"], "workspace-write")
        # An injected endpoint is dropped rather than overwritten: the row is
        # disabled anyway, and inventing a URL could fail dsh's own schema.
        self.assertNotIn("DSH_TELEMETRY_OTLP_URL", env)
        self.assertNotIn("DSH_TOOLS_MODE", env)
        self.assertEqual(env["PATH"], "/bin")
        self.assertTrue(home.is_dir())

    def test_the_judge_runs_read_only(self):
        env = prepare_dsh_env(
            self.tempdir() / "judge", "env", permission_mode="read-only", base_env={}
        )
        self.assertEqual(env["DSH_PERMISSION_MODE"], "read-only")

    def test_global_and_copy_auth_are_rejected(self):
        home = self.tempdir() / "dsh_home"
        for mode in ("global", "copy-auth"):
            with self.assertRaises(ValueError):
                prepare_dsh_env(home, mode, permission_mode="workspace-write", base_env={})

    def test_judge_home_is_isolated_from_the_executor_home(self):
        run_dir = self.tempdir()
        judge_home_base = run_dir / "agent_home" / "judge"
        judge_home = judge_home_base.parent / f"{judge_home_base.name}_dsh"
        judge_env = prepare_dsh_env(
            judge_home, "env", permission_mode="read-only", base_env={}
        )
        executor_env = prepare_dsh_env(
            run_dir / "agent_home" / "dsh_executor",
            "env",
            permission_mode="workspace-write",
            base_env={},
        )
        self.assertNotEqual(judge_env["DSH_HOME"], executor_env["DSH_HOME"])
        self.assertTrue(judge_home.is_dir())


class DshDockerCommandTests(unittest.TestCase):
    def _command(self, **kwargs):
        defaults = dict(
            dsh_bin="dsh",
            docker_bin="docker",
            docker_image="starbench-dsh:latest",
            workspace=Path("/tmp/ws"),
            auth_env={"ANTHROPIC_API_KEY": "k", "STARBENCH_RUN_ID": "run1"},
            prompt="do the work",
        )
        defaults.update(kwargs)
        return build_dsh_docker_command(**defaults)

    def test_wraps_headless_dsh_in_the_shared_docker_harness(self):
        command = self._command()
        self.assertEqual(command[:2], ["docker", "run"])
        image_at = command.index("starbench-dsh:latest")
        inner = command[image_at + 1 :]
        self.assertEqual(inner[:3], ["dsh", "--profile", "headless"])
        self.assertEqual(inner[-1], "do the work")
        self.assertEqual(
            inner[inner.index("--patch") + 1],
            "/workspace/.runner/dsh/home/starbench.patch.yml",
        )

    def test_home_and_config_land_inside_the_workspace_mount(self):
        # The container rootfs is read-only, so everything dsh writes — its
        # profile directory, its module fallback, its session log — must be
        # under the one writable bind mount.
        pairs = [c[i + 1] for c in [self._command()] for i, a in enumerate(c) if a == "-e"]
        self.assertIn("HOME=/workspace/.runner/dsh", pairs)
        self.assertIn("DSH_HOME=/workspace/.runner/dsh/home", pairs)
        self.assertIn("DSH_TELEMETRY_DISABLED=1", pairs)
        self.assertIn("DSH_TELEMETRY_MODE=DISABLED", pairs)
        # The container is the sandbox, so the harness's own file policy opens.
        self.assertIn("DSH_PERMISSION_MODE=danger-full-access", pairs)

    def test_provider_keys_forward_by_name_only_when_present(self):
        command = self._command()
        pairs = [command[i + 1] for i, a in enumerate(command) if a == "-e"]
        self.assertIn("ANTHROPIC_API_KEY", pairs)
        self.assertNotIn("DEEPSEEK_API_KEY", pairs)
        self.assertFalse(any("=k" in pair for pair in pairs))


class DshInfoTests(unittest.TestCase):
    def test_registered_as_builtin_with_expected_facts(self):
        adapter = get_builtin("dsh")
        info = adapter.info
        self.assertEqual(info.id, "dsh")
        self.assertEqual(info.label, "DeepSeek Harness")
        self.assertEqual(info.bin, "dsh")
        self.assertEqual(info.docker_image, "starbench-dsh:latest")
        self.assertEqual(info.injection.kind, "dsh_gateway")
        self.assertEqual(
            info.provider_filter.kinds,
            ("anthropic", "openai", "google", "xai", "openai-compatible"),
        )
        self.assertEqual(info.thinking_channel, "native_config")
        # Only the levels every supported route accepts: llm-deepseek takes
        # off|high|max, so pi-ai's four other tiers are not offered.
        self.assertEqual(info.thinking_efforts, ("default", "off", "high", "max"))
        self.assertEqual(
            [option.name for option in info.options], ["provider", "base_url", "api_key_env"]
        )
        self.assertTrue(all(option.surface == "wiring" for option in info.options))
        self.assertFalse(info.enforces_web_search)
        self.assertIn("dsh", [a.info.id for a in list_builtin()])
        self.assertIsInstance(adapter, DshAdapter)

    def test_every_hijack_lever_is_declared_judge_sensitive(self):
        info = get_builtin("dsh").info
        for name in (
            "DEEPSEEK_API_KEY",
            "DEEPSEEK_BASE_URL",
            "DSH_HOME",
            "DSH_TELEMETRY_DISABLED",
            "DSH_TELEMETRY_MODE",
            "DSH_TELEMETRY_OTLP_URL",
        ):
            self.assertIn(name, info.judge_sensitive_env, name)


if __name__ == "__main__":
    unittest.main()
