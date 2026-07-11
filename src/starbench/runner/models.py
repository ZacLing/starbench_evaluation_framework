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
class Rigor:
    id: str
    rubric_id: str
    requirement: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Rigor":
        return cls(
            id=str(data["id"]),
            rubric_id=str(data.get("rubric_id", data["id"])),
            requirement=str(data["requirement"]),
        )

    def public_metadata(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rubric_id": self.rubric_id,
            "requirement": self.requirement,
        }


@dataclass(frozen=True)
class ExecutorSkill:
    id: str
    source_path: Path
    activation: str
    description: str
    leakage_level: str | None = None
    sha256: str | None = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, task_dir: Path) -> "ExecutorSkill":
        return cls.from_base_dir(data, base_dir=task_dir)

    @classmethod
    def from_base_dir(cls, data: Dict[str, Any], *, base_dir: Path) -> "ExecutorSkill":
        skill_id = str(data["id"])
        if not skill_id or skill_id in {".", ".."} or "/" in skill_id or "\\" in skill_id:
            raise ValueError(f"Invalid executor skill id: {skill_id!r}")

        source_value = str(data.get("path") or f"skills/{skill_id}")
        source_path = (base_dir / source_value).resolve()
        if not source_path.exists() or not source_path.is_dir():
            raise FileNotFoundError(f"Missing executor skill directory for {skill_id}: {source_path}")

        skill_md = source_path / "SKILL.md"
        if not skill_md.exists() or not skill_md.is_file():
            raise FileNotFoundError(f"Executor skill {skill_id} is missing SKILL.md: {skill_md}")

        return cls(
            id=skill_id,
            source_path=source_path,
            activation=str(
                data.get("activation")
                or f"Use the installed executor skill `{skill_id}` as private execution guidance for this task."
            ),
            description=str(data.get("description", "")),
            leakage_level=str(data["leakage_level"]) if data.get("leakage_level") is not None else None,
            sha256=str(data["sha256"]) if data.get("sha256") is not None else None,
        )

    def public_metadata(self, *, installed_to: str | None = None) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "id": self.id,
            "activation": self.activation,
            "description": self.description,
            "source_path": str(self.source_path),
        }
        if self.leakage_level is not None:
            metadata["leakage_level"] = self.leakage_level
        if self.sha256 is not None:
            metadata["sha256"] = self.sha256
        if installed_to is not None:
            metadata["installed_to"] = installed_to
        return metadata


@dataclass(frozen=True)
class TaskSpec:
    id: str
    name: str
    source_dir: Path
    prompt_path: Path
    rubrics_path: Path
    human_reference_path: Path | None
    rigors_path: Path | None
    executor_skills_path: Path | None
    files_dir: Path | None
    material_paths: List[Path]
    timeout_seconds: int
    allow_web_search: bool
    rubrics: List[Rubric]
    human_reference_steps: List[HumanReferenceStep]
    rigors: List[Rigor]
    executor_skills: List[ExecutorSkill]

    @property
    def prompt_text(self) -> str:
        return self.prompt_path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class TaskRunSpec:
    task: TaskSpec
    instruction_mode: str
    selected_steps: List[HumanReferenceStep]
    rigor_mode: str = "none"
    selected_rigors: List[Rigor] | None = None
    selected_executor_skills: List[ExecutorSkill] | None = None
    variant_label: str | None = None

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
        labels = []
        if self.variant_label:
            labels.append(self.variant_label)
        elif self.instruction_label:
            labels.append(self.instruction_label)
        rigor_label = self.rigor_label
        if rigor_label:
            labels.append(rigor_label)
        executor_skill_label = self.executor_skill_label
        if executor_skill_label:
            labels.append(executor_skill_label)
        return "__".join(labels) if labels else "baseline"

    @property
    def rigor_ids(self) -> List[str]:
        return [rigor.id for rigor in self.selected_rigors or []]

    @property
    def rigor_rubric_ids(self) -> List[str]:
        return [rigor.rubric_id for rigor in self.selected_rigors or []]

    @property
    def rigor_label(self) -> str | None:
        if not self.selected_rigors:
            return None
        return "rigor_" + "_".join(rigor.id for rigor in self.selected_rigors)

    @property
    def executor_skill_ids(self) -> List[str]:
        return [skill.id for skill in self.selected_executor_skills or []]

    @property
    def executor_skill_label(self) -> str | None:
        if not self.selected_executor_skills:
            return None
        return "skill_" + "_".join(skill.id for skill in self.selected_executor_skills)

    def instruction_metadata(self) -> Dict[str, Any]:
        return {
            "instruction_mode": self.instruction_mode,
            "instruction_variant": self.instruction_variant,
            "instruction_step_ids": self.instruction_step_ids,
            "instruction_step_indices": self.instruction_step_indices,
            "instruction_count": len(self.selected_steps),
            "instruction_steps": [step.public_metadata() for step in self.selected_steps],
            "rigor_mode": self.rigor_mode,
            "rigor_ids": self.rigor_ids,
            "rigor_rubric_ids": self.rigor_rubric_ids,
            "rigor_count": len(self.selected_rigors or []),
            "rigors": [rigor.public_metadata() for rigor in self.selected_rigors or []],
            "executor_skill_ids": self.executor_skill_ids,
            "executor_skill_count": len(self.selected_executor_skills or []),
            "executor_skills": [skill.public_metadata() for skill in self.selected_executor_skills or []],
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


def _require_json_bool(value: Any, field: str) -> bool:
    """Judge output must use JSON booleans. Python's bool() would turn the
    string "false" into True, silently flipping a rubric verdict, so any
    non-boolean value is a parse error rather than a coercion."""
    if type(value) is not bool:
        raise ValueError(
            f"Judge result field {field!r} must be a JSON boolean, got {value!r}"
        )
    return value


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
        answer = _require_json_bool(data["answer"], "answer")
        expected = _require_json_bool(data["expected"], "expected")
        if "passed" in data:
            passed = _require_json_bool(data["passed"], "passed")
        else:
            passed = answer == expected
        return cls(
            rubric_id=str(data.get("rubric_id") or data.get("id")),
            answer=answer,
            expected=expected,
            passed=passed,
            fail_fast=_require_json_bool(data["fail_fast"], "fail_fast"),
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
