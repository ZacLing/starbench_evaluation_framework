"""Canonical API shapes shared by the console backend and its TypeScript client.

This module is the single definition of the core ``/api`` response/request
shapes. ``scripts/gen_api_types.py`` renders it into
``gui-frontend/src/lib/api-types.ts`` (committed, "GENERATED — do not edit"),
and ``lib/api.ts`` re-exports those generated types — so the front and back
ends cannot drift on a field name or nullability.

Scope: the shapes P2 touches (agents + experiment planning + their providers).
Other routes still type themselves by hand in ``api.ts``; migrate them here when
you next touch them.

Invariants:
- Import-safe on Python 3.9 (no ``typing.NotRequired``): optional fields use the
  base + ``total=False`` inheritance pattern so ``__optional_keys__`` is right.
- Mirror the wire JSON exactly — a value that is ``string | null`` on the wire is
  ``Optional[str]`` here; an absent-or-value field is an optional key.

改什么来这里: add or change a core API field, then run ``make gen-types``.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# Enumerations (rendered as TS string-literal unions)
# ---------------------------------------------------------------------------

ProviderKind = Literal["anthropic", "openai", "google", "xai", "openai-compatible"]
RuntimeProtocol = Literal["openai", "anthropic", "gemini", "xai", "none"]
AuthKind = Literal["api_key", "cli_login"]
ModelsSource = Literal["api", "catalog"]


# ---------------------------------------------------------------------------
# Runtimes (/api/agents)
# ---------------------------------------------------------------------------

class RuntimeCli(TypedDict):
    bin: str
    present: bool
    path: Optional[str]


class ProviderFilter(TypedDict):
    """Wire-protocol compatibility matrix a runtime uses to filter providers."""

    kinds: List[str]
    accepts_anthropic_endpoint: bool
    accepts_gemini_endpoint: bool


class BuiltinRuntime(TypedDict):
    id: str
    label: str
    note: str
    protocol: RuntimeProtocol
    docker_capable: bool
    docker_image: str
    builtin: Literal[True]
    cli: RuntimeCli
    provider_filter: ProviderFilter


class _CustomRuntimeBase(TypedDict):
    id: str
    spec_id: str
    builtin: Literal[False]
    source_path: str
    error: Optional[str]


class CustomRuntime(_CustomRuntimeBase, total=False):
    label: str
    description: str
    icon: str
    protocol: RuntimeProtocol
    provider_filter: ProviderFilter
    base_url_env: str
    api_key_env: str
    command: str
    args: List[str]
    judge_args: List[str]
    judge_args_inherited: bool
    model_flag: Optional[str]
    prompt_via: str
    prompt_flag: str
    parser: str
    env: Dict[str, str]
    docker_image: Optional[str]
    docker_env_passthrough: List[str]
    docker_capable: bool
    cli: RuntimeCli


class AgentsPayload(TypedDict):
    runtimes_dir: str
    builtin: List[BuiltinRuntime]
    custom: List[CustomRuntime]


# ---------------------------------------------------------------------------
# AI providers (/api/providers)
# ---------------------------------------------------------------------------

class _AiProviderBase(TypedDict):
    id: str
    name: str
    kind: ProviderKind
    auth: AuthKind
    base_url: str
    api_key_env: str
    models: List[str]
    models_fetched_at: Optional[str]
    models_source: Optional[ModelsSource]
    agent: str
    key_present: bool


class AiProvider(_AiProviderBase, total=False):
    anthropic_base_url: Optional[str]
    gemini_base_url: Optional[str]


class _ProvidersPayloadBase(TypedDict):
    providers: List[AiProvider]


class ProvidersPayload(_ProvidersPayloadBase, total=False):
    persisted: bool


# ---------------------------------------------------------------------------
# Experiments (/api/experiments)
# ---------------------------------------------------------------------------

class _ExperimentPlanItemBase(TypedDict):
    label: str
    agent: str
    model: str
    run_id: str
    backend: str
    backend_downgraded: bool
    argv: List[str]


class ExperimentPlanItem(_ExperimentPlanItemBase, total=False):
    docker_image: str


class _ContenderBase(TypedDict):
    """A contender in the reference shape: a runtime pointing at a provider.

    The backend resolves ``provider_id`` against the AI providers and computes
    the concrete auth/gateway/env at plan time (see ``gui.injection``).
    """

    agent: str
    provider_id: str
    model: str


class Contender(_ContenderBase, total=False):
    label: str
    thinking_effort: str


# Ordered list the code generator renders (aliases first, then interfaces in
# dependency order). Names not listed here are internal helpers.
GENERATED_TYPES = [
    "ProviderKind",
    "RuntimeProtocol",
    "AuthKind",
    "ModelsSource",
    "RuntimeCli",
    "ProviderFilter",
    "BuiltinRuntime",
    "CustomRuntime",
    "AgentsPayload",
    "AiProvider",
    "ProvidersPayload",
    "ExperimentPlanItem",
    "Contender",
]
