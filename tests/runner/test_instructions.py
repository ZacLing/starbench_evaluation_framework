"""Instruction/rigor ablation and augmented-prompt materialization."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.runner.run_benchmark import build_augmented_prompt_text
from starbench.runner.task_loader import build_task_runs, load_task
from helpers import DEMO_INSTRUCTION_TASK


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
                                "rubric_id": "U001",
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


if __name__ == "__main__":
    unittest.main()
