from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass(frozen=True)
class Rubric:
    id: str
    fail_fast: bool
    expected: bool
    question: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rubric":
        return cls(
            id=str(data["id"]),
            fail_fast=bool(data["fail_fast"]),
            expected=bool(data["expected"]),
            question=str(data["question"]),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "fail_fast": self.fail_fast,
            "expected": self.expected,
            "question": self.question,
        }


@dataclass(frozen=True)
class HumanReferenceStep:
    step_id: str
    step_index: int
    step_type: str
    instruction: str
    reasoning: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any], step_index: int = 0) -> "HumanReferenceStep":
        return cls(
            step_id=str(data["step_id"]),
            step_index=int(data.get("step_index", step_index)),
            step_type=str(data["step_type"]),
            instruction=str(data["instruction"]),
            reasoning=str(data["reasoning"]),
        )

    def public_metadata(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "step_index": self.step_index,
            "step_type": self.step_type,
            "instruction": self.instruction,
        }


@dataclass(frozen=True)
class TaskSpec:
    id: str
    name: str
    source_dir: Path
    prompt_path: Path
    rubrics_path: Path
    human_reference_path: Path | None
    files_dir: Path | None
    material_paths: List[Path]
    timeout_seconds: int
    allow_web_search: bool
    rubrics: List[Rubric]
    human_reference_steps: List[HumanReferenceStep]

    @property
    def prompt_text(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class TaskRunSpec:
    task: TaskSpec
    instruction_mode: str
    selected_steps: List[HumanReferenceStep]

    @property
    def instruction_step_ids(self) -> List[str]:
        return [step.step_id for step in self.selected_steps]

    @property
    def instruction_step_indices(self) -> List[int]:
        return [step.step_index for step in self.selected_steps]

    @property
    def instruction_label(self) -> str | None:
        if not self.selected_steps:
            return None
        return "_".join(step.step_id for step in self.selected_steps)

    @property
    def instruction_variant(self) -> str:
        return self.instruction_label or "baseline"

    def instruction_metadata(self) -> Dict[str, Any]:
        return {
            "instruction_mode": self.instruction_mode,
            "instruction_variant": self.instruction_variant,
            "instruction_step_ids": self.instruction_step_ids,
            "instruction_step_indices": self.instruction_step_indices,
            "instruction_count": len(self.selected_steps),
            "instruction_steps": [step.public_metadata() for step in self.selected_steps],
        }


@dataclass(frozen=True)
class ProcessResult:
    command: List[str]
    exit_code: int | None
    status: str
    timed_out: bool
    started_at: str
    ended_at: str
    duration_seconds: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "exit_code": self.exit_code,
            "status": self.status,
            "timed_out": self.timed_out,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class RubricResult:
    rubric_id: str
    answer: bool
    expected: bool
    passed: bool
    fail_fast: bool
    evidence: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RubricResult":
        answer = bool(data["answer"])
        expected = bool(data["expected"])
        passed = bool(data.get("passed", answer == expected))
        return cls(
            rubric_id=str(data.get("rubric_id") or data.get("id")),
            answer=answer,
            expected=expected,
            passed=passed,
            fail_fast=bool(data["fail_fast"]),
            evidence=str(data.get("evidence", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rubric_id": self.rubric_id,
            "answer": self.answer,
            "expected": self.expected,
            "passed": self.passed,
            "fail_fast": self.fail_fast,
            "evidence": self.evidence,
        }
