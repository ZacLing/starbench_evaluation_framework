"""Contract checks for public StarBench task and run artifacts."""
from __future__ import annotations

import importlib.util
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
    JUDGE_AGGREGATE_SCHEMA_VERSION,
    ContractValidationError,
    load_schema,
    validate_json_schema,
    validate_payload,
)
from starbench.runner.task_loader import load_task


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas" / "starbench" / "v1"
SCHEMA_V2_ROOT = ROOT / "schemas" / "starbench" / "v2"
PACKAGED_SCHEMA_ROOT = ROOT / "src" / "starbench" / "contracts" / "schemas"
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
    "run_plan.schema.json",
    "run_summary.schema.json",
    "run_state.schema.json",
    "runtime_provenance.schema.json",
    "task.schema.json",
    "task_manifest.schema.json",
    "task_summary.schema.json",
    "trace_summary.schema.json",
}
EXPECTED_V2_SCHEMAS = {"judge_aggregate.schema.json"}


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
    def test_versioned_schema_loader_reads_judge_v2(self) -> None:
        schema_payload = load_schema(
            "judge_aggregate.schema.json",
            version=JUDGE_AGGREGATE_SCHEMA_VERSION,
        )
        self.assertEqual(
            schema_payload["$id"],
            "https://starbench.dev/schemas/v2/judge_aggregate.schema.json",
        )

        with self.assertRaisesRegex(ContractValidationError, "missing required key 'outcome'"):
            validate_payload(
                "judge_aggregate.schema.json",
                {
                    "schema_version": 2,
                    "mode": "single",
                    "overall_pass": False,
                    "passed_count": 0,
                    "total_count": 1,
                    "missing": [],
                    "fail_fast_failures": [],
                    "results": [],
                },
                version=JUDGE_AGGREGATE_SCHEMA_VERSION,
            )

    def test_schema_inventory_is_valid_json(self) -> None:
        self.assertEqual(EXPECTED_SCHEMAS, {path.name for path in SCHEMA_ROOT.glob("*.json")})
        for name in sorted(EXPECTED_SCHEMAS):
            payload = schema(name)
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(payload["$id"].startswith("https://starbench.dev/schemas/v1/"))
            self.assertEqual(payload["type"], "object")

        self.assertEqual(EXPECTED_V2_SCHEMAS, {path.name for path in SCHEMA_V2_ROOT.glob("*.json")})
        for name in sorted(EXPECTED_V2_SCHEMAS):
            payload = read_json(SCHEMA_V2_ROOT / name)
            self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertTrue(payload["$id"].startswith("https://starbench.dev/schemas/v2/"))
            self.assertEqual(payload["type"], "object")

    def test_packaged_schemas_match_public_protocol_sources(self) -> None:
        for version in ("v1", "v2"):
            public_root = ROOT / "schemas" / "starbench" / version
            packaged_root = PACKAGED_SCHEMA_ROOT / version
            self.assertEqual(
                {path.name for path in public_root.glob("*.json")},
                {path.name for path in packaged_root.glob("*.json")},
            )
            for public_path in public_root.glob("*.json"):
                with self.subTest(version=version, schema=public_path.name):
                    self.assertEqual(
                        public_path.read_bytes(),
                        (packaged_root / public_path.name).read_bytes(),
                    )

    @unittest.skipUnless(
        importlib.util.find_spec("pip") is not None
        and importlib.util.find_spec("setuptools") is not None,
        "needs pip + setuptools in the venv (uv-managed venvs ship neither: "
        "`uv pip install pip setuptools`); CI must run this test",
    )
    def test_built_wheel_loads_packaged_schemas_without_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wheel_dir = tmp_path / "wheel"
            install_dir = tmp_path / "installed"
            wheel_dir.mkdir()
            env = os.environ.copy()
            env["PIP_CACHE_DIR"] = str(tmp_path / "pip-cache")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    ".",
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(wheel_dir),
                ],
                cwd=ROOT,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            wheel = next(wheel_dir.glob("*.whl"))
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--no-deps",
                    "--target",
                    str(install_dir),
                    str(wheel),
                ],
                cwd=tmp_path,
                env=env,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            smoke = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {str(install_dir)!r}); "
                        "from starbench.contracts import load_schema; "
                        "assert load_schema('task.schema.json')['title'] == 'StarBench task.json'; "
                        "assert load_schema('judge_aggregate.schema.json', version=2)['type'] == 'object'"
                    ),
                ],
                cwd=tmp_path,
                env=env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(smoke.returncode, 0, msg=smoke.stderr)

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
            ):
                assert_current_schema_version(self, payload)
            self.assertEqual(
                judge_aggregate.get("schema_version"),
                JUDGE_AGGREGATE_SCHEMA_VERSION,
            )

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
                read_json(SCHEMA_V2_ROOT / "judge_aggregate.schema.json"),
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
            "properties": {"name": {"type": "string", "format": "email"}},
        }
        with self.assertRaisesRegex(ContractValidationError, r"\$\.name.*format"):
            validate_json_schema(nested, {"name": "ok"})

    def test_string_length_keywords_are_enforced(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "at least 2 character"):
            validate_json_schema({"type": "string", "minLength": 2}, "x")
        with self.assertRaisesRegex(ContractValidationError, "at most 3 character"):
            validate_json_schema({"type": "string", "maxLength": 3}, "long")

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
