"""OpenCode adapter (open-source agent for OpenAI-compatible models).

OpenCode is provider-configurable: an OpenAI-compatible provider/base-URL/model
is injected as an inline config (``OPENCODE_CONFIG_CONTENT``). Executor uses the
``build`` agent; judge uses the read-only ``plan`` agent. Reading the final
message may require ``opencode export`` against the session state, so the same
env used to run must be reused to export — the docker path reconstructs that env
via :func:`opencode_docker_export_env` from the workspace-mounted home.

Invariants:
- ``model`` is provider-qualified (``provider/model``) via ``opencode_model_name``.
- In docker, HOME (config + session state) lives under the workspace mount so
  the host can run ``export`` afterwards.

"改什么来这里": OpenCode agent selection, inline provider config, export env.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

from ..execution.docker import build_docker_agent_command, kill_container_on_timeout
from ..execution.parsers import append_opencode_compat_events, write_opencode_final_output
from ..execution.process import run_codex_process, split_command
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import (
    OPENCODE_JUDGE_AGENT,
    append_json_schema_instruction,
    build_executor_prompt,
    opencode_model_name,
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

OPENCODE_DOCKER_ENV_WHITELIST = ["OPENAI_API_KEY", "XAI_API_KEY"]


def build_opencode_run_command(
    opencode_bin: str,
    *,
    cwd: Path,
    model: str | None = None,
    agent: str = "build",
    output_format: str = "json",
) -> List[str]:
    command = split_command(opencode_bin)
    command.extend(["run", "--dir", str(cwd), "--agent", agent, "--format", output_format])
    if model:
        command.extend(["--model", model])
    command.append("--dangerously-skip-permissions")
    return command


def _opencode_model_id(model: str | None) -> str | None:
    if not model:
        return None
    return model.split("/", 1)[1] if "/" in model else model


def _opencode_inline_config_content(
    provider: str | None,
    base_url: str | None,
    model: str | None,
    api_key_env: str | None,
) -> str | None:
    if not (provider and base_url):
        return None
    provider_config: Dict[str, Any] = {
        "npm": "@ai-sdk/openai-compatible",
        "name": provider,
        "options": {"baseURL": base_url},
        "models": {},
    }
    if api_key_env:
        provider_config["options"]["apiKey"] = f"{{env:{api_key_env}}}"
    model_id = _opencode_model_id(model)
    if model_id:
        provider_config["models"][model_id] = {
            "name": model_id,
            "limit": {"context": 128000, "output": 8192},
        }
    inline_config = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {provider: provider_config},
    }
    return json.dumps(inline_config, sort_keys=True)


def prepare_opencode_env(
    opencode_home: Path,
    auth_mode: str,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    base_env: Dict[str, str] | None = None,
) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("OpenCode agent currently supports --auth-mode env or global")
    env = dict(base_env) if base_env is not None else os.environ.copy()
    if auth_mode == "env":
        opencode_home.mkdir(parents=True, exist_ok=True)
        env["OPENCODE_CONFIG_DIR"] = str(opencode_home)
    env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")
    env.setdefault("OPENCODE_DISABLE_PRUNE", "1")

    config_content = _opencode_inline_config_content(provider, base_url, model, api_key_env)
    if config_content is not None:
        env["OPENCODE_CONFIG_CONTENT"] = config_content
    return env


def build_opencode_docker_command(
    *,
    opencode_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    model: str | None,
    auth_env: Dict[str, str],
    provider: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    container_name: str | None = None,
) -> List[str]:
    inner_command = build_opencode_run_command(
        opencode_bin, cwd=Path("/workspace"), model=model, agent="build"
    )
    extra_env = {
        # OpenCode stores config under $HOME/.config and sessions under
        # $HOME/.local/share; keep both inside the workspace mount so the
        # host can read the session afterwards.
        "HOME": "/workspace/.runner/opencode_home",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_PRUNE": "1",
    }
    config_content = _opencode_inline_config_content(provider, base_url, model, api_key_env)
    if config_content is not None:
        extra_env["OPENCODE_CONFIG_CONTENT"] = config_content
    env_whitelist = list(OPENCODE_DOCKER_ENV_WHITELIST)
    if api_key_env and api_key_env not in env_whitelist:
        env_whitelist.append(api_key_env)
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=env_whitelist,
        auth_env=auth_env,
        container_name=container_name,
        extra_env=extra_env,
    )


def opencode_docker_export_env(
    workspace: Path, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    """Environment for running `opencode export` on the host against the
    session state a containerized run left inside the workspace mount."""
    env = dict(base_env) if base_env is not None else os.environ.copy()
    home = workspace / ".runner" / "opencode_home"
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")
    env.setdefault("OPENCODE_DISABLE_PRUNE", "1")
    return env


async def run_opencode_process_in_docker(
    *,
    opencode_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    prompt: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    model: str | None,
    provider: str | None = None,
    base_url: str | None = None,
    api_key_env: str | None = None,
    base_env: Dict[str, str] | None = None,
) -> ProcessResult:
    (workspace / ".runner" / "opencode_home").mkdir(parents=True, exist_ok=True)
    auth_env = dict(base_env) if base_env is not None else os.environ.copy()
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_opencode_docker_command(
        opencode_bin=opencode_bin,
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        model=model,
        auth_env=auth_env,
        provider=provider,
        base_url=base_url,
        api_key_env=api_key_env,
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


class OpenCodeAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="opencode",
        label="OpenCode",
        description="Open-source agent for OpenAI-compatible models",
        protocol="openai",
        bin="opencode",
        docker_image="starbench-opencode:latest",
        docker_env_whitelist=tuple(OPENCODE_DOCKER_ENV_WHITELIST),
        credential_env_keys=(),
        judge_sensitive_env=(),
        default_executor_backend="local",
        # OpenAI-protocol provider/base-url/key are injected as gateway flags;
        # unlike codex, opencode also drives xai-kind providers.
        provider_filter=ProviderFilter(kinds=("openai-compatible", "openai", "xai")),
        injection=InjectionChannel(kind="opencode_gateway"),
    )

    def executor_skill_prompt_location(self) -> str:
        return "./.starbench/executor_skills/<skill-id>/"

    def executor_skill_install_root(self, paths: Dict[str, Path], executor_backend: str) -> Path:
        return paths["workspace"] / ".starbench" / "executor_skills"

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        task = task_run.task
        logs = paths["logs"]
        opencode_bin = ctx.bins["opencode"]
        model_name = opencode_model_name(ctx.model, ctx.opencode_provider)
        opencode_prompt = build_executor_prompt(
            task_run, executor_skill_location=self.executor_skill_prompt_location()
        )
        if ctx.executor_backend == "docker":
            result = await run_opencode_process_in_docker(
                opencode_bin=opencode_bin,
                docker_bin=ctx.docker_bin,
                docker_image=ctx.docker_image,
                workspace=paths["workspace"],
                prompt=opencode_prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=model_name,
                provider=ctx.opencode_provider,
                base_url=ctx.opencode_base_url,
                api_key_env=ctx.opencode_api_key_env,
                base_env=ctx.base_env,
            )
            env = opencode_docker_export_env(paths["workspace"], base_env=ctx.base_env)
        else:
            command = build_opencode_run_command(
                opencode_bin,
                cwd=paths["workspace"],
                model=model_name,
                agent="build",
            )
            env = prepare_opencode_env(
                paths["codex_home"] / "opencode_executor",
                ctx.auth_mode,
                provider=ctx.opencode_provider,
                base_url=ctx.opencode_base_url,
                model=model_name,
                api_key_env=ctx.opencode_api_key_env,
                base_env=ctx.base_env,
            )
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=opencode_prompt,
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )

        def _post() -> None:
            append_opencode_compat_events(logs / "events.jsonl")
            write_opencode_final_output(
                logs / "events.jsonl",
                logs / "final.md",
                opencode_bin=opencode_bin,
                env=env,
            )

        return finalize_success(result, stderr_path=logs / "stderr.log", label="OpenCode", work=_post)

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
        opencode_bin = ctx.bins["opencode"]
        model_name = opencode_model_name(model, ctx.opencode_provider)
        command = build_opencode_run_command(
            opencode_bin,
            cwd=judge_workspace,
            model=model_name,
            agent=OPENCODE_JUDGE_AGENT,
        )
        env = prepare_opencode_env(
            judge_home_base.parent / f"{judge_home_base.name}_opencode",
            ctx.auth_mode,
            provider=ctx.opencode_provider,
            base_url=ctx.opencode_base_url,
            model=model_name,
            api_key_env=ctx.opencode_api_key_env,
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
            append_opencode_compat_events(events_path)
            write_opencode_final_output(
                events_path,
                judge_final_path,
                opencode_bin=opencode_bin,
                env=env,
                output_schema=schema_path,
            )

        return finalize_success(result, stderr_path=stderr_path, label="OpenCode", work=_post)
