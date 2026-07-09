"""Read-only views over a StarBench runs directory.

Every function here renders what exists on disk and nothing else. Missing
files become ``None`` fields, never exceptions, so the console can show an
honest partial picture of interrupted or in-flight runs.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

RUNNING_MTIME_WINDOW_SECONDS = 120

STDERR_TAIL_BYTES = 64_000
FINAL_MD_MAX_BYTES = 512_000

# Live view: how many trailing task events we summarize, how far back into the
# file we read to find them, and how long a one-line excerpt may get.
LIVE_EVENT_TAIL_LIMIT = 20
LIVE_TAIL_MAX_BYTES = 256_000
LIVE_SUMMARY_MAX_CHARS = 200

# Trace replay: normalized timeline entries built from logs/events.jsonl.
TRACE_DEFAULT_LIMIT = 200
TRACE_MAX_LIMIT = 1000
TRACE_BODY_MAX_CHARS = 20_000
TRACE_TITLE_MAX_CHARS = 160

# Deliverable reader: a single file under workspace/outputs/.
ARTIFACT_MAX_BYTES = 1_000_000
ARTIFACT_BINARY_SNIFF_BYTES = 8_192


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
    # The measurement contract this run was launched under (written by the
    # runner from --profile-snapshot). Absent for bare runs — null, honestly.
    profile_snapshot = _read_json(run_root / "profile_snapshot.json")
    detail = {
        **overview,
        "config": config or None,
        "profile_snapshot": profile_snapshot if isinstance(profile_snapshot, dict) else None,
        "tasks": [_task_row(run_root, task_run_id) for task_run_id in task_ids],
        "progress": progress_snapshot(run_root),
        "ablation": _read_json(run_root / "instruction_ablation_summary.json"),
    }
    return detail


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


def _variant_group(
    run_root: Path, config: Dict[str, Any], base_task_id: Optional[str]
) -> List[Dict[str, Any]]:
    """All task runs in this run that share one base task (ablation variants
    and repeats), in run order. Identity comes from each sibling's recorded
    ``task_summary.json``/``manifest.json``, never from parsing directory names.
    An unknown base task id yields an empty list — no siblings can be derived.
    """
    if not base_task_id:
        return []
    rows: List[Dict[str, Any]] = []
    for name in _task_dirs(run_root, config):
        sibling_task_id, sibling_variant, evaluated = _task_identity(run_root / name)
        if sibling_task_id != base_task_id:
            continue
        rows.append(
            {
                "run_task_id": name,
                "instruction_variant": sibling_variant,
                "evaluated": evaluated,
            }
        )
    return rows


# Fallback listing is capped so a stray vendored env cannot balloon the payload.
OUTPUTS_LISTING_MAX_ENTRIES = 500


def _outputs_listing(task_root: Path) -> Optional[Dict[str, Any]]:
    """Direct listing of ``workspace/outputs/`` for runs missing the manifest.

    One honesty level below ``artifact_manifest.json`` (no hashes, taken now
    rather than at run end) but never a lie: it shows what is actually on disk.
    """
    outputs = task_root / "workspace" / "outputs"
    if not outputs.is_dir():
        return None
    entries: List[Dict[str, Any]] = []
    truncated = False
    try:
        for path in sorted(outputs.rglob("*")):
            if len(entries) >= OUTPUTS_LISTING_MAX_ENTRIES:
                truncated = True
                break
            relative = path.relative_to(outputs).as_posix()
            if path.is_dir():
                entries.append({"path": relative, "kind": "directory"})
            elif path.is_file():
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                entries.append({"path": relative, "kind": "file", "size_bytes": size})
    except OSError:
        return None
    return {
        "outputs_dir": str(outputs),
        "file_count": sum(1 for item in entries if item["kind"] == "file"),
        "entries": entries,
        "truncated": truncated,
    }


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
        with events_path.open(encoding="utf-8") as events_file:
            raw_event_count = sum(1 for line in events_file if line.strip())
    except OSError:
        raw_event_count = 0

    rubric_questions: Dict[str, str] = {}
    manifest = _read_json(task_root / "manifest.json")
    if isinstance(manifest, dict):
        for rubric in manifest.get("rubrics") or []:
            if isinstance(rubric, dict) and rubric.get("id"):
                rubric_questions[str(rubric["id"])] = str(rubric.get("question", ""))

    task_id, instruction_variant, _ = _task_identity(task_root)
    run_config = _read_json(task_root.parent / "run_config.json")
    config = run_config if isinstance(run_config, dict) else {}
    artifact_manifest = _read_json(logs / "artifact_manifest.json")

    return {
        "run_id": run_id,
        "run_task_id": task_run_id,
        "task_id": task_id,
        "instruction_variant": instruction_variant,
        "instruction_steps": summary.get("instruction_steps"),
        "executor": summary.get("executor") or _read_json(logs / "status.json"),
        "executor_timing": summary.get("executor_timing"),
        "judges": judges,
        "rubric_questions": rubric_questions,
        "trace_summary": _read_json(logs / "trace_summary.json"),
        "artifact_manifest": artifact_manifest,
        # Honest fallback for the Deliverables tree when the manifest is
        # missing: list what is actually in workspace/outputs/ right now.
        "outputs_listing": None if artifact_manifest is not None else _outputs_listing(task_root),
        "variant_group": _variant_group(task_root.parent, config, task_id),
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


# ---------------------------------------------------------------------------
# Trace replay (/api/runs/<id>/tasks/<tid>/trace)
# ---------------------------------------------------------------------------

# Claude tools that the compat layer treats as file changes; mirrored here for
# the raw stream-json events that precede compat normalization.
_CLAUDE_FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# Compat/lifecycle event types that are session plumbing, not agent work.
_LIFECYCLE_EVENT_TYPES = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "session.created",
    "system",
    "result",
}


def _trace_title(text: Any) -> str:
    collapsed = " ".join(str(text).split())
    if len(collapsed) > TRACE_TITLE_MAX_CHARS:
        return collapsed[: TRACE_TITLE_MAX_CHARS - 1] + "…"
    return collapsed


def _trace_entry(
    entry_type: str, title: str, body: str, seconds_offset: Optional[float] = None
) -> Dict[str, Any]:
    truncated = len(body) > TRACE_BODY_MAX_CHARS
    if truncated:
        body = body[:TRACE_BODY_MAX_CHARS]
    return {
        "type": entry_type,
        "title": title,
        "body": body,
        "seconds_offset": seconds_offset,
        "truncated": truncated,
    }


def _compat_item_entry(event_type: str, item: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one compat-shape event (Codex native or adapter-appended)."""
    item_type = str(item.get("type", "unknown"))
    if event_type != "item.completed":
        # item.started / item.updated are progress plumbing; the completed
        # event carries the full payload and becomes the real card.
        excerpt = item.get("command") or item.get("text") or ""
        title = f"{event_type} · {item_type}"
        if excerpt:
            title += f": {_trace_title(excerpt)}"
        return _trace_entry("lifecycle", _trace_title(title), _raw_json_body(event))
    if item_type == "command_execution":
        command = str(item.get("command") or "")
        bits = []
        if item.get("exit_code") is not None:
            bits.append(f"exit {item['exit_code']}")
        if item.get("status"):
            bits.append(str(item["status"]))
        header = " · ".join(bits)
        output = item.get("aggregated_output")
        body = f"$ {command}"
        if header:
            body += f"\n[{header}]"
        if isinstance(output, str) and output:
            body += f"\n\n{output}"
        return _trace_entry("command", _trace_title(command), body)
    if item_type == "reasoning":
        text = str(item.get("text") or item.get("summary") or item.get("content") or "")
        return _trace_entry("reasoning", _trace_title(text), text)
    if item_type == "agent_message":
        text = str(item.get("text") or "")
        return _trace_entry("message", _trace_title(text), text)
    if item_type == "file_change":
        changes = item.get("changes")
        paths = (
            [str(c.get("path")) for c in changes if isinstance(c, dict) and c.get("path")]
            if isinstance(changes, list)
            else []
        )
        title = ", ".join(paths) if paths else "file change"
        status = item.get("status")
        body = title if not status else f"{title}\n[{status}]"
        return _trace_entry("file_change", _trace_title(title), body)
    return _trace_entry("other", f"item.completed · {item_type}", _raw_json_body(event))


def _raw_json_body(event: Any) -> str:
    try:
        return json.dumps(event, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(event)


def _claude_assistant_entry(event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Claude stream-json assistant event (pre-compat shape)."""
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return _trace_entry("other", "assistant", _raw_json_body(event))
    sections: List[str] = []
    texts: List[str] = []
    thinkings: List[str] = []
    bash_commands: List[str] = []
    file_paths: List[str] = []
    tool_names: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and block.get("text"):
            texts.append(str(block["text"]))
            sections.append(str(block["text"]))
        elif block_type == "thinking" and block.get("thinking"):
            thinkings.append(str(block["thinking"]))
            sections.append(f"[thinking]\n{block['thinking']}")
        elif block_type == "tool_use":
            name = str(block.get("name") or "tool")
            tool_names.append(name)
            input_data = block.get("input")
            input_data = input_data if isinstance(input_data, dict) else {}
            if name == "Bash" and input_data.get("command"):
                bash_commands.append(str(input_data["command"]))
                sections.append(f"$ {input_data['command']}")
            elif name in _CLAUDE_FILE_TOOLS:
                path = input_data.get("file_path") or input_data.get("notebook_path")
                if path:
                    file_paths.append(str(path))
                sections.append(f"[{name}] {path or ''}".rstrip())
            else:
                sections.append(f"[{name}] {_raw_json_body(input_data)}")
    body = "\n\n".join(sections)
    if bash_commands:
        return _trace_entry("command", _trace_title(bash_commands[0]), body)
    if file_paths or (tool_names and set(tool_names) <= _CLAUDE_FILE_TOOLS):
        return _trace_entry("file_change", _trace_title(", ".join(file_paths) or "file change"), body)
    if tool_names:
        return _trace_entry("command", _trace_title(f"{tool_names[0]}(…)"), body)
    if texts:
        return _trace_entry("message", _trace_title(texts[0]), body)
    if thinkings:
        return _trace_entry("reasoning", _trace_title(thinkings[0]), body)
    return _trace_entry("other", "assistant", _raw_json_body(event))


def _claude_user_entry(event: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw Claude stream-json user event (tool results)."""
    message = event.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return _trace_entry("other", "user", _raw_json_body(event))
    parts: List[str] = []
    is_error = False
    saw_tool_result = False
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            saw_tool_result = True
            is_error = is_error or bool(block.get("is_error"))
            block_content = block.get("content")
            if isinstance(block_content, str):
                parts.append(block_content)
            elif isinstance(block_content, list):
                parts.extend(
                    str(piece.get("text", ""))
                    for piece in block_content
                    if isinstance(piece, dict) and piece.get("type") == "text"
                )
        elif block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    if not saw_tool_result and not parts:
        return _trace_entry("other", "user", _raw_json_body(event))
    title = "tool result (error)" if is_error else "tool result"
    if not saw_tool_result:
        title = "user message"
    return _trace_entry("command" if saw_tool_result else "message", title, "\n\n".join(parts))


def _normalize_trace_event(line: str, seconds_offset: Optional[float]) -> Dict[str, Any]:
    """One events.jsonl line → one timeline entry. Never drops or invents.

    Handles the normalized compat shape (Codex native plus the compat events
    the other adapters append) and the raw Claude stream-json shape that
    precedes compat normalization. Anything unrecognized — including
    unparseable lines — degrades to ``type: "other"`` carrying the raw text.
    """
    try:
        event = json.loads(line)
    except ValueError:
        event = None
    if not isinstance(event, dict):
        return _trace_entry("other", "unparseable event line", line, seconds_offset)

    event_type = str(event.get("type", "unknown"))
    item = event.get("item")
    if isinstance(item, dict):
        entry = _compat_item_entry(event_type, item, event)
    elif event_type == "assistant":
        entry = _claude_assistant_entry(event)
    elif event_type == "user":
        entry = _claude_user_entry(event)
    elif event_type in _LIFECYCLE_EVENT_TYPES:
        bits = [event_type]
        for key in ("subtype", "thread_id", "session_id", "model"):
            value = event.get(key)
            if isinstance(value, str) and value:
                bits.append(value)
                break
        usage = event.get("usage")
        if isinstance(usage, dict):
            tokens = [
                f"{key}={usage[key]}"
                for key in ("input_tokens", "output_tokens")
                if isinstance(usage.get(key), (int, float))
            ]
            bits.extend(tokens)
        entry = _trace_entry("lifecycle", _trace_title(" · ".join(bits)), _raw_json_body(event))
    else:
        entry = _trace_entry("other", event_type, _raw_json_body(event))
    entry["seconds_offset"] = seconds_offset
    return entry


def task_trace(
    runs_dir: Path, run_id: str, task_run_id: str, offset: int, limit: int
) -> Dict[str, Any]:
    """Normalized execution timeline for one task run, paginated.

    Every physical line of ``logs/events.jsonl`` becomes exactly one entry, in
    file order, so entry indexes are stable anchors and always line up with the
    raw-events pagination. ``seconds_offset`` is only filled when events carry
    parseable timestamps (most runtimes do not emit them — absent is reported
    as ``null``, never estimated).
    """
    task_root = resolve_task_run_dir(runs_dir, run_id, task_run_id)
    events_path = task_root / "logs" / "events.jsonl"
    offset = max(0, offset)
    limit = max(1, min(limit, TRACE_MAX_LIMIT))

    try:
        raw_lines = events_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {
            "run_id": run_id,
            "run_task_id": task_run_id,
            "entries": [],
            "offset": 0,
            "total": 0,
            "next_offset": None,
            "has_events": False,
        }
    lines = [line for line in raw_lines if line.strip()]

    # First parseable timestamp anchors seconds_offset for the whole file.
    epoch: Optional[datetime] = None
    stamps: Dict[int, datetime] = {}
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            stamp = _parse_iso(row.get("timestamp"))
            if stamp is not None:
                stamps[index] = stamp
                if epoch is None:
                    epoch = stamp

    entries: List[Dict[str, Any]] = []
    for index in range(offset, min(offset + limit, len(lines))):
        stamp = stamps.get(index)
        seconds_offset = (
            round((stamp - epoch).total_seconds(), 3)
            if stamp is not None and epoch is not None
            else None
        )
        entry = _normalize_trace_event(lines[index], seconds_offset)
        entry["index"] = index
        entries.append(entry)

    total = len(lines)
    end = offset + len(entries)
    return {
        "run_id": run_id,
        "run_task_id": task_run_id,
        "entries": entries,
        "offset": offset,
        "total": total,
        "next_offset": end if end < total else None,
        "has_events": True,
    }


# ---------------------------------------------------------------------------
# Deliverable reader (/api/runs/<id>/tasks/<tid>/artifact?path=...)
# ---------------------------------------------------------------------------


def read_artifact(runs_dir: Path, run_id: str, task_run_id: str, rel_path: str) -> Dict[str, Any]:
    """Read one delivered file under ``workspace/outputs/``.

    Security: the requested path must resolve (symlinks followed) to a file
    inside the outputs directory — ``..`` segments, absolute paths and symlink
    escapes are all rejected with NotFound. Content policy: files over
    ``ARTIFACT_MAX_BYTES`` return metadata only; files whose head contains a
    NUL byte are reported binary and never decoded.
    """
    task_root = resolve_task_run_dir(runs_dir, run_id, task_run_id)
    outputs = (task_root / "workspace" / "outputs").resolve()
    if not outputs.is_dir():
        raise NotFound(f"No outputs directory for task run: {task_run_id!r}")
    if not rel_path or Path(rel_path).is_absolute():
        raise NotFound(f"Invalid artifact path: {rel_path!r}")
    target = (outputs / rel_path).resolve()
    try:
        relative = target.relative_to(outputs)
    except ValueError:
        raise NotFound(f"Artifact outside outputs directory: {rel_path!r}")
    if not target.is_file():
        raise NotFound(f"No such artifact: {rel_path!r}")

    try:
        size = target.stat().st_size
        with target.open("rb") as handle:
            head = handle.read(ARTIFACT_BINARY_SNIFF_BYTES)
            is_binary = b"\x00" in head
            content: Optional[str] = None
            truncated = False
            if is_binary:
                pass
            elif size > ARTIFACT_MAX_BYTES:
                truncated = True
            else:
                data = head + handle.read()
                content = data.decode("utf-8", errors="replace")
    except OSError as error:
        raise NotFound(f"Artifact unreadable: {rel_path!r} ({error})")

    return {
        "path": relative.as_posix(),
        "size_bytes": size,
        "is_binary": is_binary,
        "truncated": truncated,
        "content": content,
    }


# ---------------------------------------------------------------------------
# Run live view (/api/runs/<id>/live)
# ---------------------------------------------------------------------------


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
            # A folder that claims to be a task package but cannot be parsed is
            # rendered as an honest broken entry, never silently dropped: the
            # operator must be able to see why a task on disk is not runnable.
            packages.append(
                {
                    "id": entry.name,
                    "dir_name": entry.name,
                    "name": entry.name,
                    "rubric_count": 0,
                    "timeout_seconds": None,
                    "allow_web_search": None,
                    "rigor_count": 0,
                    "has_human_reference": False,
                    "error": "task.json is missing required fields or is not valid JSON",
                    "warning": None,
                }
            )
            continue
        rubrics_name = str(spec.get("rubrics", "rubrics.json"))
        rubrics = _read_json(entry / rubrics_name)
        rubric_count = 0
        if isinstance(rubrics, dict) and isinstance(rubrics.get("rubrics"), list):
            rubric_count = len(rubrics["rubrics"])
        prompt_name = str(spec.get("prompt", "prompt.md"))
        error = None
        warning = None
        if not (entry / prompt_name).exists():
            error = f"prompt file `{prompt_name}` is missing"
        elif rubric_count == 0:
            warning = f"`{rubrics_name}` is missing, invalid, or has no rubrics"
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
                "error": error,
                "warning": warning,
            }
        )
    return packages


# ---------------------------------------------------------------------------
# Coverage matrix (/api/coverage)
# ---------------------------------------------------------------------------

# How many task-run references each coverage cell keeps for UI drill-down.
COVERAGE_RECENT_REFS_LIMIT = 5


def _overall_passes(task_root: Path) -> List[Any]:
    """Every judge-aggregate ``overall_pass`` recorded for one task run.

    Mirrors ``_task_row``'s judge reading: ``task_summary.json`` is
    authoritative once the judge has run; before that the standalone aggregate
    files under ``judges/`` are consulted. Nothing on disk yields an empty
    list — never an invented verdict.
    """
    summary = _read_json(task_root / "task_summary.json")
    values: List[Any] = []
    if isinstance(summary, dict) and isinstance(summary.get("judges"), dict):
        for payload in summary["judges"].values():
            aggregate = payload.get("aggregate") if isinstance(payload, dict) else None
            if isinstance(aggregate, dict):
                values.append(aggregate.get("overall_pass"))
        return values
    for mode in ("single", "parallel"):
        aggregate = _read_json(task_root / "judges" / f"{mode}_aggregate.json")
        if isinstance(aggregate, dict):
            values.append(aggregate.get("overall_pass"))
    return values


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


def coverage(runs_dir: Path, tasks_dirs: Sequence[Path]) -> Dict[str, Any]:
    """Task × executor-config coverage matrix over everything on disk.

    Rows are the union of the task library (``tasks_dirs``) and every task id
    observed in ``runs_dir``; columns are the executor configs observed in run
    configs (``executor_agent`` × ``executor_model``). HSW semantics: a cell
    with any ``overall_pass == True`` means the task was breached, so variants
    and repeats all aggregate into the same cell. Library tasks never run
    render as zero-cell rows — the visible gaps are the point. A corrupted run
    directory degrades to an "unknown" column (or is skipped mid-scan); it
    never sinks the payload.
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

    run_roots: List[Path] = []
    if runs_dir.is_dir():
        run_roots = sorted(
            (
                entry
                for entry in runs_dir.iterdir()
                if entry.is_dir()
                and (
                    (entry / "run_config.json").exists()
                    or (entry / "summary.json").exists()
                    or (entry / "progress_events.jsonl").exists()
                )
            ),
            key=lambda entry: entry.name,
        )

    for run_root in run_roots:
        runs_scanned += 1
        try:
            run_config = _read_json(run_root / "run_config.json")
            config = run_config if isinstance(run_config, dict) else {}
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
            for name in _task_dirs(run_root, config):
                task_root = run_root / name
                task_id, _, _ = _task_identity(task_root)
                if not isinstance(task_id, str) or not task_id:
                    # No recorded identity: this task run cannot be attributed
                    # to a matrix row. Skipped, never guessed from the dir name.
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
                        "last_tested": None,
                        "recent_refs": [],
                    },
                )
                cell["total"] += 1
                passes = _overall_passes(task_root)
                if any(value is not None for value in passes):
                    cell["judged"] += 1
                if any(value is True for value in passes):
                    cell["passed"] += 1
                tested_at = _task_run_tested_at(task_root)
                cell_refs.setdefault(cell_key, []).append(
                    (
                        _parse_iso(tested_at),
                        tested_at,
                        {"run_id": run_root.name, "run_task_id": name},
                    )
                )
        except OSError:
            # A run directory that vanishes or errors mid-scan keeps whatever
            # was read before the failure; the payload survives.
            continue

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

    column_order = sorted(
        columns.values(), key=lambda col: (col["agent"], col["model"] or "")
    )
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
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
