"""Measurement-profile persistence and validation."""

from __future__ import annotations

import copy
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...fsio import atomic_write_json
from ..read_models.base import SAFE_ID, _read_json
from .errors import ExperimentError

# The current on-disk profiles.json contract. v1 (this key absent) predates the
# runtime-options work and stores runtime knobs as flat launch-form fields;
# ``migrate_profiles_document`` folds those into per-role/per-contender option
# boxes and stamps this version so the one-time migration never re-runs on an
# already-migrated file. See docs/superpowers/specs/2026-07-25-runtime-options-design.md (D2).
PROFILE_SCHEMA_VERSION = 2

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


# Legacy flat launch-form knob keys this one-time migration retires. The
# opencode trio is gateway *wiring* (backend-derived at launch, never persisted
# in the repo's real file); it is handled defensively so a hand-written or
# older-console file that did store it still migrates cleanly.
_LEGACY_CLAUDE_MAX_TURNS = "claude_max_turns"
_OPENCODE_BOX_KEYS = ("provider", "base_url", "api_key_env")


def _opencode_target(key: str) -> Tuple[str, str]:
    """Map a legacy flat opencode key to ``(role, box_key)`` or ``("", "")``.

    ``role`` is ``executor``/``evaluator`` for the role-prefixed forms and
    ``shared`` for the bare ``opencode_*`` fallback (which the old console fed
    to both roles)."""
    for suffix in _OPENCODE_BOX_KEYS:
        if key == f"executor_opencode_{suffix}":
            return "executor", suffix
        if key == f"evaluator_opencode_{suffix}":
            return "evaluator", suffix
        if key == f"opencode_{suffix}":
            return "shared", suffix
    return "", ""


def _fold_into_options(container: Dict[str, Any], box_key: str, pairs: Dict[str, Any]) -> None:
    """Merge ``pairs`` into ``container[box_key]`` without clobbering values an
    earlier, more specific source already placed there."""
    existing = container.get(box_key)
    merged = dict(existing) if isinstance(existing, dict) else {}
    for name, value in pairs.items():
        merged.setdefault(name, value)
    container[box_key] = merged


def _migrate_contender_opencode(contender: Dict[str, Any]) -> None:
    """Fold any flat opencode wiring stored directly on a roster contender into
    that contender's executor option box. Real profiles never carry this (roster
    validation rejects the keys on save); it covers hand-edited files."""
    folded: Dict[str, Any] = {}
    for key in list(contender.keys()):
        for suffix in _OPENCODE_BOX_KEYS:
            if key in (f"opencode_{suffix}", f"executor_opencode_{suffix}"):
                folded[suffix] = contender.pop(key)
                break
    if folded:
        _fold_into_options(contender, "options", folded)


def _migrate_shared_opencode(shared: Dict[str, Any]) -> None:
    """Fold flat opencode wiring stored in ``shared`` into the role option
    boxes (``executor_options`` / ``evaluator_options``)."""
    role_boxes: Dict[str, Dict[str, Any]] = {"executor": {}, "evaluator": {}}
    legacy: Dict[str, Any] = {}
    for key in list(shared.keys()):
        role, suffix = _opencode_target(key)
        if not role:
            continue
        value = shared.pop(key)
        if role == "shared":
            legacy[suffix] = value
        else:
            role_boxes[role][suffix] = value
    # The bare fallback feeds both roles, but a role-specific field wins.
    for suffix, value in legacy.items():
        role_boxes["executor"].setdefault(suffix, value)
        role_boxes["evaluator"].setdefault(suffix, value)
    for role, box in role_boxes.items():
        if box:
            _fold_into_options(shared, f"{role}_options", box)


def _coerce_optional_int(value: Any) -> Optional[int]:
    """Best-effort int for a legacy cap, or ``None`` when it cannot be honored.

    ``int(value)`` per the spec, but a hand-edited non-numeric ``claude_max_turns``
    must not raise out of ``load_profiles`` (that would 500 the endpoint on read).
    An unparseable or blank cap yields ``None``: the flat field is dropped from
    the v2 contract regardless, and honest absence beats a fabricated number, so
    no options box is written for it."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _migrate_profile(profile: Dict[str, Any]) -> None:
    """Apply the per-profile migration rules in place on a copied profile."""
    shared = profile.get("shared")
    roster = profile.get("roster")
    if isinstance(shared, dict):
        # Rule 1: shared claude_max_turns -> each claude contender's option box.
        if _LEGACY_CLAUDE_MAX_TURNS in shared:
            max_turns = _coerce_optional_int(shared.pop(_LEGACY_CLAUDE_MAX_TURNS))
            if max_turns is not None and isinstance(roster, list):
                for contender in roster:
                    if isinstance(contender, dict) and contender.get("agent") == "claude":
                        # Spec rule 1: {**existing, "max_turns": int(value)} — the
                        # shared cap is authoritative, so it overwrites any
                        # pre-existing max_turns while keeping other options.
                        options = dict(contender.get("options") or {})
                        options["max_turns"] = max_turns
                        contender["options"] = options
        # Rule 2 (shared side): flat opencode wiring -> role option boxes.
        _migrate_shared_opencode(shared)
    # Rule 2 (per-contender side): flat opencode wiring on a roster entry.
    if isinstance(roster, list):
        for contender in roster:
            if isinstance(contender, dict):
                _migrate_contender_opencode(contender)


def migrate_profiles_document(document: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Fold a v1 profiles.json document into the v2 option-box shape.

    Pure: the input is never mutated — a migrated deep copy is returned. The
    four normative rules (spec D2):

    1. ``shared.claude_max_turns`` -> each ``agent == "claude"`` contender's
       ``options.max_turns`` (coerced to int); the flat field is deleted.
    2. flat ``opencode_*`` / ``executor_opencode_*`` / ``evaluator_opencode_*``
       wiring -> the matching ``executor_options`` / ``evaluator_options`` box
       key (``provider`` / ``base_url`` / ``api_key_env``); flat fields deleted.
    3. stamp ``schema_version = 2`` at the top level.
    4. a document already at ``schema_version`` 2 is returned unchanged
       (``changed=False``) so the migration never runs twice.

    Returns ``(document, changed)``. For any v1 document ``changed`` is True —
    even one with no legacy fields, because the version stamp itself is a
    change; that is what makes the loader back it up and rewrite it once.
    """
    if not isinstance(document, dict):
        return document, False
    if document.get("schema_version") == PROFILE_SCHEMA_VERSION:
        return document, False

    migrated = copy.deepcopy(document)
    profiles = migrated.get("profiles")
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, dict):
                _migrate_profile(profile)
    migrated["schema_version"] = PROFILE_SCHEMA_VERSION
    return migrated, True


def _atomic_copy(source: Path, destination: Path) -> None:
    """Copy raw bytes through a temp file + ``os.replace``, mirroring fsio's
    torn-write discipline, so a crash never leaves a partial backup that the
    write-once guard would later mistake for a complete one."""
    data = source.read_bytes()
    descriptor, temporary = tempfile.mkstemp(
        dir=str(destination.parent), prefix=f".{destination.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


# Serializes the whole read-guard + backup + rewrite critical section. The
# console runs on ThreadingHTTPServer, so two first-load callers (e.g. a
# GET /profiles racing a launch that hits load_profiles via planning) can enter
# the migration at once. Without this, both could pass the `backup.exists()`
# guard, and the second `_atomic_copy` would read the already-rewritten v2 file
# and clobber the pristine v1 backup — destroying the one recovery snapshot.
# Under the lock the backup is authored exactly once from pristine bytes, and
# the (idempotent, atomic) rewrites are serialized rather than torn.
_MIGRATION_LOCK = threading.Lock()


def _persist_one_time_migration(path: Path, document: Dict[str, Any]) -> None:
    """Back up the pristine v1 file once, then atomically install the migrated
    document. The backup is written only when absent so a re-entered migration
    (a crash before the atomic rewrite completed) never clobbers the original
    v1 snapshot; the rewrite reuses the module's atomic writer, so a torn file
    is impossible and a failed attempt simply leaves the v1 file to retry. The
    whole section is serialized so concurrent first-load callers cannot race the
    write-once backup (see ``_MIGRATION_LOCK``)."""
    backup = path.with_name(f"{path.name}.v1.bak")
    with _MIGRATION_LOCK:
        if not backup.exists():
            _atomic_copy(path, backup)
        atomic_write_json(path, document, indent=2, sort_keys=True)


def load_profiles(runs_dir: Path) -> Dict[str, Any]:
    path = profiles_path(runs_dir)
    payload = _read_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        return {
            "default_profile_id": BUILTIN_PROFILE["id"],
            "profiles": list(BUILTIN_PROFILES),
            "persisted": False,
        }
    # One-time v1->v2 migration: fold legacy flat knobs into option boxes and
    # persist the result (pristine backup + atomic rewrite) the first time an
    # un-migrated file is read. Runtime-only annotations below are added after
    # the rewrite so they never reach disk.
    migrated, changed = migrate_profiles_document(payload)
    if changed:
        _persist_one_time_migration(path, migrated)
        payload = migrated
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

    # Every save is written by current (v2-aware) code, so stamp the contract
    # version. This keeps the one-time migration one-time: without it, each save
    # would drop the marker and the next load would re-run the migration (and
    # its backup+rewrite) against an already-migrated file. Masking is not a
    # risk because load_profiles migrates on read, so any legacy flat field is
    # already folded into option boxes before a save ever observes the profile.
    stored = {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "default_profile_id": default_id,
        "profiles": revised,
    }
    runs_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(profiles_path(runs_dir), stored, indent=2, sort_keys=True)
    stored["persisted"] = True
    return stored
