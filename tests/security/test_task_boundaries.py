from __future__ import annotations

import base64
import contextlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path

from starbench.gui.library import LibraryError, validate_task_package
from starbench.runner.cli import parse_args
from starbench.runner.executor import copy_task_material, materialize_task
from starbench.runner.models import TaskRunSpec
from starbench.runner.orchestrator import make_run_task_ids
from starbench.runner.task_loader import discover_tasks, load_task


def write_task(
    task_dir: Path,
    *,
    task_overrides: dict | None = None,
    rubrics: list[dict] | None = None,
) -> None:
    task_dir.mkdir(parents=True)
    task = {"id": "boundary_task", "name": "Boundary task"}
    task.update(task_overrides or {})
    (task_dir / "task.json").write_text(json.dumps(task), encoding="utf-8")
    (task_dir / "prompt.md").write_text("Produce an output.", encoding="utf-8")
    (task_dir / "rubrics.json").write_text(
        json.dumps(
            {
                "rubrics": rubrics
                or [
                    {
                        "id": "R001",
                        "question": "Output exists?",
                        "expected": True,
                        "fail_fast": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class TaskPackageBoundaryTests(unittest.TestCase):
    def test_material_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "tasks" / "task"
            write_task(task_dir, task_overrides={"materials": ["../outside.txt"]})
            (task_dir.parent / "outside.txt").write_text("secret", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "task material|contract"):
                load_task(task_dir)

    def test_config_file_parent_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "tasks" / "task"
            write_task(task_dir, task_overrides={"prompt": "../outside.md"})
            (task_dir.parent / "outside.md").write_text("secret", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "prompt|contract"):
                load_task(task_dir)

    def test_task_package_symlink_is_rejected_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "tasks" / "task"
            write_task(task_dir, task_overrides={"materials": ["materials"]})
            materials = task_dir / "materials"
            materials.mkdir()
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            (materials / "secret.txt").symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "symbolic links"):
                load_task(task_dir)

    def test_executor_skill_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "tasks" / "task"
            write_task(task_dir, task_overrides={"executor_skills": "executor_skills.json"})
            external_skill = root / "tasks" / "external-skill"
            external_skill.mkdir()
            (external_skill / "SKILL.md").write_text("# Private", encoding="utf-8")
            (task_dir / "executor_skills.json").write_text(
                json.dumps({"skills": [{"id": "private", "path": "../external-skill"}]}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "executor skill|contract"):
                load_task(task_dir)

    def test_duplicate_rubric_ids_are_rejected(self) -> None:
        duplicate = {
            "id": "R001",
            "question": "Output exists?",
            "expected": True,
            "fail_fast": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task"
            write_task(task_dir, rubrics=[duplicate, dict(duplicate)])

            with self.assertRaisesRegex(ValueError, "Duplicate rubric id R001"):
                load_task(task_dir)

    def test_rigor_must_reference_an_existing_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task"
            write_task(task_dir, task_overrides={"rigors": "rigors.json"})
            (task_dir / "rigors.json").write_text(
                json.dumps(
                    {
                        "rigors": [
                            {
                                "id": "strict",
                                "rubric_id": "R999",
                                "requirement": "Use strict evidence.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "references unknown rubric id R999"):
                load_task(task_dir)

    def test_materialize_rejects_manually_injected_outside_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_dir = root / "task"
            write_task(task_dir)
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            task = replace(load_task(task_dir), material_paths=[outside])
            task_run = TaskRunSpec(task=task, instruction_mode="none", selected_steps=[])

            with self.assertRaisesRegex(ValueError, "outside task package"):
                materialize_task(task_run, root / "runs" / "run", "task")

    def test_copy_rejects_a_symlink_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside.txt"
            outside.write_text("secret", encoding="utf-8")
            link = root / "link.txt"
            link.symlink_to(outside)

            with self.assertRaisesRegex(ValueError, "symbolic links"):
                copy_task_material(link, root / "staged.txt")

    def test_run_task_id_is_validated_defensively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task"
            write_task(task_dir)
            task = replace(load_task(task_dir), id="../escape")
            task_run = TaskRunSpec(task=task, instruction_mode="none", selected_steps=[])

            with self.assertRaisesRegex(ValueError, "Invalid task id"):
                make_run_task_ids([task_run])

    def test_unselected_invalid_package_does_not_block_selected_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = Path(tmp) / "tasks"
            write_task(tasks_dir / "valid")
            broken = tasks_dir / "broken"
            broken.mkdir()
            (broken / "task.json").write_text("{not json", encoding="utf-8")

            tasks = discover_tasks(tasks_dir, ["boundary_task"])
            self.assertEqual([task.id for task in tasks], ["boundary_task"])

    def test_duplicate_task_ids_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = Path(tmp) / "tasks"
            write_task(tasks_dir / "one")
            write_task(tasks_dir / "two")

            with self.assertRaisesRegex(ValueError, "Duplicate task id"):
                discover_tasks(tasks_dir)


class CliAndUploadBoundaryTests(unittest.TestCase):
    def test_cli_rejects_run_id_path_traversal(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                parse_args(["--run-id", "../escape"])

    def test_upload_rejects_absolute_file_path(self) -> None:
        with self.assertRaisesRegex(LibraryError, "absolute paths"):
            validate_task_package(
                [
                    {
                        "path": "/tmp/task.json",
                        "content_b64": base64.b64encode(b"{}").decode("ascii"),
                    }
                ]
            )

    def test_zip_symlink_entry_is_rejected(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            info = zipfile.ZipInfo("pkg/materials/secret.txt")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../../outside.txt")

        with self.assertRaisesRegex(LibraryError, "symbolic link"):
            validate_task_package(
                [
                    {
                        "path": "task.zip",
                        "content_b64": base64.b64encode(buffer.getvalue()).decode("ascii"),
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
