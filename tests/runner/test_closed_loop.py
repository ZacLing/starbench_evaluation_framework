"""End-to-end closed-loop runs against fake codex/gemini/custom runtimes."""
from __future__ import annotations

import json
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
