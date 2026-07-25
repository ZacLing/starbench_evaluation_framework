"""Run listings, details, task history, and catalog rendering."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...domain import ACTIVE_RUN_STATES, RUN_STATE_FILENAME, TaskRunOutcome, aggregate_outcome
from .base import _parse_iso, _read_json, _read_jsonl, resolve_run_dir
from .catalog import RunCatalog
from .task_facts import _task_identity, _task_run_tested_at

RUNNING_MTIME_WINDOW_SECONDS = 120
# The supervisor refreshes heartbeat_at every ~1s while it monitors a run.
# A run_state stuck in an active state with a heartbeat this old means the
# supervisor itself is gone (crashed monitor thread, killed console): the
# claim of "running" is no longer backed by anything watching the process.
STALE_HEARTBEAT_SECONDS = 60
TASK_HISTORY_CONFIG_LIMIT = 4
_CATALOG_CONFIG_FIELDS = (
    "tasks_dir", "executor_agent", "executor_model", "evaluator_agent",
    "evaluator_model", "judge_mode", "executor_backend", "instruction_mode",
    "repeat", "seed", "thinking_effort",
)

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
    # Artifact truth outranks the launch registry: once summary.json exists the
    # run is complete even if a registry entry (or a recycled pgid) claims the
    # process group is still alive.
    if (run_root / "summary.json").exists():
        return "complete"
    if active_run_ids and run_root.name in active_run_ids:
        return "running"
    run_state = _read_json(run_root / RUN_STATE_FILENAME)
    if isinstance(run_state, dict):
        if run_state.get("state") == "completed":
            return "complete"
        if run_state.get("state") in ACTIVE_RUN_STATES:
            # Trust an active claim only while its supervisor is demonstrably
            # alive: the heartbeat is written every ~1s, so a stale one means
            # nobody is watching the process anymore and the state file can
            # never advance on its own.
            heartbeat = _parse_iso(
                run_state.get("heartbeat_at") or run_state.get("updated_at")
            )
            if heartbeat is None:
                return "interrupted"
            age = datetime.now(timezone.utc) - heartbeat
            if age.total_seconds() > STALE_HEARTBEAT_SECONDS:
                return "interrupted"
            return "running"
        return "interrupted"
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
    outcome = aggregate_outcome(aggregate)
    return {
        "outcome": outcome.value if outcome is not None else None,
        "overall_pass": aggregate.get("overall_pass"),
        "passed_count": aggregate.get("passed_count"),
        "total_count": aggregate.get("total_count"),
        "missing": len(aggregate.get("missing") or []),
        "fail_fast_failures": len(aggregate.get("fail_fast_failures") or []),
        "error": aggregate.get("error"),
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
    evaluator_stats = {"success": 0, "failed": 0, "timeout": 0, "skipped": 0}
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


def _batch_marker(run_root: Path) -> Optional[str]:
    """The launch batch recorded in run_state.json; None for bare/CLI runs."""
    run_state = _read_json(run_root / RUN_STATE_FILENAME)
    if isinstance(run_state, dict):
        batch = run_state.get("batch")
        if isinstance(batch, str) and batch:
            return batch
    return None


def _profile_marker(run_root: Path) -> Optional[Dict[str, Any]]:
    """Lightweight profile marker for a run row: ``{id, rev, modified}`` read
    from the run's ``profile_snapshot.json``. ``modified`` is True only when
    the snapshot says the launch deviated from the cited profile (an ad-hoc
    test). Missing, unreadable, or malformed snapshot -> ``None`` — one bad
    run directory must never break the whole listing."""
    snapshot = _read_json(run_root / "profile_snapshot.json")
    if not isinstance(snapshot, dict):
        return None
    profile = snapshot.get("profile")
    if not isinstance(profile, dict):
        return None
    profile_id = profile.get("id")
    rev = profile.get("rev")
    if not isinstance(profile_id, str) or not profile_id:
        return None
    if isinstance(rev, bool) or not isinstance(rev, int):
        return None
    return {
        "id": profile_id,
        "rev": rev,
        "modified": snapshot.get("modified") is True,
    }


def run_overview(run_root: Path, active_run_ids: Optional[set] = None) -> Dict[str, Any]:
    run_config = _read_json(run_root / "run_config.json")
    config = run_config if isinstance(run_config, dict) else {}
    task_ids = _task_dirs(run_root, config)
    rows = [_task_row(run_root, task_run_id) for task_run_id in task_ids]

    executor_stats = {"success": 0, "failed": 0, "timeout": 0, "pending": 0}
    judge_passes = {"single": 0, "parallel": 0}
    judge_totals = {"single": 0, "parallel": 0}
    judge_inconclusive = {"single": 0, "parallel": 0}
    for row in rows:
        state = row["executor_status"]
        if state in ("success", "failed", "timeout"):
            executor_stats[state] += 1
        else:
            executor_stats["pending"] += 1
        for mode in ("single", "parallel"):
            cell = row["judges"].get(mode)
            if cell is not None:
                if type(cell.get("overall_pass")) is bool:
                    judge_totals[mode] += 1
                if cell.get("overall_pass") is True:
                    judge_passes[mode] += 1
                if cell.get("outcome") in {
                    TaskRunOutcome.INCONCLUSIVE_JUDGE.value,
                    TaskRunOutcome.INCONCLUSIVE_EXECUTOR.value,
                    TaskRunOutcome.INVALID_TASK.value,
                }:
                    judge_inconclusive[mode] += 1

    started_at, ended_at, _ = _progress_bounds(run_root)
    return {
        "run_id": run_root.name,
        "status": run_status(run_root, active_run_ids),
        "task_count": len(rows),
        "executor_stats": executor_stats,
        "judge_passes": judge_passes,
        "judge_totals": judge_totals,
        "judge_inconclusive": judge_inconclusive,
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
        # The measurement contract this run cites, as a light marker (id/rev/
        # modified); null for bare runs and unreadable snapshots. The detail
        # view carries the full snapshot separately.
        "profile": _profile_marker(run_root),
        # Launch batch (runs launched together share it); null for bare runs.
        "batch": _batch_marker(run_root),
    }


def _catalog_run_record(run_root: Path) -> Dict[str, Any]:
    """Render all cross-run query facts once for a stable artifact signature."""

    run_config = _read_json(run_root / "run_config.json")
    config = run_config if isinstance(run_config, dict) else {}
    judge_mode = config.get("judge_mode")
    judge_mode = judge_mode if isinstance(judge_mode, str) and judge_mode else "single"
    task_samples: List[Dict[str, Any]] = []
    for task_run_id in _task_dirs(run_root, config):
        task_root = run_root / task_run_id
        row = _task_row(run_root, task_run_id)
        outcomes = [
            cell.get("outcome")
            for cell in row.get("judges", {}).values()
            if isinstance(cell, dict) and isinstance(cell.get("outcome"), str)
        ]
        # Rubric tallies from the run's own judge mode; a missing or crashed
        # judge stays None (honest absence), never a zero score.
        judge_cell = row.get("judges", {}).get(judge_mode)
        rubric_passed = judge_cell.get("passed_count") if isinstance(judge_cell, dict) else None
        rubric_total = judge_cell.get("total_count") if isinstance(judge_cell, dict) else None
        task_samples.append(
            {
                "run_task_id": task_run_id,
                "task_id": row.get("task_id"),
                "instruction_variant": row.get("instruction_variant"),
                "tested_at": _task_run_tested_at(task_root),
                "outcomes": outcomes,
                "executor_status": row.get("executor_status"),
                "executor_duration_seconds": row.get("executor_duration_seconds"),
                "rubric_passed": rubric_passed if isinstance(rubric_passed, int) else None,
                "rubric_total": rubric_total if isinstance(rubric_total, int) else None,
            }
        )
    return {
        "overview": run_overview(run_root),
        "config": {key: config.get(key) for key in _CATALOG_CONFIG_FIELDS},
        "tasks": task_samples,
    }


def _catalog_records(runs_dir: Path) -> List[Dict[str, Any]]:
    return [
        {
            "run_id": record.run_id,
            "sort_mtime_ns": record.sort_mtime_ns,
            **record.value,
        }
        for record in RunCatalog(runs_dir).records(_catalog_run_record)
    ]


def list_runs(runs_dir: Path, active_run_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for record in _catalog_records(runs_dir):
        overview = record.get("overview")
        if not isinstance(overview, dict):
            continue
        rendered = dict(overview)
        # Status is time-dependent (the mtime window decays, run_state can go
        # stale) but the catalog signature only tracks file stats, so a cached
        # "running" would freeze forever on a dead run. Always rederive status
        # against the live tree; everything else in the record is artifact-
        # stable and safe to serve from cache.
        rendered["status"] = run_status(runs_dir / record["run_id"], active_run_ids)
        rows.append(rendered)
    return rows


def _matches_tasks_dir(config: Dict[str, Any], tasks_dir: Optional[Path]) -> bool:
    if tasks_dir is None:
        return True
    recorded = config.get("tasks_dir")
    if not isinstance(recorded, str) or not recorded.strip():
        # Older/corrupt run configs can still be attributed by task id.
        return True
    try:
        return Path(recorded).expanduser().resolve() == tasks_dir.expanduser().resolve()
    except OSError:
        return recorded == str(tasks_dir)


def _history_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "executor_agent": config.get("executor_agent"),
        "executor_model": config.get("executor_model"),
        "evaluator_agent": config.get("evaluator_agent"),
        "evaluator_model": config.get("evaluator_model"),
        "judge_mode": config.get("judge_mode"),
        "executor_backend": config.get("executor_backend"),
        "instruction_mode": config.get("instruction_mode"),
        "repeat": config.get("repeat"),
        "seed": config.get("seed"),
        "thinking_effort": config.get("thinking_effort"),
    }


def _history_config_key(config: Dict[str, Any]) -> Tuple[Any, ...]:
    shaped = _history_config(config)
    return tuple(shaped.get(key) for key in sorted(shaped))


def task_history(runs_dir: Path, tasks_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Per-task execution history for the New experiment task picker.

    This is intentionally narrower than the coverage matrix: it answers
    "has this task been tested, how many executions, and under which launch
    configs?" from artifacts already on disk. Missing identities are skipped
    rather than guessed from directory names.
    """
    histories: Dict[str, Dict[str, Any]] = {}
    config_buckets: Dict[str, Dict[Tuple[Any, ...], Dict[str, Any]]] = {}

    if not runs_dir.is_dir():
        return {"tasks": {}}

    for record in _catalog_records(runs_dir):
        config = record.get("config")
        config = config if isinstance(config, dict) else {}
        if not _matches_tasks_dir(config, tasks_dir):
            continue
        config_shape = _history_config(config)
        config_key = _history_config_key(config)

        task_samples = record.get("tasks")
        task_samples = task_samples if isinstance(task_samples, list) else []
        for sample in task_samples:
            if not isinstance(sample, dict):
                continue
            task_id = sample.get("task_id")
            if not isinstance(task_id, str) or not task_id:
                continue
            tested_at = sample.get("tested_at")
            tested_at = tested_at if isinstance(tested_at, str) else None
            parsed_at = _parse_iso(tested_at)

            history = histories.setdefault(
                task_id,
                {
                    "task_id": task_id,
                    "run_ids": set(),
                    "task_run_count": 0,
                    "last_tested": None,
                    "_last_parsed": None,
                },
            )
            history["run_ids"].add(record["run_id"])
            history["task_run_count"] += 1
            if parsed_at is not None and (
                history["_last_parsed"] is None or parsed_at > history["_last_parsed"]
            ):
                history["_last_parsed"] = parsed_at
                history["last_tested"] = tested_at

            bucket = config_buckets.setdefault(task_id, {}).setdefault(
                config_key,
                {
                    **config_shape,
                    "run_ids": set(),
                    "task_run_count": 0,
                    "last_tested": None,
                    "_last_parsed": None,
                },
            )
            bucket["run_ids"].add(record["run_id"])
            bucket["task_run_count"] += 1
            if parsed_at is not None and (
                bucket["_last_parsed"] is None or parsed_at > bucket["_last_parsed"]
            ):
                bucket["_last_parsed"] = parsed_at
                bucket["last_tested"] = tested_at

    payload: Dict[str, Any] = {}
    epoch_floor = datetime.min.replace(tzinfo=timezone.utc)
    for task_id, history in histories.items():
        configs = list(config_buckets.get(task_id, {}).values())
        configs.sort(
            key=lambda row: row.get("_last_parsed") or epoch_floor,
            reverse=True,
        )
        rendered_configs: List[Dict[str, Any]] = []
        for row in configs[:TASK_HISTORY_CONFIG_LIMIT]:
            rendered = {key: value for key, value in row.items() if not key.startswith("_")}
            run_ids = rendered.pop("run_ids")
            rendered["run_count"] = len(run_ids)
            rendered_configs.append(rendered)

        payload[task_id] = {
            "task_id": task_id,
            "run_count": len(history["run_ids"]),
            "task_run_count": history["task_run_count"],
            "last_tested": history["last_tested"],
            "configs": rendered_configs,
        }
    return {"tasks": payload}


def run_detail(runs_dir: Path, run_id: str, active_run_ids: Optional[set] = None) -> Dict[str, Any]:
    run_root = resolve_run_dir(runs_dir, run_id)
    run_config = _read_json(run_root / "run_config.json")
    config = run_config if isinstance(run_config, dict) else {}
    task_ids = _task_dirs(run_root, config)
    overview = run_overview(run_root, active_run_ids)
    # The measurement contract this run was launched under (written by the
    # runner from --profile-snapshot). Absent for bare runs — null, honestly.
    profile_snapshot = _read_json(run_root / "profile_snapshot.json")
    interruption = None
    if overview.get("status") == "interrupted":
        # The honest story of how the run stopped: the last progress event,
        # whether the run ever marked itself finished, and whatever the
        # supervisor's run_state.json still says (usually nothing — the file
        # rarely survives the exit that interrupted the run).
        _, last_event_at, progress_finished = _progress_bounds(run_root)
        run_state = _read_json(run_root / RUN_STATE_FILENAME)
        supervision = None
        if isinstance(run_state, dict):
            state = run_state.get("state")
            heartbeat = run_state.get("heartbeat_at") or run_state.get("updated_at")
            supervision = {
                "state": state if isinstance(state, str) else None,
                "heartbeat_at": heartbeat if isinstance(heartbeat, str) else None,
            }
        interruption = {
            "last_event_at": last_event_at,
            "progress_finished": progress_finished,
            "supervision": supervision,
        }
    detail = {
        **overview,
        "config": config or None,
        "profile_snapshot": profile_snapshot if isinstance(profile_snapshot, dict) else None,
        "tasks": [_task_row(run_root, task_run_id) for task_run_id in task_ids],
        "progress": progress_snapshot(run_root),
        "ablation": _read_json(run_root / "instruction_ablation_summary.json"),
        "interruption": interruption,
    }
    return detail
