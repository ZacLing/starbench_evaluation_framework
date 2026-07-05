from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from starbench.gui import agents, data, experiments, library, providers  # noqa: E402
from starbench.gui.experiments import ExperimentError  # noqa: E402
from starbench.gui.launcher import LaunchError, build_run_argv, resolve_env_spec  # noqa: E402
from starbench.gui.library import LibraryError  # noqa: E402
from starbench.gui.providers import ProviderError  # noqa: E402


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

    def test_docker_backend_uses_one_image_per_runtime(self) -> None:
        payload = self.experiment_payload()
        payload["contenders"].append(
            {"label": "Gemini", "agent": "gemini", "model": "gemini-2.5-pro", "auth_mode": "env"}
        )
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        by_agent = {item["agent"]: item for item in plan["plans"]}
        for agent, image in (
            ("codex", "starbench-codex:latest"),
            ("claude", "starbench-claude-code:latest"),
            ("gemini", "starbench-gemini-cli:latest"),
        ):
            self.assertEqual(by_agent[agent]["backend"], "docker")
            self.assertFalse(by_agent[agent]["backend_downgraded"])
            self.assertEqual(by_agent[agent]["docker_image"], image)
            self.assertIn(f"--docker-image {image}", " ".join(by_agent[agent]["argv"]))

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


class ProviderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_prov_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_builtin_presets_until_saved(self) -> None:
        loaded = providers.load_providers(self.runs_dir)
        self.assertFalse(loaded["persisted"])
        ids = {provider["id"] for provider in loaded["providers"]}
        self.assertIn("anthropic", ids)
        self.assertIn("anthropic-cli", ids)
        self.assertIn("vercel-ai-gateway", ids)
        self.assertIn("openrouter", ids)
        by_id = {provider["id"]: provider for provider in loaded["providers"]}
        self.assertEqual(
            by_id["deepseek"]["anthropic_base_url"], "https://api.deepseek.com/anthropic"
        )
        self.assertEqual(
            by_id["vercel-ai-gateway"]["anthropic_base_url"], "https://ai-gateway.vercel.sh"
        )
        for provider in loaded["providers"]:
            self.assertIn("agent", provider)
            self.assertIn("key_present", provider)
            self.assertIn(provider["auth"], ("api_key", "cli_login"))

    def test_save_and_reload(self) -> None:
        saved = providers.save_providers(
            self.runs_dir,
            {
                "providers": [
                    {
                        "id": "yunwu",
                        "name": "Yunwu",
                        "kind": "openai-compatible",
                        "base_url": "https://yunwu.ai/v1",
                        "api_key_env": "YUNWU_KEY",
                        "anthropic_base_url": "https://yunwu.ai/anthropic",
                        "models": ["doubao-seed-2-0-pro-260215", " "],
                    }
                ]
            },
        )
        self.assertTrue(saved["persisted"])
        reloaded = providers.load_providers(self.runs_dir)
        self.assertEqual(reloaded["providers"][0]["agent"], "opencode")
        self.assertEqual(reloaded["providers"][0]["models"], ["doubao-seed-2-0-pro-260215"])
        self.assertEqual(
            reloaded["providers"][0]["anthropic_base_url"], "https://yunwu.ai/anthropic"
        )

    def test_save_validation(self) -> None:
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir, {"providers": [{"id": "x", "kind": "nope", "models": []}]}
            )
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {"id": "a", "kind": "openai", "models": []},
                        {"id": "a", "kind": "openai", "models": []},
                    ]
                },
            )
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir,
                {"providers": [{"id": "a", "kind": "openai", "auth": "nope", "models": []}]},
            )
        with self.assertRaises(ProviderError):
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "gw",
                            "kind": "openai-compatible",
                            "auth": "cli_login",
                            "models": [],
                        }
                    ]
                },
            )

    def test_refresh_models_from_api(self) -> None:
        import os

        calls = {}

        def fake_fetch(url, headers=None):
            calls["url"] = url
            calls["headers"] = headers or {}
            return {"data": [{"id": "m-2"}, {"id": "m-1"}]}

        os.environ["STARBENCH_TEST_KEY"] = "k"
        original = providers._fetch_json
        providers._fetch_json = fake_fetch
        try:
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "gw",
                            "kind": "openai-compatible",
                            "auth": "api_key",
                            "base_url": "https://gw.example/v1",
                            "api_key_env": "STARBENCH_TEST_KEY",
                            "models": [],
                        }
                    ]
                },
            )
            result = providers.refresh_provider_models(self.runs_dir, "gw")
        finally:
            providers._fetch_json = original
            del os.environ["STARBENCH_TEST_KEY"]
        provider = result["providers"][0]
        self.assertEqual(provider["models"], ["m-1", "m-2"])
        self.assertEqual(provider["models_source"], "api")
        self.assertIn("gw.example/v1/models", calls["url"])
        self.assertEqual(calls["headers"].get("Authorization"), "Bearer k")

    def test_refresh_models_cli_login_falls_back_to_catalog(self) -> None:
        def fake_fetch(url, headers=None):
            self.assertIn("ai-gateway.vercel.sh", url)
            return {"data": [{"id": "anthropic/claude-opus-4.8"}, {"id": "openai/gpt-5.5"}]}

        original = providers._fetch_json
        providers._fetch_json = fake_fetch
        try:
            providers.save_providers(
                self.runs_dir,
                {
                    "providers": [
                        {
                            "id": "anthropic-cli",
                            "kind": "anthropic",
                            "auth": "cli_login",
                            "models": [],
                        }
                    ]
                },
            )
            result = providers.refresh_provider_models(self.runs_dir, "anthropic-cli")
        finally:
            providers._fetch_json = original
        provider = result["providers"][0]
        self.assertEqual(provider["models"], ["claude-opus-4.8"])
        self.assertEqual(provider["models_source"], "catalog")

    def test_judge_gateway_conflict_detected(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        payload = {
            "name": "exp_gwconflict",
            "tasks_dir": str(tasks_dir),
            "tasks": [],
            "shared": {
                "evaluator_agent": "opencode",
                "evaluator_gateway": {
                    "opencode_provider": "gw-a",
                    "opencode_base_url": "https://a.example/v1",
                    "opencode_api_key_env": "A_KEY",
                },
                "judge_mode": "single",
            },
            "contenders": [
                {
                    "label": "doubao",
                    "agent": "opencode",
                    "model": "doubao",
                    "auth_mode": "env",
                    "opencode_provider": "gw-b",
                    "opencode_base_url": "https://b.example/v1",
                    "opencode_api_key_env": "B_KEY",
                }
            ],
        }
        with self.assertRaises(ExperimentError):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)

    def test_codex_gateway_conflicts_with_codex_judge(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        payload = {
            "name": "exp_codexgw",
            "tasks_dir": str(tasks_dir),
            "tasks": [],
            "shared": {"evaluator_agent": "codex", "judge_mode": "single"},
            "contenders": [
                {
                    "label": "codex via openrouter",
                    "agent": "codex",
                    "model": "openai/gpt-5.3-codex",
                    "auth_mode": "env",
                    "codex_bin": "codex -c model_provider=openrouter",
                }
            ],
        }
        with self.assertRaises(ExperimentError):
            experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        payload["shared"]["evaluator_agent"] = "claude"
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        joined = plan["plans"][0]["argv"]
        self.assertIn("codex -c model_provider=openrouter", joined)

    def test_judge_gateway_used_when_contender_not_opencode(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir(exist_ok=True)
        payload = {
            "name": "exp_gwjudge",
            "tasks_dir": str(tasks_dir),
            "tasks": [],
            "shared": {
                "evaluator_agent": "opencode",
                "evaluator_model": "doubao-judge",
                "evaluator_gateway": {
                    "opencode_provider": "gw-a",
                    "opencode_base_url": "https://a.example/v1",
                    "opencode_api_key_env": "A_KEY",
                },
                "judge_mode": "single",
            },
            "contenders": [
                {"label": "claude", "agent": "claude", "model": "claude-opus-4-8", "auth_mode": "global"}
            ],
        }
        plan = experiments.plan_experiment(payload, runs_dir=self.runs_dir)
        joined = " ".join(plan["plans"][0]["argv"])
        self.assertIn("--opencode-base-url https://a.example/v1", joined)
        self.assertIn("--opencode-provider gw-a", joined)

    def test_resolve_env_spec(self) -> None:
        import os

        os.environ["STARBENCH_TEST_TOKEN"] = "sekrit"
        try:
            resolved = resolve_env_spec(
                {
                    "ANTHROPIC_BASE_URL": {"value": "https://gw.example"},
                    "ANTHROPIC_AUTH_TOKEN": {"from_env": "STARBENCH_TEST_TOKEN"},
                    "MISSING": {"from_env": "STARBENCH_TEST_ABSENT"},
                }
            )
        finally:
            del os.environ["STARBENCH_TEST_TOKEN"]
        self.assertEqual(resolved["ANTHROPIC_BASE_URL"], "https://gw.example")
        self.assertEqual(resolved["ANTHROPIC_AUTH_TOKEN"], "sekrit")
        self.assertNotIn("MISSING", resolved)

    def test_experiment_plan_carries_env_spec(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir()
        plan = experiments.plan_experiment(
            {
                "name": "exp_env",
                "tasks_dir": str(tasks_dir),
                "tasks": [],
                "shared": {"evaluator_agent": "codex", "judge_mode": "single"},
                "contenders": [
                    {
                        "label": "claude via gateway",
                        "agent": "claude",
                        "model": "claude-opus-4-8",
                        "auth_mode": "env",
                        "env": {
                            "ANTHROPIC_BASE_URL": {"value": "https://gw.example"},
                            "ANTHROPIC_AUTH_TOKEN": {"from_env": "GW_TOKEN"},
                        },
                    }
                ],
            },
            runs_dir=self.runs_dir,
        )
        item = plan["plans"][0]
        self.assertEqual(item["env_keys"], ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"])
        self.assertEqual(item["env_spec"]["ANTHROPIC_BASE_URL"], {"value": "https://gw.example"})


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

    def test_preflight_accepts_custom_bin_and_env_overrides(self) -> None:
        checks = library.preflight(
            executor_agent="custom:qwen-code",
            evaluator_agent="codex",
            executor_backend="local",
            docker_image="",
            executor_auth_mode="env",
            evaluator_auth_mode="env",
            executor_bin="definitely-missing-cli",
            executor_env_keys=["STARBENCH_ABSENT_KEY"],
        )
        by_id = {check["id"]: check for check in checks}
        self.assertEqual(by_id["executor_cli"]["status"], "fail")
        self.assertIn("definitely-missing-cli", by_id["executor_cli"]["label"])
        self.assertIn("STARBENCH_ABSENT_KEY", by_id["executor_auth"]["hint"])


class AgentRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_agents_"))
        self.runtimes_dir = self.tmp / "runtimes"
        self.runtimes_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def qwen_payload(self, **overrides):
        base = {
            "id": "qwen-code",
            "label": "Qwen Code",
            "icon": "qwen",
            "command": "qwen",
            "args": ["--output-format", "json", "--yolo"],
            "judge_args": ["--output-format", "json", "--approval-mode", "plan"],
            "model_flag": "-m",
            "prompt_via": "stdin",
            "parser": "headless-json",
            "protocol": "openai",
            "base_url_env": "OPENAI_BASE_URL",
            "api_key_env": "OPENAI_API_KEY",
            "docker_image": "starbench-qwen:latest",
            "docker_env_passthrough": ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
        }
        base.update(overrides)
        return base

    def test_builtin_listing_reports_docker_capability(self) -> None:
        listing = agents.list_agents(self.runtimes_dir)
        by_id = {agent["id"]: agent for agent in listing["builtin"]}
        self.assertEqual(
            sorted(by_id), ["claude", "codex", "gemini", "grok", "opencode"]
        )
        for agent_id, meta in by_id.items():
            self.assertTrue(meta["docker_capable"], agent_id)
            self.assertTrue(meta["docker_image"].startswith("starbench-"), agent_id)
        self.assertEqual(by_id["gemini"]["docker_image"], "starbench-gemini-cli:latest")
        self.assertIn("bin", by_id["codex"]["cli"])

    def test_save_list_delete_roundtrip(self) -> None:
        saved = agents.save_custom_agent(self.runtimes_dir, self.qwen_payload())
        self.assertEqual(saved["id"], "custom:qwen-code")
        self.assertEqual(saved["protocol"], "openai")
        self.assertEqual(saved["base_url_env"], "OPENAI_BASE_URL")
        self.assertEqual(saved["docker_image"], "starbench-qwen:latest")
        self.assertTrue(saved["docker_capable"])
        self.assertTrue((self.runtimes_dir / "qwen-code.json").exists())

        # The written file must be loadable by the runner itself.
        from starbench.runner.custom_runtime import load_custom_runtime

        spec = load_custom_runtime(self.runtimes_dir, "qwen-code")
        self.assertEqual(spec.model_flag, "-m")
        self.assertEqual(spec.docker_image, "starbench-qwen:latest")

        listing = agents.list_agents(self.runtimes_dir)
        self.assertEqual(len(listing["custom"]), 1)
        agents.delete_custom_agent(self.runtimes_dir, "qwen-code")
        self.assertEqual(agents.list_agents(self.runtimes_dir)["custom"], [])

    def test_save_rejects_builtin_id_bad_parser_and_bad_protocol(self) -> None:
        with self.assertRaisesRegex(agents.AgentError, "built-in"):
            agents.save_custom_agent(self.runtimes_dir, self.qwen_payload(id="codex"))
        with self.assertRaisesRegex(agents.AgentError, "parser"):
            agents.save_custom_agent(self.runtimes_dir, self.qwen_payload(parser="yaml"))
        with self.assertRaisesRegex(agents.AgentError, "Protocol"):
            agents.save_custom_agent(self.runtimes_dir, self.qwen_payload(protocol="carrier-pigeon"))

    def test_positional_prompt_agent_roundtrip(self) -> None:
        agents.save_custom_agent(
            self.runtimes_dir,
            self.qwen_payload(
                id="trae-agent",
                command="trae-cli",
                args=["run", "--provider", "openai"],
                judge_args=None,
                model_flag="--model",
                prompt_via="arg",
                prompt_flag="",
                parser="text",
                docker_image="",
                docker_env_passthrough=None,
            ),
        )
        listed = agents.get_custom_agent(self.runtimes_dir, "trae-agent")
        self.assertIsNotNone(listed)
        self.assertEqual(listed["prompt_via"], "arg")
        self.assertEqual(listed["prompt_flag"], "")
        self.assertFalse(listed["docker_capable"])
        self.assertTrue(listed["judge_args_inherited"])

    def test_invalid_spec_file_surfaces_error(self) -> None:
        (self.runtimes_dir / "broken.json").write_text("{not json", encoding="utf-8")
        listing = agents.list_agents(self.runtimes_dir)
        self.assertEqual(len(listing["custom"]), 1)
        self.assertIn("broken", listing["custom"][0]["id"])
        self.assertTrue(listing["custom"][0]["error"])

    def test_templates_are_valid_runner_specs(self) -> None:
        from starbench.runner.custom_runtime import load_custom_runtime

        for template in agents.agent_templates():
            spec = template["spec"]
            path = self.runtimes_dir / f"{spec['id']}.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            loaded = load_custom_runtime(self.runtimes_dir, spec["id"])
            self.assertEqual(loaded.id, spec["id"])
            self.assertIn(template["spec"].get("protocol"), agents.PROTOCOL_CHOICES)
            path.unlink()

    def test_launcher_accepts_custom_agents(self) -> None:
        tasks_dir = self.tmp / "tasks"
        tasks_dir.mkdir()
        runs_dir = self.tmp / "runs"
        runs_dir.mkdir()
        argv = build_run_argv(
            {
                "run_id": "custom_run",
                "tasks_dir": str(tasks_dir),
                "executor_agent": "custom:qwen-code",
                "evaluator_agent": "custom:my-judge",
                "executor_backend": "docker",
            },
            runs_dir=runs_dir,
        )
        joined = " ".join(argv)
        self.assertIn("--executor-agent custom:qwen-code", joined)
        self.assertIn("--evaluator-agent custom:my-judge", joined)
        # Custom runtimes carry their docker image in the spec; no --docker-image.
        self.assertIn("--executor-backend docker", joined)
        self.assertNotIn("--docker-image", joined)
        with self.assertRaises(LaunchError):
            build_run_argv(
                {
                    "run_id": "bad_run",
                    "tasks_dir": str(tasks_dir),
                    "executor_agent": "custom:bad id!",
                },
                runs_dir=runs_dir,
            )


class ExperimentCustomRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_expcustom_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        self.runtimes_dir = self.tmp / "runtimes"
        self.runtimes_dir.mkdir()
        write_json(
            self.runtimes_dir / "qwen-code.json",
            {
                "id": "qwen-code",
                "label": "Qwen Code",
                "command": "qwen",
                "args": ["--output-format", "json", "--yolo"],
                "model_flag": "-m",
                "prompt_via": "stdin",
                "parser": "headless-json",
                "protocol": "openai",
                "base_url_env": "OPENAI_BASE_URL",
                "api_key_env": "OPENAI_API_KEY",
                "docker": {
                    "image": "starbench-qwen:latest",
                    "env_passthrough": ["OPENAI_API_KEY"],
                },
            },
        )
        write_json(
            self.runtimes_dir / "kimi-code.json",
            {
                "id": "kimi-code",
                "command": "kimi",
                "args": ["--print", "--quiet"],
                "prompt_via": "stdin",
                "parser": "text",
                "protocol": "none",
            },
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, **overrides):
        base = {
            "name": "exp_custom",
            "tasks_dir": str(self.tasks_dir),
            "tasks": [],
            "shared": {
                "evaluator_agent": "claude",
                "evaluator_model": "claude-opus-4-8",
                "judge_mode": "single",
                "executor_backend": "docker",
                "docker_image": "starbench-codex:latest",
            },
            "contenders": [
                {
                    "label": "Qwen Code",
                    "agent": "custom:qwen-code",
                    "model": "qwen3-coder",
                    "auth_mode": "env",
                    "env": {
                        "OPENAI_BASE_URL": {"value": "https://openrouter.ai/api/v1"},
                        "OPENAI_API_KEY": {"from_env": "OPENROUTER_API_KEY"},
                    },
                },
                {"label": "Kimi", "agent": "custom:kimi-code", "model": "", "auth_mode": "global"},
            ],
        }
        base.update(overrides)
        return base

    def test_custom_contenders_plan_with_docker_capability(self) -> None:
        plan = experiments.plan_experiment(
            self.payload(), runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        by_agent = {item["agent"]: item for item in plan["plans"]}
        qwen = by_agent["custom:qwen-code"]
        self.assertIn("--executor-agent custom:qwen-code", " ".join(qwen["argv"]))
        self.assertIn("--executor-model qwen3-coder", " ".join(qwen["argv"]))
        self.assertIn(f"--runtimes-dir {self.runtimes_dir}", " ".join(qwen["argv"]))
        self.assertEqual(qwen["backend"], "docker")
        self.assertFalse(qwen["backend_downgraded"])
        self.assertEqual(qwen["agent_label"], "Qwen Code")
        kimi = by_agent["custom:kimi-code"]
        self.assertEqual(kimi["backend"], "local")
        self.assertTrue(kimi["backend_downgraded"])

    def test_unknown_custom_contender_rejected(self) -> None:
        payload = self.payload(
            contenders=[{"label": "ghost", "agent": "custom:ghost", "model": ""}]
        )
        with self.assertRaisesRegex(ExperimentError, "custom runtime"):
            experiments.plan_experiment(
                payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
            )

    def test_contender_env_that_reroutes_judge_rejected(self) -> None:
        payload = self.payload()
        payload["shared"]["evaluator_agent"] = "codex"
        with self.assertRaisesRegex(ExperimentError, "reroute"):
            experiments.plan_experiment(
                payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
            )

    def test_custom_judge_env_merges_and_conflicts_detected(self) -> None:
        payload = self.payload()
        payload["shared"]["evaluator_agent"] = "custom:kimi-code"
        payload["shared"]["judge_env"] = {"KIMI_HOME": {"value": "/tmp/kimi"}}
        plan = experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
        )
        for item in plan["plans"]:
            self.assertIn("KIMI_HOME", item["env_keys"])
            self.assertIn("--evaluator-agent custom:kimi-code", " ".join(item["argv"]))

        # A custom judge that reads the same variables the contender injects
        # (different value) must be rejected.
        payload = self.payload(name="exp_custom2")
        payload["shared"]["evaluator_agent"] = "custom:qwen-code"
        payload["shared"]["judge_env"] = {
            "OPENAI_BASE_URL": {"value": "https://api.openai.com/v1"}
        }
        with self.assertRaisesRegex(ExperimentError, "process-wide"):
            experiments.plan_experiment(
                payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
            )

    def test_unknown_custom_judge_rejected(self) -> None:
        payload = self.payload()
        payload["shared"]["evaluator_agent"] = "custom:ghost-judge"
        with self.assertRaisesRegex(ExperimentError, "Judge runtime"):
            experiments.plan_experiment(
                payload, runs_dir=self.runs_dir, runtimes_dir=self.runtimes_dir
            )


if __name__ == "__main__":
    unittest.main()
