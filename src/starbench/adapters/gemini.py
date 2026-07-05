"""Gemini CLI adapter (Google's coding agent).

Headless runtime: the prompt is delivered on stdin (an empty ``-p ""`` is still
passed on argv, matching the historical invocation). Executor uses ``--yolo``;
judge uses ``--approval-mode plan`` for a read-only pass and appends the JSON
schema instruction to the prompt (no native schema flag). Output is a single
headless-json blob, parsed into ``final.md`` and normalised into compat events.

Invariant: in docker, HOME points into the workspace mount because the rootfs
is read-only and Gemini writes state under ``$HOME/.gemini``.

"改什么来这里": Gemini command flags, approval modes, docker HOME/env handling.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, List

from ..execution.docker import build_docker_agent_command, kill_container_on_timeout
from ..execution.parsers import normalize_headless_events, write_headless_final_output
from ..execution.process import run_codex_process, split_command
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import append_json_schema_instruction, build_executor_prompt
from .base import (
    ExecutorContext,
    InjectionChannel,
    JudgeContext,
    ProviderFilter,
    RuntimeAdapter,
    RuntimeInfo,
    finalize_success,
)

GEMINI_DOCKER_ENV_WHITELIST = ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL"]


def prepare_gemini_env(
    gemini_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("Gemini agent currently supports --auth-mode env or global")
    env = dict(base_env) if base_env is not None else os.environ.copy()
    gemini_home.mkdir(parents=True, exist_ok=True)
    return env


def build_gemini_headless_command(
    gemini_bin: str,
    *,
    prompt: str = "",
    model: str | None = None,
    approval_mode: str = "yolo",
    output_format: str = "json",
) -> List[str]:
    command = split_command(gemini_bin)
    command.extend(["--output-format", output_format, "--skip-trust"])
    if model:
        command.extend(["-m", model])
    if approval_mode == "yolo":
        command.append("--yolo")
    elif approval_mode:
        command.extend(["--approval-mode", approval_mode])
    command.extend(["-p", prompt])
    return command


def build_gemini_docker_command(
    *,
    gemini_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    model: str | None,
    auth_env: Dict[str, str],
    container_name: str | None = None,
) -> List[str]:
    inner_command = build_gemini_headless_command(gemini_bin, model=model, approval_mode="yolo")
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(GEMINI_DOCKER_ENV_WHITELIST),
        auth_env=auth_env,
        container_name=container_name,
        # Gemini CLI keeps its state under $HOME/.gemini; point HOME at a
        # writable dir inside the workspace mount (the rootfs is read-only).
        extra_env={"HOME": "/workspace/.runner/gemini_home"},
    )


async def run_gemini_process_in_docker(
    *,
    gemini_bin: str,
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
    (workspace / ".runner" / "gemini_home").mkdir(parents=True, exist_ok=True)
    auth_env = dict(base_env) if base_env is not None else os.environ.copy()
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_gemini_docker_command(
        gemini_bin=gemini_bin,
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        model=model,
        auth_env=auth_env,
        container_name=container_name,
    )
    result = await run_codex_process(
        command,
        cwd=workspace,
        prompt=prompt,
        env=auth_env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
    )
    kill_container_on_timeout(result, docker_bin, container_name)
    return result


class GeminiAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="gemini",
        label="Gemini CLI",
        description="Google's coding agent",
        protocol="gemini",
        bin="gemini",
        docker_image="starbench-gemini-cli:latest",
        docker_env_whitelist=tuple(GEMINI_DOCKER_ENV_WHITELIST),
        credential_env_keys=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        judge_sensitive_env=("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL"),
        default_executor_backend="local",
        # Gemini protocol: the official Google API, or any provider exposing a
        # gemini_base_url; wired through env vars.
        provider_filter=ProviderFilter(kinds=("google",), accepts_gemini_endpoint=True),
        injection=InjectionChannel(
            kind="gemini_env",
            base_url_var="GOOGLE_GEMINI_BASE_URL",
            api_key_var="GEMINI_API_KEY",
            default_api_key_env="GEMINI_API_KEY",
        ),
    )

    def executor_skill_prompt_location(self) -> str:
        return "./.gemini/skills/<skill-id>/"

    def executor_skill_install_root(self, paths: Dict[str, Path], executor_backend: str) -> Path:
        return paths["workspace"] / ".gemini" / "skills"

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        task = task_run.task
        logs = paths["logs"]
        gemini_bin = ctx.bins["gemini"]
        gemini_prompt = build_executor_prompt(
            task_run, executor_skill_location=self.executor_skill_prompt_location()
        )
        if ctx.executor_backend == "docker":
            result = await run_gemini_process_in_docker(
                gemini_bin=gemini_bin,
                docker_bin=ctx.docker_bin,
                docker_image=ctx.docker_image,
                workspace=paths["workspace"],
                prompt=gemini_prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=ctx.model,
                base_env=ctx.base_env,
            )
        else:
            command = build_gemini_headless_command(
                gemini_bin,
                model=ctx.model,
                approval_mode="yolo",
            )
            env = prepare_gemini_env(
                paths["codex_home"] / "gemini_executor", ctx.auth_mode, base_env=ctx.base_env
            )
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=gemini_prompt,
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )

        def _post() -> None:
            write_headless_final_output(logs / "events.jsonl", logs / "final.md")
            normalize_headless_events(logs / "events.jsonl", provider="gemini")

        return finalize_success(result, stderr_path=logs / "stderr.log", label="Gemini", work=_post)

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
        command = build_gemini_headless_command(
            ctx.bins["gemini"],
            model=model,
            approval_mode="plan",
        )
        env = prepare_gemini_env(
            judge_home_base.parent / f"{judge_home_base.name}_gemini",
            ctx.auth_mode,
            base_env=ctx.base_env,
        )
        prompt = append_json_schema_instruction(base_prompt, schema_path)
        result = await run_codex_process(
            command,
            cwd=judge_workspace,
            prompt=prompt,
            env=env,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )

        def _post() -> None:
            write_headless_final_output(events_path, judge_final_path, output_schema=schema_path)
            normalize_headless_events(events_path, provider="gemini")

        return finalize_success(result, stderr_path=stderr_path, label="Gemini", work=_post)
