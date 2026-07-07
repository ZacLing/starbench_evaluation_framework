"""AI provider presets, model refresh and judge/gateway conflict detection."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.gui import experiments, providers
from starbench.gui.experiments import ExperimentError
from starbench.gui.launcher import resolve_env_spec
from starbench.gui.providers import ProviderError


class ProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_prov_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_builtin_presets_until_saved(self) -> None:
        loaded = providers.load_providers(self.runs_dir)
        self.assertFalse(loaded["persisted"])
        ids = {provider["id"] for provider in loaded["providers"]}
        self.assertIn("anthropic", ids)
        self.assertIn("anthropic-cli", ids)
        self.assertIn("vercel-ai-gateway", ids)
        self.assertIn("openrouter", ids)
        by_id = {provider["id"]: provider for provider in loaded["providers"]}
        self.assertEqual(
            by_id["deepseek"]["anthropic_base_url"], "https://api.deepseek.com/anthropic"
        )
        self.assertEqual(
            by_id["vercel-ai-gateway"]["anthropic_base_url"], "https://ai-gateway.vercel.sh"
        )
        self.assertEqual(by_id["openrouter"]["anthropic_base_url"], "https://openrouter.ai/api")
        for provider in loaded["providers"]:
            self.assertIn("agent", provider)
            self.assertIn("key_present", provider)
            self.assertIn(provider["auth"], ("api_key", "cli_login"))
        self.assertNotIn("cli_status", by_id["anthropic-cli"])

    def test_load_providers_does_not_probe_cli_status(self) -> None:
        original_status = providers._cli_login_status

        def fail_if_called(agent):
            raise AssertionError(f"unexpected CLI status probe for {agent}")

        providers._cli_login_status = fail_if_called
        try:
            loaded = providers.load_providers(self.runs_dir)
        finally:
            providers._cli_login_status = original_status
        self.assertIn("anthropic-cli", {provider["id"] for provider in loaded["providers"]})

    def test_load_provider_cli_statuses_probes_cli_login_providers(self) -> None:
        original_status = providers._cli_login_status
        calls = []

        def fake_status(agent):
            calls.append(agent)
            return {
                "agent": agent,
                "label": agent,
                "cli_present": True,
                "cli_path": f"/bin/{agent}",
                "status": "ok",
                "message": "ok",
            }

        providers._cli_login_status = fake_status
        try:
            result = providers.load_provider_cli_statuses(self.runs_dir)
        finally:
            providers._cli_login_status = original_status
        self.assertEqual(calls, ["claude", "codex"])
        self.assertEqual(result["statuses"]["anthropic-cli"]["agent"], "claude")
        self.assertEqual(result["statuses"]["openai-cli"]["agent"], "codex")

    def test_persisted_openrouter_gets_anthropic_endpoint_default(self) -> None:
        providers.save_providers(
            self.runs_dir,
            {
                "providers": [
                    {
                        "id": "openrouter",
                        "name": "OpenRouter",
                        "kind": "openai-compatible",
                        "auth": "api_key",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key_env": "OPENROUTER_API_KEY",
                        "models": [],
                    }
                ]
            },
        )
        loaded = providers.load_providers(self.runs_dir)
        self.assertEqual(loaded["providers"][0]["anthropic_base_url"], "https://openrouter.ai/api")

    def test_save_and_reload(self) -> None:
        saved = providers.save_providers(
            self.runs_dir,
            {
                "providers": [
                    {
                        "id": "yunwu",
                        "name": "Yunwu",
                        "kind": "openai-compatible",
                        "base_url": "https://yunwu.ai/v1",
                        "api_key_env": "YUNWU_KEY",
                        "anthropic_base_url": "https://yunwu.ai/anthropic",
                        "models": ["doubao-seed-2-0-pro-260215", " "],
                    }
                ]
            },
        )
        self.assertTrue(saved["persisted"])
        reloaded = providers.load_providers(self.runs_dir)
        self.assertEqual(reloaded["providers"][0]["agent"], "opencode")
        self.assertEqual(reloaded["providers"][0]["models"], ["doubao-seed-2-0-pro-260215"])
        self.assertEqual(
            reloaded["providers"][0]["anthropic_base_url"], "https://yunwu.ai/anthropic"
        )

    def test_save_validation(self) -> None:
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir, {"providers": [{"id": "x", "kind": "nope", "models": []}]}
            )
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {"id": "a", "kind": "openai", "models": []},
                        {"id": "a", "kind": "openai", "models": []},
                    ]
                },
            )
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir,
                {"providers": [{"id": "a", "kind": "openai", "auth": "nope", "models": []}]},
            )
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "gw",
                            "kind": "openai-compatible",
                            "auth": "cli_login",
                            "models": [],
                        }
                    ]
                },
            )

    def test_refresh_models_from_api(self) -> None:
        import os

        calls = {}

        def fake_fetch(url, headers=None):
            calls["url"] = url
            calls["headers"] = headers or {}
            return {"data": [{"id": "m-2"}, {"id": "m-1"}]}

        os.environ["STARBENCH_TEST_KEY"] = "k"
        original = providers._fetch_json
        providers._fetch_json = fake_fetch
        try:
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "gw",
                            "kind": "openai-compatible",
                            "auth": "api_key",
                            "base_url": "https://gw.example/v1",
                            "api_key_env": "STARBENCH_TEST_KEY",
                            "models": [],
                        }
                    ]
                },
            )
            result = providers.refresh_provider_models(self.runs_dir, "gw")
        finally:
            providers._fetch_json = original
            del os.environ["STARBENCH_TEST_KEY"]
        provider = result["providers"][0]
        self.assertEqual(provider["models"], ["m-1", "m-2"])
        self.assertEqual(provider["models_source"], "api")
        self.assertIn("gw.example/v1/models", calls["url"])
        self.assertEqual(calls["headers"].get("Authorization"), "Bearer k")

    def test_refresh_models_cli_login_falls_back_to_catalog(self) -> None:
        def fake_fetch(url, headers=None):
            self.assertIn("ai-gateway.vercel.sh", url)
            return {"data": [{"id": "anthropic/claude-opus-4.8"}, {"id": "openai/gpt-5.5"}]}

        original = providers._fetch_json
        providers._fetch_json = fake_fetch
        try:
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "anthropic-cli",
                            "kind": "anthropic",
                            "auth": "cli_login",
                            "models": [],
                        }
                    ]
                },
            )
            result = providers.refresh_provider_models(self.runs_dir, "anthropic-cli")
        finally:
            providers._fetch_json = original
        provider = result["providers"][0]
        self.assertEqual(provider["models"], ["claude-opus-4.8"])
        self.assertEqual(provider["models_source"], "catalog")

    def test_openai_compatible_vendor_catalog_is_filtered(self) -> None:
        def fake_fetch(url, headers=None):
            self.assertIn("ai-gateway.vercel.sh", url)
            return {
                "data": [
                    {"id": "deepseek/deepseek-r1"},
                    {"id": "deepseek/deepseek-v3"},
                    {"id": "openai/gpt-5.5"},
                    {"id": "alibaba/qwen3-coder"},
                ]
            }

        original = providers._fetch_json
        providers._fetch_json = fake_fetch
        try:
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "deepseek",
                            "name": "DeepSeek",
                            "kind": "openai-compatible",
                            "auth": "api_key",
                            "models": [],
                        }
                    ]
                },
            )
            result = providers.refresh_provider_models(self.runs_dir, "deepseek")
        finally:
            providers._fetch_json = original
        provider = result["providers"][0]
        self.assertEqual(provider["models"], ["deepseek/deepseek-r1", "deepseek/deepseek-v3"])
        self.assertEqual(provider["models_source"], "catalog")

    def test_load_filters_overbroad_persisted_vendor_catalog_snapshot(self) -> None:
        providers.save_providers(
            self.runs_dir,
            {
                "providers": [
                    {
                        "id": "deepseek",
                        "name": "DeepSeek",
                        "kind": "openai-compatible",
                        "auth": "api_key",
                        "models": [
                            "alibaba/qwen3-coder",
                            "deepseek/deepseek-r1",
                            "openai/gpt-5.5",
                        ],
                        "models_source": "catalog",
                    }
                ]
            },
        )
        loaded = providers.load_providers(self.runs_dir)
        self.assertEqual(loaded["providers"][0]["models"], ["deepseek/deepseek-r1"])

    def test_codex_cli_models_use_local_cache(self) -> None:
        codex_home = self.tmp / "codex_home"
        codex_home.mkdir()
        (codex_home / "models_cache.json").write_text(
            json.dumps(
                {
                    "fetched_at": "2026-07-07T03:00:00Z",
                    "models": [
                        {"slug": "gpt-5.5", "display_name": "GPT-5.5"},
                        {"slug": "gpt-5.3-codex-spark", "display_name": "GPT-5.3-Codex-Spark"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        old_home = os.environ.get("CODEX_HOME")
        os.environ["CODEX_HOME"] = str(codex_home)
        try:
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "openai-cli",
                            "name": "OpenAI (CLI login)",
                            "kind": "openai",
                            "auth": "cli_login",
                            "models": ["gpt-3.5-turbo", "gpt-4o", "gpt-5.5"],
                            "models_source": "catalog",
                        }
                    ]
                },
            )
            loaded = providers.load_providers(self.runs_dir)
        finally:
            if old_home is None:
                del os.environ["CODEX_HOME"]
            else:
                os.environ["CODEX_HOME"] = old_home
        provider = loaded["providers"][0]
        self.assertEqual(provider["models"], ["gpt-5.5", "gpt-5.3-codex-spark"])
        self.assertEqual(provider["models_source"], "cli_cache")
        self.assertEqual(provider["models_fetched_at"], "2026-07-07T03:00:00Z")

    def test_cli_login_status_uses_runtime_status_command(self) -> None:
        original_which = providers.shutil.which
        original_run = providers.subprocess.run

        def fake_which(bin_name):
            return f"/bin/{bin_name}"

        def fake_run(command, **kwargs):
            self.assertEqual(command, ["codex", "login", "status"])
            self.assertEqual(kwargs["env"]["CODEX_CI"], "1")
            self.assertEqual(kwargs["env"]["TERM"], "dumb")
            return providers.subprocess.CompletedProcess(
                command, 0, stdout="Logged in using ChatGPT\n", stderr=""
            )

        providers.shutil.which = fake_which
        providers.subprocess.run = fake_run
        providers._CLI_STATUS_CACHE.clear()
        try:
            status = providers._cli_login_status("codex")
        finally:
            providers.shutil.which = original_which
            providers.subprocess.run = original_run
            providers._CLI_STATUS_CACHE.clear()
        self.assertEqual(status["status"], "ok")
        self.assertTrue(status["cli_present"])
        self.assertEqual(status["message"], "Logged in using ChatGPT")

    def test_codex_status_summary_prefers_logged_in_line(self) -> None:
        output = (
            "WARNING: proceeding, even though we could not update PATH\n"
            "Logged in using ChatGPT\n"
        )
        self.assertEqual(
            providers._summarize_cli_status("codex", output),
            "Logged in using ChatGPT",
        )

    def test_claude_api_key_status_is_not_cli_login(self) -> None:
        output = json.dumps(
            {
                "loggedIn": True,
                "authMethod": "api_key",
                "apiProvider": "firstParty",
                "apiKeySource": "ANTHROPIC_API_KEY",
            }
        )
        status, message = providers._interpret_cli_status("claude", output)
        self.assertEqual(status, "api_key")
        self.assertIn("not a local CLI login", message)

    def test_judge_gateway_conflict_detected(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        payload = {
            "name": "exp_gwconflict",
            "tasks_dir": str(tasks_dir),
            "tasks": [],
            "shared": {
                "evaluator_agent": "opencode",
                "evaluator_gateway": {
                    "opencode_provider": "gw-a",
                    "opencode_base_url": "https://a.example/v1",
                    "opencode_api_key_env": "A_KEY",
                },
                "judge_mode": "single",
            },
            "contenders": [
                {
                    "label": "doubao",
                    "agent": "opencode",
                    "model": "doubao",
                    "auth_mode": "env",
                    "opencode_provider": "gw-b",
                    "opencode_base_url": "https://b.example/v1",
                    "opencode_api_key_env": "B_KEY",
                }
            ],
        }
        with self.assertRaises(ExperimentError):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_codex_gateway_conflicts_with_codex_judge(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        payload = {
            "name": "exp_codexgw",
            "tasks_dir": str(tasks_dir),
            "tasks": [],
            "shared": {"evaluator_agent": "codex", "judge_mode": "single"},
            "contenders": [
                {
                    "label": "codex via openrouter",
                    "agent": "codex",
                    "model": "openai/gpt-5.3-codex",
                    "auth_mode": "env",
                    "codex_bin": "codex -c model_provider=openrouter",
                }
            ],
        }
        with self.assertRaises(ExperimentError):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        payload["shared"]["evaluator_agent"] = "claude"
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        joined = plan["plans"][0]["argv"]
        self.assertIn("codex -c model_provider=openrouter", joined)

    def test_judge_gateway_used_when_contender_not_opencode(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        payload = {
            "name": "exp_gwjudge",
            "tasks_dir": str(tasks_dir),
            "tasks": [],
            "shared": {
                "evaluator_agent": "opencode",
                "evaluator_model": "doubao-judge",
                "evaluator_gateway": {
                    "opencode_provider": "gw-a",
                    "opencode_base_url": "https://a.example/v1",
                    "opencode_api_key_env": "A_KEY",
                },
                "judge_mode": "single",
            },
            "contenders": [
                {"label": "claude", "agent": "claude", "model": "claude-opus-4-8", "auth_mode": "global"}
            ],
        }
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        joined = " ".join(plan["plans"][0]["argv"])
        self.assertIn("--opencode-base-url https://a.example/v1", joined)
        self.assertIn("--opencode-provider gw-a", joined)

    def test_resolve_env_spec(self) -> None:
        import os

        os.environ["STARBENCH_TEST_TOKEN"] = "sekrit"
        try:
            resolved = resolve_env_spec(
                {
                    "ANTHROPIC_BASE_URL": {"value": "https://gw.example"},
                    "ANTHROPIC_AUTH_TOKEN": {"from_env": "STARBENCH_TEST_TOKEN"},
                    "MISSING": {"from_env": "STARBENCH_TEST_ABSENT"},
                }
            )
        finally:
            del os.environ["STARBENCH_TEST_TOKEN"]
        self.assertEqual(resolved["ANTHROPIC_BASE_URL"], "https://gw.example")
        self.assertEqual(resolved["ANTHROPIC_AUTH_TOKEN"], "sekrit")
        self.assertNotIn("MISSING", resolved)

    def test_experiment_plan_carries_env_spec(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir()
        plan = experiments.plan_experiment(
            {
                "name": "exp_env",
                "tasks_dir": str(tasks_dir),
                "tasks": [],
                "shared": {"evaluator_agent": "codex", "judge_mode": "single"},
                "contenders": [
                    {
                        "label": "claude via gateway",
                        "agent": "claude",
                        "model": "claude-opus-4-8",
                        "auth_mode": "env",
                        "env": {
                            "ANTHROPIC_BASE_URL": {"value": "https://gw.example"},
                            "ANTHROPIC_AUTH_TOKEN": {"from_env": "GW_TOKEN"},
                        },
                    }
                ],
            },
            runs_dir=self.runs_dir,
        )
        item = plan["plans"][0]
        self.assertEqual(item["env_keys"], ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"])
        self.assertEqual(item["env_spec"]["ANTHROPIC_BASE_URL"], {"value": "https://gw.example"})


if __name__ == "__main__":
    unittest.main()
