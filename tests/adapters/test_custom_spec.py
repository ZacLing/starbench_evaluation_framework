"""Custom (data-driven) runtime specs: loading, validation, command + parsers."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.runner.run_benchmark import parse_args
from starbench.runner.trace import read_jsonl, summarize_events
from helpers import ROOT


class CustomRuntimeSpecTests(unittest.TestCase):
    def write_runtime(self, root: Path, runtime_id: str, data: dict) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{runtime_id}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_load_custom_runtime_parses_fields_and_defaults(self) -> None:
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            self.write_runtime(
                root,
                "qwen-code",
                {
                    "id": "qwen-code",
                    "command": "qwen --experimental",
                    "args": ["--output-format", "json", "--yolo"],
                    "model_flag": "-m",
                    "parser": "headless-json",
                    "docker": {"image": "starbench-qwen:latest", "env_passthrough": ["OPENAI_API_KEY"]},
                },
            )
            spec = load_custom_runtime(root, "qwen-code")
            self.assertEqual(spec.id, "qwen-code")
            self.assertEqual(spec.command, "qwen --experimental")
            self.assertEqual(spec.args, ["--output-format", "json", "--yolo"])
            self.assertEqual(spec.judge_args, spec.args)
            self.assertEqual(spec.model_flag, "-m")
            self.assertEqual(spec.prompt_via, "stdin")
            self.assertEqual(spec.prompt_flag, "-p")
            self.assertEqual(spec.parser, "headless-json")
            self.assertEqual(spec.env, {})
            self.assertEqual(spec.docker_image, "starbench-qwen:latest")
            self.assertEqual(spec.docker_env_passthrough, ["OPENAI_API_KEY"])

    def test_build_custom_command_covers_prompt_modes_and_judge_args(self) -> None:
        from starbench.runner.codex_process import build_custom_command
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            self.write_runtime(
                root,
                "argy",
                {
                    "id": "argy",
                    "command": "mycli run",
                    "args": ["--json"],
                    "judge_args": ["--json", "--read-only"],
                    "model_flag": "--model",
                    "prompt_via": "arg",
                    "prompt_flag": "-p",
                    "parser": "text",
                },
            )
            spec = load_custom_runtime(root, "argy")
            executor = build_custom_command(spec, role="executor", model="m1", prompt="do the task")
            self.assertEqual(executor, ["mycli", "run", "--json", "--model", "m1", "-p", "do the task"])
            judge = build_custom_command(spec, role="judge", model=None, prompt="judge it")
            self.assertEqual(judge, ["mycli", "run", "--json", "--read-only", "-p", "judge it"])

            self.write_runtime(
                root, "stdiny", {"id": "stdiny", "command": "othercli", "parser": "text"}
            )
            stdin_spec = load_custom_runtime(root, "stdiny")
            command = build_custom_command(stdin_spec, role="executor", model="m2", prompt="ignored on argv")
            self.assertEqual(command, ["othercli"])

    def test_null_prompt_flag_passes_prompt_positionally(self) -> None:
        from starbench.runner.codex_process import build_custom_command
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            self.write_runtime(
                root,
                "trae-agent",
                {
                    "id": "trae-agent",
                    "command": "trae-cli run",
                    "model_flag": "--model",
                    "prompt_via": "arg",
                    "prompt_flag": None,
                    "parser": "text",
                },
            )
            spec = load_custom_runtime(root, "trae-agent")
            self.assertEqual(spec.prompt_flag, "")
            command = build_custom_command(spec, role="executor", model="gpt-5.5", prompt="fix the bug")
            self.assertEqual(command, ["trae-cli", "run", "--model", "gpt-5.5", "fix the bug"])

    def test_non_string_prompt_flag_is_rejected(self) -> None:
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            self.write_runtime(
                root,
                "bad",
                {"id": "bad", "command": "cli", "prompt_via": "arg", "prompt_flag": 7, "parser": "text"},
            )
            with self.assertRaisesRegex(ValueError, "prompt_flag must be a string or null"):
                load_custom_runtime(root, "bad")

    def test_custom_text_parser_writes_final_and_synthetic_events(self) -> None:
        from starbench.runner.codex_process import normalize_custom_events, write_custom_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stdout_path = tmp_path / "events.jsonl"
            stdout_path.write_text("Built the deliverable.\nAll checks passed.\n", encoding="utf-8")
            final_path = tmp_path / "final.md"
            write_custom_final_output(stdout_path, final_path, parser="text")
            self.assertEqual(final_path.read_text(encoding="utf-8"), "Built the deliverable.\nAll checks passed.")
            normalize_custom_events(stdout_path, parser="text", provider="mycli")
            summary = summarize_events(read_jsonl(stdout_path))
            self.assertEqual(summary["agent_messages"][0]["text"], "Built the deliverable.\nAll checks passed.")

    def test_custom_jsonl_events_parser_extracts_last_agent_message(self) -> None:
        from starbench.runner.codex_process import write_custom_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stdout_path = tmp_path / "events.jsonl"
            stdout_path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "id": "m1", "text": "draft"}}),
                        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "id": "m2", "text": "final answer"}}),
                        json.dumps({"type": "turn.completed", "usage": {"output_tokens": 3}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            final_path = tmp_path / "final.md"
            write_custom_final_output(stdout_path, final_path, parser="jsonl-events")
            self.assertEqual(final_path.read_text(encoding="utf-8"), "final answer")

    def test_custom_headless_json_parser_supports_schema_output(self) -> None:
        from starbench.runner.codex_process import write_custom_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stdout_path = tmp_path / "events.jsonl"
            stdout_path.write_text(json.dumps({"response": "{\"results\": []}"}), encoding="utf-8")
            final_path = tmp_path / "result.json"
            schema_path = ROOT / "src" / "starbench" / "runner" / "schemas" / "single_result.schema.json"
            write_custom_final_output(stdout_path, final_path, parser="headless-json", output_schema=schema_path)
            self.assertEqual(json.loads(final_path.read_text(encoding="utf-8")), {"results": []})

    def test_parse_args_resolves_custom_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "runtimes"
            self.write_runtime(root, "fake", {"id": "fake", "command": "fakecli", "parser": "text"})
            args = parse_args(
                [
                    "--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                    "--runtimes-dir", str(root),
                    "--executor-agent", "custom:fake",
                    "--evaluator-agent", "codex",
                ]
            )
            self.assertEqual(args.executor_agent, "custom:fake")
            self.assertEqual(args.executor_runtime_spec.id, "fake")
            self.assertIsNone(args.evaluator_runtime_spec)
            self.assertEqual(args.executor_backend, "local")

    def test_parse_args_rejects_unknown_or_invalid_custom_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with self.assertRaises(SystemExit):
                parse_args(
                    ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                     "--runtimes-dir", str(tmp_path), "--executor-agent", "custom:missing"]
                )
            with self.assertRaises(SystemExit):
                parse_args(
                    ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                     "--executor-agent", "franken-cli"]
                )

    def test_parse_args_allows_docker_for_docker_enabled_custom_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "runtimes"
            self.write_runtime(
                root, "dockery",
                {"id": "dockery", "command": "x", "parser": "text",
                 "docker": {"image": "img:latest", "env_passthrough": ["OPENAI_API_KEY"]}},
            )
            self.write_runtime(root, "plain", {"id": "plain", "command": "x", "parser": "text"})
            args = parse_args(
                ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                 "--runtimes-dir", str(root),
                 "--executor-agent", "custom:dockery", "--executor-backend", "docker"]
            )
            self.assertEqual(args.executor_backend, "docker")
            with self.assertRaises(SystemExit):
                parse_args(
                    ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                     "--runtimes-dir", str(root),
                     "--executor-agent", "custom:plain", "--executor-backend", "docker"]
                )

    def test_load_custom_runtime_rejects_bad_configs(self) -> None:
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "missing")
            self.write_runtime(root, "bad-parser", {"id": "bad-parser", "command": "x", "parser": "yaml"})
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "bad-parser")
            self.write_runtime(root, "bad-via", {"id": "bad-via", "command": "x", "parser": "text", "prompt_via": "file"})
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "bad-via")
            self.write_runtime(root, "mismatch", {"id": "other", "command": "x", "parser": "text"})
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "mismatch")


if __name__ == "__main__":
    unittest.main()
