from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Sequence

from .models import ExecutorSkill, HumanReferenceStep, Rigor, Rubric, TaskRunSpec, TaskSpec


def _discover_material_paths(
    task_dir: Path,
    *,
    config_path: Path,
    prompt_path: Path,
    rubrics_path: Path,
    human_reference_path: Path,
    files_dir: Path | None,
    configured_materials: Sequence[str] | None,
    extra_excluded_paths: Sequence[Path] | None = None,
) -> List[Path]:
    if configured_materials is not None:
        return [(task_dir / material).resolve() for material in configured_materials]

    excluded = {config_path.resolve(), prompt_path.resolve(), rubrics_path.resolve()}
    if human_reference_path.exists():
        excluded.add(human_reference_path.resolve())
    if files_dir is not None and files_dir.exists():
        excluded.add(files_dir.resolve())
    for path in extra_excluded_paths or []:
        if path.exists():
            excluded.add(path.resolve())

    materials: List[Path] = []
    for path in sorted(task_dir.iterdir()):
        if path.name.startswith(".") or path.name == "__pycache__":
            continue
        if path.resolve() in excluded:
            continue
        materials.append(path.resolve())
    return materials


def load_task(task_dir: Path) -> TaskSpec:
    task_dir = task_dir.resolve()
    config_path = task_dir / "task.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing task.json in {task_dir}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    prompt_path = task_dir / config.get("prompt", "prompt.md")
    rubrics_path = task_dir / config.get("rubrics", "rubrics.json")
    human_reference_path = task_dir / config.get("human_reference", "human_reference.json")
    rigors_path = task_dir / config.get("rigors", "rigors.json")
    executor_skills_value = config.get("executor_skills", "executor_skills.json")
    executor_skills_path = task_dir / executor_skills_value if executor_skills_value else None
    subtle_difference_value = config.get("subtle_difference")
    subtle_difference_path = task_dir / subtle_difference_value if subtle_difference_value else None
    files_dir_value = config.get("files_dir", "files")
    files_dir = task_dir / files_dir_value if files_dir_value else None
    if files_dir is not None and not files_dir.exists():
        files_dir = None
    configured_materials = config.get("materials")
    if configured_materials is None:
        configured_materials = config.get("input_materials")
    executor_skills: List[ExecutorSkill] = []
    executor_skill_exclusions: List[Path] = []
    if executor_skills_path is not None and executor_skills_path.exists():
        executor_skills_data = json.loads(executor_skills_path.read_text(encoding="utf-8"))
        seen_executor_skill_ids = set()
        for item in executor_skills_data.get("skills", []):
            skill = ExecutorSkill.from_dict(item, task_dir=task_dir)
            if skill.id in seen_executor_skill_ids:
                raise ValueError(f"Duplicate executor skill id {skill.id} in {executor_skills_path}")
            seen_executor_skill_ids.add(skill.id)
            executor_skills.append(skill)
        executor_skill_exclusions.append(executor_skills_path)
        for skill in executor_skills:
            try:
                relative_source = skill.source_path.relative_to(task_dir)
            except ValueError:
                executor_skill_exclusions.append(skill.source_path)
            else:
                if relative_source.parts:
                    executor_skill_exclusions.append(task_dir / relative_source.parts[0])
        if (task_dir / "skills").exists():
            executor_skill_exclusions.append(task_dir / "skills")
    else:
        executor_skills_path = None
    material_paths = _discover_material_paths(
        task_dir,
        config_path=config_path,
        prompt_path=prompt_path,
        rubrics_path=rubrics_path,
        human_reference_path=human_reference_path,
        files_dir=files_dir,
        configured_materials=configured_materials,
        extra_excluded_paths=[
            path for path in (subtle_difference_path, rigors_path) if path is not None
        ]
        + executor_skill_exclusions,
    )
    missing_materials = [str(path) for path in material_paths if not path.exists()]
    if missing_materials:
        raise FileNotFoundError(f"Missing material file(s) for {task_dir}: {', '.join(missing_materials)}")

    if not prompt_path.exists():
        raise FileNotFoundError(f"Missing prompt file for {task_dir}: {prompt_path}")
    if not rubrics_path.exists():
        raise FileNotFoundError(f"Missing rubrics file for {task_dir}: {rubrics_path}")

    rubrics_data = json.loads(rubrics_path.read_text(encoding="utf-8"))
    rubrics = [Rubric.from_dict(item) for item in rubrics_data["rubrics"]]
    human_reference_steps: List[HumanReferenceStep] = []
    if human_reference_path.exists():
        human_reference_data = json.loads(human_reference_path.read_text(encoding="utf-8"))
        seen_step_ids = set()
        for step_index, item in enumerate(human_reference_data.get("steps", []), start=1):
            step = HumanReferenceStep.from_dict(item, step_index=step_index)
            if step.step_id in seen_step_ids:
                raise ValueError(f"Duplicate human reference step_id {step.step_id} in {human_reference_path}")
            seen_step_ids.add(step.step_id)
            human_reference_steps.append(step)
    else:
        human_reference_path = None
    rigors: List[Rigor] = []
    if rigors_path.exists():
        rigors_data = json.loads(rigors_path.read_text(encoding="utf-8"))
        seen_rigor_ids = set()
        for item in rigors_data.get("rigors", []):
            rigor = Rigor.from_dict(item)
            if rigor.id in seen_rigor_ids:
                raise ValueError(f"Duplicate rigor id {rigor.id} in {rigors_path}")
            seen_rigor_ids.add(rigor.id)
            rigors.append(rigor)
    else:
        rigors_path = None

    return TaskSpec(
        id=str(config["id"]),
        name=str(config.get("name", config["id"])),
        source_dir=task_dir,
        prompt_path=prompt_path,
        rubrics_path=rubrics_path,
        human_reference_path=human_reference_path,
        rigors_path=rigors_path,
        executor_skills_path=executor_skills_path,
        files_dir=files_dir,
        material_paths=material_paths,
        timeout_seconds=int(config.get("timeout_seconds", 1800)),
        allow_web_search=bool(config.get("allow_web_search", False)),
        rubrics=rubrics,
        human_reference_steps=human_reference_steps,
        rigors=rigors,
        executor_skills=executor_skills,
    )


def discover_tasks(tasks_dir: Path, selected_ids: Sequence[str] | None = None) -> List[TaskSpec]:
    selected = set(selected_ids or [])
    candidates = sorted(path for path in tasks_dir.iterdir() if (path / "task.json").exists())
    tasks = [load_task(path) for path in candidates]
    if selected:
        tasks = [task for task in tasks if task.id in selected or task.source_dir.name in selected]
        found = {task.id for task in tasks} | {task.source_dir.name for task in tasks}
        missing = sorted(selected - found)
        if missing:
            raise ValueError(f"Selected task(s) not found: {', '.join(missing)}")
    if not tasks:
        raise ValueError(f"No tasks found in {tasks_dir}")
    return tasks


def duplicate_tasks(tasks: Iterable[TaskSpec], repeat: int) -> List[TaskSpec]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1")
    expanded: List[TaskSpec] = []
    for _ in range(repeat):
        expanded.extend(tasks)
    return expanded


def build_task_runs(
    tasks: Iterable[TaskSpec],
    *,
    instruction_mode: str,
    instruction_steps: Sequence[str] | None = None,
    rigor_mode: str = "none",
    rigor_ids: Sequence[str] | None = None,
    executor_skill_ids: Sequence[str] | None = None,
    external_executor_skills: Sequence[ExecutorSkill] | None = None,
) -> List[TaskRunSpec]:
    requested_steps = list(instruction_steps or [])
    requested_rigors = list(rigor_ids or [])
    requested_executor_skills = list(executor_skill_ids or [])
    if instruction_mode == "none" and requested_steps:
        instruction_mode = "select"
    if rigor_mode == "none" and requested_rigors:
        rigor_mode = "select"
    if instruction_mode not in {"none", "traverse", "select", "ablation"}:
        raise ValueError(f"Unknown instruction mode: {instruction_mode}")
    if rigor_mode not in {"none", "select"}:
        raise ValueError(f"Unknown rigor mode: {rigor_mode}")
    if instruction_mode == "select" and not requested_steps:
        raise ValueError("--instruction-mode select requires at least one --instruction-step")
    if rigor_mode == "select" and not requested_rigors:
        raise ValueError("--rigor-mode select requires at least one --rigor")
    duplicate_requested_steps = sorted({step_id for step_id in requested_steps if requested_steps.count(step_id) > 1})
    if duplicate_requested_steps:
        raise ValueError(f"Duplicate --instruction-step value(s): {', '.join(duplicate_requested_steps)}")
    duplicate_requested_rigors = sorted({rigor_id for rigor_id in requested_rigors if requested_rigors.count(rigor_id) > 1})
    if duplicate_requested_rigors:
        raise ValueError(f"Duplicate --rigor value(s): {', '.join(duplicate_requested_rigors)}")
    duplicate_requested_executor_skills = sorted(
        {
            skill_id
            for skill_id in requested_executor_skills
            if requested_executor_skills.count(skill_id) > 1
        }
    )
    if duplicate_requested_executor_skills:
        raise ValueError(
            f"Duplicate --executor-skill value(s): {', '.join(duplicate_requested_executor_skills)}"
        )
    external_executor_skills = list(external_executor_skills or [])
    external_executor_skill_by_id = {skill.id: skill for skill in external_executor_skills}
    if len(external_executor_skill_by_id) != len(external_executor_skills):
        duplicate_external_ids = sorted(
            {
                skill.id
                for skill in external_executor_skills
                if [item.id for item in external_executor_skills].count(skill.id) > 1
            }
        )
        raise ValueError(f"Duplicate external executor skill id(s): {', '.join(duplicate_external_ids)}")

    task_runs: List[TaskRunSpec] = []
    for task in tasks:
        step_by_id = {step.step_id: step for step in task.human_reference_steps}
        requested_set = set(requested_steps)
        rigor_by_id = {rigor.id: rigor for rigor in task.rigors}
        requested_rigor_set = set(requested_rigors)
        executor_skill_by_id = {skill.id: skill for skill in task.executor_skills}
        overlapping_executor_skill_ids = sorted(set(executor_skill_by_id) & set(external_executor_skill_by_id))
        if overlapping_executor_skill_ids:
            raise ValueError(
                f"Executor skill id(s) defined both in task {task.id} and external registry: "
                f"{', '.join(overlapping_executor_skill_ids)}"
            )
        requested_executor_skill_set = set(requested_executor_skills)
        selected_rigors: List[Rigor] = []
        selected_executor_skills: List[ExecutorSkill] = []
        if rigor_mode == "select":
            if not task.rigors:
                raise ValueError(f"Task {task.id} has no rigors.json for rigor mode")
            missing_rigors = [rigor_id for rigor_id in requested_rigors if rigor_id not in rigor_by_id]
            if missing_rigors:
                raise ValueError(f"Task {task.id} missing rigor(s): {', '.join(missing_rigors)}")
            selected_rigors = [rigor for rigor in task.rigors if rigor.id in requested_rigor_set]
        if requested_executor_skills:
            missing_executor_skills = [
                skill_id
                for skill_id in requested_executor_skills
                if skill_id not in executor_skill_by_id and skill_id not in external_executor_skill_by_id
            ]
            if missing_executor_skills:
                raise ValueError(f"Task {task.id} missing executor skill(s): {', '.join(missing_executor_skills)}")
            selected_executor_skills = [
                skill for skill in task.executor_skills if skill.id in requested_executor_skill_set
            ]
            selected_executor_skills.extend(
                skill
                for skill in external_executor_skills
                if skill.id in requested_executor_skill_set
            )
        if instruction_mode == "none":
            task_runs.append(
                TaskRunSpec(
                    task=task,
                    instruction_mode="none",
                    selected_steps=[],
                    rigor_mode=rigor_mode,
                    selected_rigors=selected_rigors,
                    selected_executor_skills=selected_executor_skills,
                )
            )
        elif instruction_mode == "traverse":
            if not task.human_reference_steps:
                raise ValueError(f"Task {task.id} has no human_reference.json for traverse mode")
            for step in task.human_reference_steps:
                task_runs.append(
                    TaskRunSpec(
                        task=task,
                        instruction_mode="traverse",
                        selected_steps=[step],
                        rigor_mode=rigor_mode,
                        selected_rigors=selected_rigors,
                        selected_executor_skills=selected_executor_skills,
                    )
                )
        elif instruction_mode == "select":
            if not task.human_reference_steps:
                raise ValueError(f"Task {task.id} has no human_reference.json for select mode")
            missing = [step_id for step_id in requested_steps if step_id not in step_by_id]
            if missing:
                raise ValueError(f"Task {task.id} missing human reference step(s): {', '.join(missing)}")
            task_runs.append(
                TaskRunSpec(
                    task=task,
                    instruction_mode="select",
                    selected_steps=[step for step in task.human_reference_steps if step.step_id in requested_set],
                    rigor_mode=rigor_mode,
                    selected_rigors=selected_rigors,
                    selected_executor_skills=selected_executor_skills,
                )
            )
        elif instruction_mode == "ablation":
            if not task.human_reference_steps:
                raise ValueError(f"Task {task.id} has no human_reference.json for ablation mode")
            missing = [step_id for step_id in requested_steps if step_id not in step_by_id]
            if missing:
                raise ValueError(f"Task {task.id} missing human reference step(s): {', '.join(missing)}")
            steps = [
                step
                for step in task.human_reference_steps
                if not requested_set or step.step_id in requested_set
            ]
            task_runs.append(
                TaskRunSpec(
                    task=task,
                    instruction_mode="ablation",
                    selected_steps=[],
                    rigor_mode=rigor_mode,
                    selected_rigors=selected_rigors,
                    selected_executor_skills=selected_executor_skills,
                )
            )
            for step in steps:
                task_runs.append(
                    TaskRunSpec(
                        task=task,
                        instruction_mode="ablation",
                        selected_steps=[step],
                        rigor_mode=rigor_mode,
                        selected_rigors=selected_rigors,
                        selected_executor_skills=selected_executor_skills,
                    )
                )
            if len(steps) > 1:
                task_runs.append(
                    TaskRunSpec(
                        task=task,
                        instruction_mode="ablation",
                        selected_steps=steps,
                        rigor_mode=rigor_mode,
                        selected_rigors=selected_rigors,
                        selected_executor_skills=selected_executor_skills,
                        variant_label="all_instructions",
                    )
                )
    return task_runs
