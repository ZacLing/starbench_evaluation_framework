"""Runtime adapter registry — the one lookup from an agent id to an adapter.

``resolve(agent_id, ...)`` returns the adapter the runner drives: one of the
five built-in singletons, or a :class:`SpecAdapter` for ``custom:<id>`` (loaded
from ``runtimes/<id>.json`` unless an already-parsed spec is supplied).

``DEFAULT_DOCKER_IMAGES`` is *derived* here from the built-in adapters'
``RuntimeInfo`` — there is no longer a hand-maintained image table to keep in
sync. It is re-exported through ``runner.codex_process`` for existing importers.

To add a built-in runtime: write ``adapters/<id>.py`` and add its adapter to
``_BUILTIN_ORDER`` below (one line).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from ..runner.custom_runtime import CustomRuntimeSpec, load_custom_runtime
from .base import RuntimeAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .gemini import GeminiAdapter
from .grok import GrokAdapter
from .opencode import OpenCodeAdapter
from .spec import SpecAdapter

# Insertion order matters for DEFAULT_DOCKER_IMAGES (kept byte-identical to the
# historical literal): codex, claude, gemini, grok, opencode.
_BUILTIN_ORDER: List[RuntimeAdapter] = [
    CodexAdapter(),
    ClaudeAdapter(),
    GeminiAdapter(),
    GrokAdapter(),
    OpenCodeAdapter(),
]

_BUILTIN: Dict[str, RuntimeAdapter] = {adapter.info.id: adapter for adapter in _BUILTIN_ORDER}

BUILTIN_AGENTS = set(_BUILTIN)

# Derived, not hand-maintained: one image per built-in runtime.
DEFAULT_DOCKER_IMAGES: Dict[str, str] = {
    adapter.info.id: adapter.info.docker_image for adapter in _BUILTIN_ORDER
}


def list_builtin() -> List[RuntimeAdapter]:
    return list(_BUILTIN_ORDER)


def get_builtin(agent_id: str) -> RuntimeAdapter:
    try:
        return _BUILTIN[agent_id]
    except KeyError:
        raise ValueError(f"Unknown built-in runtime: {agent_id!r}")


def resolve(
    agent_id: str,
    runtimes_dir: Path | None = None,
    *,
    spec: CustomRuntimeSpec | None = None,
) -> RuntimeAdapter:
    """Return the adapter for ``agent_id`` (built-in or ``custom:<id>``)."""
    if agent_id in _BUILTIN:
        return _BUILTIN[agent_id]
    if agent_id.startswith("custom:"):
        if spec is None:
            if runtimes_dir is None:
                raise ValueError(f"resolve({agent_id!r}) needs a runtimes_dir or a spec")
            spec = load_custom_runtime(runtimes_dir, agent_id.split(":", 1)[1])
        return SpecAdapter(spec)
    raise ValueError(
        f"Unknown runtime {agent_id!r}: expected one of {sorted(BUILTIN_AGENTS)} or custom:<id>"
    )
