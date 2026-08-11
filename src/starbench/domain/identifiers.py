"""Identifiers that are safe to use as one filesystem path component."""

from __future__ import annotations

import hashlib
import re
from typing import Any


MAX_SAFE_ID_LENGTH = 128
SAFE_ID_PATTERN = re.compile(
    rf"^[A-Za-z0-9][A-Za-z0-9._-]{{0,{MAX_SAFE_ID_LENGTH - 1}}}$"
)
_UNBOUNDED_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def parse_safe_id(value: Any, *, kind: str = "identifier") -> str:
    """Return *value* as a validated, filesystem-safe identifier."""

    if not isinstance(value, str) or not SAFE_ID_PATTERN.fullmatch(value):
        raise ValueError(
            f"Invalid {kind}: {value!r}. Expected 1-{MAX_SAFE_ID_LENGTH} characters "
            "using letters, digits, dot, dash, or underscore, starting with a letter or digit."
        )
    return value


def compact_safe_id(value: str, *, kind: str = "derived identifier") -> str:
    """Bound a derived safe id while retaining a stable, collision-resistant suffix."""

    if not isinstance(value, str) or not _UNBOUNDED_SAFE_ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {kind}: {value!r}")
    if len(value) <= MAX_SAFE_ID_LENGTH:
        return value

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    prefix_length = MAX_SAFE_ID_LENGTH - len(digest) - 2
    prefix = value[:prefix_length].rstrip("._-") or "id"
    return parse_safe_id(f"{prefix}__{digest}", kind=kind)


__all__ = [
    "MAX_SAFE_ID_LENGTH",
    "SAFE_ID_PATTERN",
    "compact_safe_id",
    "parse_safe_id",
]
