from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from starbench.gui import data, experiments, library  # noqa: E402
from starbench.gui.experiments import ExperimentError  # noqa: E402
from starbench.gui.launcher import LaunchError, build_run_argv  # noqa: E402
from starbench.gui.library import LibraryError  # noqa: E402


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
        packages = data.list_task_packages(tasks_dir)
        self.assertEqual(packages[0]["id"], "demo")
        self.assertEqual(packages[0]["rubric_count"], 1)
        self.assertFalse(packages[0]["has_human_reference"])


class LauncherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_launch_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, **overrides):
        base = {
            "run_id": "gui_test",
            "tasks_dir": str(self.tasks_dir),
            "tasks": ["demo"],
            "executor_agent": "codex",
            "evaluator_agent": "claude",
            "judge_mode": "single",
            "auth_mode": "env",
            "executor_backend": "local",
            "executor_model": "gpt-5.5",
            "evaluator_model": "claude-opus-4-8",
            "seed": "7",
        }
        base.update(overrides)
        return base

    def test_builds_expected_argv(self) -> None:
        argv = build_run_argv(self.payload(), runs_dir=self.runs_dir)
        self.assertEqual(argv[0], sys.executable)
        self.assertIn("starbench.runner.run_benchmark", argv)
        self.assertIn("--no-progress", argv)
        joined = " ".join(argv)
        self.assertIn("--task demo", joined)
        self.assertIn("--executor-agent codex", joined)
        self.assertIn("--evaluator-agent claude", joined)
        self.assertIn("--seed 7", joined)
        self.assertNotIn("--docker-image", joined)

    def test_docker_backend_requires_image(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(
                self.payload(executor_backend="docker", docker_image=""),
                runs_dir=self.runs_dir,
            )
        argv = build_run_argv(
            self.payload(executor_backend="docker", docker_image="starbench-codex:latest"),
            runs_dir=self.runs_dir,
        )
        self.assertIn("starbench-codex:latest", argv)

    def test_rejects_bad_run_id_and_duplicates(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(run_id="../evil"), runs_dir=self.runs_dir)
        (self.runs_dir / "gui_test").mkdir()
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(), runs_dir=self.runs_dir)

    def test_rejects_unknown_choice(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(executor_agent="bash"), runs_dir=self.runs_dir)
        with self.assertRaises(LaunchError):
            build_run_argv(self.payload(judge_mode="triple"), runs_dir=self.runs_dir)

    def test_extra_args_are_split(self) -> None:
        argv = build_run_argv(
            self.payload(extra_args="--instruction-mode ablation --repeat 2"),
            runs_dir=self.runs_dir,
        )
        self.assertIn("--instruction-mode", argv)
        self.assertIn("ablation", argv)

    def test_missing_tasks_dir_rejected(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(
                self.payload(tasks_dir=str(self.tmp / "nope")), runs_dir=self.runs_dir
            )


def b64(text: str) -> str:
    import base64

    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def package_files(prefix: str = "") -> list:
    task = {"id": "uploaded_demo", "name": "Uploaded Demo", "timeout_seconds": 60}
    rubrics = {
        "rubrics": [
            {"id": "R001", "fail_fast": True, "expected": True, "question": "Exists?"}
        ]
    }
    return [
        {"path": f"{prefix}task.json", "content_b64": b64(json.dumps(task))},
        {"path": f"{prefix}prompt.md", "content_b64": b64("# Do the thing")},
        {"path": f"{prefix}rubrics.json", "content_b64": b64(json.dumps(rubrics))},
    ]


class LibraryImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_lib_"))
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_package_installs(self) -> None:
        report = library.install_task_package(package_files(), target_dir=self.tasks_dir)
        self.assertTrue(report["valid"])
        self.assertEqual(report["task"]["id"], "uploaded_demo")
        self.assertEqual(report["task"]["rubric_count"], 1)
        installed = self.tasks_dir / "uploaded_demo"
        self.assertTrue((installed / "task.json").is_file())
        self.assertTrue((installed / "rubrics.json").is_file())

    def test_dragged_folder_common_root_is_stripped(self) -> None:
        report = library.install_task_package(
            package_files("my_folder/"), target_dir=self.tasks_dir
        )
        self.assertTrue(report["valid"])
        self.assertTrue((self.tasks_dir / "uploaded_demo" / "task.json").is_file())

    def test_dry_run_reports_without_writing(self) -> None:
        report = library.install_task_package(
            package_files(), target_dir=self.tasks_dir, dry_run=True
        )
        self.assertTrue(report["valid"])
        self.assertFalse((self.tasks_dir / "uploaded_demo").exists())

    def test_missing_pieces_are_reported(self) -> None:
        files = package_files()[:1]  # task.json only
        report = library.install_task_package(files, target_dir=self.tasks_dir, dry_run=True)
        self.assertFalse(report["valid"])
        joined = " ".join(report["errors"])
        self.assertIn("prompt.md", joined)
        self.assertIn("rubrics.json", joined)

    def test_bad_rubrics_json_is_reported(self) -> None:
        files = package_files()
        files[2]["content_b64"] = b64("{not json")
        report = library.install_task_package(files, target_dir=self.tasks_dir, dry_run=True)
        self.assertFalse(report["valid"])
        self.assertTrue(any("rubrics.json" in error for error in report["errors"]))

    def test_path_traversal_rejected(self) -> None:
        files = package_files()
        files[0]["path"] = "../evil/task.json"
        with self.assertRaises(LibraryError):
            library.install_task_package(files, target_dir=self.tasks_dir, dry_run=True)

    def test_existing_package_is_not_overwritten(self) -> None:
        library.install_task_package(package_files(), target_dir=self.tasks_dir)
        with self.assertRaises(LibraryError):
            library.install_task_package(package_files(), target_dir=self.tasks_dir)

    def test_zip_upload_is_expanded(self) -> None:
        import io
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(
                "pkg/task.json", json.dumps({"id": "zipped", "name": "Zipped"})
            )
            archive.writestr("pkg/prompt.md", "# go")
            archive.writestr(
                "pkg/rubrics.json",
                json.dumps(
                    {
                        "rubrics": [
                            {
                                "id": "R001",
                                "fail_fast": True,
                                "expected": True,
                                "question": "?",
                            }
                        ]
                    }
                ),
            )
        import base64 as b64mod

        files = [
            {
                "path": "pkg.zip",
                "content_b64": b64mod.b64encode(buffer.getvalue()).decode("ascii"),
            }
        ]
        report = library.install_task_package(files, target_dir=self.tasks_dir)
        self.assertTrue(report["valid"])
        self.assertTrue((self.tasks_dir / "zipped" / "prompt.md").is_file())


class LibraryBrowseAndDetailTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_fs_", dir=str(Path.home())))
        self.tasks_dir = self.tmp / "tasks"
        (self.tasks_dir / "demo").mkdir(parents=True)
        write_json(
            self.tasks_dir / "demo" / "task.json",
            {"id": "demo", "name": "Demo Task", "timeout_seconds": 30},
        )
        (self.tasks_dir / "demo" / "prompt.md").write_text("# Prompt body", encoding="utf-8")
        write_json(
            self.tasks_dir / "demo" / "rubrics.json",
            {
                "rubrics": [
                    {"id": "R001", "fail_fast": True, "expected": True, "question": "Q?"}
                ]
            },
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_browse_lists_directories_with_task_counts(self) -> None:
        listing = library.browse_directories(str(self.tmp), cwd=self.tmp)
        names = {entry["name"]: entry for entry in listing["dirs"]}
        self.assertIn("tasks", names)
        self.assertEqual(names["tasks"]["task_count"], 1)

    def test_browse_outside_allowed_roots_rejected(self) -> None:
        with self.assertRaises(LibraryError):
            library.browse_directories("/etc", cwd=self.tmp)

    def test_task_detail_returns_prompt_and_rubrics(self) -> None:
        detail = library.task_package_detail(self.tasks_dir, "demo")
        self.assertEqual(detail["id"], "demo")
        self.assertIn("Prompt body", detail["prompt"])
        self.assertEqual(len(detail["rubrics"]), 1)

    def test_task_detail_rejects_traversal(self) -> None:
        with self.assertRaises(LibraryError):
            library.task_package_detail(self.tasks_dir, "../outside")


class ExperimentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_exp_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def experiment_payload(self, **overrides):
        base = {
            "name": "exp_demo",
            "tasks_dir": str(self.tasks_dir),
            "tasks": ["demo_task"],
            "shared": {
                "evaluator_agent": "codex",
                "evaluator_model": "gpt-5.5",
                "evaluator_auth_mode": "global",
                "judge_mode": "single",
                "evaluator_timeout_seconds": 600,
                "executor_backend": "docker",
                "docker_image": "starbench-codex:latest",
                "seed": 7,
                "batch_size": 1,
                "repeat": 1,
            },
            "contenders": [
                {"label": "GPT gpt-5.5", "agent": "codex", "model": "gpt-5.5", "auth_mode": "env"},
                {
                    "label": "Claude opus",
                    "agent": "claude",
                    "model": "claude-opus-4-8",
                    "auth_mode": "global",
                },
            ],
        }
        base.update(overrides)
        return base

    def test_plan_builds_one_run_per_contender(self) -> None:
        plan = experiments.plan_experiment(self.experiment_payload(), runs_dir=self.runs_dir)
        self.assertEqual(len(plan["plans"]), 2)
        run_ids = [item["run_id"] for item in plan["plans"]]
        self.assertEqual(run_ids, ["exp_demo__gpt-gpt-5-5", "exp_demo__claude-opus"])
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--evaluator-agent codex", joined)
            self.assertIn("--evaluator-model gpt-5.5", joined)
            self.assertIn("--seed 7", joined)
            self.assertIn("--evaluator-auth-mode global", joined)

    def test_docker_only_applies_to_codex(self) -> None:
        plan = experiments.plan_experiment(self.experiment_payload(), runs_dir=self.runs_dir)
        by_agent = {item["agent"]: item for item in plan["plans"]}
        self.assertEqual(by_agent["codex"]["backend"], "docker")
        self.assertIn("--docker-image", " ".join(by_agent["codex"]["argv"]))
        self.assertEqual(by_agent["claude"]["backend"], "local")
        self.assertTrue(by_agent["claude"]["backend_downgraded"])
        self.assertNotIn("--docker-image", " ".join(by_agent["claude"]["argv"]))

    def test_record_list_and_detail(self) -> None:
        payload = self.experiment_payload()
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        experiments.record_experiment(
            self.runs_dir, name=plan["name"], payload=payload, plans=plan["plans"]
        )
        make_run(self.runs_dir, "exp_demo__gpt-gpt-5-5")
        listed = experiments.list_experiments(self.runs_dir)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], "exp_demo")
        self.assertEqual(len(listed[0]["runs"]), 2)
        self.assertEqual(listed[0]["runs"][1]["status"], "missing")

        detail = experiments.experiment_detail(self.runs_dir, "exp_demo")
        self.assertEqual(len(detail["contenders"]), 2)
        matrix = detail["matrix"]
        self.assertEqual(matrix[0]["task_id"], "demo_task")
        rubric = matrix[0]["rubrics"][0]
        self.assertIn("exp_demo__gpt-gpt-5-5", rubric["cells"])
        self.assertEqual(rubric["cells"]["exp_demo__gpt-gpt-5-5"]["passed"], 1)

    def test_duplicate_experiment_name_rejected(self) -> None:
        payload = self.experiment_payload()
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        experiments.record_experiment(
            self.runs_dir, name=plan["name"], payload=payload, plans=plan["plans"]
        )
        with self.assertRaises(ExperimentError):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_contender_error_names_the_contender(self) -> None:
        payload = self.experiment_payload(
            contenders=[{"label": "bad", "agent": "bash", "model": "x"}]
        )
        with self.assertRaises(ExperimentError) as ctx:
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        self.assertIn("bad", str(ctx.exception))

    def test_profiles_roundtrip_and_builtin_default(self) -> None:
        loaded = experiments.load_profiles(self.runs_dir)
        self.assertFalse(loaded["persisted"])
        self.assertEqual(loaded["profiles"][0]["id"], "standard")

        saved = experiments.save_profiles(
            self.runs_dir,
            {
                "default_profile_id": "mine",
                "profiles": [
                    {
                        "id": "mine",
                        "name": "Mine",
                        "shared": {"judge_mode": "parallel", "seed": 1},
                        "per_contender_fields": ["model", "credentials"],
                    }
                ],
            },
        )
        self.assertTrue(saved["persisted"])
        reloaded = experiments.load_profiles(self.runs_dir)
        self.assertTrue(reloaded["persisted"])
        self.assertEqual(reloaded["default_profile_id"], "mine")
        self.assertEqual(reloaded["profiles"][0]["shared"]["judge_mode"], "parallel")

    def test_profiles_validation(self) -> None:
        with self.assertRaises(ExperimentError):
            experiments.save_profiles(self.runs_dir, {"profiles": []})
        with self.assertRaises(ExperimentError):
            experiments.save_profiles(
                self.runs_dir,
                {
                    "default_profile_id": "ghost",
                    "profiles": [
                        {"id": "a", "shared": {}, "per_contender_fields": []}
                    ],
                },
            )
        with self.assertRaises(ExperimentError):
            experiments.save_profiles(
                self.runs_dir,
                {
                    "profiles": [
                        {"id": "a", "shared": {}, "per_contender_fields": ["nope"]}
                    ]
                },
            )


class PreflightTest(unittest.TestCase):
    def test_preflight_reports_cli_and_auth_checks(self) -> None:
        checks = library.preflight(
            executor_agent="codex",
            evaluator_agent="claude",
            executor_backend="local",
            docker_image="",
            executor_auth_mode="env",
            evaluator_auth_mode="global",
        )
        ids = [check["id"] for check in checks]
        self.assertIn("executor_cli", ids)
        self.assertIn("evaluator_cli", ids)
        self.assertIn("executor_auth", ids)
        self.assertIn("evaluator_auth", ids)
        for check in checks:
            self.assertIn(check["status"], ("ok", "warn", "fail"))

    def test_preflight_docker_backend_checks_docker(self) -> None:
        checks = library.preflight(
            executor_agent="codex",
            evaluator_agent="codex",
            executor_backend="docker",
            docker_image="definitely-not-an-image:latest",
            executor_auth_mode="env",
            evaluator_auth_mode="env",
        )
        ids = [check["id"] for check in checks]
        self.assertIn("docker", ids)


if __name__ == "__main__":
    unittest.main()
