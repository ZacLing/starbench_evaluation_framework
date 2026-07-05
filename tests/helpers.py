"""Shared test fixtures: repo paths and JSON/run builders used across the suite.

Imported by the split test modules as ``from helpers import ...``. Both runners
put the ``tests/`` directory on ``sys.path`` (unittest via ``top_level_dir``,
pytest via prepend mode), so the bare-name import resolves to this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Belt-and-suspenders: make ``starbench`` importable even without an editable
# install. ``make test`` sets PYTHONPATH=src and pytest uses the installed
# package, but this keeps ad-hoc ``python -m unittest`` invocations working too.
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

DEMO_TASK = ROOT / "examples" / "tasks" / "demo_python_cli"
DEMO_INSTRUCTION_TASK = ROOT / "examples" / "tasks" / "demo_instruction_reference"


def write_runtime(root: Path, runtime_id: str, data: dict) -> Path:
    """Write a ``runtimes/<id>.json`` custom-runtime spec and return its path."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{runtime_id}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def make_task_run(
    run_root: Path,
    task_run_id: str,
    *,
    executor_status: str = "success",
    overall_pass: bool = True,
    evaluated: bool = True,
) -> None:
    task_root = run_root / task_run_id
    logs = task_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    status = {
        "status": executor_status,
        "exit_code": 0 if executor_status == "success" else 1,
        "timed_out": executor_status == "timeout",
        "started_at": "2026-07-04T02:00:00+00:00",
        "ended_at": "2026-07-04T02:03:20+00:00",
        "duration_seconds": 200.0,
        "command": ["codex", "exec"],
    }
    write_json(logs / "status.json", status)
    write_json(
        logs / "trace_summary.json",
        {
            "agent_messages": [{"id": "m1", "text": "done"}],
            "command_executions": [],
            "reasoning_items": [],
            "file_changes": [],
            "event_type_counts": {"turn.completed": 1},
            "item_type_counts": {"agent_message": 1},
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "thread_id": "t1",
        },
    )
    write_json(
        logs / "artifact_manifest.json",
        {
            "outputs_dir": str(task_root / "workspace" / "outputs"),
            "file_count": 1,
            "entries": [
                {"path": "hello.py", "kind": "file", "size_bytes": 10, "sha256": "ab" * 32}
            ],
        },
    )
    (logs / "final.md").write_text("# Done\n\nAll good.", encoding="utf-8")
    (logs / "events.jsonl").write_text(
        '{"type": "thread.started", "thread_id": "t1"}\n'
        '{"type": "turn.completed", "usage": {"input_tokens": 100}}\n',
        encoding="utf-8",
    )
    write_json(
        task_root / "manifest.json",
        {
            "task_id": "demo_task",
            "rubrics": [
                {"id": "R001", "question": "Does it exist?", "fail_fast": True, "expected": True},
                {"id": "R002", "question": "Does it run?", "fail_fast": False, "expected": True},
            ],
        },
    )
    if not evaluated:
        return
    aggregate = {
        "mode": "single",
        "overall_pass": overall_pass,
        "passed_count": 2 if overall_pass else 1,
        "total_count": 2,
        "missing": [],
        "fail_fast_failures": [],
        "executor_timing": None,
        "results": [
            {
                "rubric_id": "R001",
                "answer": True,
                "expected": True,
                "passed": True,
                "fail_fast": True,
                "evidence": "Found it.",
            },
            {
                "rubric_id": "R002",
                "answer": overall_pass,
                "expected": True,
                "passed": overall_pass,
                "fail_fast": False,
                "evidence": "Ran it." if overall_pass else "Crashed.",
            },
        ],
    }
    write_json(task_root / "judges" / "single_aggregate.json", aggregate)
    write_json(
        task_root / "judges" / "single_status.json",
        {"status": "success", "duration_seconds": 30.0},
    )
    write_json(
        task_root / "task_summary.json",
        {
            "run_task_id": task_run_id,
            "task_id": "demo_task",
            "instruction_variant": "baseline",
            "executor": status,
            "executor_timing": {"duration_seconds": 200.0},
            "judges": {"single": {"aggregate": aggregate, "status": {"status": "success"}}},
        },
    )


def make_run(
    runs_dir: Path,
    run_id: str,
    *,
    complete: bool = True,
    task_specs=(("demo_task__baseline_01", "success", True),),
) -> Path:
    run_root = runs_dir / run_id
    run_root.mkdir(parents=True)
    write_json(
        run_root / "run_config.json",
        {
            "run_id": run_id,
            "seed": 123,
            "batch_size": 1,
            "judge_mode": "single",
            "executor_agent": "codex",
            "executor_model": "gpt-5.5",
            "evaluator_agent": "codex",
            "evaluator_model": "gpt-5.5",
            "executor_backend": "local",
            "instruction_mode": "none",
            "task_order": [spec[0] for spec in task_specs],
        },
    )
    events = [
        {
            "timestamp": "2026-07-04T02:00:00+00:00",
            "event": "run_progress_initialized",
            "total_executors": len(task_specs),
            "total_evaluators": len(task_specs),
        }
    ]
    for task_run_id, executor_status, overall_pass in task_specs:
        make_task_run(
            run_root,
            task_run_id,
            executor_status=executor_status,
            overall_pass=overall_pass,
            evaluated=complete,
        )
        events.append(
            {
                "timestamp": "2026-07-04T02:03:20+00:00",
                "event": "executor_finished",
                "run_task_id": task_run_id,
                "status": executor_status,
            }
        )
    if complete:
        events.append(
            {"timestamp": "2026-07-04T02:05:00+00:00", "event": "run_progress_finished"}
        )
    write_jsonl(run_root / "progress_events.jsonl", events)
    if complete:
        write_json(run_root / "summary.json", {"run_id": run_id, "batches": []})
    return run_root
