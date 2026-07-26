"""End-to-end closed-loop runs against fake codex/gemini/pi/custom runtimes."""
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

from helpers import DEMO_INSTRUCTION_TASK, DEMO_TASK, ROOT


class ClosedLoopTests(unittest.TestCase):
    def make_fake_codex(self, directory: Path) -> Path:
        script = directory / "fake_codex.py"
        script.write_text(
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

                def write_executor_outputs(cwd):
                    root = Path(cwd) / "outputs" / "stellar_measure"
                    pkg = root / "stellar_measure"
                    pkg.mkdir(parents=True, exist_ok=True)
                    (pkg / "__init__.py").write_text("def parse_segments(v):\n    return [float(x) for x in v.split(',')]\n\ndef summarize_segments(v):\n    return {'total_meters': sum(v)}\n")
                    (pkg / "__main__.py").write_text("print('fake cli')\n")
                    (root / "README.md").write_text("Sample: 12.5,34.75,74.85\n")
                    (root / "test_stellar_measure.py").write_text("\n".join([f"def test_{i}():\n    assert True" for i in range(4)]))

                def rubric_ids(prompt):
                    ids = re.findall(r'"id":\s*"([A-Z]\d+)"', prompt)
                    return ids or ["R001"]

                args = sys.argv[1:]
                if args and args[0] == "--search":
                    args = args[1:]
                if args and args[0] == "exec":
                    args = args[1:]
                cwd = value_after(args, "--cd") or os.getcwd()
                final_path = Path(value_after(args, "--output-last-message") or Path(cwd) / "final.md")
                output_schema = value_after(args, "--output-schema")
                prompt = sys.stdin.read()

                emit({"type": "thread.started", "thread_id": "fake-thread"})
                if output_schema:
                    ids = rubric_ids(prompt)
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    final_path.write_text(json.dumps({
                        "mode": "single",
                        "results": [
                            {
                                "rubric_id": rid,
                                "answer": False if rid in ("R015", "R016", "U016") else True,
                                "evidence": f"fake evidence for {rid}"
                            }
                            for rid in ids
                        ],
                        "overall_notes": "fake ok"
                    }))
                    emit({"type": "item.completed", "item": {"type": "agent_message", "id": "m1", "text": final_path.read_text()}})
                else:
                    write_executor_outputs(cwd)
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    final_path.write_text("Created outputs/stellar_measure and sample verification passed.")
                    emit({"type": "item.completed", "item": {"type": "reasoning", "id": "r1", "text": "fake reasoning summary"}})
                    emit({"type": "item.completed", "item": {"type": "command_execution", "id": "c1", "command": "python -m stellar_measure --segments 12.5,34.75,74.85 --label orion-demo --json", "status": "completed", "exit_code": 0, "aggregated_output": "{\"total_meters\": 122.1, \"total_feet\": 400.591}"}})
                    emit({"type": "item.completed", "item": {"type": "file_change", "id": "f1", "status": "completed", "changes": [{"path": "outputs/stellar_measure"}]}})
                emit({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}})
                '''
            ),
            encoding="utf-8",
        )
        return script

    def make_fake_gemini(self, directory: Path) -> Path:
        script = directory / "fake_gemini.py"
        script.write_text(
            textwrap.dedent(
                r'''
                import json
                import os
                import re
                import sys
                from pathlib import Path

                def write_executor_outputs(cwd):
                    root = Path(cwd) / "outputs" / "stellar_measure"
                    pkg = root / "stellar_measure"
                    pkg.mkdir(parents=True, exist_ok=True)
                    (pkg / "__init__.py").write_text("def parse_segments(v):\n    return [float(x) for x in v.split(',')]\n\ndef summarize_segments(v):\n    return {'total_meters': sum(v)}\n")
                    (pkg / "__main__.py").write_text("print('fake cli')\n")
                    (root / "README.md").write_text("Sample: 12.5,34.75,74.85\n")
                    (root / "test_stellar_measure.py").write_text("\n".join([f"def test_{i}():\n    assert True" for i in range(4)]))

                def rubric_ids(prompt):
                    ids = re.findall(r'"id":\s*"([A-Z]\d+)"', prompt)
                    return ids or ["R001"]

                prompt = sys.stdin.read()
                if "Return only one JSON value" in prompt:
                    ids = rubric_ids(prompt)
                    response = json.dumps({
                        "mode": "single",
                        "results": [
                            {
                                "rubric_id": rid,
                                "answer": False if rid in ("R015", "R016", "U016") else True,
                                "evidence": f"fake evidence for {rid}"
                            }
                            for rid in ids
                        ],
                        "overall_notes": "fake ok"
                    })
                else:
                    write_executor_outputs(os.getcwd())
                    response = "Created outputs/stellar_measure and sample verification passed."
                print(json.dumps({"response": response, "stats": {"tokens": {"total": 30}}}))
                '''
            ),
            encoding="utf-8",
        )
        return script

    def make_fake_pi(self, directory: Path) -> tuple[Path, Path]:
        """Fake pi that serves both roles: executor turn, and judge verdict JSON.

        Both roles assert pi's headless contract (``--mode json``, ``--no-skills``,
        forced ``PI_OFFLINE``, isolated ``PI_CODING_AGENT_DIR``, prompt on stdin);
        the judge role additionally asserts the judge command carries no
        ``--skill``, so an executor skill can never ride into the evaluator.

        Each role also dumps its argv, its ``PI_CODING_AGENT_DIR`` and the
        provider key var it can see (``GEMINI_API_KEY``) to
        ``<argv-dir>/<role>.json``, so the test can check both commands and both
        env scopes from the outside instead of trusting the in-fake asserts
        alone. Returns the script path and that dump directory.
        """
        argv_dir = directory / "pi_calls"
        argv_dir.mkdir(parents=True, exist_ok=True)
        script = directory / "fake_pi.py"
        script.write_text(
            textwrap.dedent(
                r'''
                import json
                import os
                import re
                import sys
                from pathlib import Path

                CALL_DIR = Path(r"__CALL_DIR__")

                def emit(event):
                    print(json.dumps(event), flush=True)

                def rubric_ids(prompt):
                    ids = re.findall(r'"id":\s*"([A-Z]\d+)"', prompt)
                    return ids or ["R001"]

                args = sys.argv[1:]
                assert "--mode" in args and args[args.index("--mode") + 1] == "json", args
                assert "--no-skills" in args, args
                assert os.environ.get("PI_OFFLINE") == "1", "PI_OFFLINE must be forced"
                home = os.environ.get("PI_CODING_AGENT_DIR", "")
                assert home, "PI_CODING_AGENT_DIR must be set"
                prompt = sys.stdin.read()
                assert prompt.strip(), "prompt must arrive on stdin"

                role = "judge" if "Return only one JSON value" in prompt else "executor"
                (CALL_DIR / (role + ".json")).write_text(
                    json.dumps({
                        "argv": args,
                        "pi_home": home,
                        "gemini_api_key": os.environ.get("GEMINI_API_KEY"),
                    }),
                    encoding="utf-8",
                )

                emit({"type": "session", "version": 3, "id": "fake", "timestamp": "t", "cwd": os.getcwd()})
                emit({"type": "agent_start"})
                if role == "judge":
                    assert "--skill" not in args, args
                    text = json.dumps({
                        "mode": "single",
                        "results": [
                            {
                                "rubric_id": rid,
                                "answer": False if rid in ("R015", "R016", "U016") else True,
                                "evidence": f"fake evidence for {rid}"
                            }
                            for rid in rubric_ids(prompt)
                        ],
                        "overall_notes": "fake ok"
                    })
                else:
                    assert "--skill" in args, args
                    cwd = Path(os.getcwd())
                    outputs = cwd / "outputs" / "demo"
                    outputs.mkdir(parents=True, exist_ok=True)
                    (outputs / "result.txt").write_text("done")
                    emit({
                        "type": "tool_execution_end",
                        "toolCallId": "call-1",
                        "toolName": "write",
                        "result": {
                            "content": [{"type": "text", "text": "wrote outputs/demo/result.txt"}],
                            "details": {},
                        },
                    })
                    text = "Fake pi finished the task."
                emit({
                    "type": "message_end",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
                })
                emit({"type": "agent_end", "messages": []})
                '''
            ).replace("__CALL_DIR__", str(argv_dir)),
            encoding="utf-8",
        )
        return script, argv_dir

    def add_executor_skill(self, task_dir: Path, skill_id: str) -> None:
        """Give a copied task package one minimal executor skill.

        Mirrors what ``install_executor_skills`` validates: a real directory
        (no symlinks) holding a SKILL.md, declared in the task's
        ``executor_skills.json``.
        """
        task_config = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        task_config["executor_skills"] = "executor_skills.json"
        (task_dir / "task.json").write_text(json.dumps(task_config), encoding="utf-8")
        skill_dir = task_dir / "skills" / skill_id
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent(
                f"""\
                ---
                name: {skill_id}
                description: Closed-loop fixture skill.
                ---

                # Closed Loop Skill

                Write the deliverable under ./outputs/.
                """
            ),
            encoding="utf-8",
        )
        (task_dir / "executor_skills.json").write_text(
            json.dumps(
                {
                    "skills": [
                        {
                            "id": skill_id,
                            "path": f"skills/{skill_id}",
                            "activation": f"Use `{skill_id}` before writing the deliverable.",
                            "description": "Closed-loop fixture skill.",
                            "leakage_level": "S0",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def make_fake_garbage_codex(self, directory: Path) -> Path:
        """Fake codex: judge calls succeed, executor calls dump non-JSON stdout and fail."""
        script = directory / "fake_garbage_codex.py"
        script.write_text(
            textwrap.dedent(
                r'''
                import json
                import re
                import sys
                from pathlib import Path

                def value_after(args, flag):
                    return args[args.index(flag) + 1] if flag in args else None

                args = sys.argv[1:]
                prompt = sys.stdin.read()
                output_schema = value_after(args, "--output-schema")
                final_path_value = value_after(args, "--output-last-message")
                if output_schema and final_path_value:
                    ids = re.findall(r'"id":\s*"([A-Z]\d+)"', prompt) or ["R001"]
                    final_path = Path(final_path_value)
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    final_path.write_text(json.dumps({
                        "mode": "single",
                        "results": [
                            {
                                "rubric_id": rid,
                                "answer": False,
                                "evidence": "executor failed"
                            }
                            for rid in ids
                        ],
                        "overall_notes": "executor failed"
                    }))
                    print(json.dumps({"type": "turn.completed", "usage": {}}))
                    sys.exit(0)
                print("npm WARN deprecated left-pad@1.0.0")
                print("Fatal: model backend unreachable")
                sys.exit(3)
                '''
            ),
            encoding="utf-8",
        )
        return script

    def test_closed_loop_survives_failing_executor_with_garbage_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
            fake_codex = self.make_fake_garbage_codex(tmp_path)

            cmd = [
                sys.executable,
                "-m",
                "starbench.runner.run_benchmark",
                "--tasks-dir",
                str(tasks_dir),
                "--runs-dir",
                str(runs_dir),
                "--run-id",
                "garbage_run",
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
                cmd, cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            run_root = runs_dir / "garbage_run"
            self.assertTrue((run_root / "summary.json").exists())
            status = json.loads(
                (run_root / "demo_python_cli" / "logs" / "status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(status["status"], "failed")
            self.assertEqual(status["exit_code"], 3)
            summary = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
            task_summary = summary["batches"][0]["tasks"][0]
            executor_status = task_summary["executor"]
            self.assertEqual(executor_status["status"], "failed")
            self.assertEqual(task_summary["outcome"], "inconclusive_executor")
            single = task_summary["judges"]["single"]
            self.assertEqual(single["status"]["status"], "skipped")
            self.assertEqual(single["aggregate"]["outcome"], "inconclusive_executor")
            self.assertIsNone(single["aggregate"]["overall_pass"])
            self.assertFalse(
                (run_root / "demo_python_cli" / "judges" / "single_result.json").exists(),
                "a failed executor must never be sent to a Judge",
            )
            progress_rows = [
                json.loads(line)
                for line in (run_root / "progress_events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            skipped = [
                row
                for row in progress_rows
                if row.get("event") == "evaluator_finished"
                and row.get("status") == "skipped"
            ]
            self.assertEqual(len(skipped), 1)
            self.assertEqual(skipped[0]["outcome"], "inconclusive_executor")

    def test_closed_loop_with_custom_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            runtimes_dir = tmp_path / "runtimes"
            runtimes_dir.mkdir()
            shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
            fake_cli = self.make_fake_gemini(tmp_path)
            (runtimes_dir / "fakecli.json").write_text(
                json.dumps(
                    {
                        "id": "fakecli",
                        "command": f"{sys.executable} {fake_cli}",
                        "parser": "headless-json",
                        "prompt_via": "stdin",
                    }
                ),
                encoding="utf-8",
            )
            cmd = [
                sys.executable, "-m", "starbench.runner.run_benchmark",
                "--tasks-dir", str(tasks_dir), "--runs-dir", str(runs_dir),
                "--runtimes-dir", str(runtimes_dir),
                "--run-id", "custom_run", "--seed", "123",
                "--judge-mode", "single", "--auth-mode", "global",
                "--executor-agent", "custom:fakecli",
                "--evaluator-agent", "custom:fakecli",
                "--no-progress",
            ]
            completed = subprocess.run(cmd, cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            task_root = runs_dir / "custom_run" / "demo_python_cli"
            final = (task_root / "logs" / "final.md").read_text(encoding="utf-8")
            self.assertIn("Created outputs/stellar_measure", final)
            summary = json.loads((task_root / "logs" / "trace_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["agent_messages"][0]["text"], final)
            aggregate = json.loads((task_root / "judges" / "single_aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["passed_count"], aggregate["total_count"])
            run_config = json.loads((runs_dir / "custom_run" / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(run_config["executor_runtime"]["id"], "fakecli")

    def test_closed_loop_with_fake_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
            fake_codex = self.make_fake_codex(tmp_path)

            cmd = [
                sys.executable,
                "-m",
                "starbench.runner.run_benchmark",
                "--tasks-dir",
                str(tasks_dir),
                "--runs-dir",
                str(runs_dir),
                "--run-id",
                "test_run",
                "--batch",
                "exp_smoke",
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
            subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            task_root = runs_dir / "test_run" / "demo_python_cli"
            self.assertTrue((task_root / "logs" / "events.jsonl").exists())
            self.assertTrue((task_root / "logs" / "status.json").exists())
            self.assertTrue((task_root / "judges" / "single_aggregate.json").exists())
            run_config = json.loads((runs_dir / "test_run" / "run_config.json").read_text(encoding="utf-8"))
            # The batch label is a runner fact: --batch lands in run_config.json,
            # which is where the console read model looks for it first.
            self.assertEqual(run_config["batch"], "exp_smoke")
            provenance = run_config["runtime_provenance"]
            self.assertEqual(provenance["schema"], 1)
            self.assertEqual(provenance["executor"]["agent"], "codex")
            self.assertEqual(provenance["executor"]["backend"], "local")
            status = json.loads((task_root / "logs" / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["executor_runtime_provenance"]["agent"], "codex")
            aggregate = json.loads((task_root / "judges" / "single_aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["passed_count"], aggregate["total_count"])

    def test_closed_loop_with_fake_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
            fake_gemini = self.make_fake_gemini(tmp_path)

            cmd = [
                sys.executable,
                "-m",
                "starbench.runner.run_benchmark",
                "--tasks-dir",
                str(tasks_dir),
                "--runs-dir",
                str(runs_dir),
                "--run-id",
                "test_gemini_run",
                "--seed",
                "123",
                "--judge-mode",
                "single",
                "--auth-mode",
                "global",
                "--executor-backend",
                "local",
                "--executor-agent",
                "gemini",
                "--evaluator-agent",
                "gemini",
                "--gemini-bin",
                f"{sys.executable} {fake_gemini}",
                "--no-progress",
            ]
            subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            task_root = runs_dir / "test_gemini_run" / "demo_python_cli"
            final = (task_root / "logs" / "final.md").read_text(encoding="utf-8")
            self.assertIn("Created outputs/stellar_measure", final)
            summary = json.loads((task_root / "logs" / "trace_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["agent_messages"][0]["text"], final)
            aggregate = json.loads((task_root / "judges" / "single_aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["passed_count"], aggregate["total_count"])

    def test_closed_loop_with_fake_pi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
            skill_id = "closed-loop-skill"
            self.add_executor_skill(tasks_dir / "demo_python_cli", skill_id)
            fake_pi, pi_calls = self.make_fake_pi(tmp_path)
            # The shared skill registry defaults to ~/.starbench/skills; point it
            # at an empty tempdir so the run reads nothing from the real home.
            shared_skill_root = tmp_path / "shared_skills"
            shared_skill_root.mkdir()

            cmd = [
                sys.executable,
                "-m",
                "starbench.runner.run_benchmark",
                "--tasks-dir",
                str(tasks_dir),
                "--runs-dir",
                str(runs_dir),
                "--run-id",
                "test_pi_run",
                "--seed",
                "123",
                "--judge-mode",
                "single",
                # pi refuses every other auth mode: the operator's ~/.pi OAuth
                # login must never carry benchmark traffic.
                "--auth-mode",
                "env",
                "--executor-backend",
                "local",
                "--executor-agent",
                "pi",
                "--evaluator-agent",
                "pi",
                "--pi-bin",
                f"{sys.executable} {fake_pi}",
                # pi is the only runtime declaring the `off` tier; it rides its
                # native --thinking switch on both sides of the loop.
                "--thinking-effort",
                "off",
                "--executor-skill",
                skill_id,
                "--executor-skill-root",
                str(shared_skill_root),
                "--no-progress",
            ]
            # Console-style env scoping: a provider key injected for the
            # executor only, with the ambient one stripped so the judge's view
            # is decided by env_scope and not by the developer's shell.
            run_env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
            run_env["STARBENCH_EXECUTOR_ENV_GEMINI_API_KEY"] = "sentinel-executor-only"
            completed = subprocess.run(
                cmd,
                cwd=ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=run_env,
            )
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            task_root = runs_dir / "test_pi_run" / f"demo_python_cli__skill_{skill_id}"
            status = json.loads((task_root / "logs" / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "success")

            final = (task_root / "logs" / "final.md").read_text(encoding="utf-8")
            self.assertEqual(final, "Fake pi finished the task.")
            events = [
                json.loads(line)
                for line in (task_root / "logs" / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            # normalize_pi_events appends the Codex-compat tail, so the trace
            # readers downstream see the same turn terminator as every runtime.
            self.assertEqual(events[-1]["type"], "turn.completed")
            summary = json.loads((task_root / "logs" / "trace_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["agent_messages"][0]["text"], final)
            self.assertEqual(
                summary["command_executions"][0]["aggregated_output"],
                "wrote outputs/demo/result.txt",
            )

            executor_call = json.loads((pi_calls / "executor.json").read_text(encoding="utf-8"))
            judge_call = json.loads((pi_calls / "judge.json").read_text(encoding="utf-8"))

            # A provider key scoped to the executor reaches the executor and
            # stops there: the judge's pi process cannot see it, so a contender
            # cannot reroute the evaluator that grades it through a key var.
            self.assertEqual(executor_call["gemini_api_key"], "sentinel-executor-only")
            self.assertIsNone(judge_call["gemini_api_key"])

            executor_home = task_root / "agent_home" / "pi_executor"
            judge_home = task_root / "agent_home" / "judge_single_pi"
            self.assertTrue(executor_home.is_dir())
            self.assertTrue(judge_home.is_dir())
            # The judge ran under its own PI_CODING_AGENT_DIR, so a contender
            # that poisoned the executor's pi config cannot reach the evaluator.
            self.assertEqual(Path(executor_call["pi_home"]).resolve(), executor_home.resolve())
            self.assertEqual(Path(judge_call["pi_home"]).resolve(), judge_home.resolve())

            # The run installs one executor skill, so the judge-side assertion
            # below has something real to leak: pi passes each installed skill
            # explicitly with --skill.
            installed_skill = task_root / "workspace" / ".starbench" / "executor_skills" / skill_id
            self.assertTrue((installed_skill / "SKILL.md").is_file())
            executor_argv = executor_call["argv"]
            # `off` rides pi's native --thinking switch. The run-level tier is
            # not clamped per side, so the judge command carries it too — that
            # is what the runner does today, and pi accepts the tier on both.
            thinking_at = executor_argv.index("--thinking")
            self.assertEqual(executor_argv[thinking_at : thinking_at + 2], ["--thinking", "off"])
            judge_argv = judge_call["argv"]
            judge_thinking_at = judge_argv.index("--thinking")
            self.assertEqual(judge_argv[judge_thinking_at : judge_thinking_at + 2], ["--thinking", "off"])
            self.assertIn("--skill", executor_argv)
            self.assertEqual(
                Path(executor_argv[executor_argv.index("--skill") + 1]).resolve(),
                installed_skill.resolve(),
            )
            # ...and it must stop at the executor: a skill the contender chose
            # must never coach the evaluator that grades it.
            self.assertNotIn("--skill", judge_call["argv"])

            aggregate = json.loads((task_root / "judges" / "single_aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["passed_count"], aggregate["total_count"])
            provenance = json.loads(
                (runs_dir / "test_pi_run" / "run_config.json").read_text(encoding="utf-8")
            )["runtime_provenance"]
            self.assertEqual(provenance["executor"]["agent"], "pi")
            self.assertEqual(provenance["evaluator"]["agent"], "pi")

    def test_closed_loop_ablation_with_repeats_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            shutil.copytree(DEMO_INSTRUCTION_TASK, tasks_dir / "demo_instruction_reference")
            fake_codex = self.make_fake_codex(tmp_path)

            cmd = [
                sys.executable,
                "-m",
                "starbench.runner.run_benchmark",
                "--tasks-dir",
                str(tasks_dir),
                "--runs-dir",
                str(runs_dir),
                "--run-id",
                "ablation_run",
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
                "--instruction-mode",
                "ablation",
                "--repeat",
                "2",
                "--no-progress",
            ]
            subprocess.run(cmd, cwd=ROOT, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            summary_path = runs_dir / "ablation_run" / "instruction_ablation_summary.json"
            self.assertTrue(summary_path.exists())
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(len(summary["groups"]), 6)
            self.assertTrue(all(group["runs"] == 2 for group in summary["groups"]))

            run_config = json.loads((runs_dir / "ablation_run" / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(len(run_config["task_order"]), 12)
            self.assertTrue(
                any(run_task_id.startswith("demo_instruction_reference__all_instructions") for run_task_id in run_config["task_order"])
            )

            prompts = [path.read_text(encoding="utf-8") for path in runs_dir.rglob("workspace/inputs/prompt.md")]
            self.assertTrue(any("Here are some instructions you might find helpful:" in prompt for prompt in prompts))
            self.assertFalse(any("Step 1 of the expert process" in prompt for prompt in prompts))
            all_prompt = (
                runs_dir
                / "ablation_run"
                / "demo_instruction_reference__all_instructions"
                / "workspace"
                / "inputs"
                / "prompt.md"
            ).read_text(encoding="utf-8")
            self.assertIn("1. Before drafting, organize the answer", all_prompt)
            self.assertIn("4. Explicitly name implementation risks", all_prompt)


if __name__ == "__main__":
    unittest.main()
