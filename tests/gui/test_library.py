"""Task-package import, browsing, detail and preflight in ``starbench.gui.library``."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from starbench.gui import library
from starbench.gui.library import LibraryError
from helpers import write_json


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

    def test_browse_allows_directories_outside_home_and_cwd(self) -> None:
        expected = Path("/etc").resolve()
        listing = library.browse_directories("/etc", cwd=self.tmp)
        self.assertEqual(listing["path"], str(expected))
        self.assertEqual(listing["parent"], str(expected.parent))

    def test_task_detail_returns_prompt_and_rubrics(self) -> None:
        detail = library.task_package_detail(self.tasks_dir, "demo")
        self.assertEqual(detail["id"], "demo")
        self.assertIn("Prompt body", detail["prompt"])
        self.assertEqual(len(detail["rubrics"]), 1)
        # rigor_count is a new badge field; no rigors.json in this fixture.
        self.assertEqual(detail["rigor_count"], 0)

    def test_task_detail_counts_rigors(self) -> None:
        write_json(
            self.tasks_dir / "demo" / "rigors.json",
            {"rigors": [{"id": "G1"}, {"id": "G2"}]},
        )
        detail = library.task_package_detail(self.tasks_dir, "demo")
        self.assertEqual(detail["rigor_count"], 2)

    def test_task_detail_returns_rigor_detail(self) -> None:
        write_json(
            self.tasks_dir / "demo" / "rigors.json",
            {
                "rigors": [
                    {
                        "id": "G",
                        "rubric_id": "G",
                        "requirement": "The deliverable must handle near-zero denominators.",
                    },
                    {
                        "id": "H",
                        "rubric_id": "R012",
                        "requirement": "The deliverable must define continuous trading windows.",
                    },
                ]
            },
        )
        detail = library.task_package_detail(self.tasks_dir, "demo")
        self.assertEqual(
            detail["rigors"],
            [
                {
                    "id": "G",
                    "rubric_id": "G",
                    "requirement": "The deliverable must handle near-zero denominators.",
                },
                {
                    "id": "H",
                    "rubric_id": "R012",
                    "requirement": "The deliverable must define continuous trading windows.",
                },
            ],
        )
        self.assertEqual(detail["rigor_count"], 2)

    def test_task_detail_rigors_empty_when_no_file(self) -> None:
        detail = library.task_package_detail(self.tasks_dir, "demo")
        self.assertEqual(detail["rigors"], [])
        self.assertEqual(detail["rigor_count"], 0)

    def test_task_detail_rigor_rubric_id_defaults_to_id(self) -> None:
        write_json(
            self.tasks_dir / "demo" / "rigors.json",
            {"rigors": [{"id": "G", "requirement": "Must be rigorous."}]},
        )
        detail = library.task_package_detail(self.tasks_dir, "demo")
        self.assertEqual(detail["rigors"][0]["rubric_id"], "G")

    def test_task_detail_rejects_traversal(self) -> None:
        with self.assertRaises(LibraryError):
            library.task_package_detail(self.tasks_dir, "../outside")

    def test_human_reference_steps_are_public_detail(self) -> None:
        write_json(
            self.tasks_dir / "demo" / "human_reference.json",
            {
                "steps": [
                    {
                        "step_id": "H001",
                        "step_type": "structure",
                        "instruction": "Organize the answer around the required headings.",
                        "reasoning": "PRIVATE-TRACE-ALPHA should never be exposed.",
                    },
                    {
                        "step_id": "H002",
                        "step_type": "coverage",
                        "instruction": "Check every required entity is present.",
                        "reasoning": "PRIVATE-TRACE-BETA is also private.",
                    },
                ]
            },
        )
        detail = library.task_package_detail(self.tasks_dir, "demo")
        # Upgraded from a bare count to a public detail list.
        self.assertEqual(
            detail["human_reference_steps"],
            [
                {
                    "step_id": "H001",
                    "step_type": "structure",
                    "instruction": "Organize the answer around the required headings.",
                },
                {
                    "step_id": "H002",
                    "step_type": "coverage",
                    "instruction": "Check every required entity is present.",
                },
            ],
        )
        # Back-compat count field is retained.
        self.assertEqual(detail["human_reference_step_count"], 2)

    def test_reasoning_never_appears_in_detail_json(self) -> None:
        """PRIVACY RED LINE: `reasoning` must never reach any API response."""
        secret = "REASONING-SECRET-DO-NOT-LEAK-42"
        write_json(
            self.tasks_dir / "demo" / "human_reference.json",
            {
                "steps": [
                    {
                        "step_id": "H001",
                        "step_type": "structure",
                        "instruction": "Do the thing.",
                        "reasoning": secret,
                    }
                ]
            },
        )
        detail = library.task_package_detail(self.tasks_dir, "demo")
        serialized = json.dumps(detail)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("reasoning", serialized)


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
        # env auth with a known key that is absent is a guaranteed launch
        # failure, not a maybe — the check must block, not advise.
        self.assertEqual(by_id["executor_auth"]["status"], "fail")

    def test_preflight_checks_role_specific_gateway_keys(self) -> None:
        # Each role's gateway credential rides its own env-key list (planning
        # folds the opencode api_key_env into it); preflight checks them
        # independently, with no shared or runtime-named knob field.
        with mock.patch.dict(
            os.environ,
            {"EXECUTOR_GATEWAY_KEY": "set"},
            clear=True,
        ):
            checks = library.preflight(
                executor_agent="opencode",
                evaluator_agent="opencode",
                executor_backend="local",
                docker_image="",
                executor_auth_mode="env",
                evaluator_auth_mode="env",
                executor_env_keys=["EXECUTOR_GATEWAY_KEY"],
                evaluator_env_keys=["JUDGE_GATEWAY_KEY"],
            )
        by_id = {check["id"]: check for check in checks}
        self.assertEqual(by_id["executor_auth"]["status"], "ok")
        self.assertIn("EXECUTOR_GATEWAY_KEY", by_id["executor_auth"]["hint"])
        self.assertIn("JUDGE_GATEWAY_KEY", by_id["evaluator_auth"]["hint"])

    def test_preflight_probes_the_executable_in_a_command_prefix(self) -> None:
        with mock.patch("starbench.gui.library.shutil.which", return_value="/bin/codex") as which:
            check = library._cli_check(
                "executor", "codex", "codex -c model_provider=gateway"
            )
        self.assertEqual(check["status"], "ok")
        which.assert_called_once_with("codex")


if __name__ == "__main__":
    unittest.main()
