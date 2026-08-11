"""Host-side path boundaries for untrusted task packages and run ids."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .identifiers import parse_safe_id


def parse_relative_path(value: Any, *, kind: str = "path") -> Path:
    """Parse a portable relative path without normalizing unsafe segments away."""

    if not isinstance(value, (str, Path)):
        raise ValueError(f"Invalid {kind}: expected a relative path, got {value!r}")
    raw = str(value)
    if not raw or "\x00" in raw or "\\" in raw:
        raise ValueError(f"Invalid {kind}: {raw!r}")
    if PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        raise ValueError(f"Invalid {kind}: absolute paths are not allowed: {raw!r}")

    parts = PurePosixPath(raw).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Invalid {kind}: dot path segments are not allowed: {raw!r}")
    return Path(*parts)


def resolve_within(root: Path, value: Any, *, kind: str = "path") -> Path:
    """Resolve a relative path and prove that it remains under *root*."""

    root = root.resolve()
    relative = parse_relative_path(value, kind=kind)
    lexical = root / relative

    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Invalid {kind}: symbolic links are not allowed: {current}")

    resolved = lexical.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"Invalid {kind}: path escapes {root}: {value!r}") from error
    return resolved


def safe_child(root: Path, identifier: Any, *, kind: str = "identifier") -> Path:
    """Return a direct child path after validating its single-component id."""

    return root / parse_safe_id(identifier, kind=kind)


def assert_no_symlinks(path: Path, *, kind: str = "path") -> None:
    """Reject a symlink or a directory tree containing any symlink."""

    if path.is_symlink():
        raise ValueError(f"Invalid {kind}: symbolic links are not allowed: {path}")
    if not path.exists() or not path.is_dir():
        return
    for child in path.rglob("*"):
        if child.is_symlink():
            raise ValueError(f"Invalid {kind}: symbolic links are not allowed: {child}")


__all__ = ["assert_no_symlinks", "parse_relative_path", "resolve_within", "safe_child"]
