"""Recorded identity, timing, and outcome facts for one task run."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...domain import TaskRunOutcome, aggregate_outcome
from .base import _read_json

def _task_identity(task_root: Path) -> Tuple[Optional[str], Optional[str], bool]:
    """(base task id, instruction variant, evaluated) for one task-run directory.

    ``task_summary.json`` is authoritative once the judge has run; before that
    the executor-side ``manifest.json`` carries the same identity fields. Both
    missing yields ``(None, None, False)`` — never a guess parsed out of the
    directory name (variant labels may themselves contain ``__``).
    """
    summary = _read_json(task_root / "task_summary.json")
    evaluated = isinstance(summary, dict)
    task_id: Optional[str] = None
    variant: Optional[str] = None
    if evaluated:
        task_id = summary.get("task_id")
        variant = summary.get("instruction_variant")
    if task_id is None or variant is None:
        manifest = _read_json(task_root / "manifest.json")
        if isinstance(manifest, dict):
            if task_id is None:
                task_id = manifest.get("task_id") or manifest.get("id")
            if variant is None:
                variant = manifest.get("instruction_variant")
    return task_id, variant, evaluated


def _judge_outcomes(task_root: Path) -> List[TaskRunOutcome]:
    """Every classifiable judge outcome recorded for one task run.

    Mirrors ``_task_row``'s judge reading: ``task_summary.json`` is
    authoritative once the judge has run; before that the standalone aggregate
    files under ``judges/`` are consulted. Legacy aggregates are classified
    conservatively: an ``error`` is inconclusive even when old writers stored
    ``overall_pass: false``. Nothing on disk yields an empty list — never an
    invented verdict.
    """
    summary = _read_json(task_root / "task_summary.json")
    outcomes: List[TaskRunOutcome] = []
    if isinstance(summary, dict) and isinstance(summary.get("judges"), dict):
        for payload in summary["judges"].values():
            aggregate = payload.get("aggregate") if isinstance(payload, dict) else None
            if isinstance(aggregate, dict):
                outcome = aggregate_outcome(aggregate)
                if outcome is not None:
                    outcomes.append(outcome)
        return outcomes
    for mode in ("single", "parallel"):
        aggregate = _read_json(task_root / "judges" / f"{mode}_aggregate.json")
        if isinstance(aggregate, dict):
            outcome = aggregate_outcome(aggregate)
            if outcome is not None:
                outcomes.append(outcome)
    return outcomes


def _task_run_tested_at(task_root: Path) -> Optional[str]:
    """When this task run finished testing, from recorded data only.

    Preference order: the executor ``ended_at`` recorded in
    ``task_summary.json`` (executor block, then executor_timing), then in
    ``logs/status.json``. Failing those, the mtime of whichever of these files
    exists — a real filesystem timestamp, reported as such. No recorded time
    and no file yields ``None``, never an estimate.
    """
    summary = _read_json(task_root / "task_summary.json")
    if isinstance(summary, dict):
        for key in ("executor", "executor_timing"):
            section = summary.get(key)
            if isinstance(section, dict) and isinstance(section.get("ended_at"), str):
                return section["ended_at"]
    status = _read_json(task_root / "logs" / "status.json")
    if isinstance(status, dict) and isinstance(status.get("ended_at"), str):
        return status["ended_at"]
    for relative in ("task_summary.json", "logs/status.json"):
        path = task_root / relative
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        return datetime.fromtimestamp(mtime, timezone.utc).isoformat()
    return None
