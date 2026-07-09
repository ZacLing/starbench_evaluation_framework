"""Contract checks for public StarBench task and run artifacts."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, Dict

from starbench.contracts import (
    ARTIFACT_SCHEMA_VERSION,
    ContractValidationError,
    validate_json_schema,
)
from starbench.runner.task_loader import load_task


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas" / "starbench" / "v1"
EXAMPLE_TASKS = ROOT / "examples" / "tasks"


EXPECTED_SCHEMAS = {
    "artifact_manifest.schema.json",
    "executor_skills.schema.json",
    "executor_status.schema.json",
    "human_reference.schema.json",
    "judge_aggregate.schema.json",
    "profile_snapshot.schema.json",
    "progress_event.schema.json",
    "rigors.schema.json",
    "rubrics.schema.json",
    "run_summary.schema.json",
    "runtime_provenance.schema.json",
    "task.schema.json",
    "task_manifest.schema.json",
    "task_summary.schema.json",
    "trace_summary.schema.json",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema(name: str) -> Dict[str, Any]:
    return read_json(SCHEMA_ROOT / name)


def assert_current_schema_version(testcase: unittest.TestCase, payload: Dict[str, Any]) -> None:
    testcase.assertEqual(payload.get("schema_version"), ARTIFACT_SCHEMA_VERSION)


def fake_codex_script(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            r'''
            import json
            import os
            import re
            import sys
            from pathlib import Path

            def value_after(args, flag):
                return args[args.index(flag) + 1] if flag in args else None

            def emit(event):
                print(json.dumps(event), flush=True)

            def rubric_ids(prompt):
                ids = re.findall(r'"id":\s*"(R\d+)"', prompt)
                return ids or ["R001"]

            def write_executor_outputs(cwd):
                outputs = Path(cwd) / "outputs"
                outputs.mkdir(parents=True, exist_ok=True)
                (outputs / "result.txt").write_text("contract smoke output\n", encoding="utf-8")

            args = sys.argv[1:]
            if args and args[0] == "--search":
                args = args[1:]
            if args and args[0] == "exec":
                args = args[1:]

            cwd = value_after(args, "--cd") or os.getcwd()
            final_path = Path(value_after(args, "--output-last-message") or Path(cwd) / "final.md")
            output_schema = value_after(args, "--output-schema")
            prompt = sys.stdin.read()

            emit({"type": "thread.started", "thread_id": "contract-thread"})
            final_path.parent.mkdir(parents=True, exist_ok=True)
            if output_schema:
                final_path.write_text(json.dumps({
                    "mode": "single",
                    "results": [
                        {
                            "rubric_id": rid,
                            "answer": True,
                            "expected": True,
                            "passed": True,
                            "fail_fast": rid in ("R001", "R002", "R003", "R004", "R005"),
                            "evidence": f"fake evidence for {rid}"
                        }
                        for rid in rubric_ids(prompt)
                    ],
                    "overall_notes": "fake ok"
                }), encoding="utf-8")
                emit({"type": "item.completed", "item": {"type": "agent_message", "id": "m1", "text": final_path.read_text(encoding="utf-8")}})
            else:
                write_executor_outputs(cwd)
                final_path.write_text("Created outputs/result.txt", encoding="utf-8")
                emit({"type": "item.completed", "item": {"type": "reasoning", "id": "r1", "text": "summary"}})
                emit({"type": "item.completed", "item": {"type": "command_execution", "id": "c1", "command": "python -m pytest", "status": "completed", "exit_code": 0, "aggregated_output": "ok"}})
                emit({"type": "item.completed", "item": {"type": "file_change", "id": "f1", "status": "completed", "changes": [{"path": "outputs/result.txt"}]}})
            emit({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}})
            '''
        ),
        encoding="utf-8",
    )


class ArtifactSchemaTests(unittest.TestCase):
    def test_schema_inventory_is_valid_json(self) -> None:
        self.assertEqual(EXPECTED_SCHEMAS, {path.name for path in SCHEMA_ROOT.glob("*.json")})
        for name in sorted(EXPECTED_SCHEMAS):
            payload = schema(name)
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(payload["$id"].startswith("https://starbench.dev/schemas/v1/"))
            self.assertEqual(payload["type"], "object")

    def test_bundled_example_tasks_match_input_schemas(self) -> None:
        for task_dir in sorted(path for path in EXAMPLE_TASKS.iterdir() if path.is_dir()):
            with self.subTest(task=task_dir.name):
                task = read_json(task_dir / "task.json")
                validate_json_schema(schema("task.schema.json"), task)

                rubrics_path = task_dir / task.get("rubrics", "rubrics.json")
                validate_json_schema(schema("rubrics.schema.json"), read_json(rubrics_path))

                human_reference = task.get("human_reference", "human_reference.json")
                if (task_dir / human_reference).exists():
                    validate_json_schema(
                        schema("human_reference.schema.json"),
                        read_json(task_dir / human_reference),
                    )

                rigors = task.get("rigors", "rigors.json")
                if (task_dir / rigors).exists():
                    validate_json_schema(schema("rigors.schema.json"), read_json(task_dir / rigors))

                executor_skills = task.get("executor_skills")
                if executor_skills:
                    validate_json_schema(
                        schema("executor_skills.schema.json"),
                        read_json(task_dir / executor_skills),
                    )

    def test_human_reference_reasoning_is_marked_private(self) -> None:
        reasoning = schema("human_reference.schema.json")["properties"]["steps"]["items"][
            "properties"
        ]["reasoning"]
        self.assertIs(reasoning["x-starbench-private"], True)

    def test_runner_outputs_match_public_artifact_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            shutil.copytree(EXAMPLE_TASKS / "demo_python_cli", tasks_dir / "demo_python_cli")
            fake_codex = tmp_path / "fake_codex.py"
            fake_codex_script(fake_codex)

            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(
                [str(ROOT / "src"), env["PYTHONPATH"]] if env.get("PYTHONPATH") else [str(ROOT / "src")]
            )
            cmd = [
                sys.executable,
                "-m",
                "starbench.runner.run_benchmark",
                "--tasks-dir",
                str(tasks_dir),
                "--runs-dir",
                str(runs_dir),
                "--run-id",
                "contract_run",
                "--seed",
                "123",
                "--judge-mode",
                "single",
                "--auth-mode",
                "global",
                "--executor-backend",
                "local",
                "--codex-bin",
                f"{sys.executable} {fake_codex}",
                "--no-progress",
            ]
            completed = subprocess.run(
                cmd,
                cwd=ROOT,
                check=False,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)

            run_root = runs_dir / "contract_run"
            task_root = run_root / "demo_python_cli"
            logs = task_root / "logs"

            run_summary = read_json(run_root / "summary.json")
            assert_current_schema_version(self, run_summary)
            validate_json_schema(schema("run_summary.schema.json"), run_summary)
            for index, line in enumerate(
                (run_root / "progress_events.jsonl").read_text(encoding="utf-8").splitlines()
            ):
                event = json.loads(line)
                assert_current_schema_version(self, event)
                validate_json_schema(
                    schema("progress_event.schema.json"),
                    event,
                    path=f"progress[{index}]",
                )
            task_manifest = read_json(task_root / "manifest.json")
            task_summary = read_json(task_root / "task_summary.json")
            executor_status = read_json(logs / "status.json")
            trace_summary = read_json(logs / "trace_summary.json")
            artifact_manifest = read_json(logs / "artifact_manifest.json")
            judge_aggregate = read_json(task_root / "judges" / "single_aggregate.json")

            for payload in (
                task_manifest,
                task_summary,
                executor_status,
                trace_summary,
                artifact_manifest,
                judge_aggregate,
            ):
                assert_current_schema_version(self, payload)

            validate_json_schema(schema("task_manifest.schema.json"), task_manifest)
            validate_json_schema(schema("task_summary.schema.json"), task_summary)
            validate_json_schema(schema("executor_status.schema.json"), executor_status)

            # Runtime provenance must land in the run artifacts and honour
            # its own contract (fake-runner smoke: no real model involved).
            validate_json_schema(
                schema("runtime_provenance.schema.json"),
                run_summary["runtime_provenance"],
                path="summary.runtime_provenance",
            )
            validate_json_schema(
                schema("runtime_provenance.schema.json")["properties"]["executor"],
                executor_status["executor_runtime_provenance"],
                path="status.executor_runtime_provenance",
            )
            validate_json_schema(schema("trace_summary.schema.json"), trace_summary)
            validate_json_schema(schema("artifact_manifest.schema.json"), artifact_manifest)
            validate_json_schema(
                schema("judge_aggregate.schema.json"),
                judge_aggregate,
            )

    def test_runner_task_loader_rejects_non_contract_boolean_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "task"
            shutil.copytree(EXAMPLE_TASKS / "demo_python_cli", task_dir)
            task_json = read_json(task_dir / "task.json")
            task_json["allow_web_search"] = "false"
            (task_dir / "task.json").write_text(json.dumps(task_json), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "artifact contract"):
                load_task(task_dir)

    def test_shared_validator_reports_schema_errors(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "missing required key 'id'"):
            validate_json_schema(schema("task.schema.json"), {})


class ValidatorKeywordTests(unittest.TestCase):
    """The lightweight validator must refuse keywords it does not implement.

    Silently ignoring an unknown keyword would let a schema author believe a
    constraint is enforced when it is not.
    """

    def test_unknown_keyword_raises(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "unsupported schema keyword.*const"):
            validate_json_schema({"type": "string", "const": "fixed"}, "anything")

    def test_composition_keywords_still_raise(self) -> None:
        for keyword in ("$ref", "allOf", "anyOf", "oneOf", "not"):
            with self.subTest(keyword=keyword):
                with self.assertRaisesRegex(ContractValidationError, "unsupported schema keyword"):
                    validate_json_schema({keyword: []}, {})

    def test_nested_unknown_keyword_raises(self) -> None:
        nested = {
            "type": "object",
            "properties": {"name": {"type": "string", "minLength": 1}},
        }
        with self.assertRaisesRegex(ContractValidationError, r"\$\.name.*minLength"):
            validate_json_schema(nested, {"name": "ok"})

    def test_annotations_and_vendor_extensions_are_allowed(self) -> None:
        validate_json_schema(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "https://example.test/x.json",
                "$comment": "note",
                "title": "t",
                "description": "d",
                "examples": ["a"],
                "default": "a",
                "deprecated": False,
                "x-starbench-private": True,
                "type": "string",
            },
            "value",
        )

    def test_schema_valued_additional_properties_raises(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "unsupported additionalProperties form"):
            validate_json_schema(
                {"type": "object", "additionalProperties": {"type": "string"}},
                {"free": "form"},
            )

    def test_non_object_items_form_raises(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "unsupported items form"):
            validate_json_schema({"type": "array", "items": False}, ["x"])


if __name__ == "__main__":
    unittest.main()
