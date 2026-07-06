"""Benchmark orchestration: the run loop, batching, progress, and summaries.

Responsibility: turn a parsed ``argparse.Namespace`` into a full run — discover
and order task runs, resolve the executor/judge adapters once, build the two
env-scoped contexts, then batch executors and judges, writing ``run_config.json``
/ ``task_summary.json`` / ``summary.json`` (plus the instruction-ablation report).

This is the only module that holds both the executor and judge sides at once, so
it is where env isolation is *constructed*: :func:`scoped_base_envs` splits the
ambient environment into an executor base and a judge base (see
``runner.env_scope``), and each seeds its own context. The GUI's plan-time
conflict check is now just advisory; isolation happens here regardless.

Invariants:
- No per-runtime branches: ``resolve(agent)`` yields an adapter that owns all
  runtime specifics; the loop only calls ``run_executor`` / ``run_single_judge``
  / ``run_parallel_judges``.
- One crashing task must not abort the run (executor exceptions are caught and
  recorded as a failed status).

改什么来这里: the run loop, batching/progress, summary shape, or env scoping.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ..adapters import ExecutorContext, JudgeContext, resolve
from .env_scope import scoped_base_envs
from .executor import json_dump, materialize_task, run_executor
from .judge import rubric_launch_order, run_parallel_judges, run_single_judge
from ..skills.registry import expand_skill_groups, load_registry_skills
from .progress import make_benchmark_progress
from .summary import build_instruction_ablation_summary, format_instruction_ablation_markdown
from .task_loader import build_task_runs, discover_tasks, duplicate_tasks


def make_run_task_ids(task_runs: Sequence[Any]) -> List[str]:
    counts: Dict[str, int] = {}
    run_task_ids: List[str] = []
    for task_run in task_runs:
        base_id = task_run.task.id
        if task_run.instruction_variant != "baseline":
            base_id = f"{base_id}__{task_run.instruction_variant}"
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
    registry_skills = load_registry_skills(args.executor_skill_root) if args.executor_skill_root.exists() else []
    registry_skill_by_id = {skill.id: skill for skill in registry_skills}
    group_skill_ids = expand_skill_groups(args.executor_skill_root, args.executor_skill_group)
    requested_executor_skill_ids = list(args.executor_skill or []) + group_skill_ids
    duplicate_requested_executor_skill_ids = sorted(
        {
            skill_id
            for skill_id in requested_executor_skill_ids
            if requested_executor_skill_ids.count(skill_id) > 1
        }
    )
    if duplicate_requested_executor_skill_ids:
        raise ValueError(
            "Duplicate executor skill selected from ids/groups: "
            + ", ".join(duplicate_requested_executor_skill_ids)
        )
    external_executor_skills = [
        registry_skill_by_id[skill_id]
        for skill_id in requested_executor_skill_ids
        if skill_id in registry_skill_by_id
    ]
    task_runs = build_task_runs(
        tasks,
        instruction_mode=args.instruction_mode,
        instruction_steps=args.instruction_step,
        rigor_mode=args.rigor_mode,
        rigor_ids=args.rigor,
        executor_skill_ids=requested_executor_skill_ids,
        external_executor_skills=external_executor_skills,
    )
    rng = random.Random(args.seed)
    indexed = list(enumerate(task_runs))
    rng.shuffle(indexed)
    ordered_task_runs = [task_run for _, task_run in indexed]
    run_task_ids = make_run_task_ids(ordered_task_runs)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    run_root = args.runs_dir / run_id
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(
            f"Run directory already exists: {run_root}. Choose a new --run-id or remove the old run."
        )
    selected_instruction_step_ids = task_runs[0].instruction_step_ids if args.instruction_mode == "select" and task_runs else []
    instruction_variants: List[Dict[str, Any]] = []
    seen_instruction_variants = set()
    for task_run in task_runs:
        key = (task_run.task.id, task_run.instruction_variant)
        if key in seen_instruction_variants:
            continue
        seen_instruction_variants.add(key)
        instruction_variants.append(
            {
                "task_id": task_run.task.id,
                **task_run.instruction_metadata(),
            }
        )

    run_config = {
        "run_id": run_id,
        "seed": args.seed,
        "batch_size": args.batch_size,
        "judge_mode": args.judge_mode,
        "max_evaluator_parallel": args.max_evaluator_parallel,
        "auth_mode": args.auth_mode,
        "executor_auth_mode": args.executor_auth_mode,
        "evaluator_auth_mode": args.evaluator_auth_mode,
        "executor_agent": args.executor_agent,
        "evaluator_agent": args.evaluator_agent,
        "runtimes_dir": str(args.runtimes_dir),
        "executor_runtime": args.executor_runtime_spec.public_metadata() if args.executor_runtime_spec else None,
        "evaluator_runtime": args.evaluator_runtime_spec.public_metadata() if args.evaluator_runtime_spec else None,
        "thinking_effort": args.thinking_effort,
        "web_search": args.web_search,
        "claude_max_turns": args.claude_max_turns,
        "opencode_provider": args.opencode_provider,
        "opencode_base_url": args.opencode_base_url,
        "opencode_api_key_env": args.opencode_api_key_env,
        "executor_model": args.executor_model,
        "evaluator_model": args.evaluator_model,
        "executor_backend": args.executor_backend,
        "docker_image": args.docker_image if args.executor_backend == "docker" else None,
        "instruction_mode": args.instruction_mode,
        "requested_instruction_step_ids": args.instruction_step or [],
        "instruction_step_ids": selected_instruction_step_ids,
        "instruction_step_order": "human_reference",
        "rigor_mode": args.rigor_mode,
        "requested_rigor_ids": args.rigor or [],
        "requested_executor_skill_ids": requested_executor_skill_ids,
        "requested_executor_skill_groups": args.executor_skill_group or [],
        "executor_skill_root": str(args.executor_skill_root),
        "executor_skill_order": "executor_skills",
        "instruction_variants": instruction_variants,
        "task_order": run_task_ids,
        "codex_bin": args.codex_bin,
        "claude_bin": args.claude_bin,
        "grok_bin": args.grok_bin,
        "gemini_bin": args.gemini_bin,
        "opencode_bin": args.opencode_bin,
    }
    json_dump(run_root / "run_config.json", run_config)

    executor_adapter = resolve(
        args.executor_agent, spec=args.executor_runtime_spec, runtimes_dir=args.runtimes_dir
    )
    evaluator_adapter = resolve(
        args.evaluator_agent, spec=args.evaluator_runtime_spec, runtimes_dir=args.runtimes_dir
    )
    # Effort levels are a runtime fact: reject a level this executor's CLI
    # does not accept instead of passing it on to fail (or silently skew a
    # comparison) mid-run.
    supported_efforts = executor_adapter.info.thinking_efforts
    if args.thinking_effort not in supported_efforts:
        raise SystemExit(
            f"--thinking-effort {args.thinking_effort} is not supported by "
            f"{args.executor_agent} (supported: {', '.join(supported_efforts)})."
        )
    runtime_bins = {
        "codex": args.codex_bin,
        "claude": args.claude_bin,
        "grok": args.grok_bin,
        "gemini": args.gemini_bin,
        "opencode": args.opencode_bin,
    }
    # Split the ambient environment into an executor base and a judge base so a
    # contender's injected endpoint/credentials cannot reach the judge (see
    # runner.env_scope). With no STARBENCH_*_ENV_* prefixes present — standalone
    # CLI use — both equal the ambient environment, so behaviour is unchanged.
    executor_base_env, judge_base_env = scoped_base_envs(os.environ)
    executor_ctx = ExecutorContext(
        base_env=executor_base_env,
        bins=runtime_bins,
        docker_bin=args.docker_bin,
        docker_image=args.docker_image,
        executor_backend=args.executor_backend,
        auth_mode=args.executor_auth_mode,
        model=args.executor_model,
        thinking_effort=args.thinking_effort,
        claude_max_turns=args.claude_max_turns,
        opencode_provider=args.opencode_provider,
        opencode_base_url=args.opencode_base_url,
        opencode_api_key_env=args.opencode_api_key_env,
        web_search_mode=args.web_search,
    )
    judge_ctx = JudgeContext(
        base_env=judge_base_env,
        bins=runtime_bins,
        auth_mode=args.evaluator_auth_mode,
        model=args.evaluator_model,
        thinking_effort=args.thinking_effort,
        opencode_provider=args.opencode_provider,
        opencode_base_url=args.opencode_base_url,
        opencode_api_key_env=args.opencode_api_key_env,
    )

    records = []
    for task_run, run_task_id in zip(ordered_task_runs, run_task_ids):
        records.append(
            {
                "task_run": task_run,
                "task": task_run.task,
                "run_task_id": run_task_id,
                "paths": materialize_task(
                    task_run,
                    run_root,
                    run_task_id,
                    executor_backend=args.executor_backend,
                    executor_agent=args.executor_agent,
                    executor_adapter=executor_adapter,
                ),
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
                try:
                    status = await run_executor(
                        record["task_run"],
                        record["paths"],
                        adapter=executor_adapter,
                        ctx=executor_ctx,
                    )
                except Exception as exc:
                    # One crashing task must not abort the whole run.
                    logs = record["paths"]["logs"]
                    with (logs / "stderr.log").open("a", encoding="utf-8") as handle:
                        handle.write(f"\nExecutor crashed: {type(exc).__name__}: {exc}\n")
                    status = {
                        "command": [],
                        "exit_code": None,
                        "status": "failed",
                        "timed_out": False,
                        "started_at": None,
                        "ended_at": None,
                        "duration_seconds": None,
                        "error": f"{type(exc).__name__}: {exc}",
                        "executor_backend": args.executor_backend,
                        "docker_image": args.docker_image if args.executor_backend == "docker" else None,
                        "usage": None,
                        "artifact_file_count": 0,
                    }
                    json_dump(logs / "status.json", status)
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
                    try:
                        modes["single"] = await run_single_judge(
                            task,
                            paths,
                            adapter=evaluator_adapter,
                            judge_ctx=judge_ctx,
                            timeout_seconds=args.evaluator_timeout_seconds,
                            executor_timing=executor_timing,
                            semaphore=evaluator_semaphore,
                        )
                    except Exception as exc:
                        modes["single"] = {
                            "status": {"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
                            "aggregate": {
                                "mode": "single",
                                "overall_pass": False,
                                "error": f"{type(exc).__name__}: {exc}",
                                "executor_timing": executor_timing,
                                "results": [],
                            },
                        }
                    progress.evaluator_finished(
                        run_task_id=record["run_task_id"],
                        mode="single",
                        status=modes["single"].get("status"),
                        aggregate=modes["single"].get("aggregate"),
                    )
                if args.judge_mode in ("parallel", "both"):
                    rubric_order = rubric_launch_order(
                        task.rubrics, seed=args.seed, run_task_id=record["run_task_id"]
                    )
                    try:
                        modes["parallel"] = await run_parallel_judges(
                            task,
                            paths,
                            adapter=evaluator_adapter,
                            judge_ctx=judge_ctx,
                            timeout_seconds=args.evaluator_timeout_seconds,
                            executor_timing=executor_timing,
                            semaphore=evaluator_semaphore,
                            launch_order=rubric_order,
                            progress=progress,
                            run_task_id=record["run_task_id"],
                        )
                    except Exception as exc:
                        modes["parallel"] = {
                            "aggregate": {
                                "mode": "parallel",
                                "overall_pass": False,
                                "error": f"{type(exc).__name__}: {exc}",
                                "executor_timing": executor_timing,
                                "results": [],
                            },
                        }
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

    summary: Dict[str, Any] = {
        **run_config,
        "run_root": str(run_root),
        "batches": batch_summaries,
    }
    if args.instruction_mode == "ablation":
        ablation_summary = build_instruction_ablation_summary(batch_summaries)
        ablation_json_path = run_root / "instruction_ablation_summary.json"
        ablation_md_path = run_root / "instruction_ablation_summary.md"
        json_dump(ablation_json_path, ablation_summary)
        ablation_md_path.write_text(format_instruction_ablation_markdown(ablation_summary), encoding="utf-8")
        summary["instruction_ablation_summary_path"] = str(ablation_json_path)
        summary["instruction_ablation_report_path"] = str(ablation_md_path)
    json_dump(run_root / "summary.json", summary)
    return summary
