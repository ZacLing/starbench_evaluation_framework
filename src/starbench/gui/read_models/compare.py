"""Stateless cross-run comparison: rubric × run pass matrix from artifacts.

Any set of runs can be compared — the runs need not have been launched
together. Everything is computed from what is on disk at request time; there
is no comparison entity to create, persist, or clean up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import SAFE_ID, NotFound, _read_json
from .runs import run_overview

COMPARE_MAX_RUNS = 12


def compare_runs(
    runs_dir: Path, run_ids: List[str], active_run_ids: Optional[set] = None
) -> Dict[str, Any]:
    if not run_ids:
        raise NotFound("At least one run id is required.")
    if len(run_ids) > COMPARE_MAX_RUNS:
        raise NotFound(f"At most {COMPARE_MAX_RUNS} runs can be compared at once.")
    for run_id in run_ids:
        if not SAFE_ID.match(run_id):
            raise NotFound(f"Invalid run id: {run_id!r}")

    rows: List[Dict[str, Any]] = []
    for run_id in run_ids:
        run_root = runs_dir / run_id
        rows.append(
            {
                "run_id": run_id,
                # A vanished run renders as an honest hole, never an error:
                # comparison sets are user-typed and long-lived in URLs.
                "run": run_overview(run_root, active_run_ids) if run_root.is_dir() else None,
            }
        )

    return {"runs": rows, "matrix": _build_matrix(runs_dir, run_ids)}


def _build_matrix(runs_dir: Path, run_ids: List[str]) -> List[Dict[str, Any]]:
    """rubric × run pass matrix, grouped by task, from single-judge results."""
    questions: Dict[str, Dict[str, str]] = {}
    cells: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}
    task_order: List[str] = []

    for run_id in run_ids:
        run_root = runs_dir / run_id
        if not run_root.is_dir():
            continue
        for task_root in sorted(run_root.iterdir()):
            if not task_root.is_dir() or not (task_root / "logs").is_dir():
                continue
            manifest = _read_json(task_root / "manifest.json")
            task_id = (
                str(manifest.get("task_id"))
                if isinstance(manifest, dict) and manifest.get("task_id")
                else task_root.name
            )
            if task_id not in cells:
                cells[task_id] = {}
                questions.setdefault(task_id, {})
                task_order.append(task_id)
            if isinstance(manifest, dict):
                for rubric in manifest.get("rubrics") or []:
                    if isinstance(rubric, dict) and rubric.get("id"):
                        questions[task_id].setdefault(
                            str(rubric["id"]), str(rubric.get("question", ""))
                        )
            aggregate = _read_json(task_root / "judges" / "single_aggregate.json")
            if not isinstance(aggregate, dict):
                continue
            for row in aggregate.get("results") or []:
                rubric_id = str(row.get("rubric_id") or "")
                if not rubric_id:
                    continue
                bucket = cells[task_id].setdefault(rubric_id, {})
                stats = bucket.setdefault(run_id, {"passed": 0, "total": 0})
                stats["total"] += 1
                if row.get("passed"):
                    stats["passed"] += 1

    matrix = []
    for task_id in task_order:
        rubric_ids = sorted(cells[task_id].keys())
        matrix.append(
            {
                "task_id": task_id,
                "rubrics": [
                    {
                        "id": rubric_id,
                        "question": questions[task_id].get(rubric_id, ""),
                        "cells": cells[task_id][rubric_id],
                    }
                    for rubric_id in rubric_ids
                ],
            }
        )
    return matrix


__all__ = ["COMPARE_MAX_RUNS", "compare_runs"]
