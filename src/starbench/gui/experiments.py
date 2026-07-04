"""Experiments: one configuration fanned out across multiple agent runtimes.

An experiment is the console's unit of comparison: a fixed task set, one shared
judge and shared parameters (the controls), and M contenders (runtime + model,
the variable). The console orchestrates one `starbench-run` per contender and
records the grouping in `<runs-dir>/experiments/<id>.json`; the runs themselves
stay plain runs that the CLI fully owns.

Profiles live in `<runs-dir>/profiles.json`: named bundles of the shared
configuration plus a declaration of which fields each contender fills in
individually.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .data import SAFE_ID, _read_json, run_overview
from .launcher import LaunchError, build_run_argv

# Only the Codex runtime can execute inside Docker (run_benchmark.py rejects
# every other agent with a non-local backend). Keep this in one place.
DOCKER_CAPABLE_AGENTS = {"codex"}

PER_CONTENDER_FIELD_CHOICES = ["model", "credentials", "gateway", "thinking_effort"]

BUILTIN_PROFILE = {
    "id": "standard",
    "name": "Standard evaluation",
    "shared": {
        "evaluator_agent": "codex",
        "evaluator_model": "gpt-5.5",
        "evaluator_auth_mode": "env",
        "judge_mode": "single",
        "evaluator_timeout_seconds": 900,
        "executor_backend": "local",
        "docker_image": "starbench-codex:latest",
        "executor_auth_mode": "env",
        "seed": 123,
        "batch_size": 1,
        "repeat": 1,
    },
    "per_contender_fields": ["model", "credentials", "gateway"],
}


class ExperimentError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------

def profiles_path(runs_dir: Path) -> Path:
    return runs_dir / "profiles.json"


def load_profiles(runs_dir: Path) -> Dict[str, Any]:
    payload = _read_json(profiles_path(runs_dir))
    if not isinstance(payload, dict) or not isinstance(payload.get("profiles"), list):
        return {
            "default_profile_id": BUILTIN_PROFILE["id"],
            "profiles": [BUILTIN_PROFILE],
            "persisted": False,
        }
    payload.setdefault("default_profile_id", None)
    payload["persisted"] = True
    return payload


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
    default_id = payload.get("default_profile_id")
    if default_id is not None and default_id not in seen:
        raise ExperimentError(f"default_profile_id {default_id!r} matches no profile.")

    stored = {"default_profile_id": default_id, "profiles": profiles}
    runs_dir.mkdir(parents=True, exist_ok=True)
    profiles_path(runs_dir).write_text(
        json.dumps(stored, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    stored["persisted"] = True
    return stored


# ---------------------------------------------------------------------------
# Experiment orchestration
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "contender"


def experiments_dir(runs_dir: Path) -> Path:
    return runs_dir / "experiments"


def _experiment_path(runs_dir: Path, experiment_id: str) -> Path:
    if not SAFE_ID.match(experiment_id):
        raise ExperimentError(f"Invalid experiment id: {experiment_id!r}")
    return experiments_dir(runs_dir) / f"{experiment_id}.json"


def plan_experiment(payload: Dict[str, Any], *, runs_dir: Path) -> Dict[str, Any]:
    """Validate an experiment request and build one launch plan per contender."""
    name = str(payload.get("name") or "").strip()
    if not SAFE_ID.match(name):
        raise ExperimentError(
            "Experiment name is required (letters, digits, dot, dash, underscore)."
        )
    if _experiment_path(runs_dir, name).exists():
        raise ExperimentError(f"An experiment named {name} already exists.")

    shared = payload.get("shared")
    if not isinstance(shared, dict):
        raise ExperimentError("`shared` configuration object is required.")
    contenders = payload.get("contenders")
    if not isinstance(contenders, list) or not contenders:
        raise ExperimentError("At least one contender runtime is required.")
    if len(contenders) > 12:
        raise ExperimentError("At most 12 contenders per experiment.")

    backend = str(shared.get("executor_backend") or "local")
    evaluator_agent = str(shared.get("evaluator_agent") or "codex")
    evaluator_gateway = (
        shared.get("evaluator_gateway")
        if isinstance(shared.get("evaluator_gateway"), dict)
        else None
    )
    plans: List[Dict[str, Any]] = []
    used_run_ids = set()
    for index, contender in enumerate(contenders):
        if not isinstance(contender, dict):
            raise ExperimentError("Each contender must be an object.")
        agent = str(contender.get("agent") or "")
        label = str(contender.get("label") or "") or f"{agent}-{contender.get('model') or index + 1}"
        slug = _slug(label)
        run_id = f"{name}__{slug}"
        suffix = 2
        while run_id in used_run_ids:
            run_id = f"{name}__{slug}-{suffix}"
            suffix += 1
        used_run_ids.add(run_id)

        effective_backend = backend if agent in DOCKER_CAPABLE_AGENTS else "local"

        # The codex binary config is process-global: rerouting a Codex
        # contender through a gateway would silently reroute a Codex judge in
        # the same run.
        if contender.get("codex_bin") and evaluator_agent == "codex":
            raise ExperimentError(
                f"Contender {label}: routing Codex through a gateway also reroutes the "
                "Codex judge (the CLI shares one codex configuration per run). Pick a "
                "non-Codex judge or use the official OpenAI provider for this contender."
            )

        # OpenCode gateway flags are process-global in the CLI: a contender and
        # an OpenCode judge must agree on them, and an OpenCode judge supplies
        # them when the contender does not use OpenCode at all.
        gateway = {
            "opencode_provider": contender.get("opencode_provider"),
            "opencode_base_url": contender.get("opencode_base_url"),
            "opencode_api_key_env": contender.get("opencode_api_key_env"),
        }
        if evaluator_agent == "opencode" and evaluator_gateway:
            if agent == "opencode":
                for key in gateway:
                    contender_value = str(gateway.get(key) or "")
                    judge_value = str(evaluator_gateway.get(key) or "")
                    if contender_value and judge_value and contender_value != judge_value:
                        raise ExperimentError(
                            f"Contender {label}: its OpenCode gateway conflicts with the "
                            "judge's gateway; the CLI supports only one OpenCode gateway "
                            "per run."
                        )
            else:
                gateway = dict(evaluator_gateway)

        launch_payload = {
            "run_id": run_id,
            "tasks_dir": payload.get("tasks_dir"),
            "tasks": payload.get("tasks") or [],
            "executor_agent": agent,
            "executor_model": str(contender.get("model") or "").strip(),
            "executor_backend": effective_backend,
            "docker_image": str(shared.get("docker_image") or "").strip(),
            "auth_mode": str(contender.get("auth_mode") or "env"),
            "claude_thinking_effort": str(contender.get("thinking_effort") or "none"),
            "evaluator_agent": str(shared.get("evaluator_agent") or "codex"),
            "evaluator_model": str(shared.get("evaluator_model") or "").strip(),
            "evaluator_auth_mode": str(shared.get("evaluator_auth_mode") or "") or None,
            "judge_mode": str(shared.get("judge_mode") or "single"),
            "evaluator_timeout_seconds": shared.get("evaluator_timeout_seconds"),
            "seed": shared.get("seed"),
            "batch_size": shared.get("batch_size"),
            "repeat": shared.get("repeat"),
            "codex_bin": contender.get("codex_bin"),
            "opencode_provider": gateway.get("opencode_provider"),
            "opencode_base_url": gateway.get("opencode_base_url"),
            "opencode_api_key_env": gateway.get("opencode_api_key_env"),
            "extra_args": str(shared.get("extra_args") or ""),
        }
        try:
            argv = build_run_argv(launch_payload, runs_dir=runs_dir)
        except LaunchError as error:
            raise ExperimentError(f"Contender {label}: {error}")
        env_spec = contender.get("env") if isinstance(contender.get("env"), dict) else {}
        plans.append(
            {
                "label": label,
                "agent": agent,
                "model": launch_payload["executor_model"],
                "run_id": run_id,
                "backend": effective_backend,
                "backend_downgraded": backend == "docker" and effective_backend == "local",
                "env_spec": env_spec,
                "env_keys": sorted(env_spec.keys()),
                "argv": argv,
            }
        )
    return {"name": name, "shared": shared, "plans": plans}


def record_experiment(
    runs_dir: Path,
    *,
    name: str,
    payload: Dict[str, Any],
    plans: List[Dict[str, Any]],
) -> Dict[str, Any]:
    record = {
        "id": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tasks_dir": payload.get("tasks_dir"),
        "tasks": payload.get("tasks") or [],
        "shared": payload.get("shared"),
        "contenders": [
            {
                "label": plan["label"],
                "agent": plan["agent"],
                "model": plan["model"],
                "run_id": plan["run_id"],
                "backend": plan["backend"],
                "backend_downgraded": plan["backend_downgraded"],
            }
            for plan in plans
        ],
        "run_ids": [plan["run_id"] for plan in plans],
    }
    directory = experiments_dir(runs_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _experiment_path(runs_dir, name).write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def list_experiments(runs_dir: Path, active_run_ids: Optional[set] = None) -> List[Dict[str, Any]]:
    directory = experiments_dir(runs_dir)
    if not directory.is_dir():
        return []
    records: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        record = _read_json(path)
        if not isinstance(record, dict) or not isinstance(record.get("run_ids"), list):
            continue
        summary = dict(record)
        summary["runs"] = []
        for run_id in record["run_ids"]:
            run_root = runs_dir / str(run_id)
            if run_root.is_dir():
                summary["runs"].append(run_overview(run_root, active_run_ids))
            else:
                summary["runs"].append({"run_id": run_id, "status": "missing"})
        records.append(summary)
    return records


def experiment_detail(
    runs_dir: Path, experiment_id: str, active_run_ids: Optional[set] = None
) -> Dict[str, Any]:
    path = _experiment_path(runs_dir, experiment_id)
    record = _read_json(path)
    if not isinstance(record, dict):
        raise ExperimentError(f"No experiment named {experiment_id}.")

    contenders = record.get("contenders") or []
    runs: List[Dict[str, Any]] = []
    for contender in contenders:
        run_id = str(contender.get("run_id") or "")
        run_root = runs_dir / run_id
        entry = dict(contender)
        entry["run"] = run_overview(run_root, active_run_ids) if run_root.is_dir() else None
        runs.append(entry)

    matrix = _build_matrix(runs_dir, contenders)
    return {**record, "contenders": runs, "matrix": matrix}


def _build_matrix(runs_dir: Path, contenders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """rubric x contender pass matrix, grouped by task, from single-judge results."""
    questions: Dict[str, Dict[str, str]] = {}
    cells: Dict[str, Dict[str, Dict[str, Dict[str, int]]]] = {}
    task_order: List[str] = []

    for contender in contenders:
        run_id = str(contender.get("run_id") or "")
        run_root = runs_dir / run_id
        if not run_root.is_dir():
            continue
        for task_root in sorted(run_root.iterdir()):
            if not task_root.is_dir() or not (task_root / "logs").is_dir():
                continue
            manifest = _read_json(task_root / "manifest.json")
            task_id = (
                str(manifest.get("task_id"))
                if isinstance(manifest, dict) and manifest.get("task_id")
                else task_root.name
            )
            if task_id not in cells:
                cells[task_id] = {}
                questions.setdefault(task_id, {})
                task_order.append(task_id)
            if isinstance(manifest, dict):
                for rubric in manifest.get("rubrics") or []:
                    if isinstance(rubric, dict) and rubric.get("id"):
                        questions[task_id].setdefault(
                            str(rubric["id"]), str(rubric.get("question", ""))
                        )
            aggregate = _read_json(task_root / "judges" / "single_aggregate.json")
            if not isinstance(aggregate, dict):
                continue
            for row in aggregate.get("results") or []:
                rubric_id = str(row.get("rubric_id") or "")
                if not rubric_id:
                    continue
                bucket = cells[task_id].setdefault(rubric_id, {})
                stats = bucket.setdefault(run_id, {"passed": 0, "total": 0})
                stats["total"] += 1
                if row.get("passed"):
                    stats["passed"] += 1

    matrix = []
    for task_id in task_order:
        rubric_ids = sorted(cells[task_id].keys())
        matrix.append(
            {
                "task_id": task_id,
                "rubrics": [
                    {
                        "id": rubric_id,
                        "question": questions[task_id].get(rubric_id, ""),
                        "cells": cells[task_id][rubric_id],
                    }
                    for rubric_id in rubric_ids
                ],
            }
        )
    return matrix
