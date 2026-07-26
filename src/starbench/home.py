"""STARBENCH_HOME resolution — the one place the environment decides where data lives.

Precedence is decided at each entrypoint, not here: explicit CLI flag >
$STARBENCH_HOME > ~/.starbench. This module only answers "where is home?".
Entrypoints resolve it once and pass explicit paths inward, so core code and
tests never read the environment. Isolation is an explicit act (point
STARBENCH_HOME elsewhere), never a side effect of the working directory —
which is why a relative env value is an error, not a convenience.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

ENV_VAR = "STARBENCH_HOME"


def resolve_home(environ: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_VAR) or "").strip()
    if not raw:
        return Path.home() / ".starbench"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(
            f"{ENV_VAR} must be an absolute path, got {raw!r}: data location "
            "must not depend on the working directory."
        )
    return path


@dataclass(frozen=True)
class HomeLayout:
    """Canonical directory layout inside a StarBench home."""

    root: Path

    @property
    def tasks(self) -> Path:
        return self.root / "tasks"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def runtimes(self) -> Path:
        return self.root / "runtimes"

    @property
    def skills(self) -> Path:
        return self.root / "skills"
