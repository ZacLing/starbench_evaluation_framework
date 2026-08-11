"""Task-library read models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .base import SAFE_ID, _read_json

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
