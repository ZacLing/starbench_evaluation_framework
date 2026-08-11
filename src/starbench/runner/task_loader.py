from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, List, Sequence

from starbench.contracts import ContractValidationError, validate_payload
from starbench.domain import assert_no_symlinks, parse_safe_id, resolve_within

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
        return [
            resolve_within(task_dir, material, kind="task material path")
            for material in configured_materials
        ]

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
    task_dir = task_dir.expanduser()
    if task_dir.is_symlink():
        raise ValueError(f"Task package root cannot be a symbolic link: {task_dir}")
    task_dir = task_dir.resolve()
    assert_no_symlinks(task_dir, kind="task package")
    config_path = resolve_within(task_dir, "task.json", kind="task config path")
    if not config_path.exists():
        raise FileNotFoundError(f"Missing task.json in {task_dir}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    _validate_contract("task.schema.json", config, config_path)
    task_id = parse_safe_id(config["id"], kind="task id")
    prompt_path = resolve_within(
        task_dir, config.get("prompt", "prompt.md"), kind="task prompt path"
    )
    rubrics_path = resolve_within(
        task_dir, config.get("rubrics", "rubrics.json"), kind="task rubrics path"
    )
    human_reference_path = resolve_within(
        task_dir,
        config.get("human_reference", "human_reference.json"),
        kind="task human reference path",
    )
    rigors_path = resolve_within(
        task_dir, config.get("rigors", "rigors.json"), kind="task rigors path"
    )
    executor_skills_value = config.get("executor_skills", "executor_skills.json")
    executor_skills_path = (
        resolve_within(
            task_dir, executor_skills_value, kind="task executor skills manifest path"
        )
        if executor_skills_value
        else None
    )
    subtle_difference_value = config.get("subtle_difference")
    subtle_difference_path = (
        resolve_within(
            task_dir, subtle_difference_value, kind="task subtle difference path"
        )
        if subtle_difference_value
        else None
    )
    files_dir_value = config.get("files_dir", "files")
    files_dir = (
        resolve_within(task_dir, files_dir_value, kind="task files directory")
        if files_dir_value
        else None
    )
    if files_dir is not None and not files_dir.exists():
        files_dir = None
    configured_materials = config.get("materials")
    if configured_materials is None:
        configured_materials = config.get("input_materials")
    executor_skills: List[ExecutorSkill] = []
    executor_skill_exclusions: List[Path] = []
    if executor_skills_path is not None and executor_skills_path.exists():
        executor_skills_data = json.loads(executor_skills_path.read_text(encoding="utf-8"))
        _validate_contract("executor_skills.schema.json", executor_skills_data, executor_skills_path)
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
    _validate_contract("rubrics.schema.json", rubrics_data, rubrics_path)
    rubrics: List[Rubric] = []
    seen_rubric_ids = set()
    for item in rubrics_data["rubrics"]:
        rubric = Rubric.from_dict(item)
        if rubric.id in seen_rubric_ids:
            raise ValueError(f"Duplicate rubric id {rubric.id} in {rubrics_path}")
        seen_rubric_ids.add(rubric.id)
        rubrics.append(rubric)
    human_reference_steps: List[HumanReferenceStep] = []
    if human_reference_path.exists():
        human_reference_data = json.loads(human_reference_path.read_text(encoding="utf-8"))
        _validate_contract("human_reference.schema.json", human_reference_data, human_reference_path)
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
        _validate_contract("rigors.schema.json", rigors_data, rigors_path)
        seen_rigor_ids = set()
        for item in rigors_data.get("rigors", []):
            rigor = Rigor.from_dict(item)
            if rigor.id in seen_rigor_ids:
                raise ValueError(f"Duplicate rigor id {rigor.id} in {rigors_path}")
            if rigor.rubric_id not in seen_rubric_ids:
                raise ValueError(
                    f"Rigor {rigor.id} references unknown rubric id "
                    f"{rigor.rubric_id} in {rigors_path}"
                )
            seen_rigor_ids.add(rigor.id)
            rigors.append(rigor)
    else:
        rigors_path = None

    return TaskSpec(
        id=task_id,
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


def _validate_contract(schema_name: str, data: object, source_path: Path) -> None:
    try:
        validate_payload(schema_name, data, path=source_path.name)
    except ContractValidationError as error:
        raise ValueError(f"{source_path} does not match StarBench artifact contract: {error}") from error


def discover_tasks(tasks_dir: Path, selected_ids: Sequence[str] | None = None) -> List[TaskSpec]:
    selected = set(selected_ids or [])
    candidates = sorted(path for path in tasks_dir.iterdir() if (path / "task.json").exists())
    if selected:
        selected_candidates: List[Path] = []
        for candidate in candidates:
            if candidate.name in selected:
                selected_candidates.append(candidate)
                continue
            try:
                candidate_config = json.loads(
                    (candidate / "task.json").read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if isinstance(candidate_config, dict) and candidate_config.get("id") in selected:
                selected_candidates.append(candidate)
        tasks = [load_task(path) for path in selected_candidates]
        found = {task.id for task in tasks} | {task.source_dir.name for task in tasks}
        missing = sorted(selected - found)
        if missing:
            raise ValueError(f"Selected task(s) not found: {', '.join(missing)}")
    else:
        tasks = [load_task(path) for path in candidates]
    if not tasks:
        raise ValueError(f"No tasks found in {tasks_dir}")
    task_ids = [task.id for task in tasks]
    duplicate_task_ids = sorted(
        {task_id for task_id in task_ids if task_ids.count(task_id) > 1}
    )
    if duplicate_task_ids:
        raise ValueError(f"Duplicate task id(s): {', '.join(duplicate_task_ids)}")
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
    required_executor_skill_ids: Sequence[str] | None = None,
    external_executor_skills: Sequence[ExecutorSkill] | None = None,
) -> List[TaskRunSpec]:
    requested_steps = list(instruction_steps or [])
    requested_rigors = list(rigor_ids or [])
    requested_executor_skills = list(executor_skill_ids or [])
    requested_required_executor_skills = list(required_executor_skill_ids or [])
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
    duplicate_required_executor_skills = sorted(
        {
            skill_id
            for skill_id in requested_required_executor_skills
            if requested_required_executor_skills.count(skill_id) > 1
        }
    )
    if duplicate_required_executor_skills:
        raise ValueError(
            "Duplicate --required-executor-skill value(s): "
            + ", ".join(duplicate_required_executor_skills)
        )
    requested_installed_executor_skills = list(requested_executor_skills)
    requested_installed_executor_skills.extend(
        skill_id
        for skill_id in requested_required_executor_skills
        if skill_id not in requested_installed_executor_skills
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
        requested_executor_skill_set = set(requested_installed_executor_skills)
        required_executor_skill_set = set(requested_required_executor_skills)
        selected_rigors: List[Rigor] = []
        selected_executor_skills: List[ExecutorSkill] = []
        if rigor_mode == "select":
            if not task.rigors:
                raise ValueError(f"Task {task.id} has no rigors.json for rigor mode")
            missing_rigors = [rigor_id for rigor_id in requested_rigors if rigor_id not in rigor_by_id]
            if missing_rigors:
                raise ValueError(f"Task {task.id} missing rigor(s): {', '.join(missing_rigors)}")
            selected_rigors = [rigor for rigor in task.rigors if rigor.id in requested_rigor_set]
        if requested_installed_executor_skills:
            missing_executor_skills = [
                skill_id
                for skill_id in requested_installed_executor_skills
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
        selected_required_executor_skill_ids = [
            skill.id for skill in selected_executor_skills if skill.id in required_executor_skill_set
        ]
        if instruction_mode == "none":
            task_runs.append(
                TaskRunSpec(
                    task=task,
                    instruction_mode="none",
                    selected_steps=[],
                    rigor_mode=rigor_mode,
                    selected_rigors=selected_rigors,
                    selected_executor_skills=selected_executor_skills,
                    required_executor_skill_ids=selected_required_executor_skill_ids,
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
                        required_executor_skill_ids=selected_required_executor_skill_ids,
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
                    required_executor_skill_ids=selected_required_executor_skill_ids,
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
                    required_executor_skill_ids=selected_required_executor_skill_ids,
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
                        required_executor_skill_ids=selected_required_executor_skill_ids,
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
                        required_executor_skill_ids=selected_required_executor_skill_ids,
                        variant_label="all_instructions",
                    )
                )
    return task_runs
