"""AI providers: the resource side of the console.

A provider owns an endpoint, a credential, and a model catalog:
`{id, name, kind, base_url, auth, api_key_env, models, models_fetched_at,
models_source}` stored in `<runs-dir>/providers.json`. The console never
stores API keys, only the name of the environment variable that holds one;
`key_present` is computed at read time.

The model catalog is a derived fact, not a hand-maintained asset: it is
refreshed from the provider's own models API (`GET /v1/models` and friends).
Providers authenticated via a local CLI login use that CLI's local model cache
when it is available. Missing keys fall back to the public Vercel AI Gateway
catalog filtered by vendor, and the snapshot is labeled accordingly.

Provider kinds describe model/API protocol. Agent runtimes decide whether they
can consume a provider through their provider filters and injection channels.
Only `cli_login` providers are runtime-specific: a local CLI login belongs to
that CLI, not to every runtime that happens to speak the same wire protocol.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..execution.probe import run_probe
from . import contracts
from .data import SAFE_ID, _read_json

PROVIDER_KINDS = ("anthropic", "openai", "google", "xai", "openai-compatible")
PROVIDER_AUTHS = ("api_key", "cli_login")

KIND_TO_CLI_AGENT = {
    "anthropic": "claude",
    "openai": "codex",
    "google": "gemini",
    "xai": "grok",
    "openai-compatible": "opencode",
}

AGENT_LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "grok": "Grok Build",
    "opencode": "OpenCode",
}

AGENT_BINS = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "grok": "grok",
    "opencode": "opencode",
}

CLI_STATUS_COMMANDS = {
    "claude": ("claude", "auth", "status"),
    "codex": ("codex", "login", "status"),
}
CLI_STATUS_CACHE_SECONDS = 60.0
# `codex login status` is fast in the sandboxed shell but can take about five
# seconds from the unsandboxed GUI service process. Keep this off the Providers
# first paint, but allow enough time to avoid a false "unverified" badge.
CLI_STATUS_TIMEOUT_SECONDS = 6.0
_CLI_STATUS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

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

# Vendor APIs can speak OpenAI wire format without being aggregator gateways.
# When they fall back to a public catalog, filter the gateway catalog to the
# vendor's namespace instead of showing the entire multi-vendor gateway list.
OPENAI_COMPAT_CATALOG_CREATORS = {
    "deepseek": ("deepseek",),
    "doubao": ("bytedance", "doubao"),
    "kimi": ("moonshot", "moonshotai", "kimi"),
    "moonshot": ("moonshot", "moonshotai"),
    "qwen": ("alibaba", "qwen"),
    "zhipu": ("zai", "zhipu"),
    "glm": ("zai", "zhipu"),
    "minimax": ("minimax",),
    "mistral": ("mistral",),
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
        "anthropic_base_url": "https://openrouter.ai/api",
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


# The server is a ThreadingHTTPServer: two requests can hit providers.json at
# once. This lock serializes writers and read-modify-write sequences
# (refresh_provider_models holds it across load -> mutate -> save, hence
# re-entrant so save_providers can acquire it again on the same thread).
_PROVIDERS_LOCK = threading.RLock()


PROVIDER_DEFAULTS: Dict[str, Dict[str, str]] = {
    # OpenRouter exposes both OpenAI-compatible and Anthropic-compatible
    # surfaces. The Anthropic Agent SDK / Claude Code path uses /api, while
    # OpenAI-compatible clients use /api/v1.
    "openrouter": {"anthropic_base_url": "https://openrouter.ai/api"},
}


def providers_path(runs_dir: Path) -> Path:
    return runs_dir / "providers.json"


def _with_provider_defaults(provider: Dict[str, Any]) -> Dict[str, Any]:
    defaults = PROVIDER_DEFAULTS.get(str(provider.get("id") or ""))
    if not defaults:
        return provider
    merged = dict(provider)
    for key, value in defaults.items():
        if not str(merged.get(key) or "").strip():
            merged[key] = value
    return merged


def _catalog_creators(provider: Dict[str, Any]) -> Optional[Tuple[str, ...]]:
    kind = str(provider.get("kind") or "")
    creator = KIND_TO_CATALOG_CREATOR.get(kind)
    if creator:
        return (creator,)
    if kind != "openai-compatible":
        return None
    identity = f"{provider.get('id') or ''} {provider.get('name') or ''}".lower()
    creators: List[str] = []
    for hint, aliases in OPENAI_COMPAT_CATALOG_CREATORS.items():
        if hint in identity:
            creators.extend(aliases)
    if not creators:
        return None
    return tuple(dict.fromkeys(creators))


def _catalog_models_for_creators(models: Sequence[str], creators: Sequence[str]) -> List[str]:
    prefixes = tuple(f"{creator}/" for creator in creators)
    return sorted({model for model in models if model.startswith(prefixes)})


def _normalize_catalog_models(provider: Dict[str, Any]) -> List[str]:
    models = [str(model) for model in provider.get("models") or [] if str(model).strip()]
    if provider.get("models_source") != "catalog":
        return models
    creators = _catalog_creators(provider)
    if not creators:
        return models
    filtered = _catalog_models_for_creators(models, creators)
    return filtered or models


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def _codex_model_reasoning(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One model's published reasoning-effort table, when the cache row has one."""
    levels = [
        str(entry.get("effort") or "").strip()
        for entry in row.get("supported_reasoning_levels") or []
        if isinstance(entry, dict)
    ]
    levels = [level for level in levels if level]
    if not levels:
        return None
    default_level = str(row.get("default_reasoning_level") or "").strip() or None
    return {"levels": levels, "default_level": default_level}


def _codex_models_from_cache() -> Tuple[List[str], Optional[str], Dict[str, Any]]:
    path = _codex_home() / "models_cache.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None, {}
    rows = payload.get("models") if isinstance(payload, dict) else None
    models: List[str] = []
    reasoning: Dict[str, Any] = {}
    for row in rows or []:
        if isinstance(row, str):
            model = row.strip()
        elif isinstance(row, dict):
            model = str(row.get("slug") or row.get("id") or row.get("model") or "").strip()
        else:
            model = ""
        if not model:
            continue
        models.append(model)
        if isinstance(row, dict):
            table = _codex_model_reasoning(row)
            if table:
                reasoning[model] = table
    fetched_at = str(payload.get("fetched_at") or "") or None
    return list(dict.fromkeys(models)), fetched_at, reasoning


def _cli_model_snapshot(
    provider: Dict[str, Any],
) -> Optional[Tuple[List[str], Optional[str], Dict[str, Any]]]:
    if provider.get("auth") != "cli_login":
        return None
    agent = KIND_TO_CLI_AGENT.get(str(provider.get("kind") or ""))
    if agent == "codex":
        models, fetched_at, reasoning = _codex_models_from_cache()
        if models:
            return models, fetched_at, reasoning
    return None


def _cli_login_status(agent: str) -> Dict[str, Any]:
    cached = _CLI_STATUS_CACHE.get(agent)
    now = time.monotonic()
    if cached and now - cached[0] < CLI_STATUS_CACHE_SECONDS:
        return dict(cached[1])
    label = AGENT_LABELS.get(agent, agent)
    command = CLI_STATUS_COMMANDS.get(agent)
    bin_name = (command or (AGENT_BINS.get(agent, agent),))[0]
    path = shutil.which(bin_name)
    if not path:
        status = {
            "agent": agent,
            "label": label,
            "cli_present": False,
            "cli_path": None,
            "status": "fail",
            "message": f"{label} CLI not found on PATH.",
        }
        _CLI_STATUS_CACHE[agent] = (now, status)
        return dict(status)
    if not command:
        status = {
            "agent": agent,
            "label": label,
            "cli_present": True,
            "cli_path": path,
            "status": "unknown",
            "message": f"{label} login status cannot be checked by this console.",
        }
        _CLI_STATUS_CACHE[agent] = (now, status)
        return dict(status)
    # CODEX_CI is provider-specific (keeps `codex login status` non-interactive);
    # run_probe itself forces NO_COLOR/TERM so status text stays parseable even
    # when the server inherited a real terminal's TERM.
    env = os.environ.copy()
    env["CODEX_CI"] = "1"
    try:
        result = run_probe(list(command), timeout=CLI_STATUS_TIMEOUT_SECONDS, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        status = {
            "agent": agent,
            "label": label,
            "cli_present": True,
            "cli_path": path,
            "status": "warn",
            "message": f"Could not check {label} login: {error}.",
        }
        _CLI_STATUS_CACHE[agent] = (now, status)
        return dict(status)
    output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    if result.returncode == 0:
        status_kind, message = _interpret_cli_status(agent, output)
        status = {
            "agent": agent,
            "label": label,
            "cli_present": True,
            "cli_path": path,
            "status": status_kind,
            "message": message,
        }
        _CLI_STATUS_CACHE[agent] = (now, status)
        return dict(status)
    status = {
        "agent": agent,
        "label": label,
        "cli_present": True,
        "cli_path": path,
        "status": "warn",
        "message": _first_status_line(output) or f"{label} login status is not confirmed.",
    }
    _CLI_STATUS_CACHE[agent] = (now, status)
    return dict(status)


def _first_status_line(output: str) -> str:
    for line in output.splitlines():
        line = line.strip()
        if line:
            return line[:160]
    return ""


def _summarize_cli_status(agent: str, output: str) -> str:
    return _interpret_cli_status(agent, output)[1]


def _interpret_cli_status(agent: str, output: str) -> Tuple[str, str]:
    if agent == "claude":
        try:
            payload = json.loads(output)
        except ValueError:
            return "ok", _first_status_line(output) or "Claude Code reports a logged-in session."
        if payload.get("loggedIn") is True:
            source = payload.get("apiKeySource")
            method = payload.get("authMethod")
            if method == "api_key" or source:
                origin = source or method or "API key"
                return "api_key", f"Claude Code is using {origin}, not a local CLI login."
            if source:
                return "ok", f"Logged in via {source}."
            if method:
                return "ok", f"Logged in via {method}."
            return "ok", "Claude Code reports a logged-in session."
        return "warn", "Claude Code reports no active login."
    if agent == "codex":
        for line in output.splitlines():
            line = line.strip()
            if line.lower().startswith("logged in"):
                return "ok", line[:160]
        return "ok", _first_status_line(output) or "Codex reports a logged-in session."
    return "ok", _first_status_line(output) or "CLI reports a logged-in session."


def _decorate(provider: Dict[str, Any], *, include_cli_status: bool = False) -> Dict[str, Any]:
    provider = _with_provider_defaults(provider)
    api_key_env = str(provider.get("api_key_env") or "")
    agent = KIND_TO_CLI_AGENT.get(str(provider.get("kind")), "opencode")
    models = _normalize_catalog_models(provider)
    models_fetched_at = provider.get("models_fetched_at")
    models_source = provider.get("models_source")
    model_reasoning: Dict[str, Any] = {}
    cli_snapshot = _cli_model_snapshot(provider)
    if cli_snapshot:
        models, models_fetched_at, model_reasoning = cli_snapshot
        models_source = "cli_cache"
    decorated = {
        "auth": "api_key",
        "anthropic_base_url": "",
        "gemini_base_url": "",
        "models_fetched_at": None,
        "models_source": None,
        **provider,
        "models": models,
        "models_fetched_at": models_fetched_at,
        "models_source": models_source,
        "agent": agent,
        "key_present": bool(api_key_env and os.environ.get(api_key_env)),
    }
    if model_reasoning:
        decorated["model_reasoning"] = model_reasoning
    if include_cli_status and decorated["auth"] == "cli_login":
        decorated["cli_status"] = _cli_login_status(agent)
    return decorated


def load_providers(
    runs_dir: Path, *, include_cli_status: bool = False
) -> "contracts.ProvidersPayload":
    # Response shape defined once in contracts.ProvidersPayload (see gen-types).
    payload = _read_json(providers_path(runs_dir))
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), list):
        return {
            "providers": [
                _decorate(provider, include_cli_status=include_cli_status)
                for provider in BUILTIN_PROVIDERS
            ],
            "persisted": False,
        }
    return {
        "providers": [
            _decorate(provider, include_cli_status=include_cli_status)
            for provider in payload["providers"]
            if isinstance(provider, dict)
        ],
        "persisted": True,
    }


def load_provider_cli_statuses(runs_dir: Path) -> "contracts.ProviderCliStatusPayload":
    payload = load_providers(runs_dir)
    statuses = {}
    for provider in payload["providers"]:
        if provider.get("auth") != "cli_login":
            continue
        provider_id = str(provider.get("id") or "")
        agent = str(provider.get("agent") or "")
        if provider_id and agent:
            statuses[provider_id] = _cli_login_status(agent)
    return {"statuses": statuses}


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
                "gemini_base_url": str(provider.get("gemini_base_url") or "").strip(),
                "api_key_env": str(provider.get("api_key_env") or "").strip(),
                "models": [model.strip() for model in models if model.strip()],
                "models_fetched_at": provider.get("models_fetched_at"),
                "models_source": provider.get("models_source"),
            }
        )

    runs_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"providers": cleaned}, indent=2, sort_keys=True) + "\n"
    target = providers_path(runs_dir)
    with _PROVIDERS_LOCK:
        # Write-to-temp + os.replace: a crash mid-write can never leave a
        # truncated providers.json behind, and concurrent readers see either
        # the old file or the new one, never a partial.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(runs_dir), prefix=".providers-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(body)
            os.replace(tmp_name, target)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
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
    creators = _catalog_creators(provider)
    catalog = fetch_vercel_catalog()
    if creators is None:
        return catalog
    models = _catalog_models_for_creators(catalog, creators)
    if not models:
        raise ProviderError(f"No catalog models found for vendor {', '.join(creators)}.")
    if str(provider.get("kind") or "") != "openai-compatible":
        models = [model.split("/", 1)[1] for model in models]
    return models


def refresh_provider_models(runs_dir: Path, provider_id: str) -> Dict[str, Any]:
    """Refresh one provider's model catalog and persist the snapshot.

    Uses the provider's own models API when an API key is available; falls
    back to the public vendor catalog for CLI-login providers or missing keys.
    """
    # Hold the providers lock across the whole load -> mutate -> save
    # sequence so a concurrent save cannot be silently overwritten by this
    # read-modify-write (lost update).
    with _PROVIDERS_LOCK:
        return _refresh_provider_models_locked(runs_dir, provider_id)


def _refresh_provider_models_locked(runs_dir: Path, provider_id: str) -> Dict[str, Any]:
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
    fetched_at: Optional[str] = None
    if use_api:
        try:
            models = _models_from_api(target, api_key)
            source = "api"
        except ProviderError as error:
            errors.append(str(error))
    if models is None:
        cli_snapshot = _cli_model_snapshot(target)
        if cli_snapshot:
            # Reasoning tables are not persisted: _decorate re-reads the live
            # cache on every load, so the stored snapshot stays models-only.
            models, fetched_at, _reasoning = cli_snapshot
            source = "cli_cache"
    if models is None:
        try:
            models = _models_from_catalog(target)
            source = "catalog"
        except ProviderError as error:
            errors.append(str(error))
    if models is None:
        raise ProviderError(" / ".join(errors) or "Could not refresh models.")

    target["models"] = models
    target["models_fetched_at"] = fetched_at or datetime.now(timezone.utc).isoformat()
    target["models_source"] = source
    stripped = [
        {
            key: value
            for key, value in provider.items()
            if key not in ("agent", "key_present", "cli_status")
        }
        for provider in providers
    ]
    return save_providers(runs_dir, {"providers": stripped})
