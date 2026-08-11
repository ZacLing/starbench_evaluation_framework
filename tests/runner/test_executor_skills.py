"""Executor skill selection/installation and agent-runtime CLI argument parsing."""
from __future__ import annotations

import json
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from starbench.runner.run_benchmark import (
    build_augmented_prompt_text,
    build_executor_prompt,
    materialize_task,
    parse_args,
)
from starbench.runner.task_loader import build_task_runs, load_task
from starbench.skills.registry import load_registry_skills
from helpers import DEMO_TASK


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
            self.assertIn("Installed executor skills:", executor_prompt)
            self.assertIn("`demo-executor-skill`", executor_prompt)
            self.assertIn("$CODEX_HOME/skills/<skill-id>/", executor_prompt)

            run_root = tmp_path / "runs" / "skill_run"
            paths = materialize_task(
                task_run,
                run_root,
                "demo_python_cli__skill_demo-executor-skill",
                executor_backend="docker",
            )
            installed_skill = paths["agent_home"] / "docker" / "skills" / "demo-executor-skill" / "SKILL.md"
            self.assertTrue(installed_skill.exists())
            self.assertTrue((paths["agent_home"] / "docker" / "skills" / "demo-executor-skill" / "final_self_check.md").exists())
            self.assertNotIn(
                "demo-executor-skill",
                (paths["workspace"] / "inputs" / "prompt.md").read_text(encoding="utf-8"),
            )

            manifest = json.loads((paths["task_root"] / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["executor_skill_ids"], ["demo-executor-skill"])
            self.assertEqual(manifest["executor_skill_count"], 1)
            self.assertEqual(manifest["installed_executor_skills"][0]["id"], "demo-executor-skill")
            self.assertIn("sha256", manifest["installed_executor_skills"][0])

            grok_paths = materialize_task(
                task_run,
                tmp_path / "runs" / "skill_run_grok",
                "demo_python_cli__skill_demo-executor-skill",
                executor_backend="local",
                executor_agent="grok",
            )
            self.assertTrue(
                (
                    grok_paths["workspace"]
                    / ".grok"
                    / "skills"
                    / "demo-executor-skill"
                    / "SKILL.md"
                ).exists()
            )

            gemini_paths = materialize_task(
                task_run,
                tmp_path / "runs" / "skill_run_gemini",
                "demo_python_cli__skill_demo-executor-skill",
                executor_backend="local",
                executor_agent="gemini",
            )
            self.assertTrue(
                (
                    gemini_paths["workspace"]
                    / ".gemini"
                    / "skills"
                    / "demo-executor-skill"
                    / "SKILL.md"
                ).exists()
            )

    def test_executor_prompt_has_no_skill_section_when_no_skill_selected(self) -> None:
        task = load_task(DEMO_TASK)
        task_run = build_task_runs([task], instruction_mode="none")[0]
        prompt = build_executor_prompt(task_run)
        self.assertNotIn("Installed executor skills:", prompt)
        self.assertNotIn("$CODEX_HOME/skills", prompt)

    def test_required_executor_skill_is_installed_once_and_prompt_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            task = load_task(self.make_task_with_executor_skill(tmp_path))
            task_run = build_task_runs(
                [task],
                instruction_mode="none",
                required_executor_skill_ids=["demo-executor-skill"],
            )[0]

            self.assertEqual(task_run.executor_skill_ids, ["demo-executor-skill"])
            self.assertEqual(task_run.advisory_executor_skill_ids, [])
            self.assertEqual(
                task_run.required_executor_skill_ids,
                ["demo-executor-skill"],
            )
            prompt = build_executor_prompt(
                task_run,
                executor_skill_location="./.claude/skills/<skill-id>/",
            )
            self.assertIn("Required executor skills:", prompt)
            self.assertIn("read the complete SKILL.md", prompt)
            self.assertIn("./.claude/skills/<skill-id>/", prompt)
            self.assertIn("Do not skip a required skill", prompt)

            paths = materialize_task(
                task_run,
                tmp_path / "runs" / "required_skill_run",
                "demo_python_cli__skill_demo-executor-skill",
                executor_backend="local",
            )
            manifest = json.loads(
                (paths["task_root"] / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["executor_skill_count"], 1)
            self.assertEqual(manifest["advisory_executor_skill_ids"], [])
            self.assertEqual(
                manifest["required_executor_skill_ids"],
                ["demo-executor-skill"],
            )
            self.assertEqual(
                [item["id"] for item in manifest["required_executor_skills"]],
                ["demo-executor-skill"],
            )

    def test_required_executor_skill_upgrades_ordinary_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task(self.make_task_with_executor_skill(Path(tmp)))
            task_run = build_task_runs(
                [task],
                instruction_mode="none",
                executor_skill_ids=["demo-executor-skill"],
                required_executor_skill_ids=["demo-executor-skill"],
            )[0]
            self.assertEqual(task_run.executor_skill_ids, ["demo-executor-skill"])
            self.assertEqual(task_run.advisory_executor_skill_ids, [])
            self.assertEqual(
                task_run.required_executor_skill_ids,
                ["demo-executor-skill"],
            )

    def test_duplicate_required_executor_skill_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = load_task(self.make_task_with_executor_skill(Path(tmp)))
            with self.assertRaisesRegex(
                ValueError,
                "Duplicate --required-executor-skill value",
            ):
                build_task_runs(
                    [task],
                    instruction_mode="none",
                    required_executor_skill_ids=[
                        "demo-executor-skill",
                        "demo-executor-skill",
                    ],
                )

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

    def test_required_executor_skill_cli_argument_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--tasks-dir",
                    tmp,
                    "--runs-dir",
                    tmp,
                    "--required-executor-skill",
                    "skill-a",
                    "--required-executor-skill",
                    "skill-b",
                ]
            )
            self.assertEqual(args.required_executor_skill, ["skill-a", "skill-b"])

    def test_local_codex_skills_upgrade_global_executor_auth_to_copy_auth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for selection_flag in (
                "--executor-skill",
                "--required-executor-skill",
                "--executor-skill-group",
            ):
                with self.subTest(selection_flag=selection_flag):
                    args = parse_args(
                        [
                            "--tasks-dir",
                            tmp,
                            "--runs-dir",
                            tmp,
                            "--executor-agent",
                            "codex",
                            "--executor-backend",
                            "local",
                            "--auth-mode",
                            "global",
                            selection_flag,
                            "skill-a",
                        ]
                    )
                    self.assertEqual(args.executor_auth_mode, "copy-auth")
                    self.assertEqual(args.evaluator_auth_mode, "global")

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
            self.assertEqual(args.thinking_effort, "high")

    def test_agent_runtime_cli_arguments_can_select_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--tasks-dir",
                    tmp,
                    "--runs-dir",
                    tmp,
                    "--executor-agent",
                    "opencode",
                    "--evaluator-agent",
                    "opencode",
                    "--opencode-bin",
                    "/tmp/opencode",
                    "--executor-option",
                    "provider=yunwu",
                    "--executor-option",
                    "base_url=https://yunwu.ai/v1",
                    "--executor-option",
                    "api_key_env=ANTHROPIC_AUTH_TOKEN",
                    "--evaluator-option",
                    "provider=yunwu",
                    "--evaluator-option",
                    "base_url=https://yunwu.ai/v1",
                    "--evaluator-option",
                    "api_key_env=ANTHROPIC_AUTH_TOKEN",
                    "--auth-mode",
                    "env",
                    "--evaluator-auth-mode",
                    "global",
                ]
            )
            self.assertEqual(args.executor_agent, "opencode")
            self.assertEqual(args.evaluator_agent, "opencode")
            self.assertEqual(args.opencode_bin, "/tmp/opencode")
            self.assertEqual(
                args.executor_options,
                {
                    "provider": "yunwu",
                    "base_url": "https://yunwu.ai/v1",
                    "api_key_env": "ANTHROPIC_AUTH_TOKEN",
                },
            )
            self.assertEqual(
                args.evaluator_options,
                {
                    "provider": "yunwu",
                    "base_url": "https://yunwu.ai/v1",
                    "api_key_env": "ANTHROPIC_AUTH_TOKEN",
                },
            )
            self.assertEqual(args.executor_auth_mode, "env")
            self.assertEqual(args.evaluator_auth_mode, "global")

    def test_role_specific_opencode_settings_are_independent(self) -> None:
        args = parse_args(
            [
                "--executor-agent",
                "opencode",
                "--evaluator-agent",
                "opencode",
                "--executor-option",
                "provider=executor-provider",
                "--executor-option",
                "base_url=https://executor.example/v1",
                "--evaluator-option",
                "provider=judge-provider",
                "--evaluator-option",
                "base_url=https://judge.example/v1",
            ]
        )
        # Executor and evaluator boxes are independent: no shared flag, no
        # shared->role fallback. (api_key_env default-fills OPENAI_API_KEY into
        # each box; the provider/base_url each role set stay role-scoped.)
        self.assertEqual(args.executor_options["provider"], "executor-provider")
        self.assertEqual(args.executor_options["base_url"], "https://executor.example/v1")
        self.assertEqual(args.evaluator_options["provider"], "judge-provider")
        self.assertEqual(args.evaluator_options["base_url"], "https://judge.example/v1")

    def test_agent_runtime_cli_arguments_can_select_grok_and_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(
                [
                    "--tasks-dir",
                    tmp,
                    "--runs-dir",
                    tmp,
                    "--executor-agent",
                    "grok",
                    "--evaluator-agent",
                    "gemini",
                    "--grok-bin",
                    "/tmp/grok",
                    "--gemini-bin",
                    "/tmp/gemini",
                    "--auth-mode",
                    "global",
                ]
            )
            self.assertEqual(args.executor_agent, "grok")
            self.assertEqual(args.evaluator_agent, "gemini")
            self.assertEqual(args.grok_bin, "/tmp/grok")
            self.assertEqual(args.gemini_bin, "/tmp/gemini")
            self.assertEqual(args.executor_auth_mode, "global")
            self.assertEqual(args.evaluator_auth_mode, "global")

    def test_split_auth_modes_default_to_shared_auth_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = parse_args(["--tasks-dir", tmp, "--runs-dir", tmp, "--auth-mode", "global"])
            self.assertEqual(args.executor_auth_mode, "global")
            self.assertEqual(args.evaluator_auth_mode, "global")

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
            self.assertTrue((paths["agent_home"] / "skills" / "shared-demo-skill" / "SKILL.md").exists())

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


if __name__ == "__main__":
    unittest.main()
