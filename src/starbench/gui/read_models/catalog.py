"""Rebuildable read index over run artifacts.

Artifacts remain authoritative. The catalog only caches a rendered read model
behind a signature made from path, size, and mtime. Deleting or corrupting the
catalog therefore costs a rebuild, never data loss.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..fsio import atomic_write_json

CATALOG_SCHEMA_VERSION = 1
CATALOG_RELATIVE_PATH = Path(".starbench") / "run_catalog-v1.json"

_ROOT_MARKERS = (
    "run_config.json",
    "summary.json",
    "progress_events.jsonl",
    "profile_snapshot.json",
    "run_state.json",
    "instruction_ablation_summary.json",
)
_TASK_MARKERS = (
    "task_summary.json",
    "manifest.json",
    "task_manifest.json",
    "logs/status.json",
    "judges/single_aggregate.json",
    "judges/parallel_aggregate.json",
)
_TASK_DIR_MARKERS = ("logs", "judges")

_LOCKS_GUARD = threading.Lock()
_LOCKS: Dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    # Module-level indirection kept as the test seam for read-only mounts.
    atomic_write_json(path, payload, sort_keys=True)


def _stat_entry(root: Path, path: Path) -> Optional[List[Any]]:
    try:
        stat = path.stat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        return [relative, stat.st_size, stat.st_mtime_ns]
    except (OSError, ValueError):
        return None


def _artifact_signature(run_root: Path) -> List[List[Any]]:
    """Cheap change key for every artifact consumed by catalog read models."""

    entries: List[List[Any]] = []
    root_entry = _stat_entry(run_root, run_root)
    if root_entry is not None:
        entries.append(root_entry)
    for relative in _ROOT_MARKERS:
        entry = _stat_entry(run_root, run_root / relative)
        if entry is not None:
            entries.append(entry)
    try:
        task_roots = sorted(path for path in run_root.iterdir() if path.is_dir())
    except OSError:
        task_roots = []
    for task_root in task_roots:
        task_entry = _stat_entry(run_root, task_root)
        if task_entry is not None:
            entries.append(task_entry)
        for relative in _TASK_DIR_MARKERS:
            entry = _stat_entry(run_root, task_root / relative)
            if entry is not None:
                entries.append(entry)
        for relative in _TASK_MARKERS:
            entry = _stat_entry(run_root, task_root / relative)
            if entry is not None:
                entries.append(entry)
    entries.sort(key=lambda item: item[0])
    return entries


def _is_run_root(path: Path) -> bool:
    return path.is_dir() and (
        any((path / marker).exists() for marker in _ROOT_MARKERS[:3])
        or (path / "run_state.json").exists()
    )


@dataclass(frozen=True)
class CatalogRecord:
    run_id: str
    sort_mtime_ns: int
    value: Dict[str, Any]


class RunCatalog:
    """Thread-safe, atomically persisted cache of rendered run read models."""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir.resolve()
        self.path = self.runs_dir / CATALOG_RELATIVE_PATH
        self._lock = _lock_for(self.path)

    def _load(self) -> Dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"schema_version": CATALOG_SCHEMA_VERSION, "runs": {}}
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != CATALOG_SCHEMA_VERSION
            or not isinstance(payload.get("runs"), dict)
        ):
            return {"schema_version": CATALOG_SCHEMA_VERSION, "runs": {}}
        return payload

    def records(
        self, builder: Callable[[Path], Dict[str, Any]]
    ) -> List[CatalogRecord]:
        if not self.runs_dir.is_dir():
            return []
        with self._lock:
            payload = self._load()
            previous = payload["runs"]
            current: Dict[str, Any] = {}
            changed = not self.path.is_file()
            try:
                roots = sorted(
                    (path for path in self.runs_dir.iterdir() if _is_run_root(path)),
                    key=lambda path: path.name,
                )
            except OSError:
                roots = []
            records: List[CatalogRecord] = []
            for run_root in roots:
                signature = _artifact_signature(run_root)
                try:
                    sort_mtime_ns = run_root.stat().st_mtime_ns
                except OSError:
                    continue
                cached = previous.get(run_root.name)
                if (
                    isinstance(cached, dict)
                    and cached.get("signature") == signature
                    and isinstance(cached.get("value"), dict)
                ):
                    value = cached["value"]
                else:
                    try:
                        value = builder(run_root)
                    except OSError:
                        continue
                    changed = True
                entry = {
                    "signature": signature,
                    "sort_mtime_ns": sort_mtime_ns,
                    "value": value,
                }
                current[run_root.name] = entry
                records.append(CatalogRecord(run_root.name, sort_mtime_ns, value))
            if set(previous) != set(current):
                changed = True
            if changed:
                try:
                    _atomic_write_json(
                        self.path,
                        {"schema_version": CATALOG_SCHEMA_VERSION, "runs": current},
                    )
                except OSError:
                    # A read-only artifact mount still gets a correct response;
                    # it simply cannot benefit from the persisted cache.
                    pass
            records.sort(key=lambda item: item.sort_mtime_ns, reverse=True)
            return records

    def discard(self) -> None:
        """Delete only the cache; the next query rebuilds from artifacts."""

        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


__all__ = [
    "CATALOG_RELATIVE_PATH",
    "CATALOG_SCHEMA_VERSION",
    "CatalogRecord",
    "RunCatalog",
]
