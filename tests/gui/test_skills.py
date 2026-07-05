"""Executor skills: the resource service, launcher passthrough and plan-time
validation in ``starbench.gui.skills`` / ``launcher`` / ``experiments``."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.gui import experiments, skills
from starbench.gui.experiments import ExperimentError
from starbench.gui.launcher import LaunchError, build_run_argv
from starbench.gui.skills import SkillError
from helpers import write_json


def make_skill_library(root: Path, entries, groups) -> None:
    """Write a skill library: a directory + SKILL.md per skill, plus a registry."""
    registry_skills = []
    for skill_id, description in entries:
        skill_dir = root / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n{description}\n", encoding="utf-8")
        (skill_dir / "reference.md").write_text("supporting detail\n", encoding="utf-8")
        registry_skills.append({"id": skill_id, "path": skill_id, "description": description})
    write_json(root / "registry.json", {"skills": registry_skills, "groups": groups})


class SkillsServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_skills_"))
        self.root = self.tmp / "executor_skills"
        self.root.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_library_is_a_normal_empty_state(self) -> None:
        # No registry file at all: an empty library, not an error.
        payload = skills.list_skills(self.root)
        self.assertEqual(payload["skills"], [])
        self.assertEqual(payload["groups"], {})
        self.assertNotIn("error", payload)
        self.assertEqual(payload["root"], str(self.root.resolve()))

    def test_lists_skills_with_metadata_and_group_membership(self) -> None:
        make_skill_library(
            self.root,
            entries=[("alpha-expert", "Alpha guidance"), ("beta-expert", "Beta guidance")],
            groups={"core": ["alpha-expert", "beta-expert"], "solo": ["alpha-expert"]},
        )
        payload = skills.list_skills(self.root)
        self.assertNotIn("error", payload)
        by_id = {skill["id"]: skill for skill in payload["skills"]}
        self.assertEqual(set(by_id), {"alpha-expert", "beta-expert"})
        alpha = by_id["alpha-expert"]
        self.assertEqual(alpha["description"], "Alpha guidance")
        self.assertEqual(alpha["file_count"], 2)  # SKILL.md + reference.md
        self.assertGreater(alpha["size_bytes"], 0)
        self.assertEqual(alpha["groups"], ["core", "solo"])
        self.assertEqual(by_id["beta-expert"]["groups"], ["core"])
        self.assertEqual(payload["groups"]["core"], ["alpha-expert", "beta-expert"])

    def test_malformed_json_returns_error_not_500(self) -> None:
        (self.root / "registry.json").write_text("{not json", encoding="utf-8")
        payload = skills.list_skills(self.root)
        self.assertEqual(payload["skills"], [])
        self.assertIn("error", payload)
        self.assertIn("could not be read", payload["error"])

    def test_duplicate_id_returns_error_not_500(self) -> None:
        (self.root / "dup").mkdir()
        (self.root / "dup" / "SKILL.md").write_text("# dup\n", encoding="utf-8")
        write_json(
            self.root / "registry.json",
            {
                "skills": [
                    {"id": "dup", "path": "dup", "description": "one"},
                    {"id": "dup", "path": "dup", "description": "two"},
                ],
                "groups": {},
            },
        )
        payload = skills.list_skills(self.root)
        self.assertEqual(payload["skills"], [])
        self.assertIn("error", payload)


class ValidateSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_skillsel_"))
        self.root = self.tmp / "executor_skills"
        self.root.mkdir()
        make_skill_library(
            self.root,
            entries=[("alpha-expert", "Alpha"), ("beta-expert", "Beta")],
            groups={"core": ["alpha-expert", "beta-expert"], "just-alpha": ["alpha-expert"]},
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_selection_returns_empty(self) -> None:
        self.assertEqual(skills.validate_selection(self.root, [], []), [])
        self.assertEqual(skills.validate_selection(self.root, None, None), [])

    def test_group_expands_to_member_ids(self) -> None:
        self.assertEqual(
            skills.validate_selection(self.root, [], ["core"]),
            ["alpha-expert", "beta-expert"],
        )

    def test_individual_and_group_combine(self) -> None:
        # A skill picked individually plus a non-overlapping group.
        self.assertEqual(
            skills.validate_selection(self.root, ["beta-expert"], ["just-alpha"]),
            ["beta-expert", "alpha-expert"],
        )

    def test_unknown_skill_rejected(self) -> None:
        with self.assertRaisesRegex(SkillError, "Unknown skill"):
            skills.validate_selection(self.root, ["ghost-expert"], [])

    def test_unknown_group_rejected(self) -> None:
        with self.assertRaisesRegex(SkillError, "Unknown skill group"):
            skills.validate_selection(self.root, [], ["ghost-group"])

    def test_overlap_between_skill_and_group_rejected(self) -> None:
        # A skill listed individually and also inside a selected group would be
        # installed twice by the runner; the plan rejects it up front.
        with self.assertRaisesRegex(SkillError, "more than once"):
            skills.validate_selection(self.root, ["alpha-expert", "beta-expert"], ["core"])


class LauncherSkillPassthroughTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_skilllaunch_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, **overrides):
        base = {
            "run_id": "gui_skill",
            "tasks_dir": str(self.tasks_dir),
            "tasks": ["demo"],
            "executor_agent": "codex",
            "evaluator_agent": "claude",
            "judge_mode": "single",
            "auth_mode": "env",
            "executor_backend": "local",
        }
        base.update(overrides)
        return base

    def test_skill_ids_groups_and_root_pass_through(self) -> None:
        argv = build_run_argv(
            self.payload(
                executor_skills=["alpha-expert", "beta-expert"],
                executor_skill_groups=["core"],
                executor_skill_root="/srv/skills",
            ),
            runs_dir=self.runs_dir,
        )
        joined = " ".join(argv)
        self.assertEqual(joined.count("--executor-skill "), 2)
        self.assertIn("--executor-skill alpha-expert", joined)
        self.assertIn("--executor-skill beta-expert", joined)
        self.assertIn("--executor-skill-group core", joined)
        self.assertIn("--executor-skill-root /srv/skills", joined)

    def test_no_skills_emits_no_flags(self) -> None:
        argv = build_run_argv(self.payload(), runs_dir=self.runs_dir)
        joined = " ".join(argv)
        self.assertNotIn("--executor-skill", joined)
        self.assertNotIn("--executor-skill-root", joined)

    def test_non_string_skill_element_rejected(self) -> None:
        with self.assertRaises(LaunchError):
            build_run_argv(
                self.payload(executor_skills=["alpha-expert", 7]), runs_dir=self.runs_dir
            )


class ExperimentSkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_gui_skillexp_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.tasks_dir = self.tmp / "tasks"
        self.tasks_dir.mkdir()
        self.skills_dir = self.tmp / "executor_skills"
        self.skills_dir.mkdir()
        make_skill_library(
            self.skills_dir,
            entries=[("alpha-expert", "Alpha"), ("beta-expert", "Beta")],
            groups={"core": ["alpha-expert", "beta-expert"]},
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def payload(self, shared_extra=None, **overrides):
        shared = {
            "evaluator_agent": "codex",
            "evaluator_model": "gpt-5.5",
            "evaluator_auth_mode": "global",
            "judge_mode": "single",
            "executor_backend": "local",
            "seed": 7,
        }
        if shared_extra:
            shared.update(shared_extra)
        base = {
            "name": "exp_skill",
            "tasks_dir": str(self.tasks_dir),
            "tasks": ["demo_task"],
            "shared": shared,
            "contenders": [
                {"label": "GPT", "agent": "codex", "model": "gpt-5.5", "auth_mode": "env"},
                {"label": "Claude", "agent": "claude", "model": "claude-opus-4-8", "auth_mode": "global"},
            ],
        }
        base.update(overrides)
        return base

    def plan(self, payload):
        return experiments.plan_experiment(
            payload, runs_dir=self.runs_dir, skills_dir=self.skills_dir
        )

    def test_shared_skills_forward_to_every_contender(self) -> None:
        payload = self.payload(shared_extra={"executor_skills": ["alpha-expert"]})
        plan = self.plan(payload)
        self.assertEqual(len(plan["plans"]), 2)
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--executor-skill alpha-expert", joined)
            self.assertIn(f"--executor-skill-root {self.skills_dir}", joined)
            self.assertEqual(item["executor_skills"], ["alpha-expert"])

    def test_group_selection_expands_in_summary_and_passes_group_flag(self) -> None:
        payload = self.payload(shared_extra={"executor_skill_groups": ["core"]})
        plan = self.plan(payload)
        for item in plan["plans"]:
            joined = " ".join(item["argv"])
            self.assertIn("--executor-skill-group core", joined)
            # The runner expands groups, so members are NOT also passed as ids.
            self.assertNotIn("--executor-skill alpha-expert", joined)
            self.assertEqual(item["executor_skills"], ["alpha-expert", "beta-expert"])

    def test_no_skills_selected_passes_no_flags(self) -> None:
        plan = self.plan(self.payload())
        for item in plan["plans"]:
            self.assertNotIn("--executor-skill", " ".join(item["argv"]))
            self.assertEqual(item["executor_skills"], [])

    def test_unknown_skill_id_rejected_at_plan_time(self) -> None:
        payload = self.payload(shared_extra={"executor_skills": ["ghost-expert"]})
        with self.assertRaisesRegex(ExperimentError, "Unknown skill"):
            self.plan(payload)

    def test_unknown_group_rejected_at_plan_time(self) -> None:
        payload = self.payload(shared_extra={"executor_skill_groups": ["ghost-group"]})
        with self.assertRaisesRegex(ExperimentError, "Unknown skill group"):
            self.plan(payload)


if __name__ == "__main__":
    unittest.main()
