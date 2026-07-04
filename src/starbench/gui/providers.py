"""AI providers: named endpoints + credentials + model catalogs.

A provider is `{id, name, kind, base_url, api_key_env, models}` stored in
`<runs-dir>/providers.json`. The console never stores API keys, only the name
of the environment variable that holds one; `key_present` is computed at read
time. Built-in presets are served until the user saves their own file.

Provider kinds map to agent runtimes the same way model families do:
anthropic -> claude, openai -> codex, google -> gemini, xai -> grok, and
openai-compatible -> opencode (with gateway flags derived from the provider).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from .data import SAFE_ID, _read_json

PROVIDER_KINDS = ("anthropic", "openai", "google", "xai", "openai-compatible")

KIND_TO_AGENT = {
    "anthropic": "claude",
    "openai": "codex",
    "google": "gemini",
    "xai": "grok",
    "openai-compatible": "opencode",
}

BUILTIN_PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "anthropic",
        "name": "Anthropic",
        "kind": "anthropic",
        "base_url": "",
        "api_key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "kind": "openai",
        "base_url": "",
        "api_key_env": "OPENAI_API_KEY",
        "models": ["gpt-5.5"],
    },
    {
        "id": "google",
        "name": "Google",
        "kind": "google",
        "base_url": "",
        "api_key_env": "GEMINI_API_KEY",
        "models": ["gemini-2.5-pro"],
    },
    {
        "id": "xai",
        "name": "xAI",
        "kind": "xai",
        "base_url": "",
        "api_key_env": "XAI_API_KEY",
        "models": [],
    },
    {
        "id": "vercel-ai-gateway",
        "name": "Vercel AI Gateway",
        "kind": "openai-compatible",
        "base_url": "https://ai-gateway.vercel.sh/v1",
        "api_key_env": "AI_GATEWAY_API_KEY",
        "models": [],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "kind": "openai-compatible",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
]


class ProviderError(ValueError):
    pass


def providers_path(runs_dir: Path) -> Path:
    return runs_dir / "providers.json"


def _decorate(provider: Dict[str, Any]) -> Dict[str, Any]:
    api_key_env = str(provider.get("api_key_env") or "")
    return {
        **provider,
        "agent": KIND_TO_AGENT.get(str(provider.get("kind")), "opencode"),
        "key_present": bool(api_key_env and os.environ.get(api_key_env)),
    }


def load_providers(runs_dir: Path) -> Dict[str, Any]:
    payload = _read_json(providers_path(runs_dir))
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), list):
        return {
            "providers": [_decorate(provider) for provider in BUILTIN_PROVIDERS],
            "persisted": False,
        }
    return {
        "providers": [
            _decorate(provider)
            for provider in payload["providers"]
            if isinstance(provider, dict)
        ],
        "persisted": True,
    }


def save_providers(runs_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    providers = payload.get("providers")
    if not isinstance(providers, list):
        raise ProviderError("`providers` must be a list.")
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for provider in providers:
        if not isinstance(provider, dict):
            raise ProviderError("Each provider must be an object.")
        provider_id = str(provider.get("id") or "")
        if not SAFE_ID.match(provider_id):
            raise ProviderError(f"Provider id is invalid: {provider_id!r}")
        if provider_id in seen:
            raise ProviderError(f"Duplicate provider id: {provider_id}")
        seen.add(provider_id)
        kind = str(provider.get("kind") or "")
        if kind not in PROVIDER_KINDS:
            raise ProviderError(
                f"Provider {provider_id} kind must be one of {', '.join(PROVIDER_KINDS)}."
            )
        models = provider.get("models")
        if not isinstance(models, list) or not all(isinstance(model, str) for model in models):
            raise ProviderError(f"Provider {provider_id} models must be a list of strings.")
        cleaned.append(
            {
                "id": provider_id,
                "name": str(provider.get("name") or provider_id),
                "kind": kind,
                "base_url": str(provider.get("base_url") or "").strip(),
                "api_key_env": str(provider.get("api_key_env") or "").strip(),
                "models": [model.strip() for model in models if model.strip()],
            }
        )

    runs_dir.mkdir(parents=True, exist_ok=True)
    providers_path(runs_dir).write_text(
        json.dumps({"providers": cleaned}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"providers": [_decorate(provider) for provider in cleaned], "persisted": True}


VERCEL_CATALOG_URL = "https://ai-gateway.vercel.sh/v1/models"


def fetch_vercel_catalog() -> Dict[str, Any]:
    """Proxy the Vercel AI Gateway model catalog (no auth required upstream).

    Served from the backend so the browser needs no cross-origin access.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(VERCEL_CATALOG_URL, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        raise ProviderError(f"Could not reach the Vercel AI Gateway catalog: {error}")
    rows = payload.get("data") if isinstance(payload, dict) else None
    models = sorted(
        {
            str(row.get("id"))
            for row in rows or []
            if isinstance(row, dict) and row.get("id")
        }
    )
    if not models:
        raise ProviderError("The Vercel AI Gateway catalog returned no models.")
    return {"models": models, "count": len(models), "source": VERCEL_CATALOG_URL}


def contender_settings(provider: Dict[str, Any], model: str) -> Dict[str, Any]:
    """Translate a provider + model choice into launch settings.

    Returns agent, gateway flags (for opencode), and environment overrides
    (for Anthropic-compatible gateways, where the CLI reads ANTHROPIC_BASE_URL).
    Values for secrets are expressed as env-var *names*; the launcher resolves
    them from its own environment at spawn time.
    """
    kind = str(provider.get("kind") or "")
    agent = KIND_TO_AGENT.get(kind, "opencode")
    base_url = str(provider.get("base_url") or "").strip()
    api_key_env = str(provider.get("api_key_env") or "").strip()
    settings: Dict[str, Any] = {"agent": agent, "gateway": {}, "env": {}}
    if kind == "openai-compatible":
        settings["gateway"] = {
            "opencode_provider": str(provider.get("id") or ""),
            "opencode_base_url": base_url,
            "opencode_api_key_env": api_key_env or "OPENAI_API_KEY",
        }
    elif kind == "anthropic" and base_url:
        settings["env"] = {
            "ANTHROPIC_BASE_URL": {"value": base_url},
            "ANTHROPIC_AUTH_TOKEN": {"from_env": api_key_env or "ANTHROPIC_AUTH_TOKEN"},
        }
    _ = model
    return settings
