"""Tests for the dsh_gateway injection branch."""
from __future__ import annotations

import unittest

from starbench.adapters.registry import get_builtin
from starbench.gui.injection import (
    DSH_COMPAT_KEY_VAR,
    DSH_COMPAT_ROUTE,
    NATIVE_PROVIDER_KEY_VARS,
    NATIVE_PROVIDER_ROUTES,
    PI_KEY_VARS,
    PI_PROVIDER_NAMES,
    builtin_settings,
)

DSH = get_builtin("dsh").info
PI = get_builtin("pi").info


class SharedProviderTableTests(unittest.TestCase):
    def test_pi_and_dsh_read_one_table_rather_than_two_copies(self):
        # dsh's `llm-pi-ai` adapter *is* the library behind the pi CLI, so the
        # route names and official key vars are one fact with two consumers.
        self.assertIs(PI_PROVIDER_NAMES, NATIVE_PROVIDER_ROUTES)
        self.assertIs(PI_KEY_VARS, NATIVE_PROVIDER_KEY_VARS)

    def test_the_shared_table_covers_exactly_pis_declared_provider_filter(self):
        self.assertEqual(set(NATIVE_PROVIDER_ROUTES), set(PI.provider_filter.kinds))
        self.assertEqual(set(NATIVE_PROVIDER_KEY_VARS), set(PI.provider_filter.kinds))

    def test_dsh_adds_exactly_one_kind_on_top_of_the_shared_table(self):
        # The extra kind is the one dsh serves through its native DeepSeek
        # adapter instead of the pi-ai twin.
        self.assertEqual(
            set(DSH.provider_filter.kinds) - set(NATIVE_PROVIDER_ROUTES),
            {"openai-compatible"},
        )


class DshGatewayTests(unittest.TestCase):
    def test_each_native_kind_maps_to_its_pi_ai_route_and_official_key_var(self):
        cases = [
            ("anthropic", "anthropic", "ANTHROPIC_API_KEY"),
            ("openai", "openai", "OPENAI_API_KEY"),
            ("google", "google", "GEMINI_API_KEY"),
            ("xai", "xai", "XAI_API_KEY"),
        ]
        for kind, route, official_var in cases:
            with self.subTest(kind=kind):
                provider = {"id": f"my-{kind}", "kind": kind, "api_key_env": "MY_SECRET_KEY"}
                settings = builtin_settings(DSH, provider)
                self.assertEqual(settings["auth_mode"], "env")
                self.assertEqual(
                    settings["gateway"],
                    {"provider": route, "base_url": None, "api_key_env": official_var},
                )
                self.assertEqual(settings["env"], {official_var: {"from_env": "MY_SECRET_KEY"}})

    def test_openai_compatible_rides_the_native_deepseek_route_with_its_endpoint(self):
        provider = {
            "id": "deepseek",
            "kind": "openai-compatible",
            "base_url": "https://api.deepseek.com",
            "api_key_env": "MY_DEEPSEEK_KEY",
        }
        settings = builtin_settings(DSH, provider)
        self.assertEqual(
            settings["gateway"],
            {
                "provider": DSH_COMPAT_ROUTE,
                "base_url": "https://api.deepseek.com",
                "api_key_env": DSH_COMPAT_KEY_VAR,
            },
        )
        self.assertEqual(settings["env"], {DSH_COMPAT_KEY_VAR: {"from_env": "MY_DEEPSEEK_KEY"}})

    def test_secrets_stay_named_not_inlined(self):
        provider = {"id": "p", "kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"}
        settings = builtin_settings(DSH, provider)
        self.assertEqual(settings["env"], {"ANTHROPIC_API_KEY": {"from_env": "ANTHROPIC_API_KEY"}})

    def test_provider_without_key_env_yields_no_env_override(self):
        provider = {"id": "p", "kind": "openai", "api_key_env": ""}
        settings = builtin_settings(DSH, provider)
        self.assertIsNone(settings["env"])
        self.assertEqual(settings["gateway"]["provider"], "openai")

    def test_cli_login_provider_falls_back_to_global_auth_mode(self):
        provider = {"id": "p", "kind": "anthropic", "auth": "cli_login"}
        self.assertEqual(builtin_settings(DSH, provider)["auth_mode"], "global")

    def test_kind_outside_the_provider_filter_does_not_crash(self):
        provider = {"id": "p", "kind": "bedrock", "api_key_env": "MY_SECRET_KEY"}
        settings = builtin_settings(DSH, provider)
        self.assertIsNone(settings["gateway"]["provider"])
        self.assertIsNone(settings["env"])


if __name__ == "__main__":
    unittest.main()
