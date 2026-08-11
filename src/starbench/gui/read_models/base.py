"""Shared bounded filesystem readers and path resolution."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...domain import SAFE_ID_PATTERN

SAFE_ID = SAFE_ID_PATTERN
STDERR_TAIL_BYTES = 64_000
FINAL_MD_MAX_BYTES = 512_000
LIVE_TAIL_MAX_BYTES = 256_000


def _jsonl_index_root(runs_dir: Path) -> Path:
    return runs_dir / ".starbench" / "jsonl"

class NotFound(Exception):
    pass


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def _read_jsonl_slice(path: Path, offset: int, limit: int) -> Tuple[List[Dict[str, Any]], int]:
    rows = _read_jsonl(path)
    return rows[offset : offset + limit], len(rows)


def _tail_text(path: Path, max_bytes: int = STDERR_TAIL_BYTES) -> Optional[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read()
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    if size > max_bytes:
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
    return text


def _read_text(path: Path, max_bytes: int = FINAL_MD_MAX_BYTES) -> Optional[str]:
    try:
        data = path.read_bytes()[:max_bytes]
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")


def resolve_run_dir(runs_dir: Path, run_id: str) -> Path:
    if not SAFE_ID.match(run_id):
        raise NotFound(f"Invalid run id: {run_id!r}")
    run_root = (runs_dir / run_id).resolve()
    try:
        run_root.relative_to(runs_dir.resolve())
    except ValueError:
        raise NotFound(f"Run outside runs directory: {run_id!r}")
    if not run_root.is_dir():
        raise NotFound(f"No such run: {run_id!r}")
    return run_root


def resolve_task_run_dir(runs_dir: Path, run_id: str, task_run_id: str) -> Path:
    run_root = resolve_run_dir(runs_dir, run_id)
    if not SAFE_ID.match(task_run_id):
        raise NotFound(f"Invalid task run id: {task_run_id!r}")
    task_root = (run_root / task_run_id).resolve()
    try:
        task_root.relative_to(run_root)
    except ValueError:
        raise NotFound(f"Task run outside run directory: {task_run_id!r}")
    if not task_root.is_dir():
        raise NotFound(f"No such task run: {task_run_id!r}")
    return task_root


def _parse_iso(stamp: Any) -> Optional[datetime]:
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _tail_jsonl(path: Path, limit: int, max_bytes: int = LIVE_TAIL_MAX_BYTES) -> List[Dict[str, Any]]:
    """Last ``limit`` JSON rows of a JSONL file, reading at most ``max_bytes``.

    Reads only the end of the file so polling a multi-megabyte event log stays
    cheap. A partial first line (from seeking mid-line) is dropped.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > max_bytes:
                handle.seek(size - max_bytes)
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[-limit:]
