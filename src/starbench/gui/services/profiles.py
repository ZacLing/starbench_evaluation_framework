"""Measurement-profile persistence and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..fsio import atomic_write_json
from ..read_models.base import SAFE_ID, _read_json
from .errors import ExperimentError

PER_CONTENDER_FIELD_CHOICES = ["model", "credentials", "gateway", "thinking_effort"]
ROSTER_ENTRY_FIELDS = {"agent", "model", "label", "provider_id", "thinking_effort"}
TASK_SET_FIELDS = {"tasks_dir", "task_ids"}
BUILTIN_PROFILE = {
    "id": "standard",
    "name": "Standard evaluation",
    "shared": {
        "evaluator_agent": "codex", "evaluator_model": "gpt-5.5",
        "evaluator_auth_mode": "env", "judge_mode": "single",
        "evaluator_timeout_seconds": 900, "executor_backend": "local",
        "executor_auth_mode": "env", "seed": 123, "batch_size": 1, "repeat": 1,
    },
    "per_contender_fields": ["model", "credentials", "gateway"],
}
BUILTIN_PROFILE_HSW_FRONTIER = {
    "id": "hsw-frontier", "name": "HSW frontier sweep",
    "shared": {**BUILTIN_PROFILE["shared"], "repeat": 5},
    "per_contender_fields": ["model", "credentials", "gateway"], "roster": [],
}
BUILTIN_PROFILES = [BUILTIN_PROFILE, BUILTIN_PROFILE_HSW_FRONTIER]

def profiles_path(runs_dir: Path) -> Path:
    return runs_dir / "profiles.json"


def load_profiles(runs_dir: Path) -> Dict[str, Any]:
    payload = _read_json(profiles_path(runs_dir))
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        return {
            "default_profile_id": BUILTIN_PROFILE["id"],
            "profiles": list(BUILTIN_PROFILES),
            "persisted": False,
        }
    payload.setdefault("default_profile_id", None)
    payload["persisted"] = True
    return payload


def _validate_profile_roster(profile_id: str, roster: Any) -> None:
    """Roster entries follow the wizard's reference shape; unknown keys are
    rejected so credential-shaped fields can never enter profiles.json."""
    if not isinstance(roster, list):
        raise ExperimentError(f"Profile {profile_id} roster must be a list of contender specs.")
    for index, entry in enumerate(roster):
        if not isinstance(entry, dict):
            raise ExperimentError(f"Profile {profile_id} roster[{index}] must be an object.")
        unknown = set(entry) - ROSTER_ENTRY_FIELDS
        if unknown:
            raise ExperimentError(
                f"Profile {profile_id} roster[{index}] has unsupported field(s) "
                f"{sorted(unknown)}; allowed: {sorted(ROSTER_ENTRY_FIELDS)}. Credentials "
                "never belong in a profile — reference a provider by id instead."
            )
        if not isinstance(entry.get("agent"), str) or not entry.get("agent"):
            raise ExperimentError(f"Profile {profile_id} roster[{index}] needs an `agent` string.")
        for field in ("model", "label", "provider_id", "thinking_effort"):
            if field in entry and not isinstance(entry[field], str):
                raise ExperimentError(
                    f"Profile {profile_id} roster[{index}].{field} must be a string."
                )


def _validate_profile_task_set(profile_id: str, task_set: Any) -> None:
    if not isinstance(task_set, dict):
        raise ExperimentError(f"Profile {profile_id} task_set must be an object.")
    unknown = set(task_set) - TASK_SET_FIELDS
    if unknown:
        raise ExperimentError(
            f"Profile {profile_id} task_set has unsupported field(s) {sorted(unknown)}; "
            f"allowed: {sorted(TASK_SET_FIELDS)}."
        )
    if not isinstance(task_set.get("tasks_dir"), str) or not task_set.get("tasks_dir"):
        raise ExperimentError(f"Profile {profile_id} task_set needs a non-empty `tasks_dir`.")
    task_ids = task_set.get("task_ids")
    if not isinstance(task_ids, list) or not all(isinstance(item, str) for item in task_ids):
        raise ExperimentError(
            f"Profile {profile_id} task_set.task_ids must be a list of task ids "
            "(empty means every task in the directory)."
        )


def _profile_content(profile: Dict[str, Any]) -> Dict[str, Any]:
    """A profile minus its revision counter — the content `rev` versions."""
    return {key: value for key, value in profile.items() if key != "rev"}


def save_profiles(runs_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ExperimentError("`profiles` must be a non-empty list.")
    seen = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ExperimentError("Each profile must be an object.")
        profile_id = str(profile.get("id") or "")
        if not SAFE_ID.match(profile_id):
            raise ExperimentError(f"Profile id is invalid: {profile_id!r}")
        if profile_id in seen:
            raise ExperimentError(f"Duplicate profile id: {profile_id}")
        seen.add(profile_id)
        if not isinstance(profile.get("shared"), dict):
            raise ExperimentError(f"Profile {profile_id} needs a `shared` object.")
        fields = profile.get("per_contender_fields")
        if not isinstance(fields, list) or not all(
            field in PER_CONTENDER_FIELD_CHOICES for field in fields
        ):
            raise ExperimentError(
                f"Profile {profile_id} per_contender_fields must be a subset of "
                f"{PER_CONTENDER_FIELD_CHOICES}."
            )
        if "roster" in profile:
            _validate_profile_roster(profile_id, profile.get("roster"))
        if "task_set" in profile:
            _validate_profile_task_set(profile_id, profile.get("task_set"))
    default_id = payload.get("default_profile_id")
    if default_id is not None and default_id not in seen:
        raise ExperimentError(f"default_profile_id {default_id!r} matches no profile.")

    # Revision counter: server-assigned, never trusted from the client. A new
    # profile starts at 1; content changes bump the stored rev; an identical
    # save keeps it. Snapshots cite this rev to pin "the contract as of launch".
    previous = _read_json(profiles_path(runs_dir))
    previous_by_id: Dict[str, Dict[str, Any]] = {}
    if isinstance(previous, dict) and isinstance(previous.get("profiles"), list):
        previous_by_id = {
            str(entry.get("id")): entry
            for entry in previous["profiles"]
            if isinstance(entry, dict)
        }
    revised: List[Dict[str, Any]] = []
    for profile in profiles:
        profile_id = str(profile.get("id") or "")
        stored_profile = dict(profile)
        old = previous_by_id.get(profile_id)
        if old is None:
            stored_profile["rev"] = 1
        elif _profile_content(old) == _profile_content(stored_profile):
            stored_profile["rev"] = int(old.get("rev") or 1)
        else:
            stored_profile["rev"] = int(old.get("rev") or 1) + 1
        revised.append(stored_profile)

    stored = {"default_profile_id": default_id, "profiles": revised}
    runs_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(profiles_path(runs_dir), stored, indent=2, sort_keys=True)
    stored["persisted"] = True
    return stored
