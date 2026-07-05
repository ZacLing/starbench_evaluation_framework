"""Runtime adapter interface and the single-source-of-truth metadata record.

``RuntimeInfo`` is the one place that answers "what is this runtime?" — its id,
label, protocol, executable, docker image, the env vars it forwards into its
container, the credentials preflight should look for, and the env vars a
contender could use to hijack the judge. The GUI's various tables (agents /
library preflight / experiments conflict detection) are meant to derive from
this record rather than each keep their own copy (that migration is P2; P1 just
makes ``RuntimeInfo`` carry every fact).

A ``RuntimeAdapter`` owns everything runtime-specific about *running* a task:
building the executor/judge invocation, preparing its env, wrapping it in
docker, and parsing its output. The orchestrator (``run_benchmark``) holds no
per-runtime branches — it resolves an adapter from the registry and calls
``run_executor`` / ``run_judge``.

Invariants:
- Adapters never import ``run_benchmark`` (dependency arrow points down); they
  import prompt builders from ``starbench.runner.prompts`` and execution
  primitives from ``starbench.execution``.
- ``run_executor`` / ``run_judge`` return a :class:`ProcessResult`; a run that
  exited 0 but failed output post-processing is downgraded via ``mark_failed``.

To add a runtime, add an adapter module + register it in ``registry.py``.
To add a per-runtime fact, add a field here and populate it in each adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Tuple

from ..execution.process import mark_failed
from ..runner.models import ProcessResult, TaskRunSpec


@dataclass(frozen=True)
class RuntimeInfo:
    """Static facts about a runtime — the single source of truth.

    ``docker_env_whitelist``: env keys forwarded (by name) into the runtime's
    container. ``credential_env_keys``: env vars the preflight check treats as
    this runtime's API credentials. ``judge_sensitive_env``: env vars that, if a
    contender injects them, would reroute this runtime when it acts as judge.
    """

    id: str
    label: str
    description: str
    protocol: str
    bin: str
    docker_image: str | None
    docker_env_whitelist: Tuple[str, ...] = ()
    credential_env_keys: Tuple[str, ...] = ()
    judge_sensitive_env: Tuple[str, ...] = ()
    default_executor_backend: str = "local"

    @property
    def docker_capable(self) -> bool:
        return self.docker_image is not None


@dataclass(frozen=True)
class ExecutorContext:
    """Everything an adapter needs to run the executor side of a task."""

    bins: Dict[str, str]
    docker_bin: str
    docker_image: str
    executor_backend: str
    auth_mode: str
    model: str | None
    claude_thinking_effort: str
    claude_max_turns: int | None
    opencode_provider: str | None
    opencode_base_url: str | None
    opencode_api_key_env: str | None


@dataclass(frozen=True)
class JudgeContext:
    """Everything an adapter needs to run the judge side of a task."""

    bins: Dict[str, str]
    auth_mode: str
    model: str | None
    claude_thinking_effort: str
    opencode_provider: str | None
    opencode_base_url: str | None
    opencode_api_key_env: str | None


def finalize_success(
    result: ProcessResult,
    *,
    stderr_path: Path,
    label: str,
    work: Callable[[], None],
) -> ProcessResult:
    """Run output post-processing for a successful run, downgrading on error.

    Mirrors the historical ``if status == "success": try: ... except`` block:
    on exception the run is marked failed and the error is appended to the
    runtime's stderr log with the runtime-specific ``label``.
    """
    if result.status != "success":
        return result
    try:
        work()
    except Exception as exc:  # noqa: BLE001 - any post-processing failure downgrades the run
        result = mark_failed(result)
        with stderr_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{label} output post-processing failed: {type(exc).__name__}: {exc}\n")
    return result


class RuntimeAdapter:
    """Base class for runtime adapters.

    Built-in adapters are stateless singletons; the custom-spec adapter carries
    its :class:`CustomRuntimeSpec`. Subclasses set ``info`` and implement
    ``run_executor`` / ``run_judge``; the skill-location defaults below suit the
    workspace-local runtimes and are overridden by Codex/Grok/Gemini/Claude.
    """

    info: RuntimeInfo

    # -- executor skills -----------------------------------------------------
    def executor_skill_prompt_location(self) -> str:
        return "./.starbench/executor_skills/<skill-id>/"

    def executor_skill_install_root(self, paths: Dict[str, Path], executor_backend: str) -> Path:
        return paths["workspace"] / ".starbench" / "executor_skills"

    # -- run -----------------------------------------------------------------
    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        raise NotImplementedError

    async def run_judge(
        self,
        *,
        base_prompt: str,
        schema_path: Path,
        judge_workspace: Path,
        judge_final_path: Path,
        events_path: Path,
        stderr_path: Path,
        judge_home_base: Path,
        model: str | None,
        timeout_seconds: int,
        ctx: JudgeContext,
    ) -> ProcessResult:
        raise NotImplementedError
