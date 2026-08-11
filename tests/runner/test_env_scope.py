"""Executor/judge environment scope partitioning in ``runner.env_scope``."""
from __future__ import annotations

import unittest


class ScopedEnvTests(unittest.TestCase):
    def test_prefixed_vars_split_into_executor_and_judge_scopes(self) -> None:
        from starbench.runner.env_scope import (
            EXECUTOR_ENV_PREFIX,
            JUDGE_ENV_PREFIX,
            partition_scoped_env,
            scoped_base_envs,
        )

        environ = {
            "PATH": "/usr/bin",
            f"{EXECUTOR_ENV_PREFIX}OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
            f"{JUDGE_ENV_PREFIX}ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        }
        clean, executor_scope, judge_scope = partition_scoped_env(environ)
        self.assertNotIn(f"{EXECUTOR_ENV_PREFIX}OPENAI_BASE_URL", clean)
        self.assertNotIn(f"{JUDGE_ENV_PREFIX}ANTHROPIC_BASE_URL", clean)
        self.assertEqual(executor_scope, {"OPENAI_BASE_URL": "https://openrouter.ai/api/v1"})
        self.assertEqual(judge_scope, {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})

        executor_base, judge_base = scoped_base_envs(environ)
        # Executor sees X, judge does not; a plain ambient var stays visible to both.
        self.assertEqual(executor_base["OPENAI_BASE_URL"], "https://openrouter.ai/api/v1")
        self.assertNotIn("OPENAI_BASE_URL", judge_base)
        self.assertEqual(judge_base["ANTHROPIC_BASE_URL"], "https://api.anthropic.com")
        self.assertNotIn("ANTHROPIC_BASE_URL", executor_base)
        self.assertEqual(executor_base["PATH"], "/usr/bin")
        self.assertEqual(judge_base["PATH"], "/usr/bin")
        # The prefix key names themselves never reach either base env (ambient).
        for key in list(executor_base) + list(judge_base):
            self.assertFalse(key.startswith(EXECUTOR_ENV_PREFIX))
            self.assertFalse(key.startswith(JUDGE_ENV_PREFIX))

    def test_no_prefix_means_both_bases_equal_ambient(self) -> None:
        # Standalone CLI use (no console prefixes): both scopes equal the ambient
        # environment, so ordinary env vars stay visible to executor and judge.
        from starbench.runner.env_scope import scoped_base_envs

        environ = {"PATH": "/usr/bin", "OPENAI_API_KEY": "sk-real"}
        executor_base, judge_base = scoped_base_envs(environ)
        self.assertEqual(executor_base, environ)
        self.assertEqual(judge_base, environ)


if __name__ == "__main__":
    unittest.main()
