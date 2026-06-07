from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

from starbench.runner.models import ExecutorSkill


DEFAULT_REGISTRY_FILENAME = "registry.json"


def load_registry_data(skill_root: Path) -> Dict[str, Any]:
    registry_path = skill_root / DEFAULT_REGISTRY_FILENAME
    if not registry_path.exists():
        return {"skills": [], "groups": {}}
    return json.loads(registry_path.read_text(encoding="utf-8"))


def load_registry_skills(skill_root: Path) -> List[ExecutorSkill]:
    skill_root = skill_root.resolve()
    data = load_registry_data(skill_root)
    skills: List[ExecutorSkill] = []
    seen_ids = set()
    for item in data.get("skills", []):
        skill = ExecutorSkill.from_base_dir(item, base_dir=skill_root)
        if skill.id in seen_ids:
            raise ValueError(f"Duplicate executor skill id {skill.id} in {skill_root / DEFAULT_REGISTRY_FILENAME}")
        seen_ids.add(skill.id)
        skills.append(skill)
    return skills


def expand_skill_groups(skill_root: Path, group_ids: Sequence[str] | None) -> List[str]:
    if not group_ids:
        return []
    data = load_registry_data(skill_root.resolve())
    groups = data.get("groups", {})
    expanded: List[str] = []
    missing = []
    for group_id in group_ids:
        values = groups.get(group_id)
        if values is None:
            missing.append(group_id)
            continue
        if not isinstance(values, list):
            raise ValueError(f"Executor skill group {group_id} must be a list in {skill_root / DEFAULT_REGISTRY_FILENAME}")
        expanded.extend(str(value) for value in values)
    if missing:
        raise ValueError(f"Missing executor skill group(s): {', '.join(missing)}")
    return expanded


def select_registry_skills(
    skill_root: Path,
    *,
    skill_ids: Sequence[str] | None = None,
    group_ids: Sequence[str] | None = None,
) -> List[ExecutorSkill]:
    requested_ids = list(skill_ids or []) + expand_skill_groups(skill_root, group_ids)
    if not requested_ids:
        return []
    duplicates = sorted({skill_id for skill_id in requested_ids if requested_ids.count(skill_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate executor skill selected from ids/groups: {', '.join(duplicates)}")

    registry_skills = load_registry_skills(skill_root)
    skill_by_id = {skill.id: skill for skill in registry_skills}
    missing = [skill_id for skill_id in requested_ids if skill_id not in skill_by_id]
    if missing:
        raise ValueError(f"Missing executor skill(s) in {skill_root}: {', '.join(missing)}")
    return [skill_by_id[skill_id] for skill_id in requested_ids]


def write_registry_entry(
    skill_root: Path,
    *,
    skill_id: str,
    relative_path: str,
    activation: str,
    description: str,
    leakage_level: str,
    groups: Sequence[str] | None = None,
) -> Path:
    skill_root.mkdir(parents=True, exist_ok=True)
    registry_path = skill_root / DEFAULT_REGISTRY_FILENAME
    data = load_registry_data(skill_root)
    skills = [item for item in data.get("skills", []) if item.get("id") != skill_id]
    skills.append(
        {
            "id": skill_id,
            "path": relative_path,
            "activation": activation,
            "description": description,
            "leakage_level": leakage_level,
        }
    )
    skills.sort(key=lambda item: item["id"])
    registry_groups = {str(key): list(value) for key, value in data.get("groups", {}).items()}
    for group in groups or []:
        values = [value for value in registry_groups.get(group, []) if value != skill_id]
        values.append(skill_id)
        registry_groups[group] = sorted(values)

    registry_path.write_text(
        json.dumps({"skills": skills, "groups": registry_groups}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return registry_path

