"""Grok Build adapter (xAI's coding agent).

Distinctive trait: Grok takes its prompt on the command line (``-p <prompt>``),
so stdin stays empty for every Grok run. Executor uses ``bypassPermissions`` +
``--always-approve`` in a ``workspace`` sandbox; judge uses ``dontAsk`` in a
``read-only`` sandbox and appends the JSON schema instruction to the argv
prompt. Output is headless-json, parsed into ``final.md`` + compat events.

Invariant: in docker, HOME points into the workspace mount (read-only rootfs).

"改什么来这里": Grok command flags, permission/sandbox modes, docker env.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, List

from ..execution.docker import build_docker_agent_command, kill_container_on_timeout
from ..execution.parsers import normalize_headless_events, write_headless_final_output
from ..execution.process import run_cli_process, split_command
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import (
    append_json_schema_instruction,
    append_thinking_instruction,
    build_executor_prompt,
)
from .base import (
    ExecutorContext,
    InjectionChannel,
    JudgeContext,
    ProviderFilter,
    RuntimeAdapter,
    RuntimeInfo,
    finalize_success,
)

GROK_DOCKER_ENV_WHITELIST = ["XAI_API_KEY"]


def prepare_grok_env(
    grok_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("Grok agent currently supports --auth-mode env or global")
    env = dict(base_env) if base_env is not None else os.environ.copy()
    grok_home.mkdir(parents=True, exist_ok=True)
    return env


def build_grok_headless_command(
    grok_bin: str,
    *,
    cwd: Path,
    prompt: str,
    model: str | None = None,
    permission_mode: str = "bypassPermissions",
    sandbox: str = "workspace",
    output_format: str = "json",
) -> List[str]:
    command = split_command(grok_bin)
    command.extend(
        [
            "--no-auto-update",
            "--no-alt-screen",
            "--cwd",
            str(cwd),
            "--output-format",
            output_format,
            "--permission-mode",
            permission_mode,
            "--sandbox",
            sandbox,
        ]
    )
    if permission_mode == "bypassPermissions":
        command.append("--always-approve")
    if model:
        command.extend(["-m", model])
    command.extend(["-p", prompt])
    return command


def build_grok_docker_command(
    *,
    grok_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    prompt: str,
    model: str | None,
    auth_env: Dict[str, str],
    container_name: str | None = None,
) -> List[str]:
    inner_command = build_grok_headless_command(
        grok_bin,
        cwd=Path("/workspace"),
        prompt=prompt,
        model=model,
        permission_mode="bypassPermissions",
        sandbox="workspace",
    )
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(GROK_DOCKER_ENV_WHITELIST),
        auth_env=auth_env,
        container_name=container_name,
        extra_env={"HOME": "/workspace/.runner/grok_home"},
    )


async def run_grok_process_in_docker(
    *,
    grok_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    prompt: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    model: str | None,
    base_env: Dict[str, str] | None = None,
) -> ProcessResult:
    (workspace / ".runner" / "grok_home").mkdir(parents=True, exist_ok=True)
    auth_env = dict(base_env) if base_env is not None else os.environ.copy()
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_grok_docker_command(
        grok_bin=grok_bin,
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        prompt=prompt,
        model=model,
        auth_env=auth_env,
        container_name=container_name,
    )
    # Grok takes the prompt on the command line; stdin stays empty.
    result = await run_cli_process(
        command,
        cwd=workspace,
        prompt="",
        env=auth_env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
    )
    kill_container_on_timeout(result, docker_bin, container_name)
    return result


class GrokAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="grok",
        label="Grok Build",
        description="xAI's coding agent",
        protocol="xai",
        bin="grok",
        docker_image="starbench-grok:latest",
        docker_env_whitelist=tuple(GROK_DOCKER_ENV_WHITELIST),
        credential_env_keys=("XAI_API_KEY",),
        judge_sensitive_env=("XAI_API_KEY",),
        default_executor_backend="local",
        # xAI only; the CLI has no endpoint-override mechanism, so there is no
        # injection channel — the official login/credential is used as-is.
        provider_filter=ProviderFilter(kinds=("xai",)),
        injection=InjectionChannel(kind="none"),
    )

    def executor_skill_prompt_location(self) -> str:
        return "./.grok/skills/<skill-id>/"

    def executor_skill_install_root(self, paths: Dict[str, Path], executor_backend: str) -> Path:
        return paths["workspace"] / ".grok" / "skills"

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        task = task_run.task
        logs = paths["logs"]
        grok_bin = ctx.bins["grok"]
        prompt = append_thinking_instruction(
            build_executor_prompt(
                task_run, executor_skill_location=self.executor_skill_prompt_location()
            ),
            ctx.thinking_effort,
        )
        if ctx.executor_backend == "docker":
            result = await run_grok_process_in_docker(
                grok_bin=grok_bin,
                docker_bin=ctx.docker_bin,
                docker_image=ctx.docker_image,
                workspace=paths["workspace"],
                prompt=prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=ctx.model,
                base_env=ctx.base_env,
            )
        else:
            command = build_grok_headless_command(
                grok_bin,
                cwd=paths["workspace"],
                prompt=prompt,
                model=ctx.model,
                permission_mode="bypassPermissions",
                sandbox="workspace",
            )
            env = prepare_grok_env(
                paths["agent_home"] / "grok_executor", ctx.auth_mode, base_env=ctx.base_env
            )
            result = await run_cli_process(
                command,
                cwd=paths["workspace"],
                prompt="",
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )

        def _post() -> None:
            write_headless_final_output(logs / "events.jsonl", logs / "final.md")
            normalize_headless_events(logs / "events.jsonl", provider="grok")

        return finalize_success(result, stderr_path=logs / "stderr.log", label="Grok", work=_post)

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
        prompt = append_json_schema_instruction(base_prompt, schema_path)
        command = build_grok_headless_command(
            ctx.bins["grok"],
            cwd=judge_workspace,
            prompt=prompt,
            model=model,
            permission_mode="dontAsk",
            sandbox="read-only",
        )
        env = prepare_grok_env(
            judge_home_base.parent / f"{judge_home_base.name}_grok",
            ctx.auth_mode,
            base_env=ctx.base_env,
        )
        # Grok takes the prompt on argv; stdin stays empty.
        result = await run_cli_process(
            command,
            cwd=judge_workspace,
            prompt="",
            env=env,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )

        def _post() -> None:
            write_headless_final_output(events_path, judge_final_path, output_schema=schema_path)
            normalize_headless_events(events_path, provider="grok")

        return finalize_success(result, stderr_path=stderr_path, label="Grok", work=_post)
