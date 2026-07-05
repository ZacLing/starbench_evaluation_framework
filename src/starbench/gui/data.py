"""Read-only views over a StarBench runs directory.

Every function here renders what exists on disk and nothing else. Missing
files become ``None`` fields, never exceptions, so the console can show an
honest partial picture of interrupted or in-flight runs.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

RUNNING_MTIME_WINDOW_SECONDS = 120

STDERR_TAIL_BYTES = 64_000
FINAL_MD_MAX_BYTES = 512_000


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


def _progress_bounds(run_root: Path) -> Tuple[Optional[str], Optional[str], bool]:
    """First timestamp, last timestamp, and whether the run marked itself finished."""
    path = run_root / "progress_events.jsonl"
    first: Optional[str] = None
    last: Optional[str] = None
    finished = False
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
                if not isinstance(row, dict):
                    continue
                stamp = row.get("timestamp")
                if first is None:
                    first = stamp
                last = stamp
                if row.get("event") == "run_progress_finished":
                    finished = True
    except OSError:
        pass
    return first, last, finished


def run_status(run_root: Path, active_run_ids: Optional[set] = None) -> str:
    """complete | running | interrupted."""
    if active_run_ids and run_root.name in active_run_ids:
        return "running"
    if (run_root / "summary.json").exists():
        return "complete"
    progress_path = run_root / "progress_events.jsonl"
    if progress_path.exists():
        try:
            age = time.time() - progress_path.stat().st_mtime
        except OSError:
            age = None
        if age is not None and age < RUNNING_MTIME_WINDOW_SECONDS:
            return "running"
    return "interrupted"


def _task_dirs(run_root: Path, run_config: Optional[Dict[str, Any]]) -> List[str]:
    ordered: List[str] = []
    if run_config and isinstance(run_config.get("task_order"), list):
        ordered = [str(item) for item in run_config["task_order"] if isinstance(item, str)]
    existing = {
        entry.name
        for entry in run_root.iterdir()
        if entry.is_dir() and (entry / "logs").is_dir()
    }
    rows = [name for name in ordered if name in existing]
    rows.extend(sorted(existing - set(ordered)))
    return rows


def _judge_cell(aggregate: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(aggregate, dict):
        return None
    return {
        "overall_pass": aggregate.get("overall_pass"),
        "passed_count": aggregate.get("passed_count"),
        "total_count": aggregate.get("total_count"),
        "missing": len(aggregate.get("missing") or []),
        "fail_fast_failures": len(aggregate.get("fail_fast_failures") or []),
    }


def _task_row(run_root: Path, task_run_id: str) -> Dict[str, Any]:
    task_root = run_root / task_run_id
    task_summary = _read_json(task_root / "task_summary.json")
    status = _read_json(task_root / "logs" / "status.json")
    judges: Dict[str, Any] = {}
    if isinstance(task_summary, dict):
        for mode, payload in (task_summary.get("judges") or {}).items():
            aggregate = payload.get("aggregate") if isinstance(payload, dict) else None
            judges[mode] = _judge_cell(aggregate)
    else:
        single = _read_json(task_root / "judges" / "single_aggregate.json")
        parallel = _read_json(task_root / "judges" / "parallel_aggregate.json")
        if single is not None:
            judges["single"] = _judge_cell(single)
        if parallel is not None:
            judges["parallel"] = _judge_cell(parallel)

    executor: Optional[Dict[str, Any]] = None
    if isinstance(task_summary, dict) and isinstance(task_summary.get("executor"), dict):
        executor = task_summary["executor"]
    elif isinstance(status, dict):
        executor = status

    row: Dict[str, Any] = {
        "run_task_id": task_run_id,
        "task_id": task_summary.get("task_id") if isinstance(task_summary, dict) else None,
        "instruction_variant": task_summary.get("instruction_variant")
        if isinstance(task_summary, dict)
        else None,
        "executor_status": executor.get("status") if executor else None,
        "executor_duration_seconds": executor.get("duration_seconds") if executor else None,
        "executor_timed_out": executor.get("timed_out") if executor else None,
        "judges": judges,
        "evaluated": isinstance(task_summary, dict),
    }
    if row["task_id"] is None:
        manifest = _read_json(task_root / "manifest.json")
        if isinstance(manifest, dict):
            row["task_id"] = manifest.get("task_id") or manifest.get("id")
            if row["instruction_variant"] is None:
                row["instruction_variant"] = manifest.get("instruction_variant")
    return row


def progress_snapshot(run_root: Path) -> Optional[Dict[str, Any]]:
    events = _read_jsonl(run_root / "progress_events.jsonl")
    if not events:
        return None
    totals = {"executors": 0, "evaluators": 0}
    executor_done = 0
    evaluator_done = 0
    executor_stats = {"success": 0, "failed": 0, "timeout": 0}
    evaluator_stats = {"success": 0, "failed": 0, "timeout": 0}
    active_executors: List[str] = []
    for event in events:
        kind = event.get("event")
        if kind == "run_progress_initialized":
            totals["executors"] = int(event.get("total_executors") or 0)
            totals["evaluators"] = int(event.get("total_evaluators") or 0)
        elif kind == "executor_started":
            run_task_id = event.get("run_task_id")
            if isinstance(run_task_id, str):
                active_executors.append(run_task_id)
        elif kind == "executor_finished":
            executor_done += 1
            run_task_id = event.get("run_task_id")
            if run_task_id in active_executors:
                active_executors.remove(run_task_id)
            state = event.get("status")
            executor_stats[state if state in executor_stats else "failed"] += 1
        elif kind == "evaluator_finished":
            evaluator_done += 1
            state = event.get("status")
            evaluator_stats[state if state in evaluator_stats else "failed"] += 1
    return {
        "totals": totals,
        "executor_done": executor_done,
        "evaluator_done": evaluator_done,
        "executor_stats": executor_stats,
        "evaluator_stats": evaluator_stats,
        "active_executors": active_executors,
        "event_count": len(events),
    }


def run_overview(run_root: Path, active_run_ids: Optional[set] = None) -> Dict[str, Any]:
    run_config = _read_json(run_root / "run_config.json")
    config = run_config if isinstance(run_config, dict) else {}
    task_ids = _task_dirs(run_root, config)
    rows = [_task_row(run_root, task_run_id) for task_run_id in task_ids]

    executor_stats = {"success": 0, "failed": 0, "timeout": 0, "pending": 0}
    judge_passes = {"single": 0, "parallel": 0}
    judge_totals = {"single": 0, "parallel": 0}
    for row in rows:
        state = row["executor_status"]
        if state in ("success", "failed", "timeout"):
            executor_stats[state] += 1
        else:
            executor_stats["pending"] += 1
        for mode in ("single", "parallel"):
            cell = row["judges"].get(mode)
            if cell is not None:
                judge_totals[mode] += 1
                if cell.get("overall_pass"):
                    judge_passes[mode] += 1

    started_at, ended_at, _ = _progress_bounds(run_root)
    return {
        "run_id": run_root.name,
        "status": run_status(run_root, active_run_ids),
        "task_count": len(rows),
        "executor_stats": executor_stats,
        "judge_passes": judge_passes,
        "judge_totals": judge_totals,
        "judge_mode": config.get("judge_mode"),
        "executor_agent": config.get("executor_agent"),
        "executor_model": config.get("executor_model"),
        "evaluator_agent": config.get("evaluator_agent"),
        "evaluator_model": config.get("evaluator_model"),
        "executor_backend": config.get("executor_backend"),
        "seed": config.get("seed"),
        "instruction_mode": config.get("instruction_mode"),
        "started_at": started_at,
        "ended_at": ended_at,
        "has_ablation": (run_root / "instruction_ablation_summary.json").exists(),
    }


def list_runs(runs_dir: Path, active_run_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    if not runs_dir.is_dir():
        return []
    roots = [
        entry
        for entry in runs_dir.iterdir()
        if entry.is_dir()
        and (
            (entry / "run_config.json").exists()
            or (entry / "summary.json").exists()
            or (entry / "progress_events.jsonl").exists()
        )
    ]
    roots.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
    return [run_overview(root, active_run_ids) for root in roots]


def run_detail(runs_dir: Path, run_id: str, active_run_ids: Optional[set] = None) -> Dict[str, Any]:
    run_root = resolve_run_dir(runs_dir, run_id)
    run_config = _read_json(run_root / "run_config.json")
    config = run_config if isinstance(run_config, dict) else {}
    task_ids = _task_dirs(run_root, config)
    overview = run_overview(run_root, active_run_ids)
    detail = {
        **overview,
        "config": config or None,
        "tasks": [_task_row(run_root, task_run_id) for task_run_id in task_ids],
        "progress": progress_snapshot(run_root),
        "ablation": _read_json(run_root / "instruction_ablation_summary.json"),
    }
    return detail


def task_run_detail(runs_dir: Path, run_id: str, task_run_id: str) -> Dict[str, Any]:
    task_root = resolve_task_run_dir(runs_dir, run_id, task_run_id)
    logs = task_root / "logs"
    judges_dir = task_root / "judges"

    task_summary = _read_json(task_root / "task_summary.json")
    summary = task_summary if isinstance(task_summary, dict) else {}

    judges: Dict[str, Any] = {}
    single_aggregate = _read_json(judges_dir / "single_aggregate.json")
    if single_aggregate is None and isinstance(summary.get("judges"), dict):
        single = summary["judges"].get("single")
        if isinstance(single, dict):
            single_aggregate = single.get("aggregate")
    if single_aggregate is not None:
        judges["single"] = {
            "aggregate": single_aggregate,
            "status": _read_json(judges_dir / "single_status.json"),
        }
    parallel_aggregate = _read_json(judges_dir / "parallel_aggregate.json")
    if parallel_aggregate is None and isinstance(summary.get("judges"), dict):
        parallel = summary["judges"].get("parallel")
        if isinstance(parallel, dict):
            parallel_aggregate = parallel.get("aggregate")
    if parallel_aggregate is not None:
        judges["parallel"] = {"aggregate": parallel_aggregate, "status": None}

    events_path = logs / "events.jsonl"
    try:
        raw_event_count = sum(
            1 for line in events_path.open(encoding="utf-8") if line.strip()
        )
    except OSError:
        raw_event_count = 0

    rubric_questions: Dict[str, str] = {}
    manifest = _read_json(task_root / "manifest.json")
    if isinstance(manifest, dict):
        for rubric in manifest.get("rubrics") or []:
            if isinstance(rubric, dict) and rubric.get("id"):
                rubric_questions[str(rubric["id"])] = str(rubric.get("question", ""))

    return {
        "run_id": run_id,
        "run_task_id": task_run_id,
        "task_id": summary.get("task_id"),
        "instruction_variant": summary.get("instruction_variant"),
        "instruction_steps": summary.get("instruction_steps"),
        "executor": summary.get("executor") or _read_json(logs / "status.json"),
        "executor_timing": summary.get("executor_timing"),
        "judges": judges,
        "rubric_questions": rubric_questions,
        "trace_summary": _read_json(logs / "trace_summary.json"),
        "artifact_manifest": _read_json(logs / "artifact_manifest.json"),
        "final_message": _read_text(logs / "final.md"),
        "stderr_tail": _tail_text(logs / "stderr.log"),
        "raw_event_count": raw_event_count,
        "evaluated": isinstance(task_summary, dict),
    }


def raw_events(
    runs_dir: Path, run_id: str, task_run_id: str, offset: int, limit: int
) -> Dict[str, Any]:
    task_root = resolve_task_run_dir(runs_dir, run_id, task_run_id)
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    rows, total = _read_jsonl_slice(task_root / "logs" / "events.jsonl", offset, limit)
    return {
        "events": rows,
        "offset": offset,
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
    }


def rigor_count(package_dir: Path, spec: Dict[str, Any]) -> int:
    """Count the rigor requirements registered for a task package.

    Reads the rigors file the task.json points at (default ``rigors.json``) and
    returns the length of its ``rigors`` array. A missing file, unreadable JSON
    or an unexpected shape all count as 0 — never an exception.
    """
    rigors_name = str(spec.get("rigors", "rigors.json"))
    rigors = _read_json(package_dir / rigors_name)
    if isinstance(rigors, dict) and isinstance(rigors.get("rigors"), list):
        return len(rigors["rigors"])
    return 0


def read_rigors(package_dir: Path, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Public rigor metadata for a task package.

    Reads the rigors file task.json points at (default ``rigors.json``) and
    returns one dict per rigor with the three public fields ``id``,
    ``rubric_id`` and ``requirement``. Every field a rigor carries is
    executor-facing content that the runner injects verbatim into the prompt, so
    there is no private field to withhold (unlike ``human_reference.json``'s
    ``reasoning``). A missing file, unreadable JSON or an unexpected shape all
    yield an empty list — never an exception. ``rubric_id`` falls back to ``id``
    when absent, matching ``runner.models.Rigor.from_dict``.
    """
    name = str(spec.get("rigors", "rigors.json"))
    payload = _read_json(package_dir / name)
    if not isinstance(payload, dict) or not isinstance(payload.get("rigors"), list):
        return []
    rigors: List[Dict[str, Any]] = []
    for item in payload["rigors"]:
        if not isinstance(item, dict) or item.get("id") is None:
            continue
        rigor_id = str(item.get("id"))
        rigors.append(
            {
                "id": rigor_id,
                "rubric_id": str(item.get("rubric_id", rigor_id)),
                "requirement": str(item.get("requirement", "")),
            }
        )
    return rigors


def read_human_reference_steps(package_dir: Path, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Public human-reference step metadata for a task package.

    Reads the human_reference file task.json points at (default
    ``human_reference.json``) and returns one dict per step with ONLY the three
    public fields: ``step_id``, ``step_type`` and ``instruction``.

    PRIVACY RED LINE: the ``reasoning`` field (the private expert trace) is
    deliberately never read into the returned dicts, so it can never reach any
    API response. This is the single reasoning-free reader the console uses; do
    not add ``reasoning`` here. A missing file, unreadable JSON or an unexpected
    shape all yield an empty list — never an exception.
    """
    name = str(spec.get("human_reference", "human_reference.json"))
    payload = _read_json(package_dir / name)
    if not isinstance(payload, dict) or not isinstance(payload.get("steps"), list):
        return []
    steps: List[Dict[str, Any]] = []
    for item in payload["steps"]:
        if not isinstance(item, dict) or item.get("step_id") is None:
            continue
        steps.append(
            {
                "step_id": str(item.get("step_id")),
                "step_type": str(item.get("step_type", "")),
                "instruction": str(item.get("instruction", "")),
            }
        )
    return steps


def list_task_packages(tasks_dir: Path) -> List[Dict[str, Any]]:
    packages: List[Dict[str, Any]] = []
    if not tasks_dir.is_dir():
        return packages
    for entry in sorted(tasks_dir.iterdir()):
        task_json = entry / "task.json"
        if not entry.is_dir() or not task_json.exists():
            continue
        spec = _read_json(task_json)
        if not isinstance(spec, dict):
            continue
        rubrics_name = str(spec.get("rubrics", "rubrics.json"))
        rubrics = _read_json(entry / rubrics_name)
        rubric_count = 0
        if isinstance(rubrics, dict) and isinstance(rubrics.get("rubrics"), list):
            rubric_count = len(rubrics["rubrics"])
        packages.append(
            {
                "id": str(spec.get("id", entry.name)),
                "dir_name": entry.name,
                "name": str(spec.get("name", entry.name)),
                "rubric_count": rubric_count,
                "timeout_seconds": spec.get("timeout_seconds"),
                "allow_web_search": spec.get("allow_web_search"),
                "rigor_count": rigor_count(entry, spec),
                "has_human_reference": (entry / "human_reference.json").exists(),
            }
        )
    return packages
