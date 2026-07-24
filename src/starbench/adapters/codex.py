"""Codex adapter (OpenAI's coding agent) — the default runtime.

Codex is the only runtime that defaults to the docker backend, and its
executor/judge both go through ``codex exec`` with a per-role sandbox
(``workspace-write`` / ``danger-full-access`` for the executor, ``read-only``
for the judge). Output needs no post-processing: ``--output-last-message``
writes ``final.md`` / the result JSON directly.

Invariants:
- CODEX_HOME auth isolation: ``prepare_auth_home`` honours the requested auth
  mode; ``prepare_isolated_auth_home`` always isolates (used for docker).
- Executor skills install under ``$CODEX_HOME/skills`` (or ``.../docker/skills``
  for the docker backend).

"改什么来这里": Codex command flags, sandbox choices, or docker image handling.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List

from ..execution.docker import build_docker_agent_command
from ..execution.process import run_cli_process, split_command
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import append_thinking_instruction, build_executor_prompt
from .base import (
    ExecutorContext,
    InjectionChannel,
    JudgeContext,
    ProviderFilter,
    RuntimeAdapter,
    RuntimeInfo,
    effective_web_search,
)

CODEX_DOCKER_ENV_WHITELIST = ["CODEX_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"]


def prepare_auth_home(
    codex_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    env = dict(base_env) if base_env is not None else os.environ.copy()
    if auth_mode == "global":
        return env

    codex_home.mkdir(parents=True, exist_ok=True)
    env["CODEX_HOME"] = str(codex_home)

    if auth_mode == "copy-auth":
        source = Path.home() / ".codex" / "auth.json"
        if source.exists():
            shutil.copy2(source, codex_home / "auth.json")
    elif auth_mode != "env":
        raise ValueError(f"Unknown auth mode: {auth_mode}")

    return env


def prepare_isolated_auth_home(
    codex_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    """Prepare an isolated CODEX_HOME even when the caller selected global auth."""
    env = dict(base_env) if base_env is not None else os.environ.copy()
    codex_home.mkdir(parents=True, exist_ok=True)
    env["CODEX_HOME"] = str(codex_home)

    if auth_mode in {"global", "copy-auth"}:
        source = Path.home() / ".codex" / "auth.json"
        if source.exists():
            shutil.copy2(source, codex_home / "auth.json")
    elif auth_mode != "env":
        raise ValueError(f"Unknown auth mode: {auth_mode}")

    return env


def build_codex_exec_command(
    codex_bin: str,
    *,
    cwd: Path,
    final_path: Path,
    sandbox: str,
    output_schema: Path | None = None,
    model: str | None = None,
    allow_web_search: bool = False,
    include_trace_config: bool = True,
    reasoning_effort: str | None = None,
) -> List[str]:
    command = split_command(codex_bin)
    if allow_web_search:
        command.append("--search")
    command.append("exec")
    if model:
        command.extend(["-m", model])
    # Codex's native reasoning switch; "default" (legacy "none") means leave
    # the model's default alone rather than forcing a floor.
    if reasoning_effort and reasoning_effort not in ("default", "none"):
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    command.extend(
        [
            "--cd",
            str(cwd),
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--output-last-message",
            str(final_path),
            "-c",
            'approval_policy="never"',
            "--sandbox",
            sandbox,
            "--ignore-rules",
            "--disable",
            "plugins",
            "--disable",
            "memories",
        ]
    )
    if include_trace_config:
        command.extend(
            [
                "-c",
                'model_reasoning_summary="detailed"',
                "-c",
                "show_raw_agent_reasoning=true",
            ]
        )
    if output_schema is not None:
        command.extend(["--output-schema", str(output_schema)])
    command.append("-")
    return command


def build_docker_codex_command(
    *,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    codex_home: Path,
    inner_command,
    auth_env: Dict[str, str],
    container_name: str | None = None,
) -> List[str]:
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(CODEX_DOCKER_ENV_WHITELIST),
        auth_env=auth_env,
        container_name=container_name,
        extra_mounts={str(codex_home.resolve()): "/codex-home"},
        extra_env={"CODEX_HOME": "/codex-home"},
    )


async def run_codex_in_docker(
    *,
    codex_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    codex_home: Path,
    prompt: str,
    auth_mode: str,
    stdout_path: Path,
    stderr_path: Path,
    host_final_path: Path,
    timeout_seconds: int,
    sandbox: str,
    model: str | None = None,
    allow_web_search: bool = False,
    include_trace_config: bool = True,
    output_schema: Path | None = None,
    base_env: Dict[str, str] | None = None,
    reasoning_effort: str | None = None,
) -> ProcessResult:
    runner_dir = workspace / ".runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    docker_auth_home = codex_home / "docker"
    auth_env = prepare_isolated_auth_home(docker_auth_home, auth_mode, base_env=base_env)
    container_schema = None
    if output_schema is not None:
        raise ValueError("Docker Codex process currently supports executor runs only; evaluator schemas are host-local.")

    container_final_path = Path("/workspace/.runner/final.md")
    inner_command = build_codex_exec_command(
        codex_bin,
        cwd=Path("/workspace"),
        final_path=container_final_path,
        sandbox=sandbox,
        output_schema=container_schema,
        model=model,
        allow_web_search=allow_web_search,
        include_trace_config=include_trace_config,
        reasoning_effort=reasoning_effort,
    )
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_docker_codex_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        codex_home=docker_auth_home,
        inner_command=inner_command,
        auth_env=auth_env,
        container_name=container_name,
    )
    result = await run_cli_process(
        command,
        cwd=workspace,
        prompt=prompt,
        env=auth_env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
    )
    if result.timed_out:
        # Killing the docker CLI client does not stop the container itself;
        # without this the timed-out container keeps running and writing into
        # the mounted workspace.
        subprocess.run(
            split_command(docker_bin) + ["kill", container_name],
            check=False,
            capture_output=True,
        )

    container_final_on_host = workspace / ".runner" / "final.md"
    if container_final_on_host.exists():
        host_final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(container_final_on_host, host_final_path)
    return result


class CodexAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="codex",
        label="Codex",
        description="OpenAI's coding agent",
        protocol="openai",
        bin="codex",
        docker_image="starbench-codex:latest",
        docker_env_whitelist=tuple(CODEX_DOCKER_ENV_WHITELIST),
        credential_env_keys=("OPENAI_API_KEY",),
        judge_sensitive_env=("OPENAI_API_KEY", "OPENAI_BASE_URL"),
        default_executor_backend="docker",
        # Codex accepts the OpenAI protocol only (official or an OpenAI-compatible
        # gateway); it does not take xai like opencode does.
        provider_filter=ProviderFilter(kinds=("openai", "openai-compatible")),
        injection=InjectionChannel(kind="codex_config", default_api_key_env="OPENAI_API_KEY"),
        # Codex's own model_reasoning_effort config: a real switch, not a
        # prompt request. The upper tiers are model-dependent (gpt-5.6 ships
        # max/ultra); Codex coerces unsupported levels to the nearest one the
        # model accepts, and each model's real table comes from the CLI's
        # models cache (surfaced per-model by the console).
        thinking_channel="native_config",
        thinking_efforts=("default", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
        enforces_web_search=True,
    )

    def executor_skill_prompt_location(self) -> str:
        return "$CODEX_HOME/skills/<skill-id>/"

    def executor_skill_install_root(self, paths: Dict[str, Path], executor_backend: str) -> Path:
        if executor_backend == "docker":
            return paths["agent_home"] / "docker" / "skills"
        if executor_backend == "local":
            return paths["agent_home"] / "skills"
        raise ValueError(f"Unknown executor backend: {executor_backend}")

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        task = task_run.task
        logs = paths["logs"]
        codex_bin = ctx.bins["codex"]
        allow_web = effective_web_search(ctx.web_search_mode, task.allow_web_search)
        if ctx.executor_backend == "local":
            command = build_codex_exec_command(
                codex_bin,
                cwd=paths["workspace"],
                final_path=logs / "final.md",
                sandbox="workspace-write",
                model=ctx.model,
                allow_web_search=allow_web,
                include_trace_config=True,
                reasoning_effort=ctx.thinking_effort,
            )
            env = prepare_auth_home(paths["agent_home"], ctx.auth_mode, base_env=ctx.base_env)
            return await run_cli_process(
                command,
                cwd=paths["workspace"],
                prompt=build_executor_prompt(task_run),
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )
        if ctx.executor_backend == "docker":
            return await run_codex_in_docker(
                codex_bin=codex_bin,
                docker_bin=ctx.docker_bin,
                docker_image=ctx.docker_image,
                workspace=paths["workspace"],
                codex_home=paths["agent_home"],
                prompt=build_executor_prompt(task_run),
                auth_mode=ctx.auth_mode,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                host_final_path=logs / "final.md",
                timeout_seconds=task.timeout_seconds,
                sandbox="danger-full-access",
                model=ctx.model,
                allow_web_search=allow_web,
                include_trace_config=True,
                base_env=ctx.base_env,
                reasoning_effort=ctx.thinking_effort,
            )
        raise ValueError(f"Unknown executor backend: {ctx.executor_backend}")

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
        command = build_codex_exec_command(
            ctx.bins["codex"],
            cwd=judge_workspace,
            final_path=judge_final_path,
            sandbox="read-only",
            output_schema=schema_path,
            model=model,
            include_trace_config=False,
        )
        env = prepare_auth_home(judge_home_base, ctx.auth_mode, base_env=ctx.base_env)
        return await run_cli_process(
            command,
            cwd=judge_workspace,
            prompt=append_thinking_instruction(base_prompt, "default"),
            env=env,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )
