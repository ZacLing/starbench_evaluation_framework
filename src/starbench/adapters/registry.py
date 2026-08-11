"""Runtime adapter registry — the one lookup from an agent id to an adapter.

``resolve(agent_id, ...)`` returns the adapter the runner drives: one of the
built-in singletons, or a :class:`SpecAdapter` for ``custom:<id>`` (loaded
from ``runtimes/<id>.json`` unless an already-parsed spec is supplied).

``DEFAULT_DOCKER_IMAGES`` is *derived* here from the built-in adapters'
``RuntimeInfo`` — there is no longer a hand-maintained image table to keep in
sync. It is re-exported through ``runner.codex_process`` for existing importers.
A host-local-only runtime (``docker_image=None``) maps to ``None`` rather than
being dropped, so the table stays a complete roster; callers that need a string
read it as ``.get(id) or ""``.

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
from .pi import PiAdapter
from .spec import SpecAdapter

# Insertion order matters for DEFAULT_DOCKER_IMAGES: the historical five keep
# their literal order (codex, claude, gemini, grok, opencode); later runtimes
# are appended at the tail so the existing prefix never shifts.
_BUILTIN_ORDER: List[RuntimeAdapter] = [
    CodexAdapter(),
    ClaudeAdapter(),
    GeminiAdapter(),
    GrokAdapter(),
    OpenCodeAdapter(),
    PiAdapter(),
]

_BUILTIN: Dict[str, RuntimeAdapter] = {adapter.info.id: adapter for adapter in _BUILTIN_ORDER}

BUILTIN_AGENTS = set(_BUILTIN)

# Derived, not hand-maintained: one image per built-in runtime (None when the
# runtime is host-local only).
DEFAULT_DOCKER_IMAGES: Dict[str, str | None] = {
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
