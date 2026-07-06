"""Contract checks for public StarBench task and run artifacts."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any, Dict


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas" / "starbench" / "v1"
EXAMPLE_TASKS = ROOT / "examples" / "tasks"


EXPECTED_SCHEMAS = {
    "artifact_manifest.schema.json",
    "executor_skills.schema.json",
    "executor_status.schema.json",
    "human_reference.schema.json",
    "judge_aggregate.schema.json",
    "progress_event.schema.json",
    "rigors.schema.json",
    "rubrics.schema.json",
    "run_summary.schema.json",
    "task.schema.json",
    "task_manifest.schema.json",
    "task_summary.schema.json",
    "trace_summary.schema.json",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def schema(name: str) -> Dict[str, Any]:
    return read_json(SCHEMA_ROOT / name)


def validate(schema_payload: Dict[str, Any], data: Any, *, path: str = "$") -> None:
    """Validate the JSON Schema subset used by the public artifact schemas.

    The project intentionally avoids adding a runtime dependency for schema
    validation at this stage. This small validator is narrow by design: it
    covers the keywords used in ``schemas/starbench/v1`` and fails loudly if a
    schema starts using an unsupported keyword in future tests.
    """
    unsupported = set(schema_payload) & {
        "$ref",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "patternProperties",
        "dependentRequired",
    }
    if unsupported:
        raise AssertionError(f"{path}: unsupported schema keyword(s): {sorted(unsupported)}")

    expected_type = schema_payload.get("type")
    if expected_type is not None and not _matches_type(data, expected_type):
        raise AssertionError(
            f"{path}: expected type {expected_type!r}, got {type(data).__name__}"
        )

    if "enum" in schema_payload and data not in schema_payload["enum"]:
        raise AssertionError(f"{path}: expected one of {schema_payload['enum']!r}, got {data!r}")

    if isinstance(data, dict):
        required = schema_payload.get("required", [])
        for key in required:
            if key not in data:
                raise AssertionError(f"{path}: missing required key {key!r}")

        properties = schema_payload.get("properties", {})
        for key, child_schema in properties.items():
            if key in data:
                validate(child_schema, data[key], path=f"{path}.{key}")

        if schema_payload.get("additionalProperties") is False:
            extra = set(data) - set(properties)
            if extra:
                raise AssertionError(f"{path}: unexpected key(s): {sorted(extra)}")

    if isinstance(data, list):
        min_items = schema_payload.get("minItems")
        if min_items is not None and len(data) < min_items:
            raise AssertionError(f"{path}: expected at least {min_items} item(s)")

        item_schema = schema_payload.get("items")
        if item_schema is not None:
            for index, item in enumerate(data):
                validate(item_schema, item, path=f"{path}[{index}]")

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        minimum = schema_payload.get("minimum")
        if minimum is not None and data < minimum:
            raise AssertionError(f"{path}: expected >= {minimum}, got {data!r}")

    pattern = schema_payload.get("pattern")
    if pattern is not None and isinstance(data, str) and re.search(pattern, data) is None:
        raise AssertionError(f"{path}: {data!r} does not match {pattern!r}")


def _matches_type(data: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_type(data, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(data, dict)
    if expected_type == "array":
        return isinstance(data, list)
    if expected_type == "string":
        return isinstance(data, str)
    if expected_type == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    if expected_type == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    if expected_type == "boolean":
        return isinstance(data, bool)
    if expected_type == "null":
        return data is None
    raise AssertionError(f"unsupported JSON Schema type: {expected_type!r}")


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
                validate(schema("task.schema.json"), task)

                rubrics_path = task_dir / task.get("rubrics", "rubrics.json")
                validate(schema("rubrics.schema.json"), read_json(rubrics_path))

                human_reference = task.get("human_reference", "human_reference.json")
                if (task_dir / human_reference).exists():
                    validate(
                        schema("human_reference.schema.json"),
                        read_json(task_dir / human_reference),
                    )

                rigors = task.get("rigors", "rigors.json")
                if (task_dir / rigors).exists():
                    validate(schema("rigors.schema.json"), read_json(task_dir / rigors))

                executor_skills = task.get("executor_skills")
                if executor_skills:
                    validate(
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

            validate(schema("run_summary.schema.json"), read_json(run_root / "summary.json"))
            for index, line in enumerate((run_root / "progress_events.jsonl").read_text(encoding="utf-8").splitlines()):
                validate(schema("progress_event.schema.json"), json.loads(line), path=f"progress[{index}]")
            validate(schema("task_manifest.schema.json"), read_json(task_root / "manifest.json"))
            validate(schema("task_summary.schema.json"), read_json(task_root / "task_summary.json"))
            validate(schema("executor_status.schema.json"), read_json(logs / "status.json"))
            validate(schema("trace_summary.schema.json"), read_json(logs / "trace_summary.json"))
            validate(schema("artifact_manifest.schema.json"), read_json(logs / "artifact_manifest.json"))
            validate(
                schema("judge_aggregate.schema.json"),
                read_json(task_root / "judges" / "single_aggregate.json"),
            )


if __name__ == "__main__":
    unittest.main()
