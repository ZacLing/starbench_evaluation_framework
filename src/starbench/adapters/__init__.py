"""Runtime adapters: the single source of truth for "what is a runtime".

Each adapter owns everything runtime-specific about running a task — command
construction, env preparation, docker wrapping, and output parsing — plus a
``RuntimeInfo`` metadata record. The orchestrator resolves an adapter from the
registry and drives it, holding no per-runtime branches of its own.

Layout:
- ``base.py``     RuntimeInfo + RuntimeAdapter interface + Executor/JudgeContext
- ``registry.py`` get_builtin / list_builtin / resolve (built-in 7 + custom)
- ``codex/claude/gemini/grok/opencode/pi/dsh.py``  the seven built-in adapters
- ``spec.py``     the data-driven adapter for ``runtimes/<id>.json`` customs

Dependency arrow points down: adapters import ``starbench.execution`` and
``starbench.runner.prompts``; they must not import ``starbench.runner.run_benchmark``.
"""

from .base import (
    ExecutorContext,
    InjectionChannel,
    JudgeContext,
    ProviderFilter,
    RuntimeAdapter,
    RuntimeInfo,
    finalize_success,
    provider_filter_for_protocol,
    resolve_runtime_options,
)
from .registry import (
    BUILTIN_AGENTS,
    DEFAULT_DOCKER_IMAGES,
    get_builtin,
    list_builtin,
    resolve,
)

__all__ = [
    "BUILTIN_AGENTS",
    "DEFAULT_DOCKER_IMAGES",
    "ExecutorContext",
    "InjectionChannel",
    "JudgeContext",
    "ProviderFilter",
    "RuntimeAdapter",
    "RuntimeInfo",
    "finalize_success",
    "get_builtin",
    "list_builtin",
    "provider_filter_for_protocol",
    "resolve",
    "resolve_runtime_options",
]
