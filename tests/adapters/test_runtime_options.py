"""RuntimeOption declarations and the shared box resolver."""
from __future__ import annotations

import unittest

from starbench.adapters import get_builtin, list_builtin
from starbench.adapters.base import OPTION_NAME_RE, resolve_runtime_options


class DeclarationGuardTests(unittest.TestCase):
    def test_declared_knobs_match_the_spec(self) -> None:
        by_id = {a.info.id: a.info for a in list_builtin()}
        self.assertEqual(
            [(o.name, o.type, o.role, o.surface) for o in by_id["claude"].options],
            [("max_turns", "integer", "executor", "user")],
        )
        self.assertEqual(
            [(o.name, o.type, o.role, o.surface) for o in by_id["opencode"].options],
            [
                ("provider", "string", "both", "wiring"),
                ("base_url", "string", "both", "wiring"),
                ("api_key_env", "string", "both", "wiring"),
            ],
        )
        for agent_id in ("codex", "gemini", "grok"):
            self.assertEqual(by_id[agent_id].options, ())

    def test_declarations_are_well_formed(self) -> None:
        for adapter in list_builtin():
            names = [o.name for o in adapter.info.options]
            self.assertEqual(len(names), len(set(names)), adapter.info.id)
            for option in adapter.info.options:
                self.assertRegex(option.name, OPTION_NAME_RE)
                self.assertIn(option.type, ("integer", "string", "boolean", "enum"))
                self.assertIn(option.role, ("executor", "evaluator", "both"))
                self.assertIn(option.surface, ("user", "wiring"))
                if option.type == "enum":
                    self.assertTrue(option.choices)
                if option.surface == "user":
                    self.assertTrue(option.label)


class ResolverTests(unittest.TestCase):
    def test_unknown_key_is_rejected_with_declared_list(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_options(get_builtin("gemini"), "executor", {"max_turns": 50})
        message = str(ctx.exception)
        self.assertIn('gemini has no option named "max_turns"', message)
        self.assertIn("declares no executor-side options", message)

    def test_unknown_key_lists_available_options(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_options(get_builtin("claude"), "executor", {"max_turnz": 5})
        self.assertIn("max_turns (integer)", str(ctx.exception))

    def test_integer_coercion_accepts_decimal_strings(self) -> None:
        resolved = resolve_runtime_options(get_builtin("claude"), "executor", {"max_turns": "50"})
        self.assertEqual(resolved, {"max_turns": 50})

    def test_integer_rejects_non_numeric(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_options(get_builtin("claude"), "executor", {"max_turns": "abc"})
        self.assertIn('claude option max_turns expects an integer, got "abc"', str(ctx.exception))

    def test_role_filter_excludes_wrong_side(self) -> None:
        # max_turns is executor-only: the judge side must not accept it.
        with self.assertRaises(ValueError):
            resolve_runtime_options(get_builtin("claude"), "evaluator", {"max_turns": 5})

    def test_wiring_keys_resolve_for_both_roles(self) -> None:
        raw = {"provider": "yunwu", "base_url": "https://yunwu.ai/v1", "api_key_env": "OPENAI_API_KEY"}
        for role in ("executor", "evaluator"):
            self.assertEqual(resolve_runtime_options(get_builtin("opencode"), role, raw), raw)

    def test_empty_box_resolves_empty(self) -> None:
        self.assertEqual(resolve_runtime_options(get_builtin("claude"), "executor", {}), {})

    def test_opencode_box_fills_default_api_key_name(self) -> None:
        resolved = resolve_runtime_options(get_builtin("opencode"), "executor", {})
        self.assertEqual(resolved, {"api_key_env": "OPENAI_API_KEY"})
