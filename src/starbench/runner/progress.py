from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from ..contracts import ARTIFACT_SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StageBar:
    def __init__(self, total: int, description: str, *, enabled: bool) -> None:
        self.total = total
        self.description = description
        self.current = 0
        self._bar = None
        if enabled:
            try:
                from tqdm import tqdm

                self._bar = tqdm(total=total, desc=description, unit="unit", dynamic_ncols=True)
            except Exception:
                self._bar = None

    def update(self, amount: int = 1, postfix: Dict[str, Any] | None = None) -> None:
        self.current += amount
        if self._bar is not None:
            if postfix:
                self._bar.set_postfix(postfix, refresh=False)
            self._bar.update(amount)
            return
        if postfix:
            details = " ".join(f"{key}={value}" for key, value in postfix.items())
            print(f"{self.description}: {self.current}/{self.total} {details}", file=sys.stderr, flush=True)
        else:
            print(f"{self.description}: {self.current}/{self.total}", file=sys.stderr, flush=True)

    def note(self, postfix: Dict[str, Any]) -> None:
        if self._bar is not None:
            self._bar.set_postfix(postfix, refresh=True)
        else:
            details = " ".join(f"{key}={value}" for key, value in postfix.items())
            print(f"{self.description}: {self.current}/{self.total} {details}", file=sys.stderr, flush=True)

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()


class BenchmarkProgress:
    def __init__(
        self,
        *,
        run_root: Path,
        total_executors: int,
        total_evaluators: int,
        enabled: bool,
    ) -> None:
        self.enabled = enabled
        self.events_path = run_root / "progress_events.jsonl"
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.executor_bar = StageBar(total_executors, "executors", enabled=enabled)
        self.evaluator_bar = StageBar(total_evaluators, "evaluators", enabled=enabled) if total_evaluators else None
        self.executor_stats = {"success": 0, "failed": 0, "timeout": 0}
        self.evaluator_stats = {"success": 0, "failed": 0, "timeout": 0, "skipped": 0}
        self.write_event(
            "run_progress_initialized",
            total_executors=total_executors,
            total_evaluators=total_evaluators,
            progress_enabled=enabled,
        )

    def write_event(self, event: str, **payload: Any) -> None:
        row = {
            "timestamp": utc_now(),
            "event": event,
            **payload,
            "schema_version": ARTIFACT_SCHEMA_VERSION,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    def batch_started(self, *, batch_index: int, run_task_ids: Iterable[str]) -> None:
        ids = list(run_task_ids)
        self.write_event("batch_started", batch_index=batch_index, run_task_ids=ids, batch_size=len(ids))
        self.executor_bar.note({"batch": batch_index, "active": len(ids), "last": ids[-1] if ids else "-"})

    def batch_finished(self, *, batch_index: int, run_task_ids: Iterable[str]) -> None:
        ids = list(run_task_ids)
        self.write_event("batch_finished", batch_index=batch_index, run_task_ids=ids, batch_size=len(ids))

    def executor_started(self, *, run_task_id: str, task_id: str) -> None:
        self.write_event("executor_started", run_task_id=run_task_id, task_id=task_id)
        self.executor_bar.note({"active": run_task_id, **self.executor_stats})

    def executor_finished(self, *, run_task_id: str, task_id: str, status: Dict[str, Any]) -> None:
        state = str(status.get("status") or "failed")
        if state not in self.executor_stats:
            state = "failed"
        self.executor_stats[state] += 1
        duration = status.get("duration_seconds")
        self.write_event(
            "executor_finished",
            run_task_id=run_task_id,
            task_id=task_id,
            status=status.get("status"),
            exit_code=status.get("exit_code"),
            timed_out=status.get("timed_out"),
            duration_seconds=duration,
        )
        self.executor_bar.update(
            postfix={
                "last": run_task_id,
                "sec": round(duration, 1) if isinstance(duration, (int, float)) else "-",
                **self.executor_stats,
            }
        )

    def evaluator_started(self, *, run_task_id: str, mode: str, rubric_id: str | None = None) -> None:
        self.write_event("evaluator_started", run_task_id=run_task_id, mode=mode, rubric_id=rubric_id)
        if self.evaluator_bar is not None:
            label = f"{run_task_id}:{rubric_id}" if rubric_id else run_task_id
            self.evaluator_bar.note({"active": label, "mode": mode, **self.evaluator_stats})

    def evaluator_finished(
        self,
        *,
        run_task_id: str,
        mode: str,
        status: Dict[str, Any] | None,
        aggregate: Dict[str, Any] | None = None,
        rubric_id: str | None = None,
    ) -> None:
        process_status = str((status or {}).get("status") or "failed")
        if process_status not in self.evaluator_stats:
            process_status = "failed"
        self.evaluator_stats[process_status] += 1
        duration = (status or {}).get("duration_seconds")
        self.write_event(
            "evaluator_finished",
            run_task_id=run_task_id,
            mode=mode,
            rubric_id=rubric_id,
            status=(status or {}).get("status"),
            exit_code=(status or {}).get("exit_code"),
            timed_out=(status or {}).get("timed_out"),
            duration_seconds=duration,
            outcome=(aggregate or {}).get("outcome"),
            overall_pass=(aggregate or {}).get("overall_pass"),
            passed_count=(aggregate or {}).get("passed_count"),
            total_count=(aggregate or {}).get("total_count"),
        )
        if self.evaluator_bar is not None:
            label = f"{run_task_id}:{rubric_id}" if rubric_id else run_task_id
            self.evaluator_bar.update(
                postfix={
                    "last": label,
                    "sec": round(duration, 1) if isinstance(duration, (int, float)) else "-",
                    **self.evaluator_stats,
                }
            )

    def evaluator_skipped(
        self,
        *,
        run_task_id: str,
        mode: str,
        aggregate: Dict[str, Any],
        rubric_id: str | None = None,
        reason: str = "executor_not_successful",
    ) -> None:
        self.evaluator_finished(
            run_task_id=run_task_id,
            mode=mode,
            rubric_id=rubric_id,
            status={"status": "skipped", "reason": reason},
            aggregate=aggregate,
        )

    def close(self) -> None:
        self.write_event("run_progress_finished", executor_stats=self.executor_stats, evaluator_stats=self.evaluator_stats)
        self.executor_bar.close()
        if self.evaluator_bar is not None:
            self.evaluator_bar.close()


def make_benchmark_progress(
    *,
    run_root: Path,
    total_executors: int,
    total_evaluators: int,
    enabled: bool,
) -> BenchmarkProgress:
    return BenchmarkProgress(
        run_root=run_root,
        total_executors=total_executors,
        total_evaluators=total_evaluators,
        enabled=enabled,
    )
