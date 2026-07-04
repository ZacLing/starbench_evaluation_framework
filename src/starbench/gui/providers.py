"""AI providers: the resource side of the console.

A provider owns an endpoint, a credential, and a model catalog:
`{id, name, kind, base_url, auth, api_key_env, models, models_fetched_at,
models_source}` stored in `<runs-dir>/providers.json`. The console never
stores API keys, only the name of the environment variable that holds one;
`key_present` is computed at read time.

The model catalog is a derived fact, not a hand-maintained asset: it is
refreshed from the provider's own models API (`GET /v1/models` and friends).
Providers authenticated via a local CLI login, or whose key is absent, fall
back to the public Vercel AI Gateway catalog filtered by vendor, and the
snapshot is labeled accordingly.

Provider kinds map to agent runtimes: anthropic -> claude, openai -> codex,
google -> gemini, xai -> grok, openai-compatible -> opencode.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data import SAFE_ID, _read_json

PROVIDER_KINDS = ("anthropic", "openai", "google", "xai", "openai-compatible")
PROVIDER_AUTHS = ("api_key", "cli_login")

KIND_TO_AGENT = {
    "anthropic": "claude",
    "openai": "codex",
    "google": "gemini",
    "xai": "grok",
    "openai-compatible": "opencode",
}

DEFAULT_BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
}

# Vendor prefix used when falling back to the public gateway catalog.
KIND_TO_CATALOG_CREATOR = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "xai": "xai",
}

BUILTIN_PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "anthropic",
        "name": "Anthropic",
        "kind": "anthropic",
        "auth": "api_key",
        "base_url": "",
        "api_key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    },
    {
        "id": "anthropic-cli",
        "name": "Anthropic (CLI login)",
        "kind": "anthropic",
        "auth": "cli_login",
        "base_url": "",
        "api_key_env": "",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "kind": "openai",
        "auth": "api_key",
        "base_url": "",
        "api_key_env": "OPENAI_API_KEY",
        "models": ["gpt-5.5"],
    },
    {
        "id": "openai-cli",
        "name": "OpenAI (CLI login)",
        "kind": "openai",
        "auth": "cli_login",
        "base_url": "",
        "api_key_env": "",
        "models": ["gpt-5.5"],
    },
    {
        "id": "google",
        "name": "Google",
        "kind": "google",
        "auth": "api_key",
        "base_url": "",
        "api_key_env": "GEMINI_API_KEY",
        "models": ["gemini-2.5-pro"],
    },
    {
        "id": "xai",
        "name": "xAI",
        "kind": "xai",
        "auth": "api_key",
        "base_url": "",
        "api_key_env": "XAI_API_KEY",
        "models": [],
    },
    {
        "id": "vercel-ai-gateway",
        "name": "Vercel AI Gateway",
        "kind": "openai-compatible",
        "auth": "api_key",
        "base_url": "https://ai-gateway.vercel.sh/v1",
        "anthropic_base_url": "https://ai-gateway.vercel.sh",
        "api_key_env": "AI_GATEWAY_API_KEY",
        "models": [],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "kind": "openai-compatible",
        "auth": "api_key",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "models": [],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "kind": "openai-compatible",
        "auth": "api_key",
        "base_url": "https://api.deepseek.com/v1",
        "anthropic_base_url": "https://api.deepseek.com/anthropic",
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
        "auth": "api_key",
        "anthropic_base_url": "",
        "models_fetched_at": None,
        "models_source": None,
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
        auth = str(provider.get("auth") or "api_key")
        if auth not in PROVIDER_AUTHS:
            raise ProviderError(
                f"Provider {provider_id} auth must be one of {', '.join(PROVIDER_AUTHS)}."
            )
        if auth == "cli_login" and kind == "openai-compatible":
            raise ProviderError(
                f"Provider {provider_id}: OpenAI-compatible gateways need an API key."
            )
        models = provider.get("models")
        if not isinstance(models, list) or not all(isinstance(model, str) for model in models):
            raise ProviderError(f"Provider {provider_id} models must be a list of strings.")
        cleaned.append(
            {
                "id": provider_id,
                "name": str(provider.get("name") or provider_id),
                "kind": kind,
                "auth": auth,
                "base_url": str(provider.get("base_url") or "").strip(),
                "anthropic_base_url": str(provider.get("anthropic_base_url") or "").strip(),
                "api_key_env": str(provider.get("api_key_env") or "").strip(),
                "models": [model.strip() for model in models if model.strip()],
                "models_fetched_at": provider.get("models_fetched_at"),
                "models_source": provider.get("models_source"),
            }
        )

    runs_dir.mkdir(parents=True, exist_ok=True)
    providers_path(runs_dir).write_text(
        json.dumps({"providers": cleaned}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"providers": [_decorate(provider) for provider in cleaned], "persisted": True}


# ---------------------------------------------------------------------------
# Model catalog refresh
# ---------------------------------------------------------------------------

VERCEL_CATALOG_URL = "https://ai-gateway.vercel.sh/v1/models"


def _fetch_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        raise ProviderError(f"Request to {url} failed: {error}")


def fetch_vercel_catalog() -> List[str]:
    payload = _fetch_json(VERCEL_CATALOG_URL)
    rows = payload.get("data") if isinstance(payload, dict) else None
    models = sorted(
        {str(row.get("id")) for row in rows or [] if isinstance(row, dict) and row.get("id")}
    )
    if not models:
        raise ProviderError("The public model catalog returned no models.")
    return models


def _models_from_api(provider: Dict[str, Any], api_key: str) -> List[str]:
    kind = str(provider.get("kind") or "")
    base_url = str(provider.get("base_url") or "").strip() or DEFAULT_BASE_URLS.get(kind, "")
    if kind == "google":
        payload = _fetch_json(
            "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
            f"&key={api_key}"
        )
        names = [
            str(row.get("name") or "")
            for row in (payload.get("models") or [])
            if isinstance(row, dict)
        ]
        return sorted(
            {name.split("/", 1)[1] if "/" in name else name for name in names if name}
        )
    if kind == "anthropic":
        payload = _fetch_json(
            f"{base_url.rstrip('/')}/v1/models?limit=200",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
    else:  # openai, xai, openai-compatible: OpenAI wire format
        payload = _fetch_json(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    rows = payload.get("data") if isinstance(payload, dict) else None
    models = sorted(
        {str(row.get("id")) for row in rows or [] if isinstance(row, dict) and row.get("id")}
    )
    if not models:
        raise ProviderError("The provider's models API returned no models.")
    return models


def _models_from_catalog(provider: Dict[str, Any]) -> List[str]:
    creator = KIND_TO_CATALOG_CREATOR.get(str(provider.get("kind") or ""))
    catalog = fetch_vercel_catalog()
    if creator is None:
        return catalog
    models = [
        model.split("/", 1)[1]
        for model in catalog
        if model.startswith(f"{creator}/")
    ]
    if not models:
        raise ProviderError(f"No catalog models found for vendor {creator}.")
    return models


def refresh_provider_models(runs_dir: Path, provider_id: str) -> Dict[str, Any]:
    """Refresh one provider's model catalog and persist the snapshot.

    Uses the provider's own models API when an API key is available; falls
    back to the public vendor catalog for CLI-login providers or missing keys.
    """
    current = load_providers(runs_dir)
    providers = [dict(provider) for provider in current["providers"]]
    target = next((p for p in providers if p.get("id") == provider_id), None)
    if target is None:
        raise ProviderError(f"No provider named {provider_id}.")

    api_key = os.environ.get(str(target.get("api_key_env") or ""), "")
    use_api = target.get("auth") != "cli_login" and bool(api_key)
    errors: List[str] = []
    models: Optional[List[str]] = None
    source = None
    if use_api:
        try:
            models = _models_from_api(target, api_key)
            source = "api"
        except ProviderError as error:
            errors.append(str(error))
    if models is None:
        try:
            models = _models_from_catalog(target)
            source = "catalog"
        except ProviderError as error:
            errors.append(str(error))
    if models is None:
        raise ProviderError(" / ".join(errors) or "Could not refresh models.")

    target["models"] = models
    target["models_fetched_at"] = datetime.now(timezone.utc).isoformat()
    target["models_source"] = source
    stripped = [
        {key: value for key, value in provider.items() if key not in ("agent", "key_present")}
        for provider in providers
    ]
    return save_providers(runs_dir, {"providers": stripped})
