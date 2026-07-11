"""Experiment records and comparison read models."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..fsio import atomic_write_json
from ..read_models.base import SAFE_ID, _read_json
from ..read_models.runs import run_overview
from .errors import ExperimentError

def experiments_dir(runs_dir: Path) -> Path:
    return runs_dir / "experiments"


def _experiment_path(runs_dir: Path, experiment_id: str) -> Path:
    if not SAFE_ID.match(experiment_id):
        raise ExperimentError(f"Invalid experiment id: {experiment_id!r}")
    return experiments_dir(runs_dir) / f"{experiment_id}.json"


def record_experiment(
    runs_dir: Path,
    *,
    name: str,
    payload: Dict[str, Any],
    plans: List[Dict[str, Any]],
    launch_status: str = "recorded",
    launch_error: Optional[str] = None,
) -> Dict[str, Any]:
    record = {
        "id": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tasks_dir": payload.get("tasks_dir"),
        "tasks": payload.get("tasks") or [],
        "shared": payload.get("shared"),
        "contenders": [
            {
                "label": plan["label"],
                "agent": plan["agent"],
                "agent_label": plan.get("agent_label") or plan["agent"],
                "model": plan["model"],
                "run_id": plan["run_id"],
                "backend": plan["backend"],
                "backend_downgraded": plan["backend_downgraded"],
            }
            for plan in plans
        ],
        "run_ids": [plan["run_id"] for plan in plans],
        "launch_status": launch_status,
    }
    if launch_error:
        record["launch_error"] = launch_error
    directory = experiments_dir(runs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_experiment_path(runs_dir, name), record, indent=2, sort_keys=True)
    return record


def list_experiments(runs_dir: Path, active_run_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    directory = experiments_dir(runs_dir)
    if not directory.is_dir():
        return []
    records: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        record = _read_json(path)
        if not isinstance(record, dict) or not isinstance(record.get("run_ids"), list):
            continue
        summary = dict(record)
        summary["runs"] = []
        for run_id in record["run_ids"]:
            run_root = runs_dir / str(run_id)
            if run_root.is_dir():
                summary["runs"].append(run_overview(run_root, active_run_ids))
            else:
                summary["runs"].append({"run_id": run_id, "status": "missing"})
        records.append(summary)
    return records


def experiment_detail(
    runs_dir: Path, experiment_id: str, active_run_ids: Optional[set] = None
) -> Dict[str, Any]:
    path = _experiment_path(runs_dir, experiment_id)
    record = _read_json(path)
    if not isinstance(record, dict):
        raise ExperimentError(f"No experiment named {experiment_id}.")

    contenders = record.get("contenders") or []
    runs: List[Dict[str, Any]] = []
    for contender in contenders:
        run_id = str(contender.get("run_id") or "")
        run_root = runs_dir / run_id
        entry = dict(contender)
        entry["run"] = run_overview(run_root, active_run_ids) if run_root.is_dir() else None
        runs.append(entry)

    matrix = _build_matrix(runs_dir, contenders)
    return {**record, "contenders": runs, "matrix": matrix}


def _build_matrix(runs_dir: Path, contenders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """rubric x contender pass matrix, grouped by task, from single-judge results."""
    questions: Dict[str, Dict[str, str]] = {}
    cells: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}
    task_order: List[str] = []

    for contender in contenders:
        run_id = str(contender.get("run_id") or "")
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
