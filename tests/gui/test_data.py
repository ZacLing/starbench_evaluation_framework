"""Run listing and detail readers in ``starbench.gui.data``."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starbench.gui import data
from helpers import make_run, make_task_run, write_json, write_jsonl


class GuiDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_test_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_list_runs_orders_and_aggregates(self) -> None:
        make_run(
            self.runs_dir,
            "run_pass",
            task_specs=(
                ("demo_task__baseline_01", "success", True),
                ("demo_task__baseline_02", "timeout", False),
            ),
        )
        runs = data.list_runs(self.runs_dir)
        self.assertEqual(len(runs), 1)
        run = runs[0]
        self.assertEqual(run["run_id"], "run_pass")
        self.assertEqual(run["status"], "complete")
        self.assertEqual(run["task_count"], 2)
        self.assertEqual(run["executor_stats"]["success"], 1)
        self.assertEqual(run["executor_stats"]["timeout"], 1)
        self.assertEqual(run["judge_totals"]["single"], 2)
        self.assertEqual(run["judge_passes"]["single"], 1)

    def test_interrupted_run_without_summary(self) -> None:
        run_root = make_run(self.runs_dir, "run_cut", complete=False)
        progress = run_root / "progress_events.jsonl"
        old = progress.stat().st_mtime - 3600
        import os

        os.utime(progress, (old, old))
        runs = data.list_runs(self.runs_dir)
        self.assertEqual(runs[0]["status"], "interrupted")

    def test_active_registry_marks_running(self) -> None:
        make_run(self.runs_dir, "run_live", complete=False)
        runs = data.list_runs(self.runs_dir, active_run_ids={"run_live"})
        self.assertEqual(runs[0]["status"], "running")

    def test_run_detail_rows(self) -> None:
        make_run(self.runs_dir, "run_pass")
        detail = data.run_detail(self.runs_dir, "run_pass")
        self.assertEqual(detail["config"]["executor_agent"], "codex")
        self.assertEqual(len(detail["tasks"]), 1)
        row = detail["tasks"][0]
        self.assertEqual(row["task_id"], "demo_task")
        self.assertTrue(row["judges"]["single"]["overall_pass"])
        self.assertEqual(detail["progress"]["executor_done"], 1)

    def test_task_run_detail_reads_all_surfaces(self) -> None:
        make_run(self.runs_dir, "run_pass")
        detail = data.task_run_detail(self.runs_dir, "run_pass", "demo_task__baseline_01")
        self.assertEqual(detail["task_id"], "demo_task")
        self.assertIn("single", detail["judges"])
        self.assertEqual(detail["rubric_questions"]["R001"], "Does it exist?")
        self.assertEqual(detail["raw_event_count"], 2)
        self.assertIn("All good.", detail["final_message"])
        self.assertEqual(detail["artifact_manifest"]["file_count"], 1)

    def test_raw_events_pagination(self) -> None:
        make_run(self.runs_dir, "run_pass")
        page = data.raw_events(self.runs_dir, "run_pass", "demo_task__baseline_01", 0, 1)
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["events"]), 1)
        self.assertEqual(page["next_offset"], 1)
        page2 = data.raw_events(self.runs_dir, "run_pass", "demo_task__baseline_01", 1, 10)
        self.assertIsNone(page2["next_offset"])

    def test_path_traversal_rejected(self) -> None:
        make_run(self.runs_dir, "run_pass")
        for bad in ("../run_pass", "a/b", ".hidden", "..", ""):
            with self.assertRaises(data.NotFound):
                data.resolve_run_dir(self.runs_dir, bad)
        with self.assertRaises(data.NotFound):
            data.resolve_task_run_dir(self.runs_dir, "run_pass", "../../etc")

    def test_missing_files_render_as_none(self) -> None:
        run_root = self.runs_dir / "run_bare"
        (run_root / "empty_task" / "logs").mkdir(parents=True)
        write_json(run_root / "run_config.json", {"run_id": "run_bare", "task_order": ["empty_task"]})
        detail = data.task_run_detail(self.runs_dir, "run_bare", "empty_task")
        self.assertIsNone(detail["trace_summary"])
        self.assertIsNone(detail["final_message"])
        self.assertIsNone(detail["executor"])
        self.assertFalse(detail["evaluated"])

    def test_list_task_packages(self) -> None:
        tasks_dir = self.tmp / "tasks"
        task = tasks_dir / "demo"
        task.mkdir(parents=True)
        write_json(task / "task.json", {"id": "demo", "name": "Demo", "timeout_seconds": 60})
        write_json(task / "rubrics.json", {"rubrics": [{"id": "R001"}]})
        (task / "prompt.md").write_text("do the task", encoding="utf-8")
        packages = data.list_task_packages(tasks_dir)
        self.assertEqual(packages[0]["id"], "demo")
        self.assertEqual(packages[0]["rubric_count"], 1)
        self.assertFalse(packages[0]["has_human_reference"])
        # New library badge fields: web-search tri-state (unset here) and rigor
        # count (no rigors.json here).
        self.assertIsNone(packages[0]["allow_web_search"])
        self.assertEqual(packages[0]["rigor_count"], 0)
        # A healthy package carries neither error nor warning.
        self.assertIsNone(packages[0]["error"])
        self.assertIsNone(packages[0]["warning"])

    def test_list_task_packages_surfaces_broken_and_warning_entries(self) -> None:
        tasks_dir = self.tmp / "tasks"
        # Unparseable task.json: an honest error entry, never a silent skip.
        broken = tasks_dir / "broken"
        broken.mkdir(parents=True)
        (broken / "task.json").write_text("{not json", encoding="utf-8")
        # Missing prompt file: the runner cannot execute this task.
        promptless = tasks_dir / "promptless"
        promptless.mkdir()
        write_json(promptless / "task.json", {"id": "promptless", "name": "Promptless"})
        write_json(promptless / "rubrics.json", {"rubrics": [{"id": "R001"}]})
        # Zero rubrics: runnable but never scorable, a warning not an error.
        norubrics = tasks_dir / "norubrics"
        norubrics.mkdir()
        write_json(norubrics / "task.json", {"id": "norubrics", "name": "No rubrics"})
        (norubrics / "prompt.md").write_text("do it", encoding="utf-8")

        by_id = {package["id"]: package for package in data.list_task_packages(tasks_dir)}
        self.assertIn("not valid JSON", by_id["broken"]["error"])
        self.assertIn("prompt", by_id["promptless"]["error"])
        self.assertIsNone(by_id["norubrics"]["error"])
        self.assertIn("rubrics", by_id["norubrics"]["warning"])

    def test_list_task_packages_reports_web_search_and_rigor_badges(self) -> None:
        tasks_dir = self.tmp / "tasks"
        task = tasks_dir / "hardened"
        task.mkdir(parents=True)
        write_json(
            task / "task.json",
            {"id": "hardened", "name": "Hardened", "allow_web_search": False},
        )
        write_json(task / "rubrics.json", {"rubrics": [{"id": "R001"}, {"id": "R002"}]})
        write_json(task / "rigors.json", {"rigors": [{"id": "G1"}, {"id": "G2"}, {"id": "G3"}]})
        packages = data.list_task_packages(tasks_dir)
        self.assertEqual(packages[0]["allow_web_search"], False)
        self.assertEqual(packages[0]["rigor_count"], 3)

    def test_rigor_count_survives_broken_rigors_file(self) -> None:
        tasks_dir = self.tmp / "tasks"
        task = tasks_dir / "broken"
        task.mkdir(parents=True)
        write_json(task / "task.json", {"id": "broken", "name": "Broken"})
        (task / "rigors.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(data.rigor_count(task, {"id": "broken"}), 0)


class RunLiveTest(unittest.TestCase):
    """The ``run_live`` reader behind ``/api/runs/<id>/live``."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_live_test_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_inflight_run(self, run_id: str = "run_live") -> Path:
        """A run mid-flight: done, judging, failed, executing, pending lanes."""
        run_root = self.runs_dir / run_id
        run_root.mkdir()
        order = ["t_done", "t_judging", "t_failed", "t_exec", "t_pending"]
        write_json(run_root / "run_config.json", {"run_id": run_id, "task_order": order})
        # make_task_run writes logs/status.json with duration_seconds=200.
        make_task_run(run_root, "t_done", executor_status="success", evaluated=True)
        make_task_run(run_root, "t_judging", executor_status="success", evaluated=False)
        make_task_run(run_root, "t_failed", executor_status="failed", evaluated=False)
        exec_logs = run_root / "t_exec" / "logs"
        exec_logs.mkdir(parents=True)
        write_jsonl(
            exec_logs / "events.jsonl",
            [
                {"type": "item.completed", "item": {"type": "reasoning", "text": "thinking hard"}},
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "python solve.py", "status": "completed"},
                },
            ],
        )
        started_at = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        write_jsonl(
            run_root / "progress_events.jsonl",
            [
                {"timestamp": started_at, "event": "run_progress_initialized", "total_executors": 5},
                {"timestamp": started_at, "event": "executor_started", "run_task_id": "t_done"},
                {"timestamp": started_at, "event": "executor_finished", "run_task_id": "t_done", "status": "success", "duration_seconds": 200.0},
                {"timestamp": started_at, "event": "executor_started", "run_task_id": "t_judging"},
                {"timestamp": started_at, "event": "executor_finished", "run_task_id": "t_judging", "status": "success", "duration_seconds": 200.0},
                {"timestamp": started_at, "event": "executor_started", "run_task_id": "t_failed"},
                {"timestamp": started_at, "event": "executor_finished", "run_task_id": "t_failed", "status": "failed", "duration_seconds": 200.0},
                {"timestamp": started_at, "event": "executor_started", "run_task_id": "t_exec"},
            ],
        )
        return run_root

    def test_lane_states_cover_the_lifecycle(self) -> None:
        self._make_inflight_run()
        live = data.run_live(self.runs_dir, "run_live")
        states = {lane["run_task_id"]: lane["state"] for lane in live["tasks"]}
        self.assertEqual(
            states,
            {
                "t_done": "done",
                "t_judging": "judging",
                "t_failed": "failed",
                "t_exec": "executing",
                "t_pending": "pending",
            },
        )
        by_id = {lane["run_task_id"]: lane for lane in live["tasks"]}
        # Finished lanes carry the measured on-disk duration.
        self.assertEqual(by_id["t_done"]["executor_seconds"], 200.0)
        self.assertEqual(by_id["t_done"]["executor_seconds_source"], "measured")
        # The executing lane's duration is wall-clock elapsed, flagged as such.
        self.assertEqual(by_id["t_exec"]["executor_seconds_source"], "elapsed")
        self.assertGreaterEqual(by_id["t_exec"]["executor_seconds"], 29.0)
        # The pending lane has no directory on disk yet and no timing at all.
        self.assertIsNone(by_id["t_pending"]["executor_seconds"])
        self.assertIsNone(by_id["t_pending"]["executor_seconds_source"])

    def test_current_task_tail_is_summarized(self) -> None:
        self._make_inflight_run()
        live = data.run_live(self.runs_dir, "run_live")
        current = live["current"]
        self.assertEqual(current["run_task_id"], "t_exec")
        self.assertEqual(
            current["events"],
            [
                {"type": "reasoning", "summary": "thinking hard"},
                {"type": "command_execution", "summary": "python solve.py"},
            ],
        )

    def test_tail_truncates_and_never_passes_raw_payloads(self) -> None:
        run_root = self._make_inflight_run()
        rows = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": f"step {i}"}}
            for i in range(24)
        ]
        rows.append(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "x" * 500,
                    "aggregated_output": "RAW_PAYLOAD_SENTINEL " * 100,
                    "extra": {"blob": "RAW_PAYLOAD_SENTINEL"},
                },
            }
        )
        write_jsonl(run_root / "t_exec" / "logs" / "events.jsonl", rows)
        live = data.run_live(self.runs_dir, "run_live")
        events = live["current"]["events"]
        self.assertEqual(len(events), data.LIVE_EVENT_TAIL_LIMIT)
        for event in events:
            self.assertEqual(set(event), {"type", "summary"})
            self.assertLessEqual(len(event["summary"]), data.LIVE_SUMMARY_MAX_CHARS)
        # The oversized command is clipped to a one-line excerpt…
        self.assertTrue(events[-1]["summary"].endswith("…"))
        # …and nothing outside {type, summary} ever crosses the boundary.
        self.assertNotIn("RAW_PAYLOAD_SENTINEL", json.dumps(live))

    def test_eta_needs_at_least_two_samples(self) -> None:
        run_root = self.runs_dir / "run_thin"
        run_root.mkdir()
        write_json(
            run_root / "run_config.json",
            {"run_id": "run_thin", "task_order": ["t1", "t2", "t3"]},
        )
        make_task_run(run_root, "t1", executor_status="success", evaluated=True)
        write_jsonl(
            run_root / "progress_events.jsonl",
            [
                {"timestamp": "2026-07-08T02:00:00+00:00", "event": "executor_finished", "run_task_id": "t1", "status": "success"},
            ],
        )
        live = data.run_live(self.runs_dir, "run_thin")
        eta = live["eta"]
        # One sample: the average is honest but no remaining-time estimate.
        self.assertIsNone(eta["estimated_remaining_seconds"])
        self.assertEqual(eta["completed_sample_count"], 1)
        self.assertEqual(eta["average_executor_seconds"], 200.0)
        self.assertEqual(eta["remaining_task_count"], 2)
        # No executor started: nothing is "current", and that is not an error.
        self.assertIsNone(live["current"])

    def test_eta_multiplies_average_by_remaining(self) -> None:
        self._make_inflight_run()
        live = data.run_live(self.runs_dir, "run_live")
        eta = live["eta"]
        # Three measured durations of 200s; t_exec + t_pending remain.
        self.assertEqual(eta["completed_sample_count"], 3)
        self.assertEqual(eta["average_executor_seconds"], 200.0)
        self.assertEqual(eta["remaining_task_count"], 2)
        self.assertEqual(eta["estimated_remaining_seconds"], 400.0)

    def test_missing_events_file_yields_empty_tail(self) -> None:
        run_root = self._make_inflight_run()
        (run_root / "t_exec" / "logs" / "events.jsonl").unlink()
        live = data.run_live(self.runs_dir, "run_live")
        self.assertEqual(live["current"]["events"], [])

    def test_run_live_rejects_traversal_and_unsafe_lane_names(self) -> None:
        run_root = self._make_inflight_run()
        for bad in ("../run_live", "a/b", "..", ""):
            with self.assertRaises(data.NotFound):
                data.run_live(self.runs_dir, bad)
        # Unsafe names in task_order never become lanes (and never drive reads).
        write_json(
            run_root / "run_config.json",
            {"run_id": "run_live", "task_order": ["../escape", "t_done"]},
        )
        live = data.run_live(self.runs_dir, "run_live")
        lane_ids = [lane["run_task_id"] for lane in live["tasks"]]
        self.assertNotIn("../escape", lane_ids)
        self.assertIn("t_done", lane_ids)


if __name__ == "__main__":
    unittest.main()
