"""Generic per-role option flags replace the runtime-named legacy flags."""
from __future__ import annotations

import unittest

from starbench.runner.cli import parse_args


class CliOptionFlagTests(unittest.TestCase):
    def test_executor_option_pairs_are_validated_and_coerced(self) -> None:
        args = parse_args(
            ["--executor-agent", "claude", "--executor-option", "max_turns=50"]
        )
        self.assertEqual(args.executor_options, {"max_turns": 50})

    def test_unknown_option_fails_at_parse_time(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--executor-agent", "gemini", "--executor-option", "max_turns=50"])

    def test_malformed_pair_fails(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--executor-agent", "claude", "--executor-option", "max_turns"])

    def test_evaluator_option_reaches_the_judge_box(self) -> None:
        args = parse_args(
            ["--evaluator-agent", "opencode", "--evaluator-option", "provider=yunwu"]
        )
        # opencode's api_key_env declares default="OPENAI_API_KEY" (Task-2 seam
        # fix): the resolver default-fills it, so every opencode box carries the
        # key exactly as the deleted --opencode-api-key-env flag default did.
        self.assertEqual(
            args.evaluator_options, {"provider": "yunwu", "api_key_env": "OPENAI_API_KEY"}
        )

    def test_legacy_flags_are_gone(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--claude-max-turns", "5"])
