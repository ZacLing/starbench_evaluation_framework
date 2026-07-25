"""Compute the launch-time injection for a (runtime, provider) pair.

This is the backend home of the logic that used to live in the frontend
``NewRun.tsx`` ``providerSettings()``: given a runtime's ``InjectionChannel``
(carried on its ``RuntimeInfo``) or a custom runtime's spec metadata, plus a
resolved AI provider, produce the concrete ``auth_mode``, gateway flags, codex
bin override, and env overrides that ``plan_experiment`` feeds into
``build_run_argv``.

Single source of truth: the per-runtime facts come from ``adapters`` (built-in)
or the custom runtime JSON (custom, surfaced by ``agents.get_custom_agent``);
this module only maps a channel + provider to settings. The returned shape
mirrors the old ``providerSettings()`` return exactly, so a reference-shaped
contender (``{agent, provider_id, model, ...}``) yields byte-for-byte the same
launch plan as the old explicit-env shape.

Invariants:
- Output keys: ``auth_mode`` (always), ``gateway`` (always, possibly empty),
  ``codex_bin`` (only codex-config channel), ``env`` (env channels; ``None`` when
  empty, matching the frontend's ``undefined``).
- Secrets never appear here: env entries carry either a literal endpoint
  (``{"value": ...}``) or the *name* of the source env var (``{"from_env": ...}``).

改什么来这里: how a provider's endpoint/key is injected into a runtime.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from ..adapters.base import RuntimeInfo

# Mirrors brand.tsx DEFAULT_OPENAI_BASE_URLS and providers.DEFAULT_BASE_URLS:
# the official endpoint assumed when an OpenAI-protocol provider names no
# base_url of its own (only openai/xai have a well-known default).
DEFAULT_OPENAI_BASE_URLS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
}

Settings = Dict[str, Any]


def _auth_mode(provider: Dict[str, Any]) -> str:
    return "global" if provider.get("auth") == "cli_login" else "env"


def _provider_endpoint(protocol: str, provider: Dict[str, Any]) -> str:
    """The endpoint a provider exposes for a wire protocol (custom spec_env)."""
    kind = str(provider.get("kind") or "")
    base_url = str(provider.get("base_url") or "")
    if protocol == "openai":
        return base_url or DEFAULT_OPENAI_BASE_URLS.get(kind, "")
    if protocol == "anthropic":
        return base_url if kind == "anthropic" else str(provider.get("anthropic_base_url") or "")
    if protocol == "gemini":
        return base_url if kind == "google" else str(provider.get("gemini_base_url") or "")
    return ""


def _channel_endpoint(kind: str, provider: Dict[str, Any]) -> str:
    """Endpoint for a built-in env channel (anthropic_env / gemini_env)."""
    provider_kind = str(provider.get("kind") or "")
    base_url = str(provider.get("base_url") or "")
    if kind == "anthropic_env":
        return base_url if provider_kind == "anthropic" else str(provider.get("anthropic_base_url") or "")
    if kind == "gemini_env":
        return base_url if provider_kind == "google" else str(provider.get("gemini_base_url") or "")
    return ""


def custom_settings(custom_meta: Dict[str, Any], provider: Dict[str, Any]) -> Settings:
    """Injection for a custom runtime declaring endpoint/key env var names."""
    protocol = str(custom_meta.get("protocol") or "none")
    env: Dict[str, Any] = {}
    endpoint = _provider_endpoint(protocol, provider)
    base_url_env = str(custom_meta.get("base_url_env") or "")
    api_key_env = str(custom_meta.get("api_key_env") or "")
    if base_url_env and endpoint:
        env[base_url_env] = {"value": endpoint}
    if api_key_env and provider.get("api_key_env"):
        env[api_key_env] = {"from_env": provider["api_key_env"]}
    return {"auth_mode": _auth_mode(provider), "gateway": {}, "env": env or None}


def builtin_settings(info: RuntimeInfo, provider: Dict[str, Any]) -> Settings:
    """Injection for a built-in runtime, driven by its ``InjectionChannel``."""
    auth_mode = _auth_mode(provider)
    channel = info.injection
    kind = channel.kind

    if kind == "opencode_gateway":
        base = str(provider.get("base_url") or "") or DEFAULT_OPENAI_BASE_URLS.get(
            str(provider.get("kind") or ""), ""
        )
        # Gateway keys are the opencode adapter's declared option names
        # (provider/base_url/api_key_env); planning.py folds them straight into
        # the role's option box, where resolve_runtime_options validates them.
        return {
            "auth_mode": auth_mode,
            "gateway": {
                "provider": provider.get("id"),
                "base_url": base or None,
                "api_key_env": str(provider.get("api_key_env") or "") or None,
            },
        }

    if kind == "codex_config":
        # Official OpenAI needs no overrides; any other endpoint is wired through
        # a codex bin prefix that speaks the OpenAI Responses API.
        if str(provider.get("kind") or "") != "openai" and provider.get("base_url"):
            gw = re.sub(r"[^A-Za-z0-9_]", "_", str(provider.get("id") or ""))
            env_key = str(provider.get("api_key_env") or "") or channel.default_api_key_env
            base_url = str(provider.get("base_url"))
            codex_bin = " ".join(
                [
                    "codex",
                    f"-c model_provider={gw}",
                    f"-c model_providers.{gw}.name={gw}",
                    f"-c model_providers.{gw}.base_url={base_url}",
                    f"-c model_providers.{gw}.env_key={env_key}",
                    f"-c model_providers.{gw}.wire_api=responses",
                ]
            )
            return {"auth_mode": auth_mode, "gateway": {}, "codex_bin": codex_bin}
        return {"auth_mode": auth_mode, "gateway": {}}

    if kind in ("anthropic_env", "gemini_env"):
        endpoint = _channel_endpoint(kind, provider)
        if endpoint:
            token_src = str(provider.get("api_key_env") or "") or channel.default_api_key_env
            env = {
                channel.base_url_var: {"value": endpoint},
                channel.api_key_var: {"from_env": token_src},
            }
            if kind == "anthropic_env" and str(provider.get("kind") or "") != "anthropic":
                # Claude Code gives ANTHROPIC_API_KEY special meaning for the
                # official Anthropic API. Gateways such as OpenRouter document
                # ANTHROPIC_AUTH_TOKEN plus an explicitly empty API-key var, so
                # a user's ambient Anthropic key cannot override the gateway.
                env["ANTHROPIC_API_KEY"] = {"value": ""}
            return {
                "auth_mode": auth_mode,
                "gateway": {},
                "env": env,
            }
        return {"auth_mode": auth_mode, "gateway": {}}

    # kind == "none" (Grok Build): no override channel.
    return {"auth_mode": auth_mode, "gateway": {}}


def settings_for(
    provider: Dict[str, Any],
    *,
    info: Optional[RuntimeInfo] = None,
    custom_meta: Optional[Dict[str, Any]] = None,
) -> Settings:
    """Injection settings for a runtime + provider (built-in or custom)."""
    if custom_meta is not None:
        return custom_settings(custom_meta, provider)
    if info is not None:
        return builtin_settings(info, provider)
    raise ValueError("settings_for needs either info (built-in) or custom_meta (custom).")


PROVIDERLESS_SETTINGS: Settings = {"auth_mode": "global", "gateway": {}, "env": None}
