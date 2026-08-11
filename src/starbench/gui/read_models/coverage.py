"""HSW task-by-contender coverage read model."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ...domain import TaskRunOutcome
from .base import _parse_iso, _read_json
from .runs import _catalog_records
from .tasks import list_task_packages

COVERAGE_RECENT_REFS_LIMIT = 5


def _empty_cell(column_key: str, state: str = "untested") -> Dict[str, Any]:
    return {
        "column_key": column_key,
        "state": state,
        "total": 0,
        "judged": 0,
        "passed": 0,
        "inconclusive": 0,
        "last_tested": None,
        "recent_refs": [],
        "rubric_samples": 0,
        "rubric_ratio_mean": None,
        "rubric_ratio_std": None,
        "duration_mean_seconds": None,
        "duration_p95_seconds": None,
        "exec_success": 0,
        "exec_failed": 0,
        "exec_timeout": 0,
        "exec_pending": 0,
    }


def _p95(values: List[float]) -> float:
    """Nearest-rank P95 — exact for the small sample counts a cell holds."""

    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _ratio_stats(ratios: List[float]) -> Tuple[Optional[float], Optional[float]]:
    if not ratios:
        return None, None
    mean = sum(ratios) / len(ratios)
    if len(ratios) < 2:
        return mean, None
    variance = sum((value - mean) ** 2 for value in ratios) / len(ratios)
    return mean, math.sqrt(variance)

def coverage(
    runs_dir: Path,
    tasks_dirs: Sequence[Path],
    profile_id: Optional[str] = None,
    profiles: Optional[List[Dict[str, Any]]] = None,
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
    cell_durations: Dict[Tuple[str, str], List[float]] = {}
    cell_ratios: Dict[Tuple[str, str], List[float]] = {}
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
            cell = cells.setdefault(cell_key, _empty_cell(column_key, state="inconclusive"))
            cell["total"] += 1
            status = sample.get("executor_status")
            if status == "success":
                cell["exec_success"] += 1
            elif status == "failed":
                cell["exec_failed"] += 1
            elif status == "timeout":
                cell["exec_timeout"] += 1
            else:
                cell["exec_pending"] += 1
            duration = sample.get("executor_duration_seconds")
            if isinstance(duration, (int, float)) and duration >= 0:
                cell_durations.setdefault(cell_key, []).append(float(duration))
            rubric_passed = sample.get("rubric_passed")
            rubric_total = sample.get("rubric_total")
            if (
                isinstance(rubric_passed, int)
                and isinstance(rubric_total, int)
                and rubric_total > 0
            ):
                cell_ratios.setdefault(cell_key, []).append(rubric_passed / rubric_total)
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

    for cell_key, cell in cells.items():
        if cell["passed"] > 0:
            cell["state"] = "breached"
        elif cell["judged"] > 0:
            cell["state"] = "defended"
        else:
            # An observed task run with no valid HSW sample is a measurement
            # problem, whether it already carries an explicit inconclusive
            # outcome or is still missing a verdict artifact.
            cell["state"] = "inconclusive"
        durations = cell_durations.get(cell_key, [])
        if durations:
            cell["duration_mean_seconds"] = sum(durations) / len(durations)
            cell["duration_p95_seconds"] = _p95(durations)
        ratios = cell_ratios.get(cell_key, [])
        mean, std = _ratio_stats(ratios)
        cell["rubric_samples"] = len(ratios)
        cell["rubric_ratio_mean"] = mean
        cell["rubric_ratio_std"] = std

    # ------------------------------------------------------------------
    # Roster overlay. The roster defines the denominator: rostered columns lead
    # (declaration order), observed-only columns follow (sorted). A rostered
    # contender never observed still becomes a zero-cell column. Profiles are
    # injected by the service layer; a read model reaching up into services
    # would invert the layering. Without injection, the stored profiles.json
    # is read raw — equivalent for the overlay, since built-in profiles carry
    # no roster.
    # ------------------------------------------------------------------
    if profiles is None:
        stored = _read_json(runs_dir / "profiles.json")
        profiles = stored.get("profiles") if isinstance(stored, dict) else None
    profile_list = profiles if isinstance(profiles, list) else []

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

    # Column rollup: the same scan aggregated once per contender, for the
    # combination panel, comparison views, and overview heatmaps. Zero-run
    # columns carry an all-empty rollup — the hole stays visible.
    for key, column in columns.items():
        column["rostered"] = key in roster_key_set
        column_ratios: List[float] = []
        column_durations: List[float] = []
        tasks_tested = 0
        judged = 0
        passed = 0
        exec_pending = 0
        last_tested: Optional[str] = None
        last_parsed: Optional[datetime] = None
        for (task_id, cell_column_key), cell in cells.items():
            if cell_column_key != key:
                continue
            if cell["judged"] > 0:
                tasks_tested += 1
            judged += cell["judged"]
            passed += cell["passed"]
            exec_pending += cell["exec_pending"]
            column_ratios.extend(cell_ratios.get((task_id, cell_column_key), []))
            column_durations.extend(cell_durations.get((task_id, cell_column_key), []))
            parsed = _parse_iso(cell["last_tested"])
            if parsed is not None and (last_parsed is None or parsed > last_parsed):
                last_parsed = parsed
                last_tested = cell["last_tested"]
        mean, std = _ratio_stats(column_ratios)
        column["stats"] = {
            "tasks_tested": tasks_tested,
            "judged": judged,
            "passed": passed,
            "exec_pending": exec_pending,
            "rubric_samples": len(column_ratios),
            "rubric_ratio_mean": mean,
            "rubric_ratio_std": std,
            "duration_p95_seconds": _p95(column_durations) if column_durations else None,
            "last_tested": last_tested,
        }

    rostered_columns = [columns[key] for key in roster_keys]
    unrostered_columns = sorted(
        (column for key, column in columns.items() if key not in roster_key_set),
        key=lambda col: (col["agent"], col["model"] or ""),
    )
    column_order = rostered_columns + unrostered_columns
    ordered_keys = [col["key"] for col in column_order]
    rows: List[Dict[str, Any]] = []
    for task_id in library_ids | observed_tasks:
        row_cells = []
        for key in ordered_keys:
            row_cells.append(cells.get((task_id, key), _empty_cell(key)))
        rows.append(
            {
                "task_id": task_id,
                "in_library": task_id in library_ids,
                "breached": any(cell["state"] == "breached" for cell in row_cells),
                "tested_columns": sum(
                    1
                    for cell in row_cells
                    if cell["state"] in {"breached", "defended"}
                ),
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
