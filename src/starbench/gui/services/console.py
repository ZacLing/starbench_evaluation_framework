"""Application services exposed by the local Console HTTP adapter."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ...adapters import DEFAULT_DOCKER_IMAGES
from .. import agents, data, experiments, library, providers, skills
from ..agents import DEFAULT_RUNTIMES_DIR
from ..launcher import (
    AGENT_CHOICES,
    LaunchError,
    build_run_argv,
    scoped_launch_env,
)
from ...lifecycle import LaunchRegistry, launch_transaction
from ..skills import DEFAULT_SKILLS_DIR


@dataclass(frozen=True)
class ServiceResult:
    payload: Any
    created: bool = False


class ConsoleApplication:
    """Own Console use cases without depending on HTTP request objects."""

    def __init__(
        self,
        *,
        runs_dir: Path,
        tasks_dirs: List[Path],
        cwd: Path,
        registry: LaunchRegistry,
        runtimes_dir: Path = DEFAULT_RUNTIMES_DIR,
        skills_dir: Path = DEFAULT_SKILLS_DIR,
    ) -> None:
        self.runs_dir = runs_dir
        self.tasks_dirs = tasks_dirs
        self.cwd = cwd
        self.registry = registry
        self.runtimes_dir = runtimes_dir
        self.skills_dir = skills_dir

    def meta(self) -> Dict[str, Any]:
        return {
            "runs_dir": str(self.runs_dir),
            "cwd": str(self.cwd),
            "runtimes_dir": str(self.runtimes_dir),
            "skills_dir": str(self.skills_dir),
            "tasks_dirs": [
                {"dir": str(path), "exists": path.is_dir()} for path in self.tasks_dirs
            ],
            "agents": list(AGENT_CHOICES),
            "judge_modes": ["single", "parallel", "both"],
            "auth_modes": ["env", "global", "copy-auth"],
            "backends": ["local", "docker"],
            "thinking_efforts": ["default", "low", "medium", "high"],
        }

    def list_runs(self) -> Dict[str, Any]:
        return {"runs": data.list_runs(self.runs_dir, self.registry.active_run_ids())}

    def run_detail(self, run_id: str) -> Dict[str, Any]:
        return data.run_detail(self.runs_dir, run_id, self.registry.active_run_ids())

    def run_live(self, run_id: str) -> Dict[str, Any]:
        return data.run_live(self.runs_dir, run_id, self.registry.active_run_ids())

    def task_run_detail(self, run_id: str, task_id: str) -> Dict[str, Any]:
        return data.task_run_detail(self.runs_dir, run_id, task_id)

    def raw_events(
        self, run_id: str, task_id: str, offset: int, limit: int
    ) -> Dict[str, Any]:
        return data.raw_events(self.runs_dir, run_id, task_id, offset, limit)

    def task_trace(
        self, run_id: str, task_id: str, offset: int, limit: int
    ) -> Dict[str, Any]:
        return data.task_trace(self.runs_dir, run_id, task_id, offset, limit)

    def read_artifact(self, run_id: str, task_id: str, path: str) -> Dict[str, Any]:
        return data.read_artifact(self.runs_dir, run_id, task_id, path)

    def coverage(self, profile_id: Optional[str]) -> Dict[str, Any]:
        # The service layer owns composition: the authoritative profile list
        # (builtin merge, validation) is injected into the pure read model.
        profiles = experiments.load_profiles(self.runs_dir).get("profiles")
        return data.coverage(self.runs_dir, self.tasks_dirs, profile_id, profiles=profiles)

    def libraries(self) -> List[Dict[str, Any]]:
        return [
            {
                "dir": str(tasks_dir),
                "exists": tasks_dir.is_dir(),
                "tasks": data.list_task_packages(tasks_dir),
            }
            for tasks_dir in self.tasks_dirs
        ]

    def registered_dir(self, raw: str) -> Path:
        target = Path(raw).resolve() if raw else None
        for tasks_dir in self.tasks_dirs:
            if target == tasks_dir:
                return tasks_dir
        raise library.LibraryError(f"Not a registered task directory: {raw}")

    def task_history(self, tasks_dir_arg: Optional[str]) -> Dict[str, Any]:
        tasks_dir = self.registered_dir(tasks_dir_arg) if tasks_dir_arg else None
        return data.task_history(self.runs_dir, tasks_dir)

    def task_package_detail(self, tasks_dir: str, name: str) -> Dict[str, Any]:
        return library.task_package_detail(self.registered_dir(tasks_dir), name)

    def browse_directories(self, path: Optional[str]) -> Dict[str, Any]:
        return library.browse_directories(path, cwd=self.cwd)

    def preflight(self, params: Mapping[str, str]) -> Dict[str, Any]:
        def value(name: str, default: str = "") -> str:
            return params.get(name, default)

        executor_agent = value("executor_agent", "codex")
        evaluator_agent = value("evaluator_agent", "codex")
        docker_image = value("docker_image")
        executor_meta = self._custom_meta(executor_agent)
        evaluator_meta = self._custom_meta(evaluator_agent)
        if value("executor_backend", "local") == "docker":
            if executor_meta:
                docker_image = str(executor_meta.get("docker_image") or "")
            elif not docker_image:
                docker_image = DEFAULT_DOCKER_IMAGES.get(executor_agent, "")

        def env_keys(name: str) -> List[str]:
            return [item for item in value(name).split(",") if item]

        # Gateway credentials ride the role env-key lists (executor_env_keys /
        # evaluator_env_keys) that planning derives from each role's option box;
        # the preflight POST carries no runtime-named knob fields of its own.
        checks = library.preflight(
            executor_agent=executor_agent,
            evaluator_agent=evaluator_agent,
            executor_backend=value("executor_backend", "local"),
            docker_image=docker_image,
            executor_auth_mode=value("executor_auth_mode", "env"),
            evaluator_auth_mode=value("evaluator_auth_mode", "env"),
            executor_bin=(executor_meta or {}).get("cli", {}).get("bin")
            or value("executor_bin")
            or None,
            evaluator_bin=(evaluator_meta or {}).get("cli", {}).get("bin")
            or value("evaluator_bin")
            or None,
            executor_env_keys=env_keys("executor_env_keys")
            or self._agent_env_keys(executor_meta),
            evaluator_env_keys=env_keys("evaluator_env_keys")
            or self._agent_env_keys(evaluator_meta),
        )
        return {"checks": checks}

    def list_agents(self) -> Dict[str, Any]:
        return agents.list_agents(self.runtimes_dir)

    def agent_statuses(self, *, check_updates: bool) -> Dict[str, Any]:
        return agents.agent_statuses(self.runtimes_dir, check_updates=check_updates)

    def agent_templates(self) -> Dict[str, Any]:
        return {"templates": agents.agent_templates()}

    def list_skills(self) -> Dict[str, Any]:
        return skills.list_skills(self.skills_dir)

    def list_launches(self) -> Dict[str, Any]:
        return {"launches": self.registry.list()}

    def load_profiles(self) -> Dict[str, Any]:
        return experiments.load_profiles(self.runs_dir)

    def load_providers(self) -> Dict[str, Any]:
        return providers.load_providers(self.runs_dir)

    def provider_cli_statuses(self) -> Dict[str, Any]:
        return providers.load_provider_cli_statuses(self.runs_dir)

    def compare(self, run_ids: List[str]) -> Dict[str, Any]:
        return data.compare_runs(
            self.runs_dir, run_ids, self.registry.active_run_ids()
        )

    def launch(self, payload: Dict[str, Any]) -> ServiceResult:
        argv = build_run_argv(payload, runs_dir=self.runs_dir)
        if payload.get("dry_run"):
            return ServiceResult({"argv": argv, "dry_run": True})
        run_id = str(payload["run_id"]).strip()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.runs_dir / f"{run_id}.launch.log"
        launch = self.registry.launch(run_id, argv, cwd=self.cwd, log_path=log_path)
        return ServiceResult(launch, created=True)

    def stop(self, run_id: str) -> Any:
        return self.registry.stop(run_id)

    def import_task(self, payload: Dict[str, Any]) -> ServiceResult:
        files = payload.get("files")
        if not isinstance(files, list):
            raise library.LibraryError("`files` must be a list of {path, content_b64} objects.")
        dry_run = bool(payload.get("dry_run"))
        target_dir = self.registered_dir(str(payload.get("target_dir") or ""))
        report = library.install_task_package(
            files, target_dir=target_dir, dry_run=dry_run
        )
        return ServiceResult(report, created=not dry_run and bool(report["valid"]))

    @staticmethod
    def _materialized_argv(item: Dict[str, Any]) -> List[str]:
        """Write the item's run_plan to a temp file and point argv at it.

        Planning is pure (the plan document rides the item; argv carries a
        placeholder); the file exists only for the subprocess handoff and the
        supervisor deletes it at terminal state. Argv-transport items pass
        through unchanged."""
        run_plan = item.get("run_plan")
        if run_plan is None:
            return item["argv"]
        descriptor, plan_path = tempfile.mkstemp(
            prefix=f"starbench-plan-{item['run_id']}-", suffix=".json"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(run_plan, indent=2, sort_keys=True) + "\n")
        return [
            plan_path if token == "<generated-at-launch>" else token
            for token in item["argv"]
        ]

    def launch_batch(self, payload: Dict[str, Any]) -> ServiceResult:
        """Plan and launch one run per contender as a single transaction.

        There is no separate launch record: each run's run_state.json carries
        the batch name, and comparisons are computed statelessly from run
        artifacts (see read_models.compare)."""
        plan = experiments.plan_experiment(
            payload,
            runs_dir=self.runs_dir,
            runtimes_dir=self.runtimes_dir,
            skills_dir=self.skills_dir,
        )
        if payload.get("dry_run"):
            return ServiceResult({**plan, "dry_run": True})
        launch_specs = [
            {
                "run_id": item["run_id"],
                "argv": self._materialized_argv(item),
                "cwd": self.cwd,
                "log_path": self.runs_dir / f"{item['run_id']}.launch.log",
                "env_extra": scoped_launch_env(
                    item.get("executor_env_spec"), item.get("judge_env_spec")
                ),
                "batch": plan["name"],
            }
            for item in plan["plans"]
        ]
        try:
            launched = launch_transaction(self.registry, launch_specs)
        except LaunchError as error:
            raise experiments.ExperimentError(
                f"Launch rolled back: {error}"
            ) from error
        return ServiceResult(
            {
                "id": plan["name"],
                "run_ids": [item["run_id"] for item in plan["plans"]],
                "launches": launched,
            },
            created=True,
        )

    def save_profiles(self, payload: Dict[str, Any]) -> Any:
        return experiments.save_profiles(self.runs_dir, payload)

    def save_providers(self, payload: Dict[str, Any]) -> Any:
        return providers.save_providers(self.runs_dir, payload)

    def save_agent(self, payload: Dict[str, Any]) -> Any:
        return agents.save_custom_agent(self.runtimes_dir, payload)

    def install_agent(self, agent_id: str) -> Any:
        if not agent_id:
            raise agents.AgentError("`agent_id` is required.")
        return agents.install_agent(agent_id)

    def delete_agent(self, agent_id: str) -> Any:
        return agents.delete_custom_agent(self.runtimes_dir, agent_id)

    def refresh_provider_models(self, provider_id: str) -> Any:
        return providers.refresh_provider_models(self.runs_dir, provider_id)

    def register_tasks_dir(self, raw: str) -> Dict[str, Any]:
        if not raw:
            raise library.LibraryError("`dir` is required.")
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            raise library.LibraryError(f"Not a directory: {path}")
        if path not in self.tasks_dirs:
            self.tasks_dirs.append(path)
        return {"libraries": self.libraries()}

    def _custom_meta(self, agent: str) -> Optional[Dict[str, Any]]:
        if not agent.startswith("custom:"):
            return None
        return agents.get_custom_agent(self.runtimes_dir, agent.split(":", 1)[1])

    @staticmethod
    def _agent_env_keys(meta: Optional[Dict[str, Any]]) -> Optional[Sequence[str]]:
        if meta and meta.get("api_key_env"):
            return [str(meta["api_key_env"])]
        return None
