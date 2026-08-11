"""Assorted regression guards: docker command names, claude stream parsing,
backend defaults, launch ordering and CLI argument edge cases."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.runner.run_benchmark import parse_args
from starbench.runner.models import Rubric
from starbench.runner.trace import read_jsonl, summarize_events
from helpers import DEMO_TASK


class RegressionFixTests(unittest.TestCase):
    def test_default_docker_image_matches_documented_build_tag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(["--tasks-dir", tmp, "--runs-dir", tmp])
            self.assertEqual(args.docker_image, "starbench-codex:latest")

    def test_read_jsonl_skips_unparseable_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "thread.started", "thread_id": "t1"}),
                        "npm WARN deprecated something",
                        "Loaded cached credentials.",
                        json.dumps({"type": "turn.completed", "usage": {"output_tokens": 5}}),
                        "{truncated json",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            events = read_jsonl(path)
            self.assertEqual(len(events), 2)
            self.assertEqual(events[0]["type"], "thread.started")
            self.assertEqual(events[1]["type"], "turn.completed")

    def test_docker_command_includes_container_name(self) -> None:
        from starbench.runner.codex_process import build_docker_codex_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_docker_codex_command(
                docker_bin="docker",
                docker_image="starbench-codex:latest",
                workspace=tmp_path,
                codex_home=tmp_path,
                inner_command=["codex", "exec"],
                auth_env={},
                container_name="starbench-task-abc123",
            )
            name_index = command.index("--name")
            self.assertEqual(command[name_index + 1], "starbench-task-abc123")

    def test_docker_command_forwards_base_url_env(self) -> None:
        from starbench.runner.codex_process import build_docker_codex_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_docker_codex_command(
                docker_bin="docker",
                docker_image="starbench-codex:latest",
                workspace=tmp_path,
                codex_home=tmp_path,
                inner_command=["codex", "exec"],
                auth_env={"OPENAI_API_KEY": "x", "OPENAI_BASE_URL": "https://gw.example/v1"},
            )
            self.assertIn("OPENAI_BASE_URL", command)

    def make_claude_stream_events(self) -> list:
        return [
            {"type": "system", "subtype": "init", "cwd": "/workspace", "session_id": "s1"},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "Plan the demo package first."}],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01",
                            "name": "Bash",
                            "input": {"command": "echo hello-starbench"},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_01",
                            "content": "hello-starbench",
                            "is_error": False,
                        }
                    ],
                },
                "tool_use_result": {"stdout": "hello-starbench", "stderr": ""},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_02",
                            "name": "Write",
                            "input": {"file_path": "outputs/demo.md", "content": "demo"},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_02",
                            "content": "File created successfully",
                            "is_error": False,
                        }
                    ],
                },
            },
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "num_turns": 2,
                "result": "done",
                "usage": {"input_tokens": 18, "output_tokens": 177},
            },
        ]

    def test_claude_stream_final_output_written_from_result_event(self) -> None:
        from starbench.runner.codex_process import write_claude_stream_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            events_path = tmp_path / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in self.make_claude_stream_events()),
                encoding="utf-8",
            )
            final_path = tmp_path / "final.md"
            write_claude_stream_final_output(events_path, final_path)
            self.assertEqual(final_path.read_text(encoding="utf-8"), "done")

    def test_prepare_claude_env_global_keeps_host_config_dir(self) -> None:
        import os

        from starbench.runner.codex_process import prepare_claude_env

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            global_env = prepare_claude_env(tmp_path / "claude_global", "global")
            self.assertEqual(
                global_env.get("CLAUDE_CONFIG_DIR"), os.environ.get("CLAUDE_CONFIG_DIR")
            )
            isolated_env = prepare_claude_env(tmp_path / "claude_env", "env")
            self.assertEqual(isolated_env["CLAUDE_CONFIG_DIR"], str(tmp_path / "claude_env"))

    def test_claude_stream_final_output_rejects_error_result(self) -> None:
        from starbench.runner.codex_process import write_claude_stream_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            events_path = tmp_path / "events.jsonl"
            events_path.write_text(
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": True,
                        "result": "Not logged in · Please run /login",
                        "usage": {},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                write_claude_stream_final_output(events_path, tmp_path / "final.md")

    def test_claude_json_final_output_rejects_error_result(self) -> None:
        from starbench.runner.codex_process import write_claude_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stdout_path = tmp_path / "events.jsonl"
            stdout_path.write_text(
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "success",
                        "is_error": True,
                        "result": "Not logged in · Please run /login",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                write_claude_final_output(stdout_path, tmp_path / "final.md")

    def test_claude_stream_events_normalize_to_codex_trace_items(self) -> None:
        from starbench.runner.codex_process import append_claude_compat_events

        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            events_path.write_text(
                "".join(json.dumps(event) + "\n" for event in self.make_claude_stream_events()),
                encoding="utf-8",
            )
            append_claude_compat_events(events_path)
            summary = summarize_events(read_jsonl(events_path))
            self.assertEqual(summary["agent_messages"][0]["text"], "done")
            self.assertEqual(summary["reasoning_items"][0]["text"], "Plan the demo package first.")
            command = summary["command_executions"][0]
            self.assertEqual(command["command"], "echo hello-starbench")
            self.assertEqual(command["status"], "completed")
            self.assertEqual(command["aggregated_output"], "hello-starbench")
            self.assertEqual(summary["file_changes"][0]["changes"][0]["path"], "outputs/demo.md")
            self.assertEqual(summary["usage"]["output_tokens"], 177)

    def test_claude_print_command_supports_stream_json_output(self) -> None:
        from starbench.runner.codex_process import build_claude_print_command

        with tempfile.TemporaryDirectory() as tmp:
            command = build_claude_print_command(
                "claude",
                cwd=Path(tmp),
                model="claude-opus-4-8",
                output_format="stream-json",
            )
            format_index = command.index("--output-format")
            self.assertEqual(command[format_index + 1], "stream-json")
            self.assertIn("--verbose", command)

    def test_claude_executor_allowed_tools_follow_task_web_search(self) -> None:
        from starbench.adapters.claude import claude_executor_allowed_tools

        without_web = claude_executor_allowed_tools(False)
        with_web = claude_executor_allowed_tools(True)
        self.assertNotIn("WebSearch", without_web)
        self.assertIn("WebSearch", with_web)
        self.assertIn("WebFetch", with_web)
        self.assertIn("Bash", without_web)

    def test_executor_backend_defaults_follow_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(["--tasks-dir", tmp, "--runs-dir", tmp])
            self.assertEqual(args.executor_backend, "docker")
            args = parse_args(["--tasks-dir", tmp, "--runs-dir", tmp, "--executor-agent", "claude"])
            self.assertEqual(args.executor_backend, "local")
            args = parse_args(
                [
                    "--tasks-dir", tmp, "--runs-dir", tmp,
                    "--executor-agent", "claude", "--executor-backend", "docker",
                    "--docker-image", "starbench-claude-code:latest",
                ]
            )
            self.assertEqual(args.executor_backend, "docker")
            args = parse_args(
                [
                    "--tasks-dir",
                    tmp,
                    "--runs-dir",
                    tmp,
                    "--executor-agent",
                    "grok",
                    "--executor-backend",
                    "docker",
                ]
            )
            self.assertEqual(args.executor_backend, "docker")
            self.assertEqual(args.docker_image, "starbench-grok:latest")

    def test_docker_backend_error_names_the_right_remedy(self) -> None:
        # Every built-in now ships its own image, so pi + docker parses and
        # resolves starbench-pi:latest; only a custom runtime without a docker
        # section still gets the add-a-docker-section advice.
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--tasks-dir", tmp, "--runs-dir", tmp,
                    "--executor-agent", "pi", "--executor-backend", "docker",
                ]
            )
            self.assertEqual(args.executor_backend, "docker")
            self.assertEqual(args.docker_image, "starbench-pi:latest")

            runtimes = Path(tmp) / "runtimes"
            runtimes.mkdir()
            (runtimes / "hostonly.json").write_text(
                json.dumps({"id": "hostonly", "command": "hostonly-cli", "parser": "text"}),
                encoding="utf-8",
            )
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                parse_args(
                    [
                        "--tasks-dir", tmp, "--runs-dir", tmp,
                        "--runtimes-dir", str(runtimes),
                        "--executor-agent", "custom:hostonly",
                        "--executor-backend", "docker",
                    ]
                )
            self.assertIn("docker section in the custom runtime spec", stderr.getvalue())

    def test_claude_docker_command_isolates_config_dir_in_workspace(self) -> None:
        from starbench.runner.codex_process import build_claude_docker_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_claude_docker_command(
                claude_bin="claude",
                docker_bin="docker",
                docker_image="starbench-claude-code:latest",
                workspace=tmp_path,
                model="claude-opus-4-8",
                allowed_tools="Read,Bash",
                max_turns=None,
                auth_env={"ANTHROPIC_API_KEY": "x"},
                container_name="starbench-claude-1",
            )
            self.assertIn("CLAUDE_CONFIG_DIR=/workspace/.runner/claude_home", command)
            self.assertIn("ANTHROPIC_API_KEY", command)
            self.assertIn("starbench-claude-code:latest", command)
            format_index = command.index("--output-format")
            self.assertEqual(command[format_index + 1], "stream-json")

    def test_parse_args_max_turns_option_defaults_to_unlimited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                ["--tasks-dir", tmp, "--runs-dir", tmp, "--executor-agent", "claude"]
            )
            # No cap by default: claude's max_turns declares no default, so an
            # unset box omits it entirely (the runtime CLI keeps its own default).
            self.assertEqual(args.executor_options, {})
            args = parse_args(
                [
                    "--tasks-dir",
                    tmp,
                    "--runs-dir",
                    tmp,
                    "--executor-agent",
                    "claude",
                    "--executor-option",
                    "max_turns=30",
                ]
            )
            self.assertEqual(args.executor_options, {"max_turns": 30})

    def test_opencode_judges_use_read_only_plan_agent(self) -> None:
        from starbench.runner.run_benchmark import OPENCODE_JUDGE_AGENT

        self.assertEqual(OPENCODE_JUDGE_AGENT, "plan")

    def test_normalize_single_result_accepts_strict_judge_answers(self) -> None:
        from starbench.runner.evaluation import normalize_single_result

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "single_result.json"
            path.write_text(
                json.dumps(
                    {
                        "mode": "single",
                        "results": [
                            {"rubric_id": "R001", "answer": True, "evidence": "ok"}
                        ],
                        "overall_notes": "complete",
                    }
                ),
                encoding="utf-8",
            )
            results = normalize_single_result(path)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].rubric_id, "R001")

    def test_normalize_single_result_rejects_legacy_top_level_list(self) -> None:
        from starbench.runner.evaluation import normalize_single_result

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "single_result.json"
            path.write_text(
                json.dumps(
                    [{"rubric_id": "R001", "answer": True, "evidence": "ok"}]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Judge output contract"):
                normalize_single_result(path)

    def test_normalize_parallel_result_rejects_string_false(self) -> None:
        from starbench.runner.evaluation import normalize_parallel_results

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            path.write_text(
                json.dumps(
                    {"rubric_id": "R001", "answer": "false", "evidence": "missing"}
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Judge output contract"):
                normalize_parallel_results([path])

    def test_rubric_launch_order_is_deterministic_per_task(self) -> None:
        from starbench.runner.run_benchmark import rubric_launch_order

        rubrics = [
            Rubric(id=f"R{index:03d}", fail_fast=False, expected=True, question="Q?")
            for index in range(1, 9)
        ]
        first = rubric_launch_order(rubrics, seed=123, run_task_id="task_a")
        second = rubric_launch_order(rubrics, seed=123, run_task_id="task_a")
        self.assertEqual([rubric.id for rubric in first], [rubric.id for rubric in second])
        self.assertEqual({rubric.id for rubric in first}, {rubric.id for rubric in rubrics})
        other_task = rubric_launch_order(rubrics, seed=123, run_task_id="task_b")
        other_seed = rubric_launch_order(rubrics, seed=124, run_task_id="task_a")
        orders = {
            tuple(rubric.id for rubric in order) for order in (first, other_task, other_seed)
        }
        self.assertGreater(len(orders), 1)

    def test_duplicate_run_id_raises_friendly_error(self) -> None:
        import asyncio

        from starbench.runner.run_benchmark import run_benchmark

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
            (runs_dir / "existing_run").mkdir(parents=True)
            args = parse_args(
                [
                    "--tasks-dir",
                    str(tasks_dir),
                    "--runs-dir",
                    str(runs_dir),
                    "--run-id",
                    "existing_run",
                ]
            )
            with self.assertRaises(SystemExit) as context:
                asyncio.run(run_benchmark(args))
            self.assertIn("existing_run", str(context.exception))


if __name__ == "__main__":
    unittest.main()
