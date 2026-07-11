"""Incremental byte-offset indexes for append-only JSONL artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..fsio import atomic_write_json

JSONL_INDEX_SCHEMA_VERSION = 1

_LOCKS_GUARD = threading.Lock()
_LOCKS: Dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    # Module-level indirection kept as the test seam for read-only mounts.
    # Indexes are large and rewritten often: compact separators, no sorting.
    atomic_write_json(path, payload, sort_keys=False, separators=(",", ":"))


def _index_path(index_root: Path, source: Path, mode: str) -> Path:
    digest = hashlib.sha256(f"{source.resolve()}\0{mode}".encode("utf-8")).hexdigest()
    return index_root / f"{digest}.json"


def _empty_index(source: Path, mode: str, stat: os.stat_result) -> Dict[str, Any]:
    return {
        "schema_version": JSONL_INDEX_SCHEMA_VERSION,
        "source": str(source.resolve()),
        "mode": mode,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "source_size": 0,
        "source_mtime_ns": 0,
        "scan_position": 0,
        "ended_with_newline": True,
        "offsets": [],
        "first_timestamp": None,
    }


def _load_index(path: Path, source: Path, mode: str, stat: os.stat_result) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_index(source, mode, stat)
    valid = (
        isinstance(payload, dict)
        and payload.get("schema_version") == JSONL_INDEX_SCHEMA_VERSION
        and payload.get("source") == str(source.resolve())
        and payload.get("mode") == mode
        and isinstance(payload.get("offsets"), list)
        and all(isinstance(value, int) and value >= 0 for value in payload["offsets"])
        and isinstance(payload.get("scan_position"), int)
    )
    if not valid:
        return _empty_index(source, mode, stat)
    same_file = payload.get("device") == stat.st_dev and payload.get("inode") == stat.st_ino
    appended = stat.st_size >= payload.get("source_size", 0)
    append_safe = payload.get("ended_with_newline", True) or stat.st_size == payload.get(
        "source_size", 0
    )
    if not same_file or not appended or not append_safe:
        return _empty_index(source, mode, stat)
    if (
        stat.st_size == payload.get("source_size")
        and stat.st_mtime_ns != payload.get("source_mtime_ns")
    ):
        return _empty_index(source, mode, stat)
    return payload


def _scan(source: Path, index: Dict[str, Any], stat: os.stat_result) -> None:
    offsets: List[int] = index["offsets"]
    position = int(index.get("scan_position") or 0)
    ended_with_newline = True
    with source.open("rb") as handle:
        handle.seek(position)
        while True:
            offset = handle.tell()
            raw = handle.readline()
            if not raw:
                break
            ended_with_newline = raw.endswith((b"\n", b"\r"))
            stripped = raw.strip()
            include = bool(stripped)
            parsed: Any = None
            if include:
                try:
                    parsed = json.loads(stripped.decode("utf-8", errors="replace"))
                except ValueError:
                    parsed = None
            if index["mode"] == "json-object":
                include = isinstance(parsed, dict)
            if include:
                offsets.append(offset)
                if index.get("first_timestamp") is None and isinstance(parsed, dict):
                    timestamp = parsed.get("timestamp")
                    if isinstance(timestamp, str) and timestamp:
                        index["first_timestamp"] = timestamp
            position = handle.tell()
    index.update(
        {
            "device": stat.st_dev,
            "inode": stat.st_ino,
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "scan_position": position,
            "ended_with_newline": ended_with_newline,
        }
    )


@dataclass(frozen=True)
class JsonlPage:
    rows: List[Any]
    total: int
    first_timestamp: Optional[str]


def _read_page(
    source: Path,
    *,
    offset: int,
    limit: int,
    index_root: Path,
    mode: str,
) -> JsonlPage:
    try:
        stat = source.stat()
    except OSError:
        return JsonlPage([], 0, None)
    index_path = _index_path(index_root, source, mode)
    with _lock_for(index_path):
        index = _load_index(index_path, source, mode, stat)
        if (
            index.get("source_size") != stat.st_size
            or index.get("source_mtime_ns") != stat.st_mtime_ns
        ):
            _scan(source, index, stat)
            try:
                _atomic_write_json(index_path, index)
            except OSError:
                # Indexes are disposable. Read-only run mounts remain usable.
                pass
        offsets = index["offsets"]
        selected = offsets[offset : offset + limit]
        rows: List[Any] = []
        try:
            with source.open("rb") as handle:
                for byte_offset in selected:
                    handle.seek(byte_offset)
                    raw = handle.readline().decode("utf-8", errors="replace").rstrip("\r\n")
                    if mode == "json-object":
                        try:
                            value = json.loads(raw)
                        except ValueError:
                            continue
                        if isinstance(value, dict):
                            rows.append(value)
                    else:
                        rows.append(raw)
        except OSError:
            return JsonlPage([], 0, None)
        return JsonlPage(rows, len(offsets), index.get("first_timestamp"))


def read_json_objects_page(
    source: Path, *, offset: int, limit: int, index_root: Path
) -> JsonlPage:
    return _read_page(
        source,
        offset=max(0, offset),
        limit=max(1, limit),
        index_root=index_root,
        mode="json-object",
    )


def read_nonempty_lines_page(
    source: Path, *, offset: int, limit: int, index_root: Path
) -> JsonlPage:
    return _read_page(
        source,
        offset=max(0, offset),
        limit=max(1, limit),
        index_root=index_root,
        mode="nonempty-line",
    )


__all__ = [
    "JSONL_INDEX_SCHEMA_VERSION",
    "JsonlPage",
    "read_json_objects_page",
    "read_nonempty_lines_page",
]
