"""Shared primitives for short-lived CLI probes (`--version`, login status).

Three call sites used to carry their own copies of this logic (GUI agents,
GUI providers, runner provenance) and they drifted: one of them merely
*defaulted* TERM/NO_COLOR, so a server launched from a real terminal let the
probed CLI emit ANSI escapes and broke string matching. This module is the
single implementation; env sanitisation here is forced, never defaulted.

Layering: execution/ is the runtime-agnostic bottom layer, importable from
both the GUI and the runner (the runner must never import GUI modules).
"""

from __future__ import annotations

import os
import re
import subprocess
from typing import Dict, Optional, Sequence


def run_probe(
    command: Sequence[str],
    *,
    timeout: float,
    env: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Run a probe command with deterministic, colorless terminal output.

    Starts from ``env`` (default: a copy of ``os.environ`` so npm and
    user-installed CLIs find their usual config) and **forces** NO_COLOR=1 and
    TERM=dumb — assignment, not setdefault, because the inherited environment
    of a server started from a real terminal already carries a TERM.
    """
    merged = dict(env) if env is not None else os.environ.copy()
    merged["NO_COLOR"] = "1"
    merged["TERM"] = "dumb"
    return subprocess.run(
        list(command),
        env=merged,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )


def tail(text: str, limit: int = 2000) -> str:
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


def extract_version(output: str) -> Optional[str]:
    """Pull a version number out of probe output.

    Prefers a full three-part semver (with optional pre-release/build
    suffix); falls back to a bare two-part ``major.minor``.
    """
    match = re.search(r"(?<![A-Za-z0-9])v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)", output)
    if match:
        return match.group(1)
    match = re.search(r"(?<![A-Za-z0-9])v?(\d+\.\d+)(?![A-Za-z0-9])", output)
    return match.group(1) if match else None


__all__ = ["extract_version", "run_probe", "tail"]
