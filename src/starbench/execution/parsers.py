"""Output parsers: turn raw agent stdout into ``final.md`` and comparable events.

Runtime-agnostic in the sense that these functions key off an *output format*
(headless-json, jsonl-events, plain text, Claude stream-json, OpenCode export,
pi JSON events)
rather than a runtime name — several runtimes share a format. Adapters pick the
right parser for their runtime and call these helpers.

Two jobs:
- ``write_*_final_output`` extract the final deliverable text (optionally
  coerced to the evaluator JSON schema) and write ``final.md`` / result JSON.
- ``append_*_compat_events`` / ``normalize_*`` rewrite the event log into the
  Codex-style ``item.completed`` shape so ``trace_summary.json`` is comparable
  across runtimes.

Invariant: a runtime that exits 0 can still have failed (e.g. Claude "Not
logged in"); ``_raise_on_claude_error_result`` and the JSON extractors raise so
the caller can downgrade the run instead of grading empty output.

To add/adjust an output format, edit this file; then point the owning adapter's
finalize step at the new helper.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .process import split_command


def _extract_claude_payload(stdout_path: Path) -> Dict[str, Any]:
    data = json.loads(stdout_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Claude output was not a JSON object")
    _raise_on_claude_error_result(data)
    return data


def _raise_on_claude_error_result(result_event: Dict[str, Any]) -> None:
    # Claude Code can exit 0 while reporting a failed run (e.g. "Not logged
    # in"). Treat is_error results as failures instead of grading them.
    if result_event.get("is_error"):
        result_text = result_event.get("result")
        detail = result_text if isinstance(result_text, str) and result_text else result_event.get("subtype", "unknown error")
        raise ValueError(f"Claude reported an error result: {detail}")


def write_claude_final_output(stdout_path: Path, final_path: Path, *, output_schema: Path | None = None) -> None:
    data = _extract_claude_payload(stdout_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is not None:
        structured = data.get("structured_output")
        if structured is None:
            result_text = data.get("result")
            if isinstance(result_text, str):
                structured = json.loads(result_text)
        if structured is None:
            raise ValueError("Claude JSON output did not include structured_output")
        final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        final_path.write_text(str(data.get("result", "")), encoding="utf-8")


def _read_jsonl_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def write_claude_stream_final_output(stdout_path: Path, final_path: Path) -> None:
    """Extract the final assistant text from Claude Code stream-json events."""
    result_event: Dict[str, Any] | None = None
    for event in _read_jsonl_events(stdout_path):
        if event.get("type") == "result":
            result_event = event
    if result_event is None:
        raise ValueError("Claude stream-json output did not include a result event")
    _raise_on_claude_error_result(result_event)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    result_text = result_event.get("result")
    final_path.write_text(result_text if isinstance(result_text, str) else "", encoding="utf-8")


_CLAUDE_FILE_CHANGE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _claude_tool_result_text(block: Dict[str, Any]) -> str | None:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if parts:
            return "".join(parts)
    return None


def append_claude_compat_events(events_path: Path) -> None:
    """Append Codex-style item.completed events derived from Claude stream-json events.

    This keeps trace_summary.json comparable across runtimes: agent messages,
    reasoning, command executions, file changes, and usage all become visible
    to summarize_events just like Codex/OpenCode traces.
    """
    events = _read_jsonl_events(events_path)

    tool_results: Dict[str, Dict[str, Any]] = {}
    for event in events:
        if event.get("type") != "user":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            if not isinstance(tool_use_id, str):
                continue
            text = _claude_tool_result_text(block)
            if text is None:
                tool_use_result = event.get("tool_use_result")
                if isinstance(tool_use_result, dict) and isinstance(tool_use_result.get("stdout"), str):
                    text = tool_use_result["stdout"]
            tool_results[tool_use_id] = {
                "output": text,
                "is_error": bool(block.get("is_error", False)),
            }

    compat_events: List[Dict[str, Any]] = []
    usage: Any = None
    for event in events:
        event_type = event.get("type")
        if event_type == "result":
            usage = event.get("usage")
            continue
        if event_type != "assistant":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "id": block.get("id"), "text": block.get("text")},
                    }
                )
            elif block_type == "thinking":
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {"type": "reasoning", "id": block.get("id"), "text": block.get("thinking")},
                    }
                )
            elif block_type == "tool_use":
                tool = block.get("name")
                input_data = block.get("input")
                input_data = input_data if isinstance(input_data, dict) else {}
                tool_use_id = block.get("id")
                result = tool_results.get(tool_use_id) if isinstance(tool_use_id, str) else None
                status = None
                if result is not None:
                    status = "failed" if result["is_error"] else "completed"
                if tool == "Bash":
                    compat_events.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "command_execution",
                                "id": tool_use_id,
                                "command": input_data.get("command"),
                                "status": status,
                                "exit_code": None,
                                "aggregated_output": result["output"] if result else None,
                            },
                        }
                    )
                elif tool in _CLAUDE_FILE_CHANGE_TOOLS:
                    file_path = input_data.get("file_path") or input_data.get("notebook_path")
                    compat_events.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "file_change",
                                "id": tool_use_id,
                                "status": status,
                                "changes": [{"path": file_path}] if file_path else [],
                            },
                        }
                    )

    if usage is not None:
        compat_events.append({"type": "turn.completed", "usage": usage})
    if not compat_events:
        return
    with events_path.open("a", encoding="utf-8") as handle:
        for event in compat_events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _extract_json_object(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise ValueError("No JSON object found in OpenCode text output")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("OpenCode text output did not contain parseable JSON")


def _extract_opencode_session_id(stdout_path: Path) -> str:
    for line in stdout_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            session_id = event.get("sessionID") or event.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return session_id
    raise ValueError("OpenCode JSON output did not include a sessionID")


def _extract_opencode_text_from_events(stdout_path: Path) -> str | None:
    text_parts: List[str] = []
    for line in stdout_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "text":
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)
    if text_parts:
        return "".join(text_parts).strip()
    return None


def append_opencode_compat_events(events_path: Path) -> None:
    compat_events: List[Dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")
        part = event.get("part")
        if event_type == "text" and isinstance(part, dict):
            compat_events.append(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "id": part.get("id"),
                        "text": part.get("text"),
                    },
                }
            )
        elif event_type == "tool_use" and isinstance(part, dict):
            state = part.get("state")
            state = state if isinstance(state, dict) else {}
            input_data = state.get("input")
            input_data = input_data if isinstance(input_data, dict) else {}
            metadata = state.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            tool = part.get("tool")
            if tool == "bash":
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": part.get("callID") or part.get("id"),
                            "command": input_data.get("command"),
                            "status": state.get("status"),
                            "exit_code": metadata.get("exit"),
                            "aggregated_output": state.get("output") or metadata.get("output"),
                        },
                    }
                )
            elif tool in {"write", "edit"}:
                file_path = input_data.get("filePath") or input_data.get("file_path")
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "file_change",
                            "id": part.get("callID") or part.get("id"),
                            "status": state.get("status"),
                            "changes": [{"path": file_path}] if file_path else [],
                        },
                    }
                )

    if not compat_events:
        return
    with events_path.open("a", encoding="utf-8") as handle:
        for event in compat_events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _load_opencode_export(opencode_bin: str, session_id: str, *, env: Dict[str, str]) -> Dict[str, Any]:
    command = split_command(opencode_bin) + ["export", session_id]
    result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise ValueError(f"opencode export failed with exit code {result.returncode}: {result.stderr.strip()}")
    output = result.stdout
    json_start = output.find("{")
    if json_start < 0:
        raise ValueError("opencode export did not return JSON")
    data = json.loads(output[json_start:])
    if not isinstance(data, dict):
        raise ValueError("opencode export JSON was not an object")
    return data


def _extract_opencode_text(export_data: Dict[str, Any]) -> str:
    messages = export_data.get("messages")
    if not isinstance(messages, list):
        raise ValueError("opencode export JSON has no messages array")

    for message in reversed(messages):
        info = message.get("info") if isinstance(message, dict) else None
        if not isinstance(info, dict) or info.get("role") != "assistant":
            continue
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        text_parts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text") is not None
        ]
        text = "".join(text_parts).strip()
        if text:
            return text
    raise ValueError("opencode export did not contain assistant text")


def write_opencode_final_output(
    stdout_path: Path,
    final_path: Path,
    *,
    opencode_bin: str,
    env: Dict[str, str],
    output_schema: Path | None = None,
) -> None:
    text = _extract_opencode_text_from_events(stdout_path)
    if text is None:
        session_id = _extract_opencode_session_id(stdout_path)
        export_data = _load_opencode_export(opencode_bin, session_id, env=env)
        text = _extract_opencode_text(export_data)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_headless_json(stdout_path: Path) -> Dict[str, Any]:
    text = stdout_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Headless agent produced no JSON output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        return data

    last_object: Dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            last_object = event
    if last_object is not None:
        return last_object
    raise ValueError("Headless agent output did not contain a JSON object")


def _extract_headless_response_text(data: Dict[str, Any]) -> str:
    for key in ("response", "text", "output_text", "result", "message", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)

    output = data.get("output")
    if isinstance(output, str) and output.strip():
        return output.strip()
    if isinstance(output, list):
        text_parts: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
        if text_parts:
            return "".join(text_parts).strip()

    assistant = data.get("assistant")
    if isinstance(assistant, dict):
        return _extract_headless_response_text(assistant)
    raise ValueError("Headless agent JSON output did not include assistant text")


def write_headless_final_output(
    stdout_path: Path,
    final_path: Path,
    *,
    output_schema: Path | None = None,
) -> None:
    data = _load_headless_json(stdout_path)
    text = _extract_headless_response_text(data)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_headless_events(stdout_path: Path, *, provider: str) -> None:
    data = _load_headless_json(stdout_path)
    text = _extract_headless_response_text(data)
    usage = data.get("usage") or data.get("stats")
    events = [
        {"type": f"{provider}.raw", "payload": data},
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "id": f"{provider}-final",
                "text": text,
            },
        },
        {"type": "turn.completed", "usage": usage},
    ]
    stdout_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def _extract_last_agent_message_text(events_path: Path) -> str:
    text: str | None = None
    for event in _read_jsonl_events(events_path):
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            candidate = item.get("text")
            if isinstance(candidate, str) and candidate.strip():
                text = candidate
    if text is None:
        raise ValueError("JSONL events output did not include an agent_message with text")
    return text


def write_custom_final_output(
    stdout_path: Path,
    final_path: Path,
    *,
    parser: str,
    output_schema: Path | None = None,
) -> None:
    if parser == "headless-json":
        write_headless_final_output(stdout_path, final_path, output_schema=output_schema)
        return
    if parser == "jsonl-events":
        text = _extract_last_agent_message_text(stdout_path)
    elif parser == "text":
        text = stdout_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("Custom text runtime produced empty stdout")
    else:
        raise ValueError(f"Unknown custom runtime parser: {parser}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_custom_events(stdout_path: Path, *, parser: str, provider: str) -> None:
    if parser == "headless-json":
        normalize_headless_events(stdout_path, provider=provider)
        return
    if parser == "jsonl-events":
        return
    if parser != "text":
        raise ValueError(f"Unknown custom runtime parser: {parser}")
    raw = stdout_path.read_text(encoding="utf-8")
    events = [
        {"type": f"{provider}.raw", "payload": {"stdout": raw}},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "id": f"{provider}-final", "text": raw.strip()},
        },
        {"type": "turn.completed", "usage": None},
    ]
    stdout_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def _pi_assistant_text(message: Dict[str, Any]) -> str:
    parts = [
        str(block.get("text") or "")
        for block in message.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part).strip()


def _read_pi_events(events_path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def write_pi_final_output(
    events_path: Path, final_path: Path, *, output_schema: Path | None = None
) -> None:
    """Write ``final.md`` from a pi ``--mode json`` event stream.

    The deliverable is the last assistant ``message_end`` text; if the stream
    never carried one (pi buffered the turn), fall back to the assistant
    messages replayed in the terminal ``agent_end`` event.
    """
    events = _read_pi_events(events_path)
    text = ""
    for event in events:
        if event.get("type") == "message_end":
            message = event.get("message")
            message = message if isinstance(message, dict) else {}
            if message.get("role") == "assistant":
                candidate = _pi_assistant_text(message)
                if candidate:
                    text = candidate
    if not text:
        for event in events:
            if event.get("type") == "agent_end":
                for message in event.get("messages") or []:
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        candidate = _pi_assistant_text(message)
                        if candidate:
                            text = candidate
    if not text:
        raise ValueError("Pi produced no assistant message")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_pi_events(events_path: Path) -> None:
    """Append Codex-compat ``item.completed`` events after pi's raw events.

    Idempotent: a stream that already carries compat items is left untouched,
    so a re-run of finalize cannot double-count items in ``trace_summary``.
    """
    events = _read_pi_events(events_path)
    if any(event.get("type") == "item.completed" for event in events):
        return
    compat: List[Dict[str, Any]] = []
    counter = 0
    for event in events:
        event_type = event.get("type")
        if event_type == "message_end":
            message = event.get("message")
            message = message if isinstance(message, dict) else {}
            if message.get("role") != "assistant":
                continue
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                counter += 1
                if block.get("type") == "text" and block.get("text"):
                    compat.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "id": f"pi-{counter}",
                                "text": block.get("text"),
                            },
                        }
                    )
                elif block.get("type") == "thinking" and block.get("thinking"):
                    compat.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "reasoning",
                                "id": f"pi-{counter}",
                                "text": block.get("thinking"),
                            },
                        }
                    )
        elif event_type == "tool_execution_end":
            counter += 1
            is_error = bool(event.get("isError"))
            compat.append(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "id": str(event.get("toolCallId") or f"pi-{counter}"),
                        "command": str(event.get("toolName") or ""),
                        "status": "failed" if is_error else "completed",
                        "exit_code": 1 if is_error else 0,
                        "aggregated_output": json.dumps(event.get("result"), ensure_ascii=False),
                    },
                }
            )
    compat.append({"type": "turn.completed", "usage": None})
    with events_path.open("a", encoding="utf-8") as handle:
        for event in compat:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
