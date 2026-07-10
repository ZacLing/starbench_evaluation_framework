"""Live run lanes derived from bounded progress and event tails."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import SAFE_ID, _parse_iso, _read_json, _read_jsonl, _tail_jsonl, resolve_run_dir
from .runs import _task_dirs, run_overview, run_status

LIVE_EVENT_TAIL_LIMIT = 20
LIVE_SUMMARY_MAX_CHARS = 200

def _clip_line(text: Any) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) > LIVE_SUMMARY_MAX_CHARS:
        return collapsed[: LIVE_SUMMARY_MAX_CHARS - 1] + "…"
    return collapsed


def _live_event_summary(event: Dict[str, Any]) -> Dict[str, str]:
    """Reduce one raw task event to ``{type, summary}`` — never the raw payload.

    Handles the normalized Codex-style compat shape (``item.completed`` with an
    ``item`` dict) plus the raw Claude stream-json shape that precedes compat
    normalization during a live run; anything else degrades to a generic
    one-line text probe. Excerpts are single-line and capped at
    ``LIVE_SUMMARY_MAX_CHARS`` characters.
    """
    event_type = str(event.get("type", "unknown"))

    item = event.get("item")
    if isinstance(item, dict):
        item_type = str(item.get("type", "unknown"))
        if item_type == "command_execution":
            text = item.get("command") or item.get("aggregated_output") or ""
        elif item_type == "file_change":
            changes = item.get("changes")
            paths = (
                [str(c.get("path")) for c in changes if isinstance(c, dict) and c.get("path")]
                if isinstance(changes, list)
                else []
            )
            text = ", ".join(paths)
        else:
            text = item.get("text") or item.get("summary") or item.get("content") or ""
        return {"type": item_type, "summary": _clip_line(text)}

    if event_type == "turn.completed":
        usage = event.get("usage")
        if isinstance(usage, dict):
            bits = [
                f"{key}={usage[key]}"
                for key in ("input_tokens", "output_tokens")
                if isinstance(usage.get(key), (int, float))
            ]
            return {"type": event_type, "summary": _clip_line(" ".join(bits))}
        return {"type": event_type, "summary": ""}

    if event_type in ("assistant", "user"):
        # Raw Claude stream-json: excerpt the message content blocks.
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        bits: List[str] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text" and block.get("text"):
                    bits.append(str(block["text"]))
                elif block_type == "thinking" and block.get("thinking"):
                    bits.append(str(block["thinking"]))
                elif block_type == "tool_use":
                    bits.append(f"{block.get('name') or 'tool'}(…)")
                elif block_type == "tool_result":
                    bits.append("tool_result")
        return {"type": event_type, "summary": _clip_line(" ".join(bits))}

    for key in ("text", "summary", "message", "error", "thread_id"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return {"type": event_type, "summary": _clip_line(value)}
    return {"type": event_type, "summary": ""}


def _live_task_order(run_root: Path, config: Dict[str, Any]) -> List[str]:
    """Planned task order plus any on-disk task dirs the config missed.

    Unlike ``_task_dirs`` this keeps planned tasks whose directory does not
    exist yet — those are the pending lanes. Names that fail ``SAFE_ID`` are
    dropped entirely: the runner never generates them and they must not drive
    filesystem reads.
    """
    ordered: List[str] = []
    if isinstance(config.get("task_order"), list):
        ordered = [
            item
            for item in config["task_order"]
            if isinstance(item, str) and SAFE_ID.match(item)
        ]
    try:
        existing = {
            entry.name
            for entry in run_root.iterdir()
            if entry.is_dir() and (entry / "logs").is_dir() and SAFE_ID.match(entry.name)
        }
    except OSError:
        existing = set()
    return ordered + sorted(existing - set(ordered))


def run_live(runs_dir: Path, run_id: str, active_run_ids: Optional[set] = None) -> Dict[str, Any]:
    """Assemble the live progress view for one run, from files only.

    Per-task lane states are derived from ``progress_events.jsonl`` plus each
    task's ``logs/status.json`` / ``task_summary.json``; the currently executing
    task additionally gets a summarized tail of its ``logs/events.jsonl``. The
    ETA is an estimate (average measured executor duration × remaining tasks)
    and is ``None`` until at least two tasks have finished — too few samples is
    reported as "unknown", never invented.
    """
    run_root = resolve_run_dir(runs_dir, run_id)
    run_config = _read_json(run_root / "run_config.json")
    config = run_config if isinstance(run_config, dict) else {}
    now = datetime.now(timezone.utc)

    started: Dict[str, Optional[datetime]] = {}
    started_order: List[str] = []
    finished: Dict[str, Dict[str, Any]] = {}
    for event in _read_jsonl(run_root / "progress_events.jsonl"):
        kind = event.get("event")
        run_task_id = event.get("run_task_id")
        if not isinstance(run_task_id, str):
            continue
        if kind == "executor_started":
            started[run_task_id] = _parse_iso(event.get("timestamp"))
            started_order.append(run_task_id)
        elif kind == "executor_finished":
            finished[run_task_id] = event

    tasks: List[Dict[str, Any]] = []
    lanes_by_id: Dict[str, Dict[str, Any]] = {}
    durations: List[float] = []
    for name in _live_task_order(run_root, config):
        task_root = run_root / name
        status = _read_json(task_root / "logs" / "status.json")
        status = status if isinstance(status, dict) else None
        progress_finish = finished.get(name)

        executor_status: Optional[str] = None
        measured: Optional[float] = None
        if status is not None:
            executor_status = status.get("status")
            if isinstance(status.get("duration_seconds"), (int, float)):
                measured = float(status["duration_seconds"])
        if executor_status is None and progress_finish is not None:
            executor_status = progress_finish.get("status")
        if measured is None and progress_finish is not None:
            if isinstance(progress_finish.get("duration_seconds"), (int, float)):
                measured = float(progress_finish["duration_seconds"])

        executor_done = status is not None or progress_finish is not None
        seconds: Optional[float] = None
        source: Optional[str] = None
        if executor_done:
            if measured is not None:
                seconds = measured
                source = "measured"
                durations.append(measured)
            if executor_status in ("failed", "timeout"):
                state = "failed"
            elif (task_root / "task_summary.json").is_file():
                state = "done"
            else:
                state = "judging"
        elif name in started:
            state = "executing"
            started_at = started[name]
            if started_at is not None:
                seconds = max(0.0, round((now - started_at).total_seconds(), 1))
                source = "elapsed"
        else:
            state = "pending"

        lane = {
            "run_task_id": name,
            "state": state,
            "executor_status": executor_status,
            "executor_seconds": seconds,
            "executor_seconds_source": source,
        }
        tasks.append(lane)
        lanes_by_id[name] = lane

    current: Optional[Dict[str, Any]] = None
    for name in reversed(started_order):
        lane = lanes_by_id.get(name)
        if lane is None or lane["state"] != "executing":
            continue
        task_root = run_root / name
        manifest = _read_json(task_root / "manifest.json")
        started_at = started.get(name)
        current = {
            "run_task_id": name,
            "task_id": manifest.get("task_id") if isinstance(manifest, dict) else None,
            "started_at": started_at.isoformat() if started_at is not None else None,
            "elapsed_seconds": lane["executor_seconds"] if lane["executor_seconds_source"] == "elapsed" else None,
            "events": [
                _live_event_summary(event)
                for event in _tail_jsonl(task_root / "logs" / "events.jsonl", LIVE_EVENT_TAIL_LIMIT)
            ],
        }
        break

    remaining = sum(1 for lane in tasks if lane["state"] in ("pending", "executing"))
    sample_count = len(durations)
    average = round(sum(durations) / sample_count, 1) if sample_count else None
    estimate: Optional[float] = None
    if sample_count >= 2 and average is not None:
        estimate = round(average * remaining, 1)

    return {
        "run_id": run_root.name,
        "status": run_status(run_root, active_run_ids),
        "generated_at": now.isoformat(),
        "tasks": tasks,
        "current": current,
        "eta": {
            "estimated_remaining_seconds": estimate,
            "average_executor_seconds": average,
            "completed_sample_count": sample_count,
            "remaining_task_count": remaining,
        },
    }
