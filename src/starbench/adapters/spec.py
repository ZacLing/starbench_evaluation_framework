"""Data-driven adapter for custom runtimes (``runtimes/<id>.json``).

One adapter instance wraps one :class:`CustomRuntimeSpec`. It proves the
abstraction the built-in adapters generalise: command, args, model flag, prompt
delivery (stdin vs argv positional/flag), output parser, static env, and an
optional docker section all come from data rather than code. Executor skills use
the workspace-local default location (inherited from the base adapter).

Invariants:
- ``prompt_via`` decides stdin vs argv; when ``"arg"`` the process gets an empty
  stdin and the prompt travels on the command line.
- Docker requires a ``docker`` section in the spec; missing it, the docker
  backend is refused (the same guard the CLI applies up front).

"改什么来这里": how a JSON spec maps to a command/env/docker invocation.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import Dict, List

from ..execution.docker import build_docker_agent_command
from ..execution.parsers import normalize_custom_events, write_custom_final_output
from ..execution.process import run_codex_process, split_command
from ..runner.custom_runtime import CustomRuntimeSpec
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import (
    append_json_schema_instruction,
    build_executor_prompt,
)
from .base import ExecutorContext, JudgeContext, RuntimeAdapter, RuntimeInfo, finalize_success


def build_custom_command(
    spec: CustomRuntimeSpec,
    *,
    role: str,
    model: str | None,
    prompt: str,
) -> List[str]:
    if role not in {"executor", "judge"}:
        raise ValueError(f"Unknown custom runtime role: {role}")
    command = split_command(spec.command)
    command.extend(spec.judge_args if role == "judge" else spec.args)
    if model and spec.model_flag:
        command.extend([spec.model_flag, model])
    if spec.prompt_via == "arg":
        # An empty prompt_flag means the CLI takes the task as a positional
        # argument (e.g. `trae-cli run "<task>"`).
        command.extend([spec.prompt_flag, prompt] if spec.prompt_flag else [prompt])
    return command


def build_custom_docker_command(
    spec: CustomRuntimeSpec,
    *,
    docker_bin: str,
    workspace: Path,
    prompt: str,
    model: str | None,
    auth_env: Dict[str, str],
    container_name: str | None = None,
) -> List[str]:
    if not spec.docker_image:
        raise ValueError(f"Custom runtime {spec.id} has no docker image configured")
    inner_command = build_custom_command(spec, role="executor", model=model, prompt=prompt)
    # Same treatment as the built-in runtimes: the container rootfs is
    # read-only, so HOME must point into the workspace mount. The spec's
    # static env wins if it sets HOME itself.
    extra_env = {"HOME": "/workspace/.runner/custom_home", **dict(spec.env)}
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=spec.docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(spec.docker_env_passthrough),
        auth_env=auth_env,
        container_name=container_name,
        extra_env=extra_env,
    )


async def run_custom_process_in_docker(
    spec: CustomRuntimeSpec,
    *,
    docker_bin: str,
    workspace: Path,
    prompt: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    model: str | None = None,
    base_env: Dict[str, str] | None = None,
) -> ProcessResult:
    (workspace / ".runner" / "custom_home").mkdir(parents=True, exist_ok=True)
    auth_env = dict(base_env) if base_env is not None else os.environ.copy()
    auth_env.update(spec.env)
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_custom_docker_command(
        spec,
        docker_bin=docker_bin,
        workspace=workspace,
        prompt=prompt,
        model=model,
        auth_env=auth_env,
        container_name=container_name,
    )
    result = await run_codex_process(
        command,
        cwd=workspace,
        prompt=prompt if spec.prompt_via == "stdin" else "",
        env=auth_env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
    )
    if result.timed_out:
        subprocess.run(
            split_command(docker_bin) + ["kill", container_name],
            check=False,
            capture_output=True,
        )
    return result


def _custom_runtime_info(spec: CustomRuntimeSpec) -> RuntimeInfo:
    try:
        bin_name = split_command(spec.command)[0] if spec.command.strip() else spec.command
    except ValueError:
        bin_name = spec.command
    return RuntimeInfo(
        id=f"custom:{spec.id}",
        label=spec.id,
        description="",
        protocol="none",
        bin=bin_name,
        docker_image=spec.docker_image,
        docker_env_whitelist=tuple(spec.docker_env_passthrough),
        credential_env_keys=(),
        judge_sensitive_env=tuple(spec.env.keys()),
        default_executor_backend="local",
    )


class SpecAdapter(RuntimeAdapter):
    """Adapter bound to a single custom runtime spec."""

    def __init__(self, spec: CustomRuntimeSpec) -> None:
        self.spec = spec
        self.agent_id = f"custom:{spec.id}"
        self.info = _custom_runtime_info(spec)

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        spec = self.spec
        task = task_run.task
        logs = paths["logs"]
        if ctx.executor_backend != "local" and spec.docker_image is None:
            raise ValueError(
                f"{self.agent_id} executor requires a docker section for --executor-backend docker"
            )
        prompt_text = build_executor_prompt(
            task_run, executor_skill_location=self.executor_skill_prompt_location()
        )
        if ctx.executor_backend == "docker":
            result = await run_custom_process_in_docker(
                spec,
                docker_bin=ctx.docker_bin,
                workspace=paths["workspace"],
                prompt=prompt_text,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=ctx.model,
                base_env=ctx.base_env,
            )
        else:
            command = build_custom_command(spec, role="executor", model=ctx.model, prompt=prompt_text)
            env = dict(ctx.base_env)
            env.update(spec.env)
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=prompt_text if spec.prompt_via == "stdin" else "",
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )

        def _post() -> None:
            write_custom_final_output(logs / "events.jsonl", logs / "final.md", parser=spec.parser)
            normalize_custom_events(logs / "events.jsonl", parser=spec.parser, provider=spec.id)

        return finalize_success(result, stderr_path=logs / "stderr.log", label="Custom runtime", work=_post)

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
        spec = self.spec
        prompt = append_json_schema_instruction(base_prompt, schema_path)
        command = build_custom_command(spec, role="judge", model=model, prompt=prompt)
        env = dict(ctx.base_env)
        env.update(spec.env)
        prompt_over_stdin = spec.prompt_via != "arg"
        result = await run_codex_process(
            command,
            cwd=judge_workspace,
            prompt=prompt if prompt_over_stdin else "",
            env=env,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )

        def _post() -> None:
            write_custom_final_output(
                events_path,
                judge_final_path,
                parser=spec.parser,
                output_schema=schema_path,
            )
            normalize_custom_events(events_path, parser=spec.parser, provider=spec.id)

        return finalize_success(result, stderr_path=stderr_path, label="Custom runtime", work=_post)
