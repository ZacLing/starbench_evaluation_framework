"""RuntimeOption declarations and the shared box resolver."""
from __future__ import annotations

import unittest

from starbench.adapters import get_builtin, list_builtin
from starbench.adapters.base import (
    OPTION_NAME_RE,
    RuntimeOption,
    _coerce_option,
    resolve_runtime_options,
)


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


class CoerceOptionTests(unittest.TestCase):
    """Direct coverage of _coerce_option's boolean and enum branches.

    No adapter declares a boolean or enum knob yet, so the resolver tests above
    only reach the integer/string paths through real adapters. These build a
    throwaway RuntimeOption inline to exercise the untested branches — no adapter
    changes.
    """

    def test_boolean_accepts_python_bools(self) -> None:
        option = RuntimeOption(name="x", type="boolean")
        self.assertIs(_coerce_option("claude", option, True), True)
        self.assertIs(_coerce_option("claude", option, False), False)

    def test_boolean_accepts_true_false_strings_case_insensitively(self) -> None:
        option = RuntimeOption(name="x", type="boolean")
        self.assertIs(_coerce_option("claude", option, "true"), True)
        self.assertIs(_coerce_option("claude", option, "TRUE"), True)
        self.assertIs(_coerce_option("claude", option, "false"), False)
        self.assertIs(_coerce_option("claude", option, "False"), False)

    def test_boolean_rejects_non_boolean_string(self) -> None:
        option = RuntimeOption(name="x", type="boolean")
        with self.assertRaises(ValueError) as ctx:
            _coerce_option("claude", option, "yes")
        self.assertIn(
            'claude option x expects true or false, got "yes".', str(ctx.exception)
        )

    def test_enum_accepts_a_declared_choice(self) -> None:
        option = RuntimeOption(name="x", type="enum", choices=("a", "b"))
        self.assertEqual(_coerce_option("claude", option, "a"), "a")

    def test_enum_rejects_an_undeclared_choice(self) -> None:
        option = RuntimeOption(name="x", type="enum", choices=("a", "b"))
        with self.assertRaises(ValueError) as ctx:
            _coerce_option("claude", option, "c")
        self.assertIn(
            'claude option x must be one of a, b; got "c".', str(ctx.exception)
        )

    def test_integer_rejects_python_bool(self) -> None:
        # The isinstance(value, bool) guard: True must not coerce to 1.
        option = RuntimeOption(name="x", type="integer")
        with self.assertRaises(ValueError) as ctx:
            _coerce_option("claude", option, True)
        self.assertIn(
            'claude option x expects an integer, got "True".', str(ctx.exception)
        )
