"""Task-run detail and bounded deliverable reads."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base import (
    NotFound, _jsonl_index_root, _read_json, _read_text, _tail_text,
    resolve_task_run_dir,
)
from .jsonl import read_nonempty_lines_page
from .runs import _task_dirs
from .task_facts import _task_identity

ARTIFACT_MAX_BYTES = 1_000_000
ARTIFACT_BINARY_SNIFF_BYTES = 8_192
OUTPUTS_LISTING_MAX_ENTRIES = 500

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
    raw_event_count = read_nonempty_lines_page(
        events_path,
        offset=0,
        limit=1,
        index_root=_jsonl_index_root(runs_dir),
    ).total

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
