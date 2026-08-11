"""Executor skills: the third resource side of the console.

A skill is a real directory of guidance the console can install into an
executor runtime's isolated workspace for a run. The skill library lives on
disk under a root directory (default ``executor_skills/``) whose ``registry``
lists the skills and the groups that bundle them — exactly the files
``starbench-run`` consumes via ``--executor-skill`` / ``--executor-skill-group``
/ ``--executor-skill-root``. The console reads the same files, so it and the CLI
cannot drift.

This module is a thin, read-only wrapper over ``starbench.skills.registry``:
``list_skills`` renders the library for the resource page (never raising — a
broken library comes back as an ``error`` field), and ``validate_selection``
expands groups and checks a wizard selection at plan time, reusing the same
expansion the runner uses so a selection the console accepts is one the CLI
will run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from ..skills import registry as skills_registry
from . import contracts

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[3] / "executor_skills"


class SkillError(ValueError):
    pass


@dataclass(frozen=True)
class SkillSelection:
    installed_ids: List[str]
    advisory_ids: List[str]
    required_ids: List[str]


def _directory_stats(path: Path) -> tuple[int, int]:
    """Count files and total bytes under a skill directory."""
    file_count = 0
    total_bytes = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                file_count += 1
                try:
                    total_bytes += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return file_count, total_bytes


def _membership(groups: Dict[str, Any]) -> Dict[str, List[str]]:
    """Reverse the group -> [skill] map into skill -> [group]."""
    membership: Dict[str, List[str]] = {}
    for group_id, members in groups.items():
        if not isinstance(members, list):
            continue
        for member in members:
            membership.setdefault(str(member), []).append(str(group_id))
    return membership


def list_skills(skill_root: Path) -> "contracts.SkillsPayload":
    """Render the skill library for the resource page.

    A missing library is a normal empty state (``skills`` empty, no ``error``).
    A library that cannot be read (malformed contents, a duplicate id, a skill
    directory that has gone missing) comes back with a human-readable ``error``
    instead of raising, so the route can render an error card rather than 500.
    """
    skill_root = skill_root.resolve()
    try:
        data = skills_registry.load_registry_data(skill_root)
        skill_models = skills_registry.load_registry_skills(skill_root)
    except (ValueError, OSError, TypeError, AttributeError) as error:
        return {
            "root": str(skill_root),
            "skills": [],
            "groups": {},
            "error": f"The skill library could not be read: {error}",
        }

    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, dict):
        groups = {}
    membership = _membership(groups)

    skills: List[Dict[str, Any]] = []
    for skill in skill_models:
        file_count, size_bytes = _directory_stats(skill.source_path)
        skills.append(
            {
                "id": skill.id,
                "description": skill.description,
                "source_path": str(skill.source_path),
                "file_count": file_count,
                "size_bytes": size_bytes,
                "sha256": skill.sha256,
                "leakage_level": skill.leakage_level,
                "groups": sorted(membership.get(skill.id, [])),
            }
        )

    return {
        "root": str(skill_root),
        "skills": skills,
        "groups": {
            str(group_id): [str(member) for member in members]
            for group_id, members in groups.items()
            if isinstance(members, list)
        },
    }


def _clean_ids(values: Sequence[Any] | None, label: str) -> List[str]:
    if values is None:
        return []
    if not isinstance(values, (list, tuple)):
        raise SkillError(f"{label} must be a list.")
    cleaned: List[str] = []
    for value in values:
        if not isinstance(value, str):
            raise SkillError(f"{label} must be a list of names.")
        text = value.strip()
        if text:
            cleaned.append(text)
    return cleaned


def validate_selection(
    skill_root: Path,
    skill_ids: Sequence[Any] | None,
    group_ids: Sequence[Any] | None,
) -> List[str]:
    """Expand groups, validate a wizard selection, and return the final id list.

    Reuses the same expansion the runner performs, so a selection this accepts
    is one ``starbench-run`` will run. Raises ``SkillError`` with a plain-English
    message for an unknown skill, an unknown group, or a skill selected more than
    once (individually and via a group, or via two overlapping groups) — the
    runner rejects that same overlap, so surfacing it here keeps the plan honest.
    """
    return resolve_selection(skill_root, skill_ids, group_ids, []).installed_ids


def resolve_selection(
    skill_root: Path,
    skill_ids: Sequence[Any] | None,
    group_ids: Sequence[Any] | None,
    required_skill_ids: Sequence[Any] | None,
) -> SkillSelection:
    """Validate and normalize Available/Required skill selections.

    Required ids imply installation and upgrade an ordinary or group-provided
    skill rather than creating a duplicate installation.
    """
    requested_skill_ids = _clean_ids(skill_ids, "Executor skills")
    requested_group_ids = _clean_ids(group_ids, "Executor skill groups")
    requested_required_ids = _clean_ids(
        required_skill_ids, "Required executor skills"
    )
    if not requested_skill_ids and not requested_group_ids and not requested_required_ids:
        return SkillSelection(installed_ids=[], advisory_ids=[], required_ids=[])

    skill_root = skill_root.resolve()
    try:
        data = skills_registry.load_registry_data(skill_root)
        skill_models = skills_registry.load_registry_skills(skill_root)
    except (ValueError, OSError, TypeError, AttributeError) as error:
        raise SkillError(f"The skill library could not be read: {error}")

    available_ids = {skill.id for skill in skill_models}
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, dict):
        groups = {}

    unknown_groups = [group_id for group_id in requested_group_ids if group_id not in groups]
    if unknown_groups:
        raise SkillError(f"Unknown skill group(s): {', '.join(unknown_groups)}")

    expanded: List[str] = list(requested_skill_ids)
    for group_id in requested_group_ids:
        members = groups.get(group_id) or []
        if not isinstance(members, list):
            raise SkillError(f"Skill group {group_id} is not a list of skills.")
        expanded.extend(str(member) for member in members)

    unknown = [
        skill_id for skill_id in dict.fromkeys(expanded) if skill_id not in available_ids
    ]
    if unknown:
        raise SkillError(f"Unknown skill(s): {', '.join(unknown)}")

    duplicates = sorted({skill_id for skill_id in expanded if expanded.count(skill_id) > 1})
    if duplicates:
        raise SkillError(
            "These skills are selected more than once (a skill and a group that "
            f"contains it, or two overlapping groups): {', '.join(duplicates)}"
        )
    duplicate_required = sorted(
        {
            skill_id
            for skill_id in requested_required_ids
            if requested_required_ids.count(skill_id) > 1
        }
    )
    if duplicate_required:
        raise SkillError(
            "These skills are required more than once: "
            + ", ".join(duplicate_required)
        )
    unknown_required = [
        skill_id
        for skill_id in dict.fromkeys(requested_required_ids)
        if skill_id not in available_ids
    ]
    if unknown_required:
        raise SkillError(f"Unknown required skill(s): {', '.join(unknown_required)}")

    installed = list(expanded)
    installed.extend(
        skill_id for skill_id in requested_required_ids if skill_id not in installed
    )
    required_set = set(requested_required_ids)
    return SkillSelection(
        installed_ids=installed,
        advisory_ids=[skill_id for skill_id in installed if skill_id not in required_set],
        required_ids=[skill_id for skill_id in installed if skill_id in required_set],
    )


__all__ = [
    "DEFAULT_SKILLS_DIR",
    "SkillError",
    "SkillSelection",
    "list_skills",
    "resolve_selection",
    "validate_selection",
]
