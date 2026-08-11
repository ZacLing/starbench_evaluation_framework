"""Skill distiller: writes skill registry and atomic execution cards."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.skill_distiller.distill import resolve_source_task, write_skill
from starbench.skills.registry import load_registry_skills


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


if __name__ == "__main__":
    unittest.main()
