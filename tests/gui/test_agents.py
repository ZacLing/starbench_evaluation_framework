"""Custom agent registry CRUD and templates in ``starbench.gui.agents``."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from starbench.gui import agents
from starbench.gui.launcher import LaunchError, build_run_argv


class AgentRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_agents_"))
        self.runtimes_dir = self.tmp / "runtimes"
        self.runtimes_dir.mkdir()
        agents._clear_status_caches()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        agents._clear_status_caches()

    def qwen_payload(self, **overrides):
        base = {
            "id": "qwen-code",
            "label": "Qwen Code",
            "icon": "qwen",
            "command": "qwen",
            "args": ["--output-format", "json", "--yolo"],
            "judge_args": ["--output-format", "json", "--approval-mode", "plan"],
            "model_flag": "-m",
            "prompt_via": "stdin",
            "parser": "headless-json",
            "protocol": "openai",
            "base_url_env": "OPENAI_BASE_URL",
            "api_key_env": "OPENAI_API_KEY",
            "docker_image": "starbench-qwen:latest",
            "docker_env_passthrough": ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
        }
        base.update(overrides)
        return base

    def test_builtin_listing_reports_docker_capability(self) -> None:
        listing = agents.list_agents(self.runtimes_dir)
        by_id = {agent["id"]: agent for agent in listing["builtin"]}
        self.assertEqual(
            sorted(by_id), ["claude", "codex", "gemini", "grok", "opencode"]
        )
        for agent_id, meta in by_id.items():
            self.assertTrue(meta["docker_capable"], agent_id)
            self.assertTrue(meta["docker_image"].startswith("starbench-"), agent_id)
        self.assertEqual(by_id["gemini"]["docker_image"], "starbench-gemini-cli:latest")
        self.assertIn("bin", by_id["codex"]["cli"])

    def test_save_list_delete_roundtrip(self) -> None:
        saved = agents.save_custom_agent(self.runtimes_dir, self.qwen_payload())
        self.assertEqual(saved["id"], "custom:qwen-code")
        self.assertEqual(saved["protocol"], "openai")
        self.assertEqual(saved["base_url_env"], "OPENAI_BASE_URL")
        self.assertEqual(saved["docker_image"], "starbench-qwen:latest")
        self.assertTrue(saved["docker_capable"])
        self.assertTrue((self.runtimes_dir / "qwen-code.json").exists())

        # The written file must be loadable by the runner itself.
        from starbench.runner.custom_runtime import load_custom_runtime

        spec = load_custom_runtime(self.runtimes_dir, "qwen-code")
        self.assertEqual(spec.model_flag, "-m")
        self.assertEqual(spec.docker_image, "starbench-qwen:latest")

        listing = agents.list_agents(self.runtimes_dir)
        self.assertEqual(len(listing["custom"]), 1)
        agents.delete_custom_agent(self.runtimes_dir, "qwen-code")
        self.assertEqual(agents.list_agents(self.runtimes_dir)["custom"], [])

    def test_save_rejects_builtin_id_bad_parser_and_bad_protocol(self) -> None:
        with self.assertRaisesRegex(agents.AgentError, "built-in"):
            agents.save_custom_agent(self.runtimes_dir, self.qwen_payload(id="codex"))
        with self.assertRaisesRegex(agents.AgentError, "parser"):
            agents.save_custom_agent(self.runtimes_dir, self.qwen_payload(parser="yaml"))
        with self.assertRaisesRegex(agents.AgentError, "Protocol"):
            agents.save_custom_agent(self.runtimes_dir, self.qwen_payload(protocol="carrier-pigeon"))

    def test_positional_prompt_agent_roundtrip(self) -> None:
        agents.save_custom_agent(
            self.runtimes_dir,
            self.qwen_payload(
                id="trae-agent",
                command="trae-cli",
                args=["run", "--provider", "openai"],
                judge_args=None,
                model_flag="--model",
                prompt_via="arg",
                prompt_flag="",
                parser="text",
                docker_image="",
                docker_env_passthrough=None,
            ),
        )
        listed = agents.get_custom_agent(self.runtimes_dir, "trae-agent")
        self.assertIsNotNone(listed)
        self.assertEqual(listed["prompt_via"], "arg")
        self.assertEqual(listed["prompt_flag"], "")
        self.assertFalse(listed["docker_capable"])
        self.assertTrue(listed["judge_args_inherited"])

    def test_invalid_spec_file_surfaces_error(self) -> None:
        (self.runtimes_dir / "broken.json").write_text("{not json", encoding="utf-8")
        listing = agents.list_agents(self.runtimes_dir)
        self.assertEqual(len(listing["custom"]), 1)
        self.assertIn("broken", listing["custom"][0]["id"])
        self.assertTrue(listing["custom"][0]["error"])

    def test_templates_are_valid_runner_specs(self) -> None:
        from starbench.runner.custom_runtime import load_custom_runtime

        for template in agents.agent_templates():
            spec = template["spec"]
            path = self.runtimes_dir / f"{spec['id']}.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            loaded = load_custom_runtime(self.runtimes_dir, spec["id"])
            self.assertEqual(loaded.id, spec["id"])
            self.assertIn(template["spec"].get("protocol"), agents.PROTOCOL_CHOICES)
            path.unlink()

    def test_bundled_runtime_specs_are_valid_and_labeled(self) -> None:
        listing = agents.list_agents(agents.DEFAULT_RUNTIMES_DIR)
        by_spec = {agent["spec_id"]: agent for agent in listing["custom"]}
        for spec_id in ("qwen-code", "kimi-code", "trae-agent"):
            self.assertIn(spec_id, by_spec)
            self.assertIsNone(by_spec[spec_id]["error"], spec_id)
        for spec_id in ("qwen-code", "kimi-code", "trae-agent"):
            self.assertTrue(by_spec[spec_id]["docker_capable"], spec_id)
        self.assertEqual(by_spec["kimi-code"]["protocol"], "openai")
        self.assertEqual(by_spec["kimi-code"]["docker_image"], "starbench-kimi:latest")

    def test_provider_backed_templates_ship_docker_isolation(self) -> None:
        by_id = {template["template_id"]: template["spec"] for template in agents.agent_templates()}
        self.assertEqual(by_id["qwen-code"]["docker"]["image"], "starbench-qwen:latest")
        self.assertEqual(by_id["trae-agent"]["docker"]["image"], "starbench-trae-agent:latest")
        # Kimi runs containerized via a seeded ~/.kimi/config.toml baked into
        # the image; OPENAI_* env vars override its endpoint and key.
        self.assertEqual(by_id["kimi-code"]["docker"]["image"], "starbench-kimi:latest")
        self.assertEqual(by_id["kimi-code"]["protocol"], "openai")

    def test_agent_status_reports_versions_and_updates(self) -> None:
        original_which = agents.shutil.which
        original_run = agents._run

        def fake_which(name: str):
            if name in {"codex", "npm"}:
                return f"/bin/{name}"
            return None

        def fake_run(command, *, timeout):
            if command[:2] == ["/bin/codex", "--version"]:
                return subprocess.CompletedProcess(command, 0, "codex 0.141.0\n", "")
            if command[:3] == ["npm", "view", "@openai/codex"]:
                return subprocess.CompletedProcess(command, 0, "0.142.5\n", "")
            return subprocess.CompletedProcess(command, 1, "", "not found")

        agents.shutil.which = fake_which
        agents._run = fake_run
        try:
            status = agents.agent_statuses(self.runtimes_dir, check_updates=True)[
                "statuses"
            ]["codex"]
        finally:
            agents.shutil.which = original_which
            agents._run = original_run

        self.assertTrue(status["present"])
        self.assertEqual(status["version"], "0.141.0")
        self.assertEqual(status["latest_version"], "0.142.5")
        self.assertTrue(status["update_available"])
        self.assertEqual(status["package"]["name"], "@openai/codex")

    def test_agent_statuses_default_path_never_calls_npm(self) -> None:
        original_which = agents.shutil.which
        original_run = agents._run
        commands = []

        def fake_which(name: str):
            if name in {"codex", "npm"}:
                return f"/bin/{name}"
            return None

        def fake_run(command, *, timeout):
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 0, "codex 0.141.0\n", "")

        agents.shutil.which = fake_which
        agents._run = fake_run
        try:
            payload = agents.agent_statuses(self.runtimes_dir)
        finally:
            agents.shutil.which = original_which
            agents._run = original_run

        self.assertFalse(
            [command for command in commands if command and command[0] == "npm"],
            f"default status path must not hit npm, got: {commands}",
        )
        status = payload["statuses"]["codex"]
        # "not checked", not "check failed": all latest_* fields stay None.
        self.assertIsNone(status["latest_version"])
        self.assertIsNone(status["latest_checked_at"])
        self.assertIsNone(status["latest_error"])
        self.assertIsNone(status["update_available"])
        self.assertEqual(status["version"], "0.141.0")

    def test_default_path_serves_still_fresh_npm_answers_from_cache(self) -> None:
        """A reload without check_updates must not forget an update the console
        already learned — the cached npm answer is served, npm is not called."""
        original_which = agents.shutil.which
        original_run = agents._run
        npm_calls = []

        def fake_which(name: str):
            if name in {"codex", "npm"}:
                return f"/bin/{name}"
            return None

        def fake_run(command, *, timeout):
            if command[:2] == ["/bin/codex", "--version"]:
                return subprocess.CompletedProcess(command, 0, "codex 0.141.0\n", "")
            if command[:3] == ["npm", "view", "@openai/codex"]:
                npm_calls.append(list(command))
                return subprocess.CompletedProcess(command, 0, "0.142.5\n", "")
            return subprocess.CompletedProcess(command, 1, "", "not found")

        agents.shutil.which = fake_which
        agents._run = fake_run
        try:
            agents.agent_statuses(self.runtimes_dir, check_updates=True)
            status = agents.agent_statuses(self.runtimes_dir)["statuses"]["codex"]
        finally:
            agents.shutil.which = original_which
            agents._run = original_run

        self.assertEqual(len(npm_calls), 1, npm_calls)
        self.assertEqual(status["latest_version"], "0.142.5")
        self.assertTrue(status["update_available"])

    def test_agent_statuses_caches_local_probes(self) -> None:
        original_which = agents.shutil.which
        original_run = agents._run
        version_calls = []

        def fake_which(name: str):
            return f"/bin/{name}" if name == "codex" else None

        def fake_run(command, *, timeout):
            version_calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, "codex 0.141.0\n", "")

        agents.shutil.which = fake_which
        agents._run = fake_run
        try:
            agents.agent_statuses(self.runtimes_dir)
            agents.agent_statuses(self.runtimes_dir)
        finally:
            agents.shutil.which = original_which
            agents._run = original_run

        self.assertEqual(len(version_calls), 1, version_calls)

    def test_version_key_orders_prereleases_below_releases(self) -> None:
        self.assertTrue(agents._is_newer("1.0.0", "1.0.0-rc1"))
        self.assertFalse(agents._is_newer("1.0.0-rc1", "1.0.0"))
        self.assertTrue(agents._is_newer("1.0.0-rc2", "1.0.0-rc1"))
        self.assertFalse(agents._is_newer("1.0.0-rc1", "1.0.0-rc2"))
        self.assertFalse(agents._is_newer("1.0.0", "1.0.0"))
        self.assertTrue(agents._is_newer("1.0.1-rc1", "1.0.0"))
        self.assertIsNone(agents._is_newer(None, "1.0.0"))
        self.assertIsNone(agents._is_newer("1.0.0", None))

    def test_install_agent_rejects_concurrent_install(self) -> None:
        acquired = agents._INSTALL_LOCK.acquire(blocking=False)
        self.assertTrue(acquired)
        try:
            with self.assertRaisesRegex(agents.AgentError, "already running"):
                agents.install_agent("codex")
        finally:
            agents._INSTALL_LOCK.release()

    def test_install_agent_uses_whitelisted_command(self) -> None:
        original_run = agents._run
        calls = []

        def fake_run(command, *, timeout):
            calls.append((list(command), timeout))
            return subprocess.CompletedProcess(command, 0, "installed\n", "")

        agents._run = fake_run
        try:
            result = agents.install_agent("custom:qwen-code")
        finally:
            agents._run = original_run

        self.assertEqual(result["status"], "installed")
        self.assertEqual(calls[0][0][:4], ["npm", "install", "-g", "@qwen-code/qwen-code@latest"])
        self.assertEqual(calls[0][1], agents.INSTALL_TIMEOUT_SECONDS)

    def test_install_agent_rejects_unknown_runtime(self) -> None:
        with self.assertRaisesRegex(agents.AgentError, "No built-in installer"):
            agents.install_agent("custom:unknown")

    def test_launcher_accepts_custom_agents(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir()
        runs_dir = self.tmp / "runs"
        runs_dir.mkdir()
        argv = build_run_argv(
            {
                "run_id": "custom_run",
                "tasks_dir": str(tasks_dir),
                "executor_agent": "custom:qwen-code",
                "evaluator_agent": "custom:my-judge",
                "executor_backend": "docker",
            },
            runs_dir=runs_dir,
        )
        joined = " ".join(argv)
        self.assertIn("--executor-agent custom:qwen-code", joined)
        self.assertIn("--evaluator-agent custom:my-judge", joined)
        # Custom runtimes carry their docker image in the spec; no --docker-image.
        self.assertIn("--executor-backend docker", joined)
        self.assertNotIn("--docker-image", joined)
        with self.assertRaises(LaunchError):
            build_run_argv(
                {
                    "run_id": "bad_run",
                    "tasks_dir": str(tasks_dir),
                    "executor_agent": "custom:bad id!",
                },
                runs_dir=runs_dir,
            )

    def test_display_order_appends_unknown_ids_alphabetically(self) -> None:
        from starbench.gui.agents import _display_order

        self.assertEqual(
            _display_order(["opencode", "zeta-agent", "claude", "alpha-agent"]),
            ["claude", "opencode", "alpha-agent", "zeta-agent"],
        )


if __name__ == "__main__":
    unittest.main()
