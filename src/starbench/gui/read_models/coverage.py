"""HSW task-by-contender coverage read model."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...domain import TaskRunOutcome
from .base import _parse_iso
from .runs import _catalog_records
from .tasks import list_task_packages

COVERAGE_RECENT_REFS_LIMIT = 5

def coverage(
    runs_dir: Path, tasks_dirs: Sequence[Path], profile_id: Optional[str] = None
) -> Dict[str, Any]:
    """Task × executor-config coverage matrix over everything on disk.

    Rows are the union of the task library (``tasks_dirs``) and every task id
    observed in ``runs_dir``; columns are the union of a profile's declared
    roster and the executor configs observed in run configs (``executor_agent``
    × ``executor_model``). HSW semantics: a cell with any ``agent_pass`` outcome
    means the task was breached, so variants and repeats all aggregate into the
    same cell. Inconclusive outcomes count as attempts but never as judged HSW
    samples. Library tasks never run render as zero-cell rows — the visible gaps
    are the point. A corrupted run directory degrades to an "unknown" column
    (or is skipped mid-scan); it never sinks the payload.

    Roster overlay: the first profile carrying a non-empty ``roster`` (or the
    one named by ``profile_id``) defines the coverage denominator. Its declared
    contender columns come first, in declaration order, flagged ``rostered``;
    columns observed only on disk sort after them. A rostered contender never
    seen in any run still becomes a column — a zero-cell column is the hole in
    the denominator, the whole point of a roster. With no rostered profile on
    disk the matrix falls back to pure disk induction: ``profile`` is null and
    every column is ``rostered: False``.
    """
    library_ids: set = set()
    for tasks_dir in tasks_dirs:
        for package in list_task_packages(tasks_dir):
            library_ids.add(str(package["id"]))

    columns: Dict[str, Dict[str, Any]] = {}
    cells: Dict[Tuple[str, str], Dict[str, Any]] = {}
    # (parsed timestamp, raw timestamp string, ref) per task run, per cell.
    cell_refs: Dict[Tuple[str, str], List[Tuple[Optional[datetime], Optional[str], Dict[str, str]]]] = {}
    observed_tasks: set = set()
    runs_scanned = 0

    catalog_records = _catalog_records(runs_dir)
    for record in sorted(catalog_records, key=lambda item: item["run_id"]):
        runs_scanned += 1
        config = record.get("config")
        config = config if isinstance(config, dict) else {}
        agent = config.get("executor_agent")
        agent = agent if isinstance(agent, str) and agent else "unknown"
        model = config.get("executor_model")
        model = model if isinstance(model, str) and model else None
        column_key = f"{agent}::{model or ''}"
        column = columns.setdefault(
            column_key,
            {"key": column_key, "agent": agent, "model": model, "run_count": 0},
        )
        column["run_count"] += 1
        task_samples = record.get("tasks")
        task_samples = task_samples if isinstance(task_samples, list) else []
        for sample in task_samples:
            if not isinstance(sample, dict):
                continue
            task_id = sample.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            observed_tasks.add(task_id)
            cell_key = (task_id, column_key)
            cell = cells.setdefault(
                cell_key,
                {
                    "column_key": column_key,
                    "total": 0,
                    "judged": 0,
                    "passed": 0,
                    "inconclusive": 0,
                    "last_tested": None,
                    "recent_refs": [],
                },
            )
            cell["total"] += 1
            outcomes: List[TaskRunOutcome] = []
            for value in sample.get("outcomes") or []:
                try:
                    outcomes.append(TaskRunOutcome(value))
                except (TypeError, ValueError):
                    continue
            valid_outcomes = [outcome for outcome in outcomes if outcome.is_hsw_sample]
            if valid_outcomes:
                cell["judged"] += 1
            if TaskRunOutcome.AGENT_PASS in valid_outcomes:
                cell["passed"] += 1
            if not valid_outcomes and any(
                outcome
                in {
                    TaskRunOutcome.INCONCLUSIVE_JUDGE,
                    TaskRunOutcome.INCONCLUSIVE_EXECUTOR,
                    TaskRunOutcome.INVALID_TASK,
                }
                for outcome in outcomes
            ):
                cell["inconclusive"] += 1
            tested_at = sample.get("tested_at")
            tested_at = tested_at if isinstance(tested_at, str) else None
            run_task_id = str(sample.get("run_task_id") or "")
            cell_refs.setdefault(cell_key, []).append(
                (
                    _parse_iso(tested_at),
                    tested_at,
                    {"run_id": record["run_id"], "run_task_id": run_task_id},
                )
            )

    epoch_floor = datetime.min.replace(tzinfo=timezone.utc)
    for cell_key, refs in cell_refs.items():
        # Newest first; refs without a parseable timestamp sink to the end
        # (stable sort keeps run order among equals, runs iterate name-sorted).
        refs.sort(key=lambda item: item[0] or epoch_floor, reverse=True)
        newest_parsed, newest_raw, _ = refs[0]
        if newest_parsed is not None:
            cells[cell_key]["last_tested"] = newest_raw
        cells[cell_key]["recent_refs"] = [
            ref for _, _, ref in refs[:COVERAGE_RECENT_REFS_LIMIT]
        ]

    # ------------------------------------------------------------------
    # Roster overlay. The roster defines the denominator: rostered columns lead
    # (declaration order), observed-only columns follow (sorted). A rostered
    # contender never observed still becomes a zero-cell column. ``load_profiles``
    # is imported lazily here because ``experiments`` imports this module at
    # module load — a top-level import would be circular.
    # ------------------------------------------------------------------
    from ..experiments import load_profiles

    profiles_payload = load_profiles(runs_dir)
    profile_list = profiles_payload.get("profiles")
    profile_list = profile_list if isinstance(profile_list, list) else []

    def _has_roster(profile: Any) -> bool:
        return (
            isinstance(profile, dict)
            and isinstance(profile.get("roster"), list)
            and bool(profile.get("roster"))
        )

    roster_profile: Optional[Dict[str, Any]] = None
    if profile_id:
        for profile in profile_list:
            if (
                isinstance(profile, dict)
                and str(profile.get("id")) == profile_id
                and _has_roster(profile)
            ):
                roster_profile = profile
                break
    else:
        roster_profile = next((p for p in profile_list if _has_roster(p)), None)

    roster_keys: List[str] = []
    roster_key_set: set = set()
    profile_field: Optional[Dict[str, Any]] = None
    if roster_profile is not None:
        rev = roster_profile.get("rev")
        profile_field = {
            "id": str(roster_profile.get("id")),
            "name": str(roster_profile.get("name") or roster_profile.get("id")),
            "rev": rev if isinstance(rev, int) else 0,
        }
        for entry in roster_profile["roster"]:
            if not isinstance(entry, dict):
                continue
            agent = entry.get("agent")
            agent = agent if isinstance(agent, str) and agent else "unknown"
            model = entry.get("model")
            model = model if isinstance(model, str) and model else None
            key = f"{agent}::{model or ''}"
            if key in roster_key_set:
                continue
            roster_key_set.add(key)
            roster_keys.append(key)
            # A rostered contender never observed on disk still becomes a
            # column — the zero-cell column is the visible denominator hole.
            columns.setdefault(
                key,
                {"key": key, "agent": agent, "model": model, "run_count": 0},
            )

    for key, column in columns.items():
        column["rostered"] = key in roster_key_set

    rostered_columns = [columns[key] for key in roster_keys]
    unrostered_columns = sorted(
        (column for key, column in columns.items() if key not in roster_key_set),
        key=lambda col: (col["agent"], col["model"] or ""),
    )
    column_order = rostered_columns + unrostered_columns
    ordered_keys = [col["key"] for col in column_order]
    rows: List[Dict[str, Any]] = []
    for task_id in library_ids | observed_tasks:
        row_cells = [
            cells[(task_id, key)] for key in ordered_keys if (task_id, key) in cells
        ]
        rows.append(
            {
                "task_id": task_id,
                "in_library": task_id in library_ids,
                "breached": any(cell["passed"] > 0 for cell in row_cells),
                "tested_columns": sum(1 for cell in row_cells if cell["judged"] > 0),
                "cells": row_cells,
            }
        )
    rows.sort(key=lambda row: (not row["breached"], row["task_id"]))

    return {
        "columns": column_order,
        "rows": rows,
        "runs_scanned": runs_scanned,
        "profile": profile_field,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
