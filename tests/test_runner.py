from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from starbench.runner.evaluation import aggregate_results
from starbench.runner.models import Rubric, RubricResult
from starbench.runner.run_benchmark import build_augmented_prompt_text, build_executor_prompt, materialize_task, parse_args
from starbench.runner.task_loader import build_task_runs, load_task
from starbench.skill_distiller.distill import resolve_source_task, write_skill
from starbench.skills.registry import load_registry_skills
from starbench.runner.trace import read_jsonl, summarize_events


ROOT = Path(__file__).resolve().parents[1]
DEMO_TASK = ROOT / "examples" / "tasks" / "demo_python_cli"
DEMO_INSTRUCTION_TASK = ROOT / "examples" / "tasks" / "demo_instruction_reference"


class TraceParserTests(unittest.TestCase):
    def test_read_jsonl_does_not_split_on_unicode_line_separator_like_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            event = {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "aggregated_output": "before\u0084after",
                },
            }
            path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(read_jsonl(path), [event])

    def test_trace_summary_preserves_reasoning_commands_files_and_usage(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread_1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "reasoning", "id": "r1", "text": "Reasoning summary."}},
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "id": "c1",
                    "command": "python -m stellar_measure",
                    "exit_code": 0,
                    "status": "completed",
                    "aggregated_output": "122.1 400.591",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "id": "f1",
                    "status": "completed",
                    "changes": [{"path": "outputs/stellar_measure/README.md"}],
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}},
        ]
        summary = summarize_events(events)
        self.assertEqual(summary["thread_id"], "thread_1")
        self.assertEqual(summary["reasoning_items"][0]["text"], "Reasoning summary.")
        self.assertEqual(summary["command_executions"][0]["aggregated_output"], "122.1 400.591")
        self.assertEqual(summary["file_changes"][0]["changes"][0]["path"], "outputs/stellar_measure/README.md")
        self.assertEqual(summary["usage"]["output_tokens"], 2)


class AggregationTests(unittest.TestCase):
    def test_fail_fast_failure_fails_overall(self) -> None:
        rubrics = [
            Rubric(id="R001", fail_fast=True, expected=True, question="Required?"),
            Rubric(id="R002", fail_fast=False, expected=False, question="Forbidden?"),
        ]
        results = [
            RubricResult(rubric_id="R001", answer=False, expected=True, passed=False, fail_fast=True, evidence="Missing."),
            RubricResult(rubric_id="R002", answer=False, expected=False, passed=True, fail_fast=False, evidence="Absent."),
        ]
        aggregate = aggregate_results(rubrics, results, mode="single", executor_timing={"duration_seconds": 5.0})
        self.assertFalse(aggregate["overall_pass"])
        self.assertEqual(aggregate["fail_fast_failures"], ["R001"])
        self.assertEqual(aggregate["passed_count"], 1)
        self.assertEqual(aggregate["executor_timing"]["duration_seconds"], 5.0)


class InstructionAblationTests(unittest.TestCase):
    def test_ablation_mode_creates_baseline_and_one_variant_per_step(self) -> None:
        task = load_task(DEMO_INSTRUCTION_TASK)
        task_runs = build_task_runs([task], instruction_mode="ablation")
        self.assertEqual(
            [task_run.instruction_variant for task_run in task_runs],
            ["baseline", "H001", "H002", "H003", "H004", "all_instructions"],
        )

    def test_augmented_prompt_materializes_instruction_without_reasoning(self) -> None:
        task = load_task(DEMO_INSTRUCTION_TASK)
        task_run = build_task_runs([task], instruction_mode="select", instruction_steps=["H001"])[0]
        prompt = build_augmented_prompt_text(task_run)
        self.assertIn("Here are some instructions you might find helpful:", prompt)
        self.assertIn("Before drafting, organize the answer", prompt)
        self.assertNotIn("Step 1 of the expert process", prompt)

    def test_augmented_prompt_materializes_selected_rigors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp) / "demo_instruction_reference"
            shutil.copytree(DEMO_INSTRUCTION_TASK, task_dir)
            (task_dir / "task.json").write_text(
                json.dumps(
                    {
                        "id": "demo_instruction_reference",
                        "name": "Demo instruction reference",
                        "prompt": "prompt.md",
                        "rubrics": "rubrics.json",
                        "human_reference": "human_reference.json",
                        "rigors": "rigors.json",
                    }
                ),
                encoding="utf-8",
            )
            (task_dir / "rigors.json").write_text(
                json.dumps(
                    {
                        "rigors": [
                            {
                                "id": "R001",
                                "rubric_id": "R001",
                                "requirement": "The answer must include a boundary-condition table.",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            task = load_task(task_dir)
            task_run = build_task_runs([task], instruction_mode="none", rigor_mode="select", rigor_ids=["R001"])[0]
            prompt = build_augmented_prompt_text(task_run)
            self.assertIn("Ensure your answer reaches an equivalent level of rigor and depth", prompt)
            self.assertIn("The answer must include a boundary-condition table.", prompt)
            self.assertEqual(task_run.instruction_variant, "rigor_R001")


class ExecutorSkillTests(unittest.TestCase):
    def make_task_with_executor_skill(self, root: Path) -> Path:
        task_dir = root / "demo_python_cli"
        shutil.copytree(DEMO_TASK, task_dir)
        task_config = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        task_config["executor_skills"] = "executor_skills.json"
        (task_dir / "task.json").write_text(json.dumps(task_config), encoding="utf-8")

        skill_dir = task_dir / "skills" / "demo-executor-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent(
                """\
                ---
                name: demo-executor-skill
                description: Use for demo executor skill testing.
                ---

                # Demo Executor Skill

                Use this skill as private execution guidance.
                """
            ),
            encoding="utf-8",
        )
        (skill_dir / "final_self_check.md").write_text("- Check the output path.\n", encoding="utf-8")
        (task_dir / "executor_skills.json").write_text(
            json.dumps(
                {
                    "skills": [
                        {
                            "id": "demo-executor-skill",
                            "path": "skills/demo-executor-skill",
                            "activation": "Use `demo-executor-skill` to plan and self-check the deliverable.",
                            "description": "Demo executor skill.",
                            "leakage_level": "S0",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return task_dir

    def test_executor_skill_is_selected_installed_and_not_copied_as_material(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            task_dir = self.make_task_with_executor_skill(tmp_path)
            task = load_task(task_dir)
            self.assertEqual([skill.id for skill in task.executor_skills], ["demo-executor-skill"])
            self.assertFalse(any(path.name == "executor_skills.json" for path in task.material_paths))
            self.assertFalse(any(path.name == "skills" for path in task.material_paths))

            task_run = build_task_runs(
                [task],
                instruction_mode="none",
                executor_skill_ids=["demo-executor-skill"],
            )[0]
            self.assertEqual(task_run.instruction_variant, "skill_demo-executor-skill")

            augmented_prompt = build_augmented_prompt_text(task_run)
            self.assertNotIn("demo-executor-skill", augmented_prompt)

            executor_prompt = build_executor_prompt(task_run)
            self.assertIn("Installed executor Codex skills:", executor_prompt)
            self.assertIn("`demo-executor-skill`", executor_prompt)
            self.assertIn("$CODEX_HOME/skills/<skill-id>/", executor_prompt)

            run_root = tmp_path / "runs" / "skill_run"
            paths = materialize_task(
                task_run,
                run_root,
                "demo_python_cli__skill_demo-executor-skill",
                executor_backend="docker",
            )
            installed_skill = paths["codex_home"] / "docker" / "skills" / "demo-executor-skill" / "SKILL.md"
            self.assertTrue(installed_skill.exists())
            self.assertTrue((paths["codex_home"] / "docker" / "skills" / "demo-executor-skill" / "final_self_check.md").exists())
            self.assertNotIn(
                "demo-executor-skill",
                (paths["workspace"] / "inputs" / "prompt.md").read_text(encoding="utf-8"),
            )

            manifest = json.loads((paths["task_root"] / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["executor_skill_ids"], ["demo-executor-skill"])
            self.assertEqual(manifest["executor_skill_count"], 1)
            self.assertEqual(manifest["installed_executor_skills"][0]["id"], "demo-executor-skill")
            self.assertIn("sha256", manifest["installed_executor_skills"][0])

    def test_executor_prompt_has_no_skill_section_when_no_skill_selected(self) -> None:
        task = load_task(DEMO_TASK)
        task_run = build_task_runs([task], instruction_mode="none")[0]
        prompt = build_executor_prompt(task_run)
        self.assertNotIn("Installed executor Codex skills:", prompt)
        self.assertNotIn("$CODEX_HOME/skills", prompt)

    def test_executor_skill_cli_argument_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--tasks-dir",
                    tmp,
                    "--runs-dir",
                    tmp,
                    "--executor-skill",
                    "skill-a",
                    "--executor-skill",
                    "skill-b",
                ]
            )
            self.assertEqual(args.executor_skill, ["skill-a", "skill-b"])

    def test_agent_runtime_cli_arguments_can_select_claude(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--tasks-dir",
                    tmp,
                    "--runs-dir",
                    tmp,
                    "--executor-agent",
                    "claude",
                    "--evaluator-agent",
                    "claude",
                    "--claude-bin",
                    "/tmp/claude-wrapper",
                    "--claude-thinking-effort",
                    "high",
                ]
            )
            self.assertEqual(args.executor_agent, "claude")
            self.assertEqual(args.evaluator_agent, "claude")
            self.assertEqual(args.claude_bin, "/tmp/claude-wrapper")
            self.assertEqual(args.claude_thinking_effort, "high")

    def test_shared_executor_skill_registry_can_be_selected_and_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            task = load_task(DEMO_TASK)
            skill_root = tmp_path / "executor_skills"
            skill_dir = skill_root / "generated" / "shared-demo-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                textwrap.dedent(
                    """\
                    ---
                    name: shared-demo-skill
                    description: Shared registry demo skill.
                    ---

                    # Shared Demo Skill
                    """
                ),
                encoding="utf-8",
            )
            (skill_root / "registry.json").write_text(
                json.dumps(
                    {
                        "skills": [
                            {
                                "id": "shared-demo-skill",
                                "path": "generated/shared-demo-skill",
                                "activation": "Use the shared demo skill.",
                                "description": "Shared demo skill.",
                                "leakage_level": "S0",
                            }
                        ],
                        "groups": {"demo-group": ["shared-demo-skill"]},
                    }
                ),
                encoding="utf-8",
            )
            shared_skill = load_registry_skills(skill_root)[0]
            task_run = build_task_runs(
                [task],
                instruction_mode="none",
                executor_skill_ids=["shared-demo-skill"],
                external_executor_skills=[shared_skill],
            )[0]
            self.assertEqual(task_run.executor_skill_ids, ["shared-demo-skill"])
            paths = materialize_task(
                task_run,
                tmp_path / "runs" / "shared_skill_run",
                "demo_python_cli__skill_shared-demo-skill",
                executor_backend="local",
            )
            self.assertTrue((paths["codex_home"] / "skills" / "shared-demo-skill" / "SKILL.md").exists())

            args = parse_args(
                [
                    "--tasks-dir",
                    str(tmp_path),
                    "--runs-dir",
                    str(tmp_path),
                    "--executor-skill-root",
                    str(skill_root),
                    "--executor-skill-group",
                    "demo-group",
                ]
            )
            self.assertEqual(args.executor_skill_group, ["demo-group"])


class SkillDistillerTests(unittest.TestCase):
    def make_source_task(self, root: Path) -> Path:
        task_root = root / "source_task"
        task_package = task_root / "task_package"
        review_dir = task_root / "trace" / "reviews" / "r001_review"
        task_package.mkdir(parents=True)
        review_dir.mkdir(parents=True)
        (task_package / "task.json").write_text(
            json.dumps(
                {
                    "id": "source_measurement_platform",
                    "name": "Source measurement platform",
                    "prompt": "prompt.md",
                    "rubrics": "rubrics.json",
                    "human_reference": "human_reference.json",
                }
            ),
            encoding="utf-8",
        )
        (task_package / "prompt.md").write_text("请写一份中文技术方案，定位为研究评估平台。", encoding="utf-8")
        (task_package / "rubrics.json").write_text(
            json.dumps(
                {
                    "rubrics": [
                        {
                            "id": "A",
                            "fail_fast": True,
                            "expected": True,
                            "question": "Does the deliverable define an immutable pre-registration mechanism with timestamps and hashes?",
                        },
                        {
                            "id": "B",
                            "fail_fast": False,
                            "expected": True,
                            "question": "交付物是否定义数据血缘、缺失值处理和样本可比性规则?",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        (task_package / "human_reference.json").write_text(
            json.dumps(
                {
                    "steps": [
                        {
                            "step_id": "H001",
                            "step_type": "任务定位",
                            "instruction": "Position the answer as a reusable evaluation and governance platform.",
                            "reasoning": "The expert avoids one-off analysis and requires auditable governance.",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (review_dir / "review.json").write_text(
            json.dumps(
                {
                    "review_id": "r001_review",
                    "round_under_review": "v000_cold_start",
                    "weaknesses": [
                        "The draft mentions governance but lacks concrete pre-registration timestamps, hashes, amendment logs, and downgrade rules."
                    ],
                }
            ),
            encoding="utf-8",
        )
        return task_root

    def test_distiller_writes_skill_registry_and_atomic_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source_task = self.make_source_task(tmp_path)
            task = resolve_source_task(source_task)
            skill_dir = write_skill(
                [task],
                output_root=tmp_path / "executor_skills",
                skill_id=None,
                title=None,
                description=None,
                groups=["measurement"],
                leakage_level="S4-test",
                expert_archetype_id="empirical-measurement-governance-expert",
            )
            self.assertTrue((skill_dir / "SKILL.md").exists())
            atomic_cards = (skill_dir / "references" / "atomic_execution_cards.md").read_text(encoding="utf-8")
            self.assertIn("locked configurations", atomic_cards)
            self.assertIn("Research governance and selection control", atomic_cards)
            self.assertIn("Observable evidence", atomic_cards)
            skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("empirical-research platform tasks", skill_md)
            self.assertNotIn("Distilled executor harness from", skill_md)
            self.assertTrue((skill_dir / "references" / "expert_profile.md").exists())
            self.assertTrue((skill_dir / "references" / "specializations" / "source-measurement-platform.md").exists())
            registry = json.loads((tmp_path / "executor_skills" / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["groups"]["measurement"], ["empirical-measurement-governance-expert"])
            self.assertEqual(load_registry_skills(tmp_path / "executor_skills")[0].id, "empirical-measurement-governance-expert")


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
                    ids = re.findall(r'"id":\s*"(R\d+)"', prompt)
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
                                "answer": False if rid in ("R015", "R016") else True,
                                "expected": False if rid in ("R015", "R016") else True,
                                "passed": True,
                                "fail_fast": rid in ("R001", "R002", "R003", "R004", "R005", "R015", "R016"),
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
