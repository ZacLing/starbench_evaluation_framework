from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..contracts import ARTIFACT_SCHEMA_VERSION


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    if not path.exists():
        return events
    with path.open(encoding="utf-8") as handle:
        lines = list(handle)
    for line in lines:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # Agent CLIs can interleave warnings or crash text with JSONL events,
            # especially on failed runs. Skip unparseable lines instead of
            # aborting the whole benchmark.
            continue
        events.append(event)
    return events


def summarize_events(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    event_type_counts: Counter[str] = Counter()
    item_type_counts: Counter[str] = Counter()
    reasoning_items: List[Dict[str, Any]] = []
    agent_messages: List[Dict[str, Any]] = []
    command_executions: List[Dict[str, Any]] = []
    file_changes: List[Dict[str, Any]] = []
    usage: Dict[str, Any] | None = None
    thread_id: str | None = None

    for event in events:
        event_type = str(event.get("type", "unknown"))
        event_type_counts[event_type] += 1
        if event_type == "thread.started":
            thread_id = event.get("thread_id")
        if event_type == "turn.completed":
            usage = event.get("usage")

        item = event.get("item")
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", "unknown"))
        item_type_counts[item_type] += 1

        if item_type == "reasoning":
            reasoning_items.append(
                {
                    "id": item.get("id"),
                    "text": item.get("text") or item.get("summary") or item.get("content"),
                }
            )
        elif item_type == "agent_message":
            agent_messages.append({"id": item.get("id"), "text": item.get("text")})
        elif item_type == "command_execution":
            command_executions.append(
                {
                    "id": item.get("id"),
                    "command": item.get("command"),
                    "status": item.get("status"),
                    "exit_code": item.get("exit_code"),
                    "aggregated_output": item.get("aggregated_output"),
                }
            )
        elif item_type == "file_change":
            file_changes.append(
                {
                    "id": item.get("id"),
                    "status": item.get("status"),
                    "changes": item.get("changes"),
                }
            )

    return {
        "thread_id": thread_id,
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "item_type_counts": dict(sorted(item_type_counts.items())),
        "reasoning_items": reasoning_items,
        "agent_messages": agent_messages,
        "command_executions": command_executions,
        "file_changes": file_changes,
        "usage": usage,
    }


def write_trace_summary(events_path: Path, output_path: Path) -> Dict[str, Any]:
    summary = {
        **summarize_events(read_jsonl(events_path)),
        "schema_version": ARTIFACT_SCHEMA_VERSION,
    }
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_manifest(outputs_dir: Path, output_path: Path) -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    if outputs_dir.exists():
        for path in sorted(outputs_dir.rglob("*")):
            relative = path.relative_to(outputs_dir).as_posix()
            if path.is_dir():
                files.append({"path": relative, "kind": "directory"})
            elif path.is_file():
                files.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "size_bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )

    manifest = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "outputs_dir": str(outputs_dir),
        "file_count": sum(1 for item in files if item["kind"] == "file"),
        "entries": files,
    }
    output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
