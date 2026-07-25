"""P2 acceptance tests: GUI reads the registry, and the reference-shaped
experiment payload is byte-for-byte equivalent to the old explicit shape.

Two things are asserted here:

1. ``/api/agents`` (``agents.list_agents``) still carries every historical
   built-in field unchanged, plus the new ``provider_filter`` derived from the
   adapter registry (the single source of truth).

2. For a matrix of (contender, judge) combinations, a payload written in the new
   *reference* shape (``{agent, provider_id, model, ...}`` / shared
   ``evaluator_provider_id``) and the same combination written in the old
   *explicit* shape (inline env / codex_bin / gateway) produce identical launch
   plans — same ``argv``, ``env_spec`` and ``env_keys`` per contender. This is
   the guard that lets the frontend delete ``providerSettings()`` safely.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from starbench.gui import agents, experiments  # noqa: E402

# The exact codex bin prefix providerSettings() built for an OpenAI-compatible
# gateway; the reference path must reproduce it character-for-character.
OPENROUTER_CODEX_BIN = (
    "codex -c model_provider=openrouter "
    "-c model_providers.openrouter.name=openrouter "
    "-c model_providers.openrouter.base_url=https://openrouter.ai/api/v1 "
    "-c model_providers.openrouter.env_key=OPENROUTER_API_KEY "
    "-c model_providers.openrouter.wire_api=responses"
)


class AgentsRegistrySnapshotTest(unittest.TestCase):
    def test_builtin_carries_old_fields_plus_provider_filter(self) -> None:
        listing = agents.list_agents(agents.DEFAULT_RUNTIMES_DIR)
        by_id = {agent["id"]: agent for agent in listing["builtin"]}
        # Historical display order preserved.
        self.assertEqual(
            [a["id"] for a in listing["builtin"]],
            ["claude", "codex", "gemini", "grok", "opencode"],
        )
        # Every historical field intact.
        codex = by_id["codex"]
        self.assertEqual(codex["label"], "Codex")
        self.assertEqual(codex["note"], "OpenAI's coding agent")
        self.assertEqual(codex["protocol"], "openai")
        self.assertTrue(codex["docker_capable"])
        self.assertEqual(codex["docker_image"], "starbench-codex:latest")
        self.assertTrue(codex["builtin"])
        self.assertIn("bin", codex["cli"])
        # New field: provider_filter, and codex (unlike opencode) excludes xai.
        self.assertEqual(codex["provider_filter"]["kinds"], ["openai", "openai-compatible"])
        self.assertEqual(
            by_id["opencode"]["provider_filter"]["kinds"],
            ["openai-compatible", "openai", "xai"],
        )
        self.assertTrue(by_id["claude"]["provider_filter"]["accepts_anthropic_endpoint"])
        self.assertTrue(by_id["gemini"]["provider_filter"]["accepts_gemini_endpoint"])
        self.assertEqual(by_id["grok"]["provider_filter"]["kinds"], ["xai"])

    def test_custom_provider_filter_derived_from_protocol(self) -> None:
        listing = agents.list_agents(agents.DEFAULT_RUNTIMES_DIR)
        by_id = {agent["id"]: agent for agent in listing["custom"]}
        qwen = by_id["custom:qwen-code"]
        # openai custom runtimes accept xai (matching the frontend custom branch).
        self.assertEqual(
            qwen["provider_filter"]["kinds"], ["openai-compatible", "openai", "xai"]
        )


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class ReferenceShapeEquivalenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_ref_equiv_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        task_dir = self.tasks_dir / "demo"
        task_dir.mkdir()
        _write_json(
            task_dir / "task.json",
            {
                "id": "demo",
                "name": "Equivalence fixture",
                "prompt": "prompt.md",
                "rubrics": "rubrics.json",
                "timeout_seconds": 60,
                "allow_web_search": False,
            },
        )
        (task_dir / "prompt.md").write_text("Create outputs/result.txt.\n", encoding="utf-8")
        _write_json(
            task_dir / "rubrics.json",
            {
                "rubrics": [
                    {
                        "id": "R001",
                        "question": "Does outputs/result.txt exist?",
                        "expected": True,
                        "fail_fast": True,
                    }
                ]
            },
        )
        self.runtimes_dir = self.tmp / "runtimes"
        self.runtimes_dir.mkdir()
        _write_json(
            self.runtimes_dir / "qwen-code.json",
            {
                "id": "qwen-code",
                "command": "qwen",
                "args": ["--output-format", "json", "--yolo"],
                "model_flag": "-m",
                "prompt_via": "stdin",
                "parser": "headless-json",
                "protocol": "openai",
                "base_url_env": "OPENAI_BASE_URL",
                "api_key_env": "OPENAI_API_KEY",
                "docker": {"image": "starbench-qwen:latest"},
            },
        )
        _write_json(
            self.runtimes_dir / "kimi-code.json",
            {
                "id": "kimi-code",
                "command": "kimi",
                "args": ["--print"],
                "prompt_via": "stdin",
                "parser": "text",
                "protocol": "none",
            },
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plan(self, contender: dict, shared_extra: dict) -> dict:
        shared = {
            "judge_mode": "single",
            "executor_backend": "local",
            "seed": 7,
            "batch_size": 1,
            "repeat": 1,
            "evaluator_timeout_seconds": 600,
            **shared_extra,
        }
        payload = {
            "name": "equiv",
            "tasks_dir": str(self.tasks_dir),
            "tasks": ["demo"],
            "shared": shared,
            "contenders": [contender],
        }
        return experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )

    def _assert_equivalent(
        self,
        *,
        ref_contender: dict,
        legacy_contender: dict,
        ref_shared: dict,
        legacy_shared: dict,
    ) -> None:
        ref = self._plan(ref_contender, ref_shared)
        legacy = self._plan(legacy_contender, legacy_shared)
        self.assertEqual(len(ref["plans"]), 1)
        self.assertEqual(len(legacy["plans"]), 1)
        r, l = ref["plans"][0], legacy["plans"][0]
        self.assertEqual(r["argv"], l["argv"], "argv differs")
        self.assertEqual(r.get("run_plan"), l.get("run_plan"), "run_plan differs")
        self.assertEqual(r["env_spec"], l["env_spec"], "env_spec differs")
        self.assertEqual(r["env_keys"], l["env_keys"], "env_keys differs")
        self.assertEqual(r["run_id"], l["run_id"])

    # -- codex through an OpenAI-compatible gateway (bin config overrides) -----
    def test_codex_gateway(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "codex",
                "provider_id": "openrouter",
                "model": "openai/gpt-5.3-codex",
                "thinking_effort": "none",
            },
            legacy_contender={
                "label": "c",
                "agent": "codex",
                "model": "openai/gpt-5.3-codex",
                "auth_mode": "env",
                "thinking_effort": "none",
                "codex_bin": OPENROUTER_CODEX_BIN,
            },
            # Non-codex judge so the codex-bin gateway does not reroute the judge.
            ref_shared={
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "evaluator_provider_id": "anthropic",
            },
            legacy_shared={
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "evaluator_auth_mode": "env",
            },
        )

    # -- claude through deepseek's anthropic-compatible endpoint (env) ---------
    def test_claude_deepseek(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "claude",
                "provider_id": "deepseek",
                "model": "deepseek-chat",
            },
            legacy_contender={
                "label": "c",
                "agent": "claude",
                "model": "deepseek-chat",
                "auth_mode": "env",
                "env": {
                    "ANTHROPIC_BASE_URL": {"value": "https://api.deepseek.com/anthropic"},
                    "ANTHROPIC_AUTH_TOKEN": {"from_env": "DEEPSEEK_API_KEY"},
                    "ANTHROPIC_API_KEY": {"value": ""},
                },
            },
            ref_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_provider_id": "openai",
            },
            legacy_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "env",
            },
        )

    # -- claude through OpenRouter's Anthropic-compatible endpoint -------------
    def test_claude_openrouter(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "claude",
                "provider_id": "openrouter",
                "model": "anthropic/claude-sonnet-4.5",
            },
            legacy_contender={
                "label": "c",
                "agent": "claude",
                "model": "anthropic/claude-sonnet-4.5",
                "auth_mode": "env",
                "env": {
                    "ANTHROPIC_BASE_URL": {"value": "https://openrouter.ai/api"},
                    "ANTHROPIC_AUTH_TOKEN": {"from_env": "OPENROUTER_API_KEY"},
                    "ANTHROPIC_API_KEY": {"value": ""},
                },
            },
            ref_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_provider_id": "openai",
            },
            legacy_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "env",
            },
        )

    # -- gemini on the official Google API (no injection) ---------------------
    def test_gemini_google(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "gemini",
                "provider_id": "google",
                "model": "gemini-2.5-pro",
            },
            legacy_contender={
                "label": "c",
                "agent": "gemini",
                "model": "gemini-2.5-pro",
                "auth_mode": "env",
            },
            ref_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_provider_id": "openai",
            },
            legacy_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "env",
            },
        )

    # -- opencode through openrouter (gateway flags) --------------------------
    def test_opencode_openrouter(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "opencode",
                "provider_id": "openrouter",
                "model": "openrouter/some-model",
            },
            legacy_contender={
                "label": "c",
                "agent": "opencode",
                "model": "openrouter/some-model",
                "auth_mode": "env",
                "provider": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key_env": "OPENROUTER_API_KEY",
            },
            ref_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_provider_id": "openai",
            },
            legacy_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "env",
            },
        )

    # -- custom qwen through openrouter (spec-declared env vars) ---------------
    def test_custom_qwen_openrouter(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "custom:qwen-code",
                "provider_id": "openrouter",
                "model": "qwen3-coder",
            },
            legacy_contender={
                "label": "c",
                "agent": "custom:qwen-code",
                "model": "qwen3-coder",
                "auth_mode": "env",
                "env": {
                    "OPENAI_BASE_URL": {"value": "https://openrouter.ai/api/v1"},
                    "OPENAI_API_KEY": {"from_env": "OPENROUTER_API_KEY"},
                },
            },
            # claude judge: a codex judge would clash with the OPENAI_* injection.
            ref_shared={
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "evaluator_provider_id": "anthropic",
            },
            legacy_shared={
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "evaluator_auth_mode": "env",
            },
        )

    # -- custom kimi with no provider (own login/config) ----------------------
    def test_custom_kimi_providerless(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "custom:kimi-code",
                "provider_id": "",
                "model": "",
            },
            legacy_contender={
                "label": "c",
                "agent": "custom:kimi-code",
                "model": "",
                "auth_mode": "global",
            },
            ref_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_provider_id": "openai",
            },
            legacy_shared={
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "env",
            },
        )

    # -- judge = claude on the official Anthropic API -------------------------
    def test_judge_claude_official(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "codex",
                "provider_id": "openai",
                "model": "gpt-5.5",
            },
            legacy_contender={
                "label": "c",
                "agent": "codex",
                "model": "gpt-5.5",
                "auth_mode": "env",
            },
            ref_shared={
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "evaluator_provider_id": "anthropic",
            },
            legacy_shared={
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "evaluator_auth_mode": "env",
            },
        )

    # -- judge = opencode through a gateway, propagated to a non-opencode run --
    def test_judge_opencode_gateway(self) -> None:
        self._assert_equivalent(
            ref_contender={
                "label": "c",
                "agent": "claude",
                "provider_id": "anthropic-cli",
                "model": "claude-opus-4-8",
            },
            legacy_contender={
                "label": "c",
                "agent": "claude",
                "model": "claude-opus-4-8",
                "auth_mode": "global",
            },
            ref_shared={
                "evaluator_agent": "opencode",
                "evaluator_model": "judge-model",
                "evaluator_provider_id": "openrouter",
            },
            legacy_shared={
                "evaluator_agent": "opencode",
                "evaluator_model": "judge-model",
                "evaluator_auth_mode": "env",
                "evaluator_gateway": {
                    "provider": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key_env": "OPENROUTER_API_KEY",
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
