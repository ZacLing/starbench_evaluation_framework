from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .codex_process import (
    build_codex_exec_command,
    prepare_auth_home,
    run_codex_process,
    run_codex_process_in_docker,
)
from .evaluation import aggregate_results, normalize_parallel_results, normalize_single_result, write_aggregate
from .models import Rubric, TaskRunSpec, TaskSpec
from .progress import BenchmarkProgress, make_benchmark_progress
from .task_loader import build_task_runs, discover_tasks, duplicate_tasks
from .trace import build_artifact_manifest, write_trace_summary


PROJECT_ROOT = Path.cwd()
DEFAULT_TASKS_DIR = PROJECT_ROOT / "tasks"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def json_dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_executor_prompt(task_run: TaskRunSpec) -> str:
    task = task_run.task
    base_prompt = f"""You are running inside an isolated benchmark task workspace.

Rules:
- Read task materials from ./inputs/.
- Write all deliverables under ./outputs/.
- Do not inspect parent directories or sibling benchmark tasks.
- Do not look for or infer hidden rubrics.
- Use only the capabilities requested by the task.
- Before finishing, run the requested sample verification if the task asks for one.

Task prompt from ./inputs/prompt.md:

{task.prompt_text}
"""
    if not task_run.selected_steps:
        return base_prompt

    instructions = "\n".join(
        f"{index}. {step.instruction}" for index, step in enumerate(task_run.selected_steps, start=1)
    )
    return f"""{base_prompt}
Additional human reference instructions:
{instructions}
"""


def build_single_judge_prompt(task: TaskSpec) -> str:
    rubrics = [rubric.to_dict() for rubric in task.rubrics]
    return f"""You are an evaluator for a Codex benchmark task.

Inspect this task run directory. The executor deliverables are under ./workspace/outputs/.
The executor trace is available in ./logs/events.jsonl, ./logs/trace_summary.json, ./logs/artifact_manifest.json, and ./logs/final.md.
Executor timing is available in ./logs/status.json.
Raw input materials are intentionally omitted from this evaluator workspace for speed and isolation; use ./manifest.json and the trace/artifact summaries to understand what was available to the executor.

Your job is rubric evidence checking, not solving the original task again.
Use this review order:
1. Read ./workspace/outputs/ and the log summaries first.
2. Read ./workspace/inputs/prompt.md only to understand what the executor was asked to do.
3. Read ./manifest.json and ./logs/artifact_manifest.json for file inventory.
4. If a rubric appears to require raw-material verification that is not present here, judge from the executor-visible evidence and explain the limitation.

Strict evaluator limits:
- Do not redo the task, write a replacement answer, or conduct open-ended analysis.
- Do not browse the web.
- Prefer bounded reads such as file listings, small excerpts, targeted grep/rg, or focused jq queries over reading entire large files.
- If a rubric asks whether the executor cited or used evidence, judge what the executor delivered; do not give credit for evidence you discovered yourself but the executor did not use.
- If a rubric is ambiguous after reasonable bounded inspection, answer using the visible executor package and explain the uncertainty in evidence.

Judge every rubric independently. Each rubric is a yes/no question. For each rubric:
- answer is your yes/no judgment as a boolean.
- expected is the rubric's expected boolean.
- passed is true only when answer == expected.
- fail_fast must match the rubric.
- evidence must cite concrete files, commands, outputs, or trace entries.

Return one JSON object matching the schema, with a result for every rubric.

Task id: {task.id}
Rubrics:
{json.dumps(rubrics, indent=2, sort_keys=True)}
"""


def build_parallel_judge_prompt(task: TaskSpec, rubric: Rubric) -> str:
    return f"""You are an evaluator for one Codex benchmark rubric.

Inspect this task run directory. The executor deliverables are under ./workspace/outputs/.
The executor trace is available in ./logs/events.jsonl, ./logs/trace_summary.json, ./logs/artifact_manifest.json, and ./logs/final.md.
Executor timing is available in ./logs/status.json.
Raw input materials are intentionally omitted from this evaluator workspace for speed and isolation; use ./manifest.json and the trace/artifact summaries to understand what was available to the executor.

Your job is rubric evidence checking, not solving the original task again.
Use this review order:
1. Read ./workspace/outputs/ and the log summaries first.
2. Read ./workspace/inputs/prompt.md only to understand what the executor was asked to do.
3. Read ./manifest.json and ./logs/artifact_manifest.json for file inventory.
4. If this rubric appears to require raw-material verification that is not present here, judge from the executor-visible evidence and explain the limitation.

Strict evaluator limits:
- Do not redo the task, write a replacement answer, or conduct open-ended analysis.
- Do not browse the web.
- Prefer bounded reads such as file listings, small excerpts, targeted grep/rg, or focused jq queries over reading entire large files.
- If this rubric asks whether the executor cited or used evidence, judge what the executor delivered; do not give credit for evidence you discovered yourself but the executor did not use.
- If this rubric is ambiguous after reasonable bounded inspection, answer using the visible executor package and explain the uncertainty in evidence.

Judge only this rubric. It is a yes/no question.
- answer is your yes/no judgment as a boolean.
- expected is the rubric's expected boolean.
- passed is true only when answer == expected.
- fail_fast must match the rubric.
- evidence must cite concrete files, commands, outputs, or trace entries.

Return one JSON object matching the schema.

Task id: {task.id}
Rubric:
{json.dumps(rubric.to_dict(), indent=2, sort_keys=True)}
"""


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
        shutil.copytree(outputs_path, judge_workspace / "workspace" / "outputs", dirs_exist_ok=True)

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


def materialize_task(task_run: TaskRunSpec, run_root: Path, run_task_id: str) -> Dict[str, Path]:
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

    shutil.copy2(task.prompt_path, inputs / "prompt.md")
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

    json_dump(
        task_root / "manifest.json",
        {
            "task_id": task.id,
            "task_name": task.name,
            "run_task_id": run_task_id,
            "rubric_count": len(task.rubrics),
            "timeout_seconds": task.timeout_seconds,
            "allow_web_search": task.allow_web_search,
            "input_materials": input_materials,
            **task_run.instruction_metadata(),
        },
    )

    return {
        "task_root": task_root,
        "workspace": workspace,
        "inputs": inputs,
        "outputs": outputs,
        "logs": logs,
        "judges": judges,
        "codex_home": codex_home,
    }


async def run_executor(
    task_run: TaskRunSpec,
    paths: Dict[str, Path],
    *,
    codex_bin: str,
    auth_mode: str,
    model: str | None,
    executor_backend: str,
    docker_bin: str,
    docker_image: str,
) -> Dict[str, Any]:
    task = task_run.task
    logs = paths["logs"]
    if executor_backend == "local":
        command = build_codex_exec_command(
            codex_bin,
            cwd=paths["workspace"],
            final_path=logs / "final.md",
            sandbox="workspace-write",
            model=model,
            allow_web_search=task.allow_web_search,
            include_trace_config=True,
        )
        env = prepare_auth_home(paths["codex_home"], auth_mode)
        result = await run_codex_process(
            command,
            cwd=paths["workspace"],
            prompt=build_executor_prompt(task_run),
            env=env,
            stdout_path=logs / "events.jsonl",
            stderr_path=logs / "stderr.log",
            timeout_seconds=task.timeout_seconds,
        )
    elif executor_backend == "docker":
        result = await run_codex_process_in_docker(
            codex_bin=codex_bin,
            docker_bin=docker_bin,
            docker_image=docker_image,
            workspace=paths["workspace"],
            codex_home=paths["codex_home"],
            prompt=build_executor_prompt(task_run),
            auth_mode=auth_mode,
            stdout_path=logs / "events.jsonl",
            stderr_path=logs / "stderr.log",
            host_final_path=logs / "final.md",
            timeout_seconds=task.timeout_seconds,
            sandbox="danger-full-access",
            model=model,
            allow_web_search=task.allow_web_search,
            include_trace_config=True,
        )
    else:
        raise ValueError(f"Unknown executor backend: {executor_backend}")
    trace_summary = write_trace_summary(logs / "events.jsonl", logs / "trace_summary.json")
    artifact_manifest = build_artifact_manifest(paths["outputs"], logs / "artifact_manifest.json")
    status = {
        **result.to_dict(),
        "executor_backend": executor_backend,
        "docker_image": docker_image if executor_backend == "docker" else None,
        "trace_summary_path": str(logs / "trace_summary.json"),
        "artifact_manifest_path": str(logs / "artifact_manifest.json"),
        "usage": trace_summary.get("usage"),
        "artifact_file_count": artifact_manifest["file_count"],
    }
    json_dump(logs / "status.json", status)
    return status


async def run_single_judge(
    task: TaskSpec,
    paths: Dict[str, Path],
    *,
    codex_bin: str,
    auth_mode: str,
    model: str | None,
    timeout_seconds: int,
    executor_timing: Dict[str, Any] | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> Dict[str, Any]:
    judges = paths["judges"]
    final_path = judges / "single_result.json"

    async def run() -> Dict[str, Any]:
        judge_workspace = prepare_evaluator_workspace(paths, "single")
        judge_final_path = judge_workspace / "single_result.json"
        command = build_codex_exec_command(
            codex_bin,
            cwd=judge_workspace,
            final_path=judge_final_path,
            sandbox="read-only",
            output_schema=SCHEMAS_DIR / "single_result.schema.json",
            model=model,
            include_trace_config=False,
        )
        env = prepare_auth_home(paths["codex_home"] / "judge_single", auth_mode)
        process_result = await run_codex_process(
            command,
            cwd=judge_workspace,
            prompt=build_single_judge_prompt(task),
            env=env,
            stdout_path=judges / "single_events.jsonl",
            stderr_path=judges / "single_stderr.log",
            timeout_seconds=timeout_seconds,
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
    codex_bin: str,
    auth_mode: str,
    model: str | None,
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
            command = build_codex_exec_command(
                codex_bin,
                cwd=judge_workspace,
                final_path=judge_final_path,
                sandbox="read-only",
                output_schema=SCHEMAS_DIR / "rubric_result.schema.json",
                model=model,
                include_trace_config=False,
            )
            env = prepare_auth_home(paths["codex_home"] / f"judge_{rubric.id}", auth_mode)
            process_result = await run_codex_process(
                command,
                cwd=judge_workspace,
                prompt=build_parallel_judge_prompt(task, rubric),
                env=env,
                stdout_path=rubric_dir / "events.jsonl",
                stderr_path=rubric_dir / "stderr.log",
                timeout_seconds=timeout_seconds,
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


def make_run_task_ids(task_runs: Sequence[TaskRunSpec]) -> List[str]:
    counts: Dict[str, int] = {}
    run_task_ids: List[str] = []
    for task_run in task_runs:
        base_id = task_run.task.id
        if task_run.instruction_label:
            base_id = f"{base_id}__{task_run.instruction_label}"
        counts[base_id] = counts.get(base_id, 0) + 1
        suffix = counts[base_id]
        run_task_ids.append(base_id if suffix == 1 else f"{base_id}__{suffix:03d}")
    return run_task_ids


def executor_timing_from_status(status: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "started_at": status.get("started_at"),
        "ended_at": status.get("ended_at"),
        "duration_seconds": status.get("duration_seconds"),
        "status": status.get("status"),
        "exit_code": status.get("exit_code"),
        "timed_out": status.get("timed_out"),
    }


async def run_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    tasks = duplicate_tasks(discover_tasks(args.tasks_dir, args.task), args.repeat)
    task_runs = build_task_runs(
        tasks,
        instruction_mode=args.instruction_mode,
        instruction_steps=args.instruction_step,
    )
    rng = random.Random(args.seed)
    indexed = list(enumerate(task_runs))
    rng.shuffle(indexed)
    ordered_task_runs = [task_run for _, task_run in indexed]
    run_task_ids = make_run_task_ids(ordered_task_runs)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    run_root = args.runs_dir / run_id
    run_root.mkdir(parents=True, exist_ok=False)
    selected_instruction_step_ids = task_runs[0].instruction_step_ids if args.instruction_mode == "select" and task_runs else []

    run_config = {
        "run_id": run_id,
        "seed": args.seed,
        "batch_size": args.batch_size,
        "judge_mode": args.judge_mode,
        "max_evaluator_parallel": args.max_evaluator_parallel,
        "auth_mode": args.auth_mode,
        "executor_model": args.executor_model,
        "evaluator_model": args.evaluator_model,
        "executor_backend": args.executor_backend,
        "docker_image": args.docker_image if args.executor_backend == "docker" else None,
        "instruction_mode": args.instruction_mode,
        "requested_instruction_step_ids": args.instruction_step or [],
        "instruction_step_ids": selected_instruction_step_ids,
        "instruction_step_order": "human_reference",
        "task_order": run_task_ids,
        "codex_bin": args.codex_bin,
    }
    json_dump(run_root / "run_config.json", run_config)

    records = []
    for task_run, run_task_id in zip(ordered_task_runs, run_task_ids):
        records.append(
            {
                "task_run": task_run,
                "task": task_run.task,
                "run_task_id": run_task_id,
                "paths": materialize_task(task_run, run_root, run_task_id),
            }
        )

    evaluator_semaphore = asyncio.Semaphore(args.max_evaluator_parallel)
    batch_summaries: List[Dict[str, Any]] = []
    evaluator_total = len(records) if args.judge_mode == "single" else 0
    if args.judge_mode == "parallel":
        evaluator_total = sum(len(record["task"].rubrics) for record in records)
    elif args.judge_mode == "both":
        evaluator_total = len(records) + sum(len(record["task"].rubrics) for record in records)
    progress = make_benchmark_progress(
        run_root=run_root,
        total_executors=len(records),
        total_evaluators=evaluator_total,
        enabled=not args.no_progress,
    )

    try:
        for batch_index, start in enumerate(range(0, len(records), args.batch_size), start=1):
            batch = records[start : start + args.batch_size]
            progress.batch_started(
                batch_index=batch_index,
                run_task_ids=[record["run_task_id"] for record in batch],
            )

            async def execute_record(record: Dict[str, Any]) -> Dict[str, Any]:
                progress.executor_started(run_task_id=record["run_task_id"], task_id=record["task"].id)
                status = await run_executor(
                    record["task_run"],
                    record["paths"],
                    codex_bin=args.codex_bin,
                    auth_mode=args.auth_mode,
                    model=args.executor_model,
                    executor_backend=args.executor_backend,
                    docker_bin=args.docker_bin,
                    docker_image=args.docker_image,
                )
                progress.executor_finished(
                    run_task_id=record["run_task_id"],
                    task_id=record["task"].id,
                    status=status,
                )
                return status

            executor_statuses = await asyncio.gather(
                *(execute_record(record) for record in batch)
            )

            async def evaluate_record(record: Dict[str, Any], executor_status: Dict[str, Any]) -> Dict[str, Any]:
                task = record["task"]
                paths = record["paths"]
                modes: Dict[str, Any] = {}
                executor_timing = executor_timing_from_status(executor_status)
                if args.judge_mode in ("single", "both"):
                    progress.evaluator_started(run_task_id=record["run_task_id"], mode="single")
                    modes["single"] = await run_single_judge(
                        task,
                        paths,
                        codex_bin=args.codex_bin,
                        auth_mode=args.auth_mode,
                        model=args.evaluator_model,
                        timeout_seconds=args.evaluator_timeout_seconds,
                        executor_timing=executor_timing,
                        semaphore=evaluator_semaphore,
                    )
                    progress.evaluator_finished(
                        run_task_id=record["run_task_id"],
                        mode="single",
                        status=modes["single"].get("status"),
                        aggregate=modes["single"].get("aggregate"),
                    )
                if args.judge_mode in ("parallel", "both"):
                    rubric_order = list(task.rubrics)
                    rng.shuffle(rubric_order)
                    modes["parallel"] = await run_parallel_judges(
                        task,
                        paths,
                        codex_bin=args.codex_bin,
                        auth_mode=args.auth_mode,
                        model=args.evaluator_model,
                        timeout_seconds=args.evaluator_timeout_seconds,
                        executor_timing=executor_timing,
                        semaphore=evaluator_semaphore,
                        launch_order=rubric_order,
                        progress=progress,
                        run_task_id=record["run_task_id"],
                    )
                result = {
                    "run_task_id": record["run_task_id"],
                    "task_id": task.id,
                    **record["task_run"].instruction_metadata(),
                    "executor_timing": executor_timing,
                    "executor": executor_status,
                    "judges": modes,
                }
                json_dump(paths["task_root"] / "task_summary.json", result)
                return result

            judge_results = await asyncio.gather(
                *(evaluate_record(record, executor_status) for record, executor_status in zip(batch, executor_statuses))
            )

            batch_summaries.append(
                {
                    "batch_index": batch_index,
                    "run_task_ids": [record["run_task_id"] for record in batch],
                    "tasks": judge_results,
                }
            )
            progress.batch_finished(
                batch_index=batch_index,
                run_task_ids=[record["run_task_id"] for record in batch],
            )
    finally:
        progress.close()

    summary = {
        **run_config,
        "run_root": str(run_root),
        "batches": batch_summaries,
    }
    json_dump(run_root / "summary.json", summary)
    return summary


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex benchmark tasks and rubric judges.")
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--judge-mode", choices=["both", "single", "parallel"], default="both")
    parser.add_argument("--max-evaluator-parallel", type=int, default=4)
    parser.add_argument("--run-id")
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--task", action="append", help="Task id or task directory name to include. Repeatable.")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat the selected task list N times.")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable, or a shell-like command prefix.")
    parser.add_argument("--auth-mode", choices=["env", "global", "copy-auth"], default="env")
    parser.add_argument("--executor-model", help="Exact model id passed to executor `codex exec -m`.")
    parser.add_argument("--evaluator-model", help="Exact model id passed to evaluator `codex exec -m`.")
    parser.add_argument(
        "--executor-backend",
        choices=["local", "docker"],
        default="docker",
        help="Run executor directly on the host or inside a per-task Docker container.",
    )
    parser.add_argument("--docker-bin", default="docker", help="Docker executable or shell-like command prefix.")
    parser.add_argument(
        "--docker-image",
        default="codex-bench:latest",
        help="Image used when --executor-backend docker is selected.",
    )
    parser.add_argument("--evaluator-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--instruction-mode",
        choices=["none", "traverse", "select"],
        default="none",
        help="Append human_reference instructions: none, one run per step, or selected step bundle.",
    )
    parser.add_argument(
        "--instruction-step",
        action="append",
        help="Human reference step_id to include. Repeatable. Implies select mode when mode is none.",
    )
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars and progress stderr output.")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.max_evaluator_parallel < 1:
        parser.error("--max-evaluator-parallel must be at least 1")
    if args.instruction_step and args.instruction_mode == "none":
        args.instruction_mode = "select"
    if args.instruction_mode == "select" and not args.instruction_step:
        parser.error("--instruction-mode select requires at least one --instruction-step")
    args.tasks_dir = args.tasks_dir.resolve()
    args.runs_dir = args.runs_dir.resolve()
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = asyncio.run(run_benchmark(args))
    print(json.dumps({"run_id": summary["run_id"], "run_root": summary["run_root"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
