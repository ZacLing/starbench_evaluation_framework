"""Registry adapter facts (RuntimeInfo) match the GUI tables they replace.

``RuntimeInfo`` is the single source of truth for per-runtime facts; these
tests pin each adapter's metadata against the GUI copies so they cannot drift."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.adapters import DEFAULT_DOCKER_IMAGES, get_builtin, list_builtin, resolve
from starbench.adapters.registry import BUILTIN_AGENTS
from starbench.adapters.spec import SpecAdapter
from starbench.gui.agents import BUILTIN_AGENTS as GUI_BUILTIN_AGENTS
from starbench.gui.experiments import JUDGE_ENV_SENSITIVE
from starbench.gui.library import AGENT_ENV_KEYS


CLAUDE_DOCKER_ENV_WHITELIST = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]
DOCKER_ENV_WHITELIST_BY_ID = {
    "codex": ["CODEX_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"],
    "claude": CLAUDE_DOCKER_ENV_WHITELIST,
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL"],
    "grok": ["XAI_API_KEY"],
    "opencode": ["OPENAI_API_KEY", "XAI_API_KEY"],
}


class RegistryTests(unittest.TestCase):
    def test_five_builtins_in_stable_order(self) -> None:
        ids = [adapter.info.id for adapter in list_builtin()]
        self.assertEqual(ids, ["codex", "claude", "gemini", "grok", "opencode"])
        self.assertEqual(BUILTIN_AGENTS, {"codex", "claude", "gemini", "grok", "opencode"})

    def test_default_docker_images_are_derived_and_match_gui(self) -> None:
        self.assertEqual(
            DEFAULT_DOCKER_IMAGES,
            {
                "codex": "starbench-codex:latest",
                "claude": "starbench-claude-code:latest",
                "gemini": "starbench-gemini-cli:latest",
                "grok": "starbench-grok:latest",
                "opencode": "starbench-opencode:latest",
            },
        )
        for agent in GUI_BUILTIN_AGENTS:
            self.assertEqual(agent["docker_image"], DEFAULT_DOCKER_IMAGES[agent["id"]])

    def test_runtime_info_matches_gui_agents_table(self) -> None:
        gui_by_id = {agent["id"]: agent for agent in GUI_BUILTIN_AGENTS}
        for adapter in list_builtin():
            info = adapter.info
            gui = gui_by_id[info.id]
            self.assertEqual(info.label, gui["label"])
            self.assertEqual(info.description, gui["note"])
            self.assertEqual(info.protocol, gui["protocol"])
            self.assertEqual(info.bin, gui["bin"])
            self.assertEqual(info.docker_image, gui["docker_image"])
            self.assertTrue(info.docker_capable)

    def test_credential_env_keys_match_preflight_table(self) -> None:
        for adapter in list_builtin():
            self.assertEqual(
                list(adapter.info.credential_env_keys),
                AGENT_ENV_KEYS.get(adapter.info.id, []),
            )

    def test_judge_sensitive_env_matches_experiments_table(self) -> None:
        for adapter in list_builtin():
            self.assertEqual(
                adapter.info.judge_sensitive_env,
                JUDGE_ENV_SENSITIVE[adapter.info.id],
            )

    def test_docker_env_whitelist_matches_container_forwarding(self) -> None:
        for adapter in list_builtin():
            self.assertEqual(
                list(adapter.info.docker_env_whitelist),
                DOCKER_ENV_WHITELIST_BY_ID[adapter.info.id],
            )

    def test_default_executor_backend_is_docker_only_for_codex(self) -> None:
        for adapter in list_builtin():
            expected = "docker" if adapter.info.id == "codex" else "local"
            self.assertEqual(adapter.info.default_executor_backend, expected)

    def test_get_builtin_rejects_unknown(self) -> None:
        with self.assertRaises(ValueError):
            get_builtin("nope")

    def test_resolve_returns_the_same_builtin_singletons(self) -> None:
        self.assertIs(resolve("codex"), get_builtin("codex"))

    def test_resolve_custom_wraps_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtimes = Path(tmp)
            (runtimes / "fake.json").write_text(
                json.dumps(
                    {
                        "id": "fake",
                        "command": "fake-cli",
                        "args": ["run"],
                        "parser": "text",
                        "prompt_via": "stdin",
                        "docker": {"image": "starbench-fake:latest"},
                    }
                ),
                encoding="utf-8",
            )
            adapter = resolve("custom:fake", runtimes)
            self.assertIsInstance(adapter, SpecAdapter)
            self.assertEqual(adapter.info.id, "custom:fake")
            self.assertEqual(adapter.info.bin, "fake-cli")
            self.assertEqual(adapter.info.docker_image, "starbench-fake:latest")
            self.assertTrue(adapter.info.docker_capable)
            self.assertEqual(adapter.info.default_executor_backend, "local")

    def test_resolve_rejects_unknown_agent(self) -> None:
        with self.assertRaises(ValueError):
            resolve("bogus")


if __name__ == "__main__":
    unittest.main()
