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
        # A bare run carries no measurement contract: null, honestly.
        self.assertIsNone(detail["profile_snapshot"])

    def test_run_detail_reads_profile_snapshot(self) -> None:
        run_root = make_run(self.runs_dir, "run_profiled")
        snapshot = {
            "schema_version": 1,
            "captured_at": "2026-07-09T08:00:00+00:00",
            "profile": {"id": "hsw", "rev": 2, "name": "HSW sweep"},
            "contender": {"agent": "codex", "model": "gpt-5.5"},
            "roster": [{"agent": "codex", "model": "gpt-5.5"}],
            "instrument": {
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "env",
                "judge_mode": "single",
            },
            "execution": {
                "seed": 123,
                "batch_size": 1,
                "repeat": 5,
                "executor_backend": "local",
                "executor_auth_mode": "env",
            },
            "task_set": {"tasks_dir": "tasks", "task_ids": ["demo_task"]},
        }
        write_json(run_root / "profile_snapshot.json", snapshot)
        detail = data.run_detail(self.runs_dir, "run_profiled")
        self.assertEqual(detail["profile_snapshot"], snapshot)

    def test_run_detail_unreadable_profile_snapshot_is_null(self) -> None:
        run_root = make_run(self.runs_dir, "run_broken_snapshot")
        (run_root / "profile_snapshot.json").write_text("{not json", encoding="utf-8")
        detail = data.run_detail(self.runs_dir, "run_broken_snapshot")
        self.assertIsNone(detail["profile_snapshot"])

    def test_list_runs_carries_profile_marker(self) -> None:
        run_root = make_run(self.runs_dir, "run_adhoc")
        write_json(
            run_root / "profile_snapshot.json",
            {
                "schema_version": 1,
                "profile": {"id": "hsw", "rev": 3, "name": "HSW sweep"},
                "modified": True,
                "modified_fields": ["repeat"],
            },
        )
        runs = data.list_runs(self.runs_dir)
        self.assertEqual(runs[0]["profile"], {"id": "hsw", "rev": 3, "modified": True})

    def test_list_runs_profile_marker_defaults_modified_false(self) -> None:
        # A snapshot from before the deviation record (no `modified` key)
        # reads as a faithful profile launch.
        run_root = make_run(self.runs_dir, "run_faithful")
        write_json(
            run_root / "profile_snapshot.json",
            {"profile": {"id": "hsw", "rev": 1, "name": "HSW sweep"}},
        )
        runs = data.list_runs(self.runs_dir)
        self.assertEqual(runs[0]["profile"], {"id": "hsw", "rev": 1, "modified": False})

    def test_list_runs_profile_marker_soft_fails_to_null(self) -> None:
        make_run(self.runs_dir, "run_bare")  # no snapshot at all
        broken = make_run(self.runs_dir, "run_broken")
        (broken / "profile_snapshot.json").write_text("{not json", encoding="utf-8")
        malformed = make_run(self.runs_dir, "run_malformed")
        write_json(
            malformed / "profile_snapshot.json", {"profile": {"id": "hsw"}}  # no rev
        )
        rows = {row["run_id"]: row for row in data.list_runs(self.runs_dir)}
        self.assertEqual(len(rows), 3, "a bad snapshot never hides a run")
        self.assertIsNone(rows["run_bare"]["profile"])
        self.assertIsNone(rows["run_broken"]["profile"])
        self.assertIsNone(rows["run_malformed"]["profile"])

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


class TraceReplayTest(unittest.TestCase):
    """The ``task_trace`` assembler behind ``/api/runs/<id>/tasks/<tid>/trace``."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_trace_test_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.run_root = make_run(self.runs_dir, "run_trace")
        self.events = self.run_root / "demo_task__baseline_01" / "logs" / "events.jsonl"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_events(self, lines: list) -> None:
        self.events.write_text(
            "\n".join(
                line if isinstance(line, str) else json.dumps(line) for line in lines
            )
            + "\n",
            encoding="utf-8",
        )

    def _trace(self, offset: int = 0, limit: int = 200) -> dict:
        return data.task_trace(self.runs_dir, "run_trace", "demo_task__baseline_01", offset, limit)

    def test_compat_events_normalize_to_typed_entries(self) -> None:
        self._write_events(
            [
                {"type": "thread.started", "thread_id": "t1"},
                {
                    "type": "item.completed",
                    "item": {"type": "reasoning", "id": "r1", "text": "think hard"},
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "python hello.py",
                        "exit_code": 0,
                        "status": "completed",
                        "aggregated_output": "hello world",
                    },
                },
                {
                    "type": "item.completed",
                    "item": {"type": "file_change", "changes": [{"path": "outputs/hello.py"}]},
                },
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "done, see outputs/"},
                },
                {"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}},
            ]
        )
        trace = self._trace()
        self.assertTrue(trace["has_events"])
        self.assertEqual(trace["total"], 6)
        types = [entry["type"] for entry in trace["entries"]]
        self.assertEqual(
            types, ["lifecycle", "reasoning", "command", "file_change", "message", "lifecycle"]
        )
        command = trace["entries"][2]
        self.assertEqual(command["title"], "python hello.py")
        self.assertIn("hello world", command["body"])
        self.assertIn("exit 0", command["body"])
        # Indexes are physical line positions — stable anchors.
        self.assertEqual([entry["index"] for entry in trace["entries"]], list(range(6)))
        # These events carry no timestamps: offsets are null, never invented.
        self.assertTrue(all(entry["seconds_offset"] is None for entry in trace["entries"]))

    def test_claude_stream_json_events_normalize(self) -> None:
        self._write_events(
            [
                {"type": "system", "subtype": "init", "model": "claude-x"},
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "thinking", "thinking": "let me look"},
                            {
                                "type": "tool_use",
                                "id": "tu1",
                                "name": "Bash",
                                "input": {"command": "ls outputs"},
                            },
                        ]
                    },
                },
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "tu1",
                                "content": [{"type": "text", "text": "hello.py"}],
                            }
                        ]
                    },
                },
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "All done."}]},
                },
                {"type": "result", "usage": {"input_tokens": 9}},
            ]
        )
        trace = self._trace()
        types = [entry["type"] for entry in trace["entries"]]
        self.assertEqual(types, ["lifecycle", "command", "command", "message", "lifecycle"])
        self.assertEqual(trace["entries"][1]["title"], "ls outputs")
        self.assertIn("[thinking]", trace["entries"][1]["body"])
        self.assertEqual(trace["entries"][2]["title"], "tool result")
        self.assertIn("hello.py", trace["entries"][2]["body"])
        self.assertEqual(trace["entries"][3]["title"], "All done.")

    def test_bad_lines_degrade_to_other_and_are_never_dropped(self) -> None:
        self._write_events(
            [
                "not json at all {{{",
                {"type": "totally.unknown", "payload": {"x": 1}},
                {"type": "item.completed", "item": {"type": "mystery_item"}},
            ]
        )
        trace = self._trace()
        self.assertEqual(trace["total"], 3)
        self.assertEqual([entry["type"] for entry in trace["entries"]], ["other"] * 3)
        self.assertEqual(trace["entries"][0]["title"], "unparseable event line")
        self.assertIn("not json at all", trace["entries"][0]["body"])
        self.assertIn('"totally.unknown"', trace["entries"][1]["body"])

    def test_long_bodies_are_truncated_and_flagged(self) -> None:
        self._write_events(
            [
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "yes",
                        "aggregated_output": "y" * (data.TRACE_BODY_MAX_CHARS + 500),
                    },
                }
            ]
        )
        entry = self._trace()["entries"][0]
        self.assertTrue(entry["truncated"])
        self.assertEqual(len(entry["body"]), data.TRACE_BODY_MAX_CHARS)

    def test_pagination_counts_every_line(self) -> None:
        self._write_events(
            ["bad line"] + [{"type": "item.completed", "item": {"type": "agent_message", "text": f"m{i}"}} for i in range(5)]
        )
        page = self._trace(offset=0, limit=2)
        self.assertEqual(page["total"], 6)
        self.assertEqual(len(page["entries"]), 2)
        self.assertEqual(page["next_offset"], 2)
        last = self._trace(offset=4, limit=10)
        self.assertEqual(len(last["entries"]), 2)
        self.assertIsNone(last["next_offset"])
        self.assertEqual(last["entries"][0]["index"], 4)

    def test_timestamps_become_seconds_offsets(self) -> None:
        self._write_events(
            [
                {"type": "thread.started", "timestamp": "2026-07-04T02:00:00+00:00"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "hi"}},
                {"type": "turn.completed", "timestamp": "2026-07-04T02:00:12.500+00:00"},
            ]
        )
        entries = self._trace()["entries"]
        self.assertEqual(entries[0]["seconds_offset"], 0.0)
        self.assertIsNone(entries[1]["seconds_offset"])
        self.assertEqual(entries[2]["seconds_offset"], 12.5)

    def test_missing_events_file_reports_has_events_false(self) -> None:
        self.events.unlink()
        trace = self._trace()
        self.assertFalse(trace["has_events"])
        self.assertEqual(trace["entries"], [])
        self.assertEqual(trace["total"], 0)


class ArtifactReaderTest(unittest.TestCase):
    """The ``read_artifact`` reader behind ``…/artifact?path=``."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_artifact_test_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.run_root = make_run(self.runs_dir, "run_art")
        self.outputs = self.run_root / "demo_task__baseline_01" / "workspace" / "outputs"
        self.outputs.mkdir(parents=True)
        (self.outputs / "report.md").write_text("# Report\n\nbody", encoding="utf-8")
        (self.outputs / "sub").mkdir()
        (self.outputs / "sub" / "notes.txt").write_text("nested", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read(self, rel: str) -> dict:
        return data.read_artifact(self.runs_dir, "run_art", "demo_task__baseline_01", rel)

    def test_reads_text_content(self) -> None:
        payload = self._read("report.md")
        self.assertEqual(payload["path"], "report.md")
        self.assertEqual(payload["content"], "# Report\n\nbody")
        self.assertFalse(payload["is_binary"])
        self.assertFalse(payload["truncated"])
        nested = self._read("sub/notes.txt")
        self.assertEqual(nested["content"], "nested")

    def test_rejects_traversal_and_absolute_paths(self) -> None:
        # A real secret outside outputs that traversal would otherwise reach.
        secret = self.run_root / "demo_task__baseline_01" / "workspace" / "secret.txt"
        secret.write_text("secret", encoding="utf-8")
        for bad in ("../secret.txt", "../../logs/final.md", str(secret), "/etc/hosts", ""):
            with self.assertRaises(data.NotFound):
                self._read(bad)

    def test_rejects_symlink_escape(self) -> None:
        secret = self.tmp / "outside.txt"
        secret.write_text("outside", encoding="utf-8")
        (self.outputs / "sneaky.txt").symlink_to(secret)
        with self.assertRaises(data.NotFound):
            self._read("sneaky.txt")

    def test_binary_files_are_flagged_not_decoded(self) -> None:
        (self.outputs / "blob.bin").write_bytes(b"PK\x00\x01\x02")
        payload = self._read("blob.bin")
        self.assertTrue(payload["is_binary"])
        self.assertIsNone(payload["content"])

    def test_oversize_files_return_metadata_only(self) -> None:
        big = self.outputs / "big.txt"
        big.write_text("x" * (data.ARTIFACT_MAX_BYTES + 10), encoding="utf-8")
        payload = self._read("big.txt")
        self.assertTrue(payload["truncated"])
        self.assertIsNone(payload["content"])
        self.assertEqual(payload["size_bytes"], data.ARTIFACT_MAX_BYTES + 10)

    def test_missing_outputs_dir_is_not_found(self) -> None:
        shutil.rmtree(self.outputs)
        with self.assertRaises(data.NotFound):
            self._read("report.md")


class VariantGroupTest(unittest.TestCase):
    """Sibling derivation for the Deliverables variant switcher."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_variant_test_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_variant_group_lists_same_base_task_only(self) -> None:
        run_root = self.runs_dir / "run_ablate"
        run_root.mkdir()
        write_json(
            run_root / "run_config.json",
            {
                "run_id": "run_ablate",
                "task_order": [
                    "demo_task",
                    "demo_task__step01",
                    "demo_task__step01__002",
                    "other_task",
                ],
            },
        )
        make_task_run(run_root, "demo_task", task_id="demo_task", instruction_variant="baseline")
        make_task_run(
            run_root, "demo_task__step01", task_id="demo_task", instruction_variant="step01"
        )
        make_task_run(
            run_root,
            "demo_task__step01__002",
            task_id="demo_task",
            instruction_variant="step01",
            evaluated=False,
        )
        make_task_run(run_root, "other_task", task_id="other_task")

        detail = data.task_run_detail(self.runs_dir, "run_ablate", "demo_task__step01")
        group = detail["variant_group"]
        self.assertEqual(
            [row["run_task_id"] for row in group],
            ["demo_task", "demo_task__step01", "demo_task__step01__002"],
        )
        self.assertEqual(
            [row["instruction_variant"] for row in group], ["baseline", "step01", "step01"]
        )
        # The unevaluated repeat is still derivable from its manifest.
        self.assertFalse(group[2]["evaluated"])
        # Identity comes from recorded metadata, not the directory name.
        self.assertEqual(detail["task_id"], "demo_task")
        self.assertEqual(detail["instruction_variant"], "step01")

    def test_unknown_identity_yields_empty_group(self) -> None:
        run_root = self.runs_dir / "run_bare"
        (run_root / "mystery" / "logs").mkdir(parents=True)
        write_json(run_root / "run_config.json", {"run_id": "run_bare", "task_order": ["mystery"]})
        detail = data.task_run_detail(self.runs_dir, "run_bare", "mystery")
        self.assertEqual(detail["variant_group"], [])

    def test_outputs_listing_fallback_when_manifest_missing(self) -> None:
        run_root = self.runs_dir / "run_nomanifest"
        task_root = run_root / "demo_task"
        (task_root / "logs").mkdir(parents=True)
        outputs = task_root / "workspace" / "outputs"
        (outputs / "docs").mkdir(parents=True)
        (outputs / "docs" / "a.md").write_text("hi", encoding="utf-8")
        write_json(run_root / "run_config.json", {"run_id": "run_nomanifest", "task_order": ["demo_task"]})

        detail = data.task_run_detail(self.runs_dir, "run_nomanifest", "demo_task")
        self.assertIsNone(detail["artifact_manifest"])
        listing = detail["outputs_listing"]
        self.assertEqual(listing["file_count"], 1)
        self.assertIn(
            {"path": "docs/a.md", "kind": "file", "size_bytes": 2}, listing["entries"]
        )
        self.assertFalse(listing["truncated"])

    def test_outputs_listing_absent_when_manifest_present(self) -> None:
        make_run(self.runs_dir, "run_ok")
        detail = data.task_run_detail(self.runs_dir, "run_ok", "demo_task__baseline_01")
        self.assertIsNotNone(detail["artifact_manifest"])
        self.assertIsNone(detail["outputs_listing"])


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


class CoverageTest(unittest.TestCase):
    """The ``coverage`` assembler behind ``/api/coverage``.

    Fixture layout (all under one tmp dir):
      - library: ``demo_task`` + ``untouched_task`` (never run)
      - run_a (codex::gpt-5.5): demo_task ×2 judged-fail, ×3 unjudged repeats,
        plus ghost_task (judged-fail, not in the library)
      - run_b (codex::gpt-5.5): demo_task ×1 judged-fail → same cell as run_a
      - run_c (claude::claude-opus-4-8): demo_task ×1 judged-PASS → breached
      - run_broken: no run_config at all → "unknown" column; contains an
        identity-less task run (skipped), ``bare_task`` with only a manifest
        (no timestamps anywhere → last_tested null) and ``mtime_task`` whose
        status.json has no ended_at (falls back to file mtime).
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_coverage_test_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"

        for task_id in ("demo_task", "untouched_task"):
            package = self.tasks_dir / task_id
            package.mkdir(parents=True)
            write_json(package / "task.json", {"id": task_id, "name": task_id})
            write_json(package / "rubrics.json", {"rubrics": [{"id": "R001"}]})
            (package / "prompt.md").write_text("do the task", encoding="utf-8")

        run_a = make_run(
            self.runs_dir,
            "run_a",
            task_specs=(
                ("demo_task__baseline_01", "success", False),
                ("demo_task__baseline_02", "success", False),
            ),
        )
        for repeat in ("03", "04", "05"):
            make_task_run(run_a, f"demo_task__baseline_{repeat}", evaluated=False)
        make_task_run(run_a, "ghost_task_01", task_id="ghost_task", overall_pass=False)

        make_run(
            self.runs_dir,
            "run_b",
            task_specs=(("demo_task__baseline_01", "success", False),),
        )

        make_run(
            self.runs_dir,
            "run_c",
            task_specs=(("demo_task__baseline_01", "success", True),),
        )
        self._patch_config("run_c", executor_agent="claude", executor_model="claude-opus-4-8")

        # A corrupted run: discoverable (progress events) but no run_config.
        broken = self.runs_dir / "run_broken"
        (broken / "mystery" / "logs").mkdir(parents=True)  # no identity → skipped
        bare = broken / "bare_task_01"
        (bare / "logs").mkdir(parents=True)
        write_json(bare / "manifest.json", {"task_id": "bare_task"})
        stale = broken / "mtime_task_01"
        (stale / "logs").mkdir(parents=True)
        write_json(stale / "manifest.json", {"task_id": "mtime_task"})
        write_json(stale / "logs" / "status.json", {"status": "success"})  # no ended_at
        write_jsonl(
            broken / "progress_events.jsonl",
            [{"timestamp": "2026-07-04T02:00:00+00:00", "event": "run_progress_initialized"}],
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _patch_config(self, run_id: str, **overrides) -> None:
        path = self.runs_dir / run_id / "run_config.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update(overrides)
        write_json(path, payload)

    def _coverage(self) -> dict:
        return data.coverage(self.runs_dir, [self.tasks_dir])

    @staticmethod
    def _row(payload: dict, task_id: str) -> dict:
        return next(row for row in payload["rows"] if row["task_id"] == task_id)

    @staticmethod
    def _cell(row: dict, column_key: str) -> dict:
        return next(cell for cell in row["cells"] if cell["column_key"] == column_key)

    def test_same_config_repeats_aggregate_into_one_cell(self) -> None:
        payload = self._coverage()
        cell = self._cell(self._row(payload, "demo_task"), "codex::gpt-5.5")
        # run_a: 2 judged + 3 unjudged repeats; run_b: 1 judged — one cell.
        self.assertEqual(cell["total"], 6)
        self.assertEqual(cell["judged"], 3)
        self.assertEqual(cell["passed"], 0)
        codex = next(col for col in payload["columns"] if col["key"] == "codex::gpt-5.5")
        self.assertEqual(codex["run_count"], 2)

    def test_distinct_configs_become_columns_sorted_by_agent_then_model(self) -> None:
        payload = self._coverage()
        self.assertEqual(
            [col["key"] for col in payload["columns"]],
            ["claude::claude-opus-4-8", "codex::gpt-5.5", "unknown::"],
        )
        unknown = payload["columns"][-1]
        self.assertEqual(unknown["agent"], "unknown")
        self.assertIsNone(unknown["model"])
        self.assertEqual(unknown["run_count"], 1)

    def test_any_pass_breaches_the_row_and_breached_rows_sort_first(self) -> None:
        payload = self._coverage()
        self.assertEqual(
            [row["task_id"] for row in payload["rows"]],
            ["demo_task", "bare_task", "ghost_task", "mtime_task", "untouched_task"],
        )
        demo = payload["rows"][0]
        self.assertTrue(demo["breached"])
        self.assertEqual(self._cell(demo, "claude::claude-opus-4-8")["passed"], 1)
        # codex (3 judged) + claude (1 judged) count; the unknown column has
        # no demo_task cell at all.
        self.assertEqual(demo["tested_columns"], 2)
        self.assertTrue(all(not row["breached"] for row in payload["rows"][1:]))

    def test_library_task_never_run_is_a_zero_cell_row(self) -> None:
        row = self._row(self._coverage(), "untouched_task")
        self.assertTrue(row["in_library"])
        self.assertEqual(row["cells"], [])
        self.assertEqual(row["tested_columns"], 0)
        self.assertFalse(row["breached"])

    def test_run_only_task_is_marked_not_in_library(self) -> None:
        payload = self._coverage()
        self.assertFalse(self._row(payload, "ghost_task")["in_library"])
        self.assertTrue(self._row(payload, "demo_task")["in_library"])

    def test_unjudged_task_run_counts_total_not_judged(self) -> None:
        cell = self._cell(self._row(self._coverage(), "bare_task"), "unknown::")
        self.assertEqual(cell["total"], 1)
        self.assertEqual(cell["judged"], 0)
        self.assertEqual(cell["passed"], 0)
        # No task_summary, no status timestamps: honest null, never estimated.
        self.assertIsNone(cell["last_tested"])

    def test_broken_run_degrades_to_unknown_and_never_sinks_payload(self) -> None:
        payload = self._coverage()
        self.assertEqual(payload["runs_scanned"], 4)
        task_ids = [row["task_id"] for row in payload["rows"]]
        # The identity-less task run is skipped, never guessed from its name.
        self.assertNotIn("mystery", task_ids)
        self.assertNotIn(None, task_ids)
        self.assertIsInstance(payload["generated_at"], str)

    def test_last_tested_falls_back_to_file_mtime_when_unrecorded(self) -> None:
        cell = self._cell(self._row(self._coverage(), "mtime_task"), "unknown::")
        # status.json exists but carries no ended_at → its mtime, still ISO.
        self.assertIsNotNone(cell["last_tested"])
        datetime.fromisoformat(cell["last_tested"])  # parseable, no exception

    def test_last_tested_and_recent_refs_are_newest_first_capped_at_five(self) -> None:
        newer = "2026-07-06T09:00:00+00:00"
        summary_path = self.runs_dir / "run_b" / "demo_task__baseline_01" / "task_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["executor"]["ended_at"] = newer
        write_json(summary_path, summary)

        cell = self._cell(self._row(self._coverage(), "demo_task"), "codex::gpt-5.5")
        self.assertEqual(cell["last_tested"], newer)
        self.assertEqual(len(cell["recent_refs"]), 5)  # 6 task runs, capped
        self.assertEqual(
            cell["recent_refs"][0],
            {"run_id": "run_b", "run_task_id": "demo_task__baseline_01"},
        )
        # The remaining refs tie on timestamp and keep run/task order.
        self.assertEqual(
            [ref["run_task_id"] for ref in cell["recent_refs"][1:]],
            [
                "demo_task__baseline_01",
                "demo_task__baseline_02",
                "demo_task__baseline_03",
                "demo_task__baseline_04",
            ],
        )
        self.assertTrue(all(ref["run_id"] == "run_a" for ref in cell["recent_refs"][1:]))

    # -- roster overlay ----------------------------------------------------

    def _write_profiles(self, profiles: list, default: object = None) -> None:
        write_json(
            self.runs_dir / "profiles.json",
            {"default_profile_id": default, "profiles": profiles},
        )

    def test_absent_profiles_file_is_pure_disk_induction(self) -> None:
        # No profiles.json (and the built-in HSW profile carries an empty
        # roster): the matrix is inducted purely from disk.
        payload = self._coverage()
        self.assertIsNone(payload["profile"])
        self.assertTrue(all(col["rostered"] is False for col in payload["columns"]))

    def test_roster_columns_lead_and_carry_the_rostered_flag(self) -> None:
        self._write_profiles(
            [
                {
                    "id": "hsw",
                    "rev": 4,
                    "name": "HSW sweep",
                    "roster": [
                        {"agent": "claude", "model": "claude-opus-4-8"},
                        {"agent": "codex", "model": "gpt-5.5"},
                        {"agent": "gemini", "model": "gemini-3.1-pro"},
                    ],
                }
            ]
        )
        payload = self._coverage()
        # Rostered columns lead in declaration order; the observed-only
        # "unknown::" config sorts after them.
        self.assertEqual(
            [col["key"] for col in payload["columns"]],
            [
                "claude::claude-opus-4-8",
                "codex::gpt-5.5",
                "gemini::gemini-3.1-pro",
                "unknown::",
            ],
        )
        self.assertEqual(
            {col["key"]: col["rostered"] for col in payload["columns"]},
            {
                "claude::claude-opus-4-8": True,
                "codex::gpt-5.5": True,
                "gemini::gemini-3.1-pro": True,
                "unknown::": False,
            },
        )
        self.assertEqual(payload["profile"], {"id": "hsw", "name": "HSW sweep", "rev": 4})

    def test_rostered_config_never_observed_is_a_zero_cell_column(self) -> None:
        self._write_profiles(
            [
                {
                    "id": "hsw",
                    "rev": 4,
                    "name": "HSW sweep",
                    "roster": [
                        {"agent": "codex", "model": "gpt-5.5"},
                        {"agent": "gemini", "model": "gemini-3.1-pro"},
                    ],
                }
            ]
        )
        payload = self._coverage()
        gemini = next(col for col in payload["columns"] if col["key"] == "gemini::gemini-3.1-pro")
        self.assertTrue(gemini["rostered"])
        # In the roster, never run: a column with no runs behind it…
        self.assertEqual(gemini["run_count"], 0)
        # …and no task row carries a cell for it — the hole in the denominator.
        for row in payload["rows"]:
            self.assertNotIn(
                "gemini::gemini-3.1-pro", [cell["column_key"] for cell in row["cells"]]
            )

    def test_empty_roster_is_not_a_roster_source(self) -> None:
        # A profile whose roster is empty declares no denominator: fall back.
        self._write_profiles([{"id": "bare", "rev": 1, "name": "Bare", "roster": []}])
        payload = self._coverage()
        self.assertIsNone(payload["profile"])
        self.assertEqual(
            [col["key"] for col in payload["columns"]],
            ["claude::claude-opus-4-8", "codex::gpt-5.5", "unknown::"],
        )
        self.assertTrue(all(not col["rostered"] for col in payload["columns"]))

    def test_profile_id_selects_a_named_roster(self) -> None:
        self._write_profiles(
            [
                {
                    "id": "first",
                    "rev": 1,
                    "name": "First",
                    "roster": [{"agent": "codex", "model": "gpt-5.5"}],
                },
                {
                    "id": "second",
                    "rev": 2,
                    "name": "Second",
                    "roster": [{"agent": "claude", "model": "claude-opus-4-8"}],
                },
            ]
        )
        # Default: the first profile carrying a non-empty roster.
        self.assertEqual(
            data.coverage(self.runs_dir, [self.tasks_dir])["profile"]["id"], "first"
        )
        # An explicit id overrides the default selection.
        payload = data.coverage(self.runs_dir, [self.tasks_dir], "second")
        self.assertEqual(payload["profile"], {"id": "second", "name": "Second", "rev": 2})
        claude = next(c for c in payload["columns"] if c["key"] == "claude::claude-opus-4-8")
        self.assertTrue(claude["rostered"])
        # codex was observed on disk but is not in the "second" roster.
        codex = next(c for c in payload["columns"] if c["key"] == "codex::gpt-5.5")
        self.assertFalse(codex["rostered"])


if __name__ == "__main__":
    unittest.main()
