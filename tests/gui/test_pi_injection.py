"""Tests for the pi_gateway injection branch."""
from __future__ import annotations

import unittest

from starbench.adapters.registry import get_builtin
from starbench.gui.injection import PI_KEY_VARS, PI_PROVIDER_NAMES, builtin_settings

PI = get_builtin("pi").info


class PiGatewayTests(unittest.TestCase):
    def test_injection_tables_cover_exactly_the_declared_provider_filter(self):
        # The adapter's provider_filter is the single source for which kinds pi
        # serves; these two tables are the injection side of the same fact. Add
        # a kind to one without the others and this fails instead of silently
        # producing a provider the console offers but cannot wire.
        self.assertEqual(set(PI_KEY_VARS), set(PI.provider_filter.kinds))
        self.assertEqual(set(PI_PROVIDER_NAMES), set(PI.provider_filter.kinds))

    def test_each_native_kind_maps_to_pi_provider_and_official_key_var(self):
        cases = [
            ("anthropic", "anthropic", "ANTHROPIC_API_KEY"),
            ("openai", "openai", "OPENAI_API_KEY"),
            ("google", "google", "GEMINI_API_KEY"),
            ("xai", "xai", "XAI_API_KEY"),
        ]
        for kind, pi_name, official_var in cases:
            with self.subTest(kind=kind):
                provider = {"id": f"my-{kind}", "kind": kind, "api_key_env": "MY_SECRET_KEY"}
                settings = builtin_settings(PI, provider)
                self.assertEqual(settings["auth_mode"], "env")
                self.assertEqual(settings["gateway"], {"provider": pi_name})
                self.assertEqual(settings["env"], {official_var: {"from_env": "MY_SECRET_KEY"}})

    def test_official_key_var_source_stays_named_not_inlined(self):
        provider = {"id": "p", "kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"}
        settings = builtin_settings(PI, provider)
        self.assertEqual(settings["env"], {"ANTHROPIC_API_KEY": {"from_env": "ANTHROPIC_API_KEY"}})

    def test_provider_without_key_env_yields_no_env_overrides(self):
        provider = {"id": "p", "kind": "openai", "api_key_env": ""}
        settings = builtin_settings(PI, provider)
        self.assertIsNone(settings["env"])
        self.assertEqual(settings["gateway"], {"provider": "openai"})

    def test_kind_outside_the_provider_filter_does_not_crash(self):
        # "openai-compatible" is the one ProviderKind pi's filter excludes, so
        # the GUI never offers it here; the branch must still degrade quietly
        # rather than crash: no pi provider name, no env override.
        provider = {"id": "p", "kind": "openai-compatible", "api_key_env": "MY_SECRET_KEY"}
        settings = builtin_settings(PI, provider)
        self.assertEqual(settings["gateway"], {"provider": None})
        self.assertIsNone(settings["env"])


if __name__ == "__main__":
    unittest.main()
