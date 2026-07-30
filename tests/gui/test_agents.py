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

# Built-in runtimes that ship no Docker image and run host-local only.
# Empty today — every built-in has its own image.
HOST_LOCAL_ONLY: set = set()


class AgentRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_agents_"))
        self.runtimes_dir = self.tmp / "runtimes"
        self.runtimes_dir.mkdir()
        agents._clear_status_caches()
        # The shadow scan probes real install drop points (~/.local/bin/…);
        # point it at nothing so tests never observe this machine's installs.
        self._original_probe_paths = agents._STANDALONE_PROBE_PATHS
        agents._STANDALONE_PROBE_PATHS = {}

    def tearDown(self) -> None:
        agents._STANDALONE_PROBE_PATHS = self._original_probe_paths
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
            sorted(by_id), ["claude", "codex", "gemini", "grok", "opencode", "pi"]
        )
        # Docker capability is reported per runtime, not assumed for all;
        # every current built-in ships its own starbench- image.
        for agent_id, meta in by_id.items():
            if agent_id in HOST_LOCAL_ONLY:
                self.assertFalse(meta["docker_capable"], agent_id)
                self.assertIsNone(meta["docker_image"], agent_id)
                continue
            self.assertTrue(meta["docker_capable"], agent_id)
            self.assertTrue(meta["docker_image"].startswith("starbench-"), agent_id)
        self.assertEqual(by_id["gemini"]["docker_image"], "starbench-gemini-cli:latest")
        self.assertIn("bin", by_id["codex"]["cli"])

    def test_builtin_rows_carry_option_declarations(self) -> None:
        listing = agents.list_agents(self.runtimes_dir)
        by_id = {agent["id"]: agent for agent in listing["builtin"]}
        claude = by_id["claude"]["options"]
        self.assertEqual(claude[0]["name"], "max_turns")
        self.assertEqual(claude[0]["surface"], "user")
        self.assertEqual(
            [o["surface"] for o in by_id["opencode"]["options"]],
            ["wiring", "wiring", "wiring"],
        )
        self.assertEqual(by_id["gemini"]["options"], [])

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

    def test_install_specs_follow_each_vendors_official_channel(self) -> None:
        by_id = agents.INSTALL_SPECS
        for agent_id, spec in by_id.items():
            self.assertIn(spec["channel"], ("standalone", "npm"), agent_id)
            self.assertTrue(spec["bin"], agent_id)
            self.assertTrue(spec["install_command"], agent_id)
            self.assertTrue(spec["update_command"], agent_id)
            if spec["channel"] == "standalone":
                # Vendor installer scripts run through a login shell; the
                # script's source domain is surfaced to the operator.
                self.assertEqual(spec["install_command"][:2], ["bash", "-lc"], agent_id)
                self.assertIsNone(spec["name"], agent_id)
                self.assertTrue(spec["script_domain"], agent_id)
                self.assertIn("github", spec["latest_source"], agent_id)
            else:
                self.assertEqual(spec["install_command"][:2], ["npm", "install"], agent_id)
                self.assertEqual(spec["latest_source"], {"npm": spec["name"]}, agent_id)
                self.assertIsNone(spec["script_domain"], agent_id)
        # Self-updating CLIs update through their own updater, not a reinstall.
        self.assertEqual(by_id["codex"]["update_command"], ["codex", "update"])
        self.assertEqual(by_id["claude"]["update_command"], ["claude", "update"])
        self.assertEqual(by_id["opencode"]["update_command"], ["opencode", "upgrade"])
        # kimi-code has no self-updater: update re-runs the official installer.
        self.assertEqual(
            by_id["custom:kimi-code"]["update_command"],
            by_id["custom:kimi-code"]["install_command"],
        )
        self.assertEqual(by_id["codex"]["script_domain"], "chatgpt.com")
        self.assertEqual(by_id["claude"]["script_domain"], "claude.ai")
        self.assertEqual(by_id["codex"]["latest_source"], {"github": "openai/codex"})
        self.assertEqual(
            by_id["opencode"]["latest_source"], {"github": "anomalyco/opencode"}
        )
        # npm stays the official channel where the vendor recommends npm.
        self.assertEqual(by_id["gemini"]["channel"], "npm")
        self.assertEqual(by_id["grok"]["channel"], "npm")
        self.assertEqual(by_id["pi"]["channel"], "npm")
        self.assertEqual(by_id["custom:qwen-code"]["channel"], "npm")

    def test_agent_status_reports_versions_and_updates_via_github(self) -> None:
        original_which = agents.shutil.which
        original_run = agents._run
        original_fetch = agents._fetch_json
        fetched_urls = []

        def fake_which(name: str):
            if name == "codex":
                return "/bin/codex"
            return None

        def fake_run(command, *, timeout):
            if command[:2] == ["/bin/codex", "--version"]:
                return subprocess.CompletedProcess(command, 0, "codex 0.134.0\n", "")
            return subprocess.CompletedProcess(command, 1, "", "not found")

        def fake_fetch(url, *, timeout):
            fetched_urls.append(url)
            return {"tag_name": "rust-v0.146.0", "name": "0.146.0"}

        agents.shutil.which = fake_which
        agents._run = fake_run
        agents._fetch_json = fake_fetch
        try:
            status = agents.agent_statuses(self.runtimes_dir, check_updates=True)[
                "statuses"
            ]["codex"]
        finally:
            agents.shutil.which = original_which
            agents._run = original_run
            agents._fetch_json = original_fetch

        self.assertTrue(status["present"])
        self.assertEqual(status["version"], "0.134.0")
        self.assertEqual(status["latest_version"], "0.146.0")
        self.assertTrue(status["update_available"])
        self.assertEqual(status["package"]["channel"], "standalone")
        self.assertIn(
            "https://api.github.com/repos/openai/codex/releases/latest", fetched_urls
        )

    def test_agent_status_reports_versions_and_updates_via_npm(self) -> None:
        original_which = agents.shutil.which
        original_run = agents._run
        original_fetch = agents._fetch_json

        def fake_which(name: str):
            if name in {"gemini", "npm"}:
                return f"/bin/{name}"
            return None

        def fake_run(command, *, timeout):
            if command[:2] == ["/bin/gemini", "--version"]:
                return subprocess.CompletedProcess(command, 0, "0.9.0\n", "")
            if command[:3] == ["npm", "view", "@google/gemini-cli"]:
                return subprocess.CompletedProcess(command, 0, "0.10.2\n", "")
            return subprocess.CompletedProcess(command, 1, "", "not found")

        agents.shutil.which = fake_which
        agents._run = fake_run
        # GitHub-sourced runtimes are probed in the same sweep; stub the fetch
        # so no test ever leaves the process.
        agents._fetch_json = lambda url, *, timeout: {"tag_name": "v0.0.1"}
        try:
            status = agents.agent_statuses(self.runtimes_dir, check_updates=True)[
                "statuses"
            ]["gemini"]
        finally:
            agents.shutil.which = original_which
            agents._run = original_run
            agents._fetch_json = original_fetch

        self.assertTrue(status["present"])
        self.assertEqual(status["version"], "0.9.0")
        self.assertEqual(status["latest_version"], "0.10.2")
        self.assertTrue(status["update_available"])
        self.assertEqual(status["package"]["name"], "@google/gemini-cli")

    def test_classify_channel_recognizes_install_layouts(self) -> None:
        classify = agents.classify_channel
        self.assertEqual(
            classify("/Users/op/.codex/packages/standalone/codex-0.134.0/codex"),
            "standalone",
        )
        self.assertEqual(
            classify("/Users/op/.local/share/claude/versions/2.1.220/claude"),
            "standalone",
        )
        self.assertEqual(classify("/Users/op/.opencode/bin/opencode"), "standalone")
        self.assertEqual(classify("/Users/op/.kimi-code/bin/kimi"), "standalone")
        self.assertEqual(
            classify("/opt/homebrew/lib/node_modules/@google/gemini-cli/bin/gemini"),
            "npm",
        )
        # npm-under-Homebrew: node_modules must win over the Homebrew prefix.
        self.assertEqual(
            classify("/opt/homebrew/Cellar/node/23.1/lib/node_modules/x/bin/x"),
            "npm",
        )
        self.assertEqual(classify("/opt/homebrew/Cellar/foo/1.0.0/bin/foo"), "homebrew")
        self.assertEqual(classify("/usr/local/bin/foo"), "unknown")

    def test_classify_channel_resolves_symlinked_launchers(self) -> None:
        home = self.tmp / "home"
        target = home / ".codex" / "packages" / "standalone" / "codex-0.134.0" / "codex"
        target.parent.mkdir(parents=True)
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        link = home / ".local" / "bin" / "codex"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        self.assertEqual(agents.classify_channel(str(link)), "standalone")

    def _two_channel_codex_layout(self) -> tuple:
        """A codex installed twice: standalone (official) and npm."""
        home = self.tmp / "home"
        standalone_real = (
            home / ".codex" / "packages" / "standalone" / "codex-0.134.0" / "codex"
        )
        standalone_real.parent.mkdir(parents=True)
        standalone_real.write_text("", encoding="utf-8")
        standalone_link = home / ".local" / "bin" / "codex"
        standalone_link.parent.mkdir(parents=True)
        standalone_link.symlink_to(standalone_real)
        npm_real = (
            home / "npm" / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        )
        npm_real.parent.mkdir(parents=True)
        npm_real.write_text("", encoding="utf-8")
        npm_link = home / "npm" / "bin" / "codex"
        npm_link.parent.mkdir(parents=True)
        npm_link.symlink_to(npm_real)
        return home, standalone_link, npm_link

    def _scan_codex(self, home: Path, path_hit: Path, standalone_link: Path):
        """Run agent_statuses against the fake layout with `path_hit` on PATH."""
        original_which = agents.shutil.which
        original_run = agents._run

        def fake_which(name: str):
            if name == "codex":
                return str(path_hit)
            if name == "npm":
                return str(home / "npm" / "bin" / "npm")
            return None

        def fake_run(command, *, timeout):
            if command == ["npm", "prefix", "-g"]:
                return subprocess.CompletedProcess(command, 0, f"{home / 'npm'}\n", "")
            if command[1:] == ["--version"] and "/.local/bin/" in command[0]:
                return subprocess.CompletedProcess(command, 0, "codex 0.134.0\n", "")
            if command[1:] == ["--version"] and "/npm/bin/" in command[0]:
                return subprocess.CompletedProcess(command, 0, "codex 0.146.0\n", "")
            return subprocess.CompletedProcess(command, 1, "", "not found")

        agents.shutil.which = fake_which
        agents._run = fake_run
        agents._STANDALONE_PROBE_PATHS = {"codex": (str(standalone_link),)}
        try:
            return agents.agent_statuses(self.runtimes_dir)["statuses"]["codex"]
        finally:
            agents.shutil.which = original_which
            agents._run = original_run

    def test_shadowed_npm_copy_is_reported_with_evidence(self) -> None:
        home, standalone_link, npm_link = self._two_channel_codex_layout()
        status = self._scan_codex(home, path_hit=standalone_link, standalone_link=standalone_link)

        self.assertEqual(status["official_channel"], "standalone")
        self.assertEqual(status["active_channel"], "standalone")
        self.assertEqual(
            [(i["channel"], i["version"], i["active"]) for i in status["installations"]],
            [("standalone", "0.134.0", True), ("npm", "0.146.0", False)],
        )
        self.assertEqual(
            [w["kind"] for w in status["channel_warnings"]], ["shadowed_copies"]
        )
        message = status["channel_warnings"][0]["message"]
        self.assertIn("0.146.0", message)
        self.assertIn(str(npm_link), message)
        self.assertIn("remove", message)

    def test_path_hitting_wrong_channel_is_a_mismatch_warning(self) -> None:
        home, standalone_link, npm_link = self._two_channel_codex_layout()
        status = self._scan_codex(home, path_hit=npm_link, standalone_link=standalone_link)

        self.assertEqual(status["official_channel"], "standalone")
        self.assertEqual(status["active_channel"], "npm")
        self.assertEqual(
            [(i["channel"], i["active"]) for i in status["installations"]],
            [("npm", True), ("standalone", False)],
        )
        self.assertEqual(
            [w["kind"] for w in status["channel_warnings"]], ["channel_mismatch"]
        )
        message = status["channel_warnings"][0]["message"]
        self.assertIn("official channel is standalone", message)
        self.assertIn(str(standalone_link), message)

    def test_single_official_install_raises_no_warning(self) -> None:
        home, standalone_link, npm_link = self._two_channel_codex_layout()
        npm_link.unlink()
        status = self._scan_codex(home, path_hit=standalone_link, standalone_link=standalone_link)

        self.assertEqual(status["active_channel"], "standalone")
        self.assertEqual(len(status["installations"]), 1)
        self.assertEqual(status["channel_warnings"], [])

    def test_latest_github_version_degrades_without_raising(self) -> None:
        original_fetch = agents._fetch_json

        def failing_fetch(url, *, timeout):
            raise OSError("HTTP Error 403: rate limit exceeded")

        agents._fetch_json = failing_fetch
        try:
            latest = agents._latest_github_version("openai/codex")
        finally:
            agents._fetch_json = original_fetch

        self.assertIsNone(latest["latest_version"])
        self.assertIn("rate limit", latest["latest_error"])
        self.assertTrue(latest["latest_checked_at"])

        # A release without any readable semver is an error, not a crash.
        agents._fetch_json = lambda url, *, timeout: {"tag_name": "nightly", "name": ""}
        try:
            latest = agents._latest_github_version("openai/codex")
        finally:
            agents._fetch_json = original_fetch
        self.assertIsNone(latest["latest_version"])
        self.assertIn("did not include a semver", latest["latest_error"])

    def test_agent_statuses_default_path_never_checks_latest(self) -> None:
        original_which = agents.shutil.which
        original_run = agents._run
        original_fetch = agents._fetch_json
        commands = []

        def fake_which(name: str):
            if name in {"codex", "npm"}:
                return f"/bin/{name}"
            return None

        def fake_run(command, *, timeout):
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 0, "codex 0.141.0\n", "")

        def forbidden_fetch(url, *, timeout):
            raise AssertionError(f"default status path must not fetch {url}")

        agents.shutil.which = fake_which
        agents._run = fake_run
        agents._fetch_json = forbidden_fetch
        try:
            payload = agents.agent_statuses(self.runtimes_dir)
        finally:
            agents.shutil.which = original_which
            agents._run = original_run
            agents._fetch_json = original_fetch

        self.assertFalse(
            [command for command in commands if command[:2] == ["npm", "view"]],
            f"default status path must not query the npm registry, got: {commands}",
        )
        status = payload["statuses"]["codex"]
        # "not checked", not "check failed": all latest_* fields stay None.
        self.assertIsNone(status["latest_version"])
        self.assertIsNone(status["latest_checked_at"])
        self.assertIsNone(status["latest_error"])
        self.assertIsNone(status["update_available"])
        self.assertEqual(status["version"], "0.141.0")

    def test_default_path_serves_still_fresh_latest_answers_from_cache(self) -> None:
        """A reload without check_updates must not forget an update the console
        already learned — the cached answer is served, the network is not hit.
        The same cache is what keeps GitHub's anonymous 60 req/h quota safe."""
        original_which = agents.shutil.which
        original_run = agents._run
        original_fetch = agents._fetch_json
        fetched_urls = []
        codex_url = "https://api.github.com/repos/openai/codex/releases/latest"

        def fake_which(name: str):
            if name in {"codex", "npm"}:
                return f"/bin/{name}"
            return None

        def fake_run(command, *, timeout):
            if command[:2] == ["/bin/codex", "--version"]:
                return subprocess.CompletedProcess(command, 0, "codex 0.141.0\n", "")
            return subprocess.CompletedProcess(command, 1, "", "not found")

        def fake_fetch(url, *, timeout):
            fetched_urls.append(url)
            return {"tag_name": "rust-v0.146.0", "name": "0.146.0"}

        agents.shutil.which = fake_which
        agents._run = fake_run
        agents._fetch_json = fake_fetch
        try:
            agents.agent_statuses(self.runtimes_dir, check_updates=True)
            status = agents.agent_statuses(self.runtimes_dir)["statuses"]["codex"]
        finally:
            agents.shutil.which = original_which
            agents._run = original_run
            agents._fetch_json = original_fetch

        self.assertEqual(fetched_urls.count(codex_url), 1, fetched_urls)
        self.assertEqual(status["latest_version"], "0.146.0")
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

    def test_install_agent_prefers_self_update_when_cli_is_present(self) -> None:
        original_run = agents._run
        original_which = agents.shutil.which
        calls = []

        def fake_run(command, *, timeout):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, "ok\n", "")

        agents._run = fake_run
        agents.shutil.which = lambda name: "/bin/codex" if name == "codex" else None
        try:
            present = agents.install_agent("codex")
            agents.shutil.which = lambda name: None
            absent = agents.install_agent("codex")
        finally:
            agents._run = original_run
            agents.shutil.which = original_which

        # Present: the CLI's own updater (it knows its install channel and
        # swaps atomically). Absent: the official installer script.
        self.assertEqual(present["command"], ["codex", "update"])
        self.assertEqual(absent["command"][:2], ["bash", "-lc"])
        self.assertIn("chatgpt.com/codex/install.sh", absent["command"][2])
        self.assertEqual(calls, [present["command"], absent["command"]])

    def test_pi_installs_its_npm_package_without_lifecycle_scripts(self) -> None:
        original_run = agents._run
        calls = []

        def fake_run(command, *, timeout):
            calls.append(list(command))
            return subprocess.CompletedProcess(command, 0, "installed\n", "")

        agents._run = fake_run
        try:
            result = agents.install_agent("pi")
        finally:
            agents._run = original_run

        self.assertEqual(result["status"], "installed")
        self.assertEqual(
            calls[0][:4], ["npm", "install", "-g", "@earendil-works/pi-coding-agent@latest"]
        )
        self.assertIn("--ignore-scripts", calls[0])
        self.assertNotIn("--ignore-scripts", agents.INSTALL_SPECS["codex"]["install_command"])

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
