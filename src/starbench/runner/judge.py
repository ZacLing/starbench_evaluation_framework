"""Judge side of a benchmark task: evaluator workspace + single/parallel judging.

Responsibility: everything after the executor finishes — building a slim judge
workspace that omits raw inputs (``prepare_evaluator_workspace``), driving the
judge adapter once (``run_single_judge``) or once per rubric
(``run_parallel_judges``), and aggregating the rubric verdicts.

The judge runs under its *own* env scope (``JudgeContext.base_env``), built by the
orchestrator from a clean ambient plus judge-only overrides; nothing a contender
injects into the executor scope reaches the judge here.

Invariants:
- The judge never mutates the executor's ``workspace``; it copies deliverables
  into a fresh ``*_workspace`` and reads from there.
- ``rubric_launch_order`` is deterministic per (seed, run_task_id) so parallel
  judging order does not depend on async scheduling.

改什么来这里: judge workspace contents, judge dispatch, or rubric aggregation.
"""

from __future__ import annotations

import asyncio
import random
import shutil
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ..adapters import JudgeContext, RuntimeAdapter
from .evaluation import (
    aggregate_results,
    normalize_parallel_results,
    normalize_single_result,
    write_aggregate,
)
from .executor import json_dump
from .models import Rubric, TaskSpec
from .progress import BenchmarkProgress
from .prompts import build_parallel_judge_prompt, build_single_judge_prompt

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def rubric_launch_order(rubrics: Sequence[Rubric], *, seed: int, run_task_id: str) -> List[Rubric]:
    """Deterministic per-task rubric launch order, independent of async scheduling."""
    order = list(rubrics)
    random.Random(f"{seed}:{run_task_id}").shuffle(order)
    return order


def prepare_evaluator_workspace(paths: Dict[str, Path], name: str) -> Path:
    """Create a slim judge workspace that omits raw input materials by default."""
    task_root = paths["task_root"]
    source_workspace = paths["workspace"]
    judge_workspace = paths["judges"] / f"{name}_workspace"
    if judge_workspace.exists():
        shutil.rmtree(judge_workspace)
    (judge_workspace / "workspace" / "inputs").mkdir(parents=True, exist_ok=True)
    (judge_workspace / "workspace" / "outputs").mkdir(parents=True, exist_ok=True)
    (judge_workspace / "logs").mkdir(parents=True, exist_ok=True)

    prompt_path = source_workspace / "inputs" / "prompt.md"
    if prompt_path.exists():
        shutil.copy2(prompt_path, judge_workspace / "workspace" / "inputs" / "prompt.md")

    outputs_path = source_workspace / "outputs"
    if outputs_path.exists():
        # Executor outputs may include temporary Python environments or vendored
        # packages created while extracting PDFs. They are not deliverables and
        # can contain container-local symlinks that break host-side copytree.
        shutil.copytree(
            outputs_path,
            judge_workspace / "workspace" / "outputs",
            dirs_exist_ok=True,
            symlinks=True,
            ignore=shutil.ignore_patterns(".venv", "venv", "__pycache__", "_vendor"),
        )

    for path in sorted(source_workspace.iterdir()):
        if path.name in {"inputs", "outputs", ".runner"}:
            continue
        destination = judge_workspace / "workspace" / path.name
        if path.is_file():
            shutil.copy2(path, destination)

    for filename in ("events.jsonl", "final.md", "status.json", "trace_summary.json", "artifact_manifest.json"):
        source = task_root / "logs" / filename
        if source.exists():
            shutil.copy2(source, judge_workspace / "logs" / filename)

    manifest_path = task_root / "manifest.json"
    if manifest_path.exists():
        shutil.copy2(manifest_path, judge_workspace / "manifest.json")

    return judge_workspace


async def run_single_judge(
    task: TaskSpec,
    paths: Dict[str, Path],
    *,
    adapter: RuntimeAdapter,
    judge_ctx: JudgeContext,
    timeout_seconds: int,
    executor_timing: Dict[str, Any] | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> Dict[str, Any]:
    judges = paths["judges"]
    final_path = judges / "single_result.json"

    async def run() -> Dict[str, Any]:
        judge_workspace = prepare_evaluator_workspace(paths, "single")
        judge_final_path = judge_workspace / "single_result.json"
        process_result = await adapter.run_judge(
            base_prompt=build_single_judge_prompt(task),
            schema_path=SCHEMAS_DIR / "single_result.schema.json",
            judge_workspace=judge_workspace,
            judge_final_path=judge_final_path,
            events_path=judges / "single_events.jsonl",
            stderr_path=judges / "single_stderr.log",
            judge_home_base=paths["codex_home"] / "judge_single",
            model=judge_ctx.model,
            timeout_seconds=timeout_seconds,
            ctx=judge_ctx,
        )
        if judge_final_path.exists():
            shutil.copy2(judge_final_path, final_path)
        return process_result.to_dict()

    if semaphore is None:
        status = await run()
    else:
        async with semaphore:
            status = await run()

    try:
        aggregate = aggregate_results(
            task.rubrics,
            normalize_single_result(final_path),
            mode="single",
            executor_timing=executor_timing,
        )
    except Exception as exc:
        aggregate = {
            "mode": "single",
            "overall_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
            "executor_timing": executor_timing,
            "results": [],
        }
    write_aggregate(judges / "single_aggregate.json", aggregate)
    json_dump(judges / "single_status.json", status)
    return {"status": status, "aggregate": aggregate}


async def run_parallel_judges(
    task: TaskSpec,
    paths: Dict[str, Path],
    *,
    adapter: RuntimeAdapter,
    judge_ctx: JudgeContext,
    timeout_seconds: int,
    executor_timing: Dict[str, Any] | None,
    semaphore: asyncio.Semaphore,
    launch_order: Sequence[Rubric],
    progress: BenchmarkProgress | None = None,
    run_task_id: str | None = None,
) -> Dict[str, Any]:
    async def run_one(rubric: Rubric) -> None:
        async with semaphore:
            if progress is not None and run_task_id is not None:
                progress.evaluator_started(run_task_id=run_task_id, mode="parallel", rubric_id=rubric.id)
            rubric_dir = paths["judges"] / "parallel" / rubric.id
            rubric_dir.mkdir(parents=True, exist_ok=True)
            judge_workspace = prepare_evaluator_workspace(paths, f"parallel_{rubric.id}")
            judge_final_path = judge_workspace / "result.json"
            process_result = await adapter.run_judge(
                base_prompt=build_parallel_judge_prompt(task, rubric),
                schema_path=SCHEMAS_DIR / "rubric_result.schema.json",
                judge_workspace=judge_workspace,
                judge_final_path=judge_final_path,
                events_path=rubric_dir / "events.jsonl",
                stderr_path=rubric_dir / "stderr.log",
                judge_home_base=paths["codex_home"] / f"judge_{rubric.id}",
                model=judge_ctx.model,
                timeout_seconds=timeout_seconds,
                ctx=judge_ctx,
            )
            if judge_final_path.exists():
                shutil.copy2(judge_final_path, rubric_dir / "result.json")
            status = process_result.to_dict()
            json_dump(rubric_dir / "status.json", status)
            if progress is not None and run_task_id is not None:
                progress.evaluator_finished(
                    run_task_id=run_task_id,
                    mode="parallel",
                    rubric_id=rubric.id,
                    status=status,
                    aggregate=None,
                )

    await asyncio.gather(*(run_one(rubric) for rubric in launch_order))
    result_paths = [paths["judges"] / "parallel" / rubric.id / "result.json" for rubric in task.rubrics]
    try:
        aggregate = aggregate_results(
            task.rubrics,
            normalize_parallel_results(result_paths),
            mode="parallel",
            executor_timing=executor_timing,
        )
    except Exception as exc:
        aggregate = {
            "mode": "parallel",
            "overall_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
            "executor_timing": executor_timing,
            "results": [],
        }
    write_aggregate(paths["judges"] / "parallel_aggregate.json", aggregate)
    return {"aggregate": aggregate}
