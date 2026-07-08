"""Executor side of a benchmark task: materialize, install skills, run.

Responsibility: everything that happens *before* judging one task run —
laying out the per-task workspace on disk (``materialize_task``), copying task
materials, installing executor skills at the runtime's own location, and driving
the executor adapter (``run_executor``) to produce ``outputs/`` + logs.

Invariants:
- ``materialize_task`` is the only writer of a task root's ``workspace`` /
  ``inputs`` / ``manifest.json`` layout; the judge side reads that layout but
  never creates it.
- Skill install location is a runtime fact: it comes from the resolved adapter
  (``executor_skill_install_root``), never branched on the agent id here.
- ``run_executor`` writes ``logs/status.json`` and returns it; a crash is the
  orchestrator's concern, not this module's.

改什么来这里: workspace layout, skill install, or how the executor adapter is
invoked for one task.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from ..adapters import BUILTIN_AGENTS, ExecutorContext, RuntimeAdapter, get_builtin
from ..contracts import ARTIFACT_SCHEMA_VERSION
from .models import TaskRunSpec
from .prompts import build_augmented_prompt_text
from .trace import build_artifact_manifest, write_trace_summary

IGNORED_EXECUTOR_SKILL_NAMES = {".DS_Store", ".git", "__pycache__"}

# Skill install paths for custom runtimes are runtime-agnostic; a bare base
# adapter supplies those defaults when a real (spec-backed) adapter is not on
# hand (e.g. tests that materialize a task by agent id).
_SKILLS_DEFAULT_ADAPTER = RuntimeAdapter()


def _skills_adapter(executor_agent: str) -> RuntimeAdapter:
    if executor_agent in BUILTIN_AGENTS:
        return get_builtin(executor_agent)
    return _SKILLS_DEFAULT_ADAPTER


def json_dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def copy_task_material(source: Path, destination: Path) -> None:
    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _is_ignored_executor_skill_path(path: Path) -> bool:
    return any(part in IGNORED_EXECUTOR_SKILL_NAMES for part in path.parts)


def hash_executor_skill_directory(source: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        relative_path = path.relative_to(source)
        if _is_ignored_executor_skill_path(relative_path):
            continue
        if not path.is_file():
            continue
        hasher.update(str(relative_path).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def install_executor_skills(
    task_run: TaskRunSpec,
    paths: Dict[str, Path],
    *,
    executor_backend: str,
    executor_adapter: RuntimeAdapter,
) -> List[Dict[str, Any]]:
    installed: List[Dict[str, Any]] = []
    if not task_run.selected_executor_skills:
        return installed

    install_root = executor_adapter.executor_skill_install_root(paths, executor_backend)
    install_root.mkdir(parents=True, exist_ok=True)
    for skill in task_run.selected_executor_skills:
        digest = hash_executor_skill_directory(skill.source_path)
        if skill.sha256 is not None and skill.sha256 != digest:
            raise ValueError(
                f"Executor skill {skill.id} sha256 mismatch: expected {skill.sha256}, got {digest}"
            )

        destination = install_root / skill.id
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.copytree(
            skill.source_path,
            destination,
            ignore=shutil.ignore_patterns(*IGNORED_EXECUTOR_SKILL_NAMES),
        )
        try:
            installed_to = str(destination.relative_to(paths["task_root"]))
        except ValueError:
            installed_to = str(destination)
        metadata = skill.public_metadata(installed_to=installed_to)
        metadata["sha256"] = digest
        installed.append(metadata)
    return installed


def materialize_task(
    task_run: TaskRunSpec,
    run_root: Path,
    run_task_id: str,
    *,
    executor_backend: str = "docker",
    executor_agent: str = "codex",
    executor_adapter: RuntimeAdapter | None = None,
) -> Dict[str, Path]:
    task = task_run.task
    task_root = run_root / run_task_id
    workspace = task_root / "workspace"
    inputs = workspace / "inputs"
    outputs = workspace / "outputs"
    logs = task_root / "logs"
    judges = task_root / "judges"
    codex_home = task_root / "codex_home"

    inputs.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    judges.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)

    (inputs / "prompt.md").write_text(build_augmented_prompt_text(task_run), encoding="utf-8")
    if task.files_dir is not None:
        destination = inputs / "files"
        copy_task_material(task.files_dir, destination)
    input_materials = []
    for material_path in task.material_paths:
        try:
            relative_path = material_path.relative_to(task.source_dir)
        except ValueError:
            relative_path = Path(material_path.name)
        destination = inputs / relative_path
        copy_task_material(material_path, destination)
        input_materials.append(str(relative_path))

    paths = {
        "task_root": task_root,
        "workspace": workspace,
        "inputs": inputs,
        "outputs": outputs,
        "logs": logs,
        "judges": judges,
        "codex_home": codex_home,
    }
    installed_executor_skills = install_executor_skills(
        task_run,
        paths,
        executor_backend=executor_backend,
        executor_adapter=executor_adapter or _skills_adapter(executor_agent),
    )

    json_dump(
        task_root / "manifest.json",
        {
            "schema_version": ARTIFACT_SCHEMA_VERSION,
            "task_id": task.id,
            "task_name": task.name,
            "run_task_id": run_task_id,
            "rubric_count": len(task.rubrics),
            "timeout_seconds": task.timeout_seconds,
            "allow_web_search": task.allow_web_search,
            "input_materials": input_materials,
            "installed_executor_skills": installed_executor_skills,
            **task_run.instruction_metadata(),
        },
    )

    return paths


async def run_executor(
    task_run: TaskRunSpec,
    paths: Dict[str, Path],
    *,
    adapter: RuntimeAdapter,
    ctx: ExecutorContext,
    runtime_provenance: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    logs = paths["logs"]
    result = await adapter.run_executor(task_run, paths, ctx=ctx)
    trace_summary = write_trace_summary(logs / "events.jsonl", logs / "trace_summary.json")
    artifact_manifest = build_artifact_manifest(paths["outputs"], logs / "artifact_manifest.json")
    status = {
        **result.to_dict(),
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "executor_backend": ctx.executor_backend,
        "docker_image": ctx.docker_image if ctx.executor_backend == "docker" else None,
        "trace_summary_path": str(logs / "trace_summary.json"),
        "artifact_manifest_path": str(logs / "artifact_manifest.json"),
        "usage": trace_summary.get("usage"),
        "artifact_file_count": artifact_manifest["file_count"],
    }
    if runtime_provenance is not None:
        status["executor_runtime_provenance"] = runtime_provenance
    json_dump(logs / "status.json", status)
    return status
