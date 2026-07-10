"""Indexed raw-event pages and normalized execution timelines."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import _jsonl_index_root, _parse_iso, resolve_task_run_dir
from .jsonl import read_json_objects_page, read_nonempty_lines_page

TRACE_DEFAULT_LIMIT = 200
TRACE_MAX_LIMIT = 1000
TRACE_BODY_MAX_CHARS = 20_000
TRACE_TITLE_MAX_CHARS = 160
_CLAUDE_FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
_LIFECYCLE_EVENT_TYPES = {
    "thread.started", "turn.started", "turn.completed", "turn.failed",
    "session.created", "system", "result",
}

def raw_events(
    runs_dir: Path, run_id: str, task_run_id: str, offset: int, limit: int
) -> Dict[str, Any]:
    task_root = resolve_task_run_dir(runs_dir, run_id, task_run_id)
    offset = max(0, offset)
    limit = max(1, min(limit, 500))
    page = read_json_objects_page(
        task_root / "logs" / "events.jsonl",
        offset=offset,
        limit=limit,
        index_root=_jsonl_index_root(runs_dir),
    )
    rows = page.rows
    total = page.total
    return {
        "events": rows,
        "offset": offset,
        "total": total,
        "next_offset": offset + len(rows) if offset + len(rows) < total else None,
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

    has_events = events_path.is_file()
    page = read_nonempty_lines_page(
        events_path,
        offset=offset,
        limit=limit,
        index_root=_jsonl_index_root(runs_dir),
    )
    if not has_events:
        return {
            "run_id": run_id,
            "run_task_id": task_run_id,
            "entries": [],
            "offset": 0,
            "total": 0,
            "next_offset": None,
            "has_events": False,
        }
    lines = page.rows

    # The offset index records the first timestamp while scanning append-only
    # input, so page N does not need to replay pages 0..N-1 to derive offsets.
    epoch = _parse_iso(page.first_timestamp)

    entries: List[Dict[str, Any]] = []
    for page_index, line in enumerate(lines):
        index = offset + page_index
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        stamp = _parse_iso(event.get("timestamp")) if isinstance(event, dict) else None
        seconds_offset = (
            round((stamp - epoch).total_seconds(), 3)
            if stamp is not None and epoch is not None
            else None
        )
        entry = _normalize_trace_event(line, seconds_offset)
        entry["index"] = index
        entries.append(entry)

    total = page.total
    end = offset + len(entries)
    return {
        "run_id": run_id,
        "run_task_id": task_run_id,
        "entries": entries,
        "offset": offset,
        "total": total,
        "next_offset": end if end < total else None,
        "has_events": has_events,
    }
