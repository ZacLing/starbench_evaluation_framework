"""Claude Code adapter (Anthropic's coding agent).

Executor drives ``claude -p`` in ``stream-json`` mode (so tool calls/reasoning
become compat events); judge drives it with a native ``--json-schema``. Claude
is the only runtime with a prompt-level thinking instruction (it has no native
reasoning-effort flag), applied to both executor and judge prompts.

Invariants:
- Auth binds to the config dir: global auth keeps the host ``CLAUDE_CONFIG_DIR``
  untouched; env auth points it at an isolated per-run home.
- Executor skills install under the workspace ``.claude/skills``.
- Output post-processing (final text + compat events) can fail an otherwise-OK
  run; ``finalize_success`` downgrades it.

"改什么来这里": Claude command flags, allowed-tools, thinking mapping, docker env.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Dict, List

from ..execution.docker import build_docker_agent_command, kill_container_on_timeout
from ..execution.parsers import (
    append_claude_compat_events,
    write_claude_final_output,
    write_claude_stream_final_output,
)
from ..execution.process import run_codex_process, split_command
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import (
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
    effective_web_search,
    finalize_success,
)

CLAUDE_DOCKER_ENV_WHITELIST = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]

CLAUDE_JUDGE_ALLOWED_TOOLS = "Read,Glob,Grep,Bash,LS"

CLAUDE_EXECUTOR_BASE_TOOLS = "Read,Write,Edit,MultiEdit,Bash,Glob,Grep,LS"
CLAUDE_EXECUTOR_WEB_TOOLS = "WebSearch,WebFetch"


def claude_executor_allowed_tools(allow_web_search: bool) -> str:
    if allow_web_search:
        return f"{CLAUDE_EXECUTOR_BASE_TOOLS},{CLAUDE_EXECUTOR_WEB_TOOLS}"
    return CLAUDE_EXECUTOR_BASE_TOOLS


def prepare_claude_env(
    claude_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("Claude agent currently supports --auth-mode env or global")
    env = dict(base_env) if base_env is not None else os.environ.copy()
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    if auth_mode == "global":
        # Keep the host CLAUDE_CONFIG_DIR: Claude Code login credentials are
        # bound to the config dir, so overriding it would break host login.
        return env
    claude_home.mkdir(parents=True, exist_ok=True)
    env["CLAUDE_CONFIG_DIR"] = str(claude_home)
    return env


def build_claude_print_command(
    claude_bin: str,
    *,
    cwd: Path,
    model: str | None = None,
    output_schema: Path | None = None,
    permission_mode: str | None = None,
    allowed_tools: str | None = None,
    max_turns: int | None = None,
    output_format: str = "json",
    effort: str | None = None,
) -> List[str]:
    command = split_command(claude_bin)
    command.extend(["-p", "--output-format", output_format, "--no-session-persistence"])
    if output_format == "stream-json":
        # Claude Code print mode requires --verbose for stream-json output.
        command.append("--verbose")
    if model:
        command.extend(["--model", model])
    # Claude Code's native reasoning switch (adaptive-thinking effort level);
    # "default" (legacy "none") leaves the CLI's own default alone.
    if effort and effort not in ("default", "none"):
        command.extend(["--effort", effort])
    if permission_mode:
        command.extend(["--permission-mode", permission_mode])
    if allowed_tools:
        command.extend(["--allowedTools", allowed_tools])
    if max_turns is not None:
        command.extend(["--max-turns", str(max_turns)])
    if output_schema is not None:
        command.extend(["--json-schema", output_schema.read_text(encoding="utf-8")])
    return command


def build_claude_docker_command(
    *,
    claude_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    model: str | None,
    allowed_tools: str | None,
    max_turns: int | None,
    auth_env: Dict[str, str],
    container_name: str | None = None,
    effort: str | None = None,
) -> List[str]:
    inner_command = build_claude_print_command(
        claude_bin,
        cwd=Path("/workspace"),
        model=model,
        permission_mode="acceptEdits",
        allowed_tools=allowed_tools,
        max_turns=max_turns,
        output_format="stream-json",
        effort=effort,
    )
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(CLAUDE_DOCKER_ENV_WHITELIST),
        auth_env=auth_env,
        container_name=container_name,
        extra_env={
            "CLAUDE_CONFIG_DIR": "/workspace/.runner/claude_home",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        },
    )


async def run_claude_process_in_docker(
    *,
    claude_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    prompt: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    model: str | None,
    allowed_tools: str | None,
    max_turns: int | None,
    base_env: Dict[str, str] | None = None,
    effort: str | None = None,
) -> ProcessResult:
    (workspace / ".runner" / "claude_home").mkdir(parents=True, exist_ok=True)
    auth_env = dict(base_env) if base_env is not None else os.environ.copy()
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_claude_docker_command(
        claude_bin=claude_bin,
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        model=model,
        allowed_tools=allowed_tools,
        max_turns=max_turns,
        auth_env=auth_env,
        container_name=container_name,
        effort=effort,
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


class ClaudeAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="claude",
        label="Claude Code",
        description="Anthropic's coding agent",
        protocol="anthropic",
        bin="claude",
        docker_image="starbench-claude-code:latest",
        docker_env_whitelist=tuple(CLAUDE_DOCKER_ENV_WHITELIST),
        credential_env_keys=("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"),
        judge_sensitive_env=("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"),
        default_executor_backend="local",
        # Anthropic protocol: the official API, or any provider exposing an
        # anthropic_base_url; wired through env vars.
        provider_filter=ProviderFilter(kinds=("anthropic",), accepts_anthropic_endpoint=True),
        injection=InjectionChannel(
            kind="anthropic_env",
            base_url_var="ANTHROPIC_BASE_URL",
            api_key_var="ANTHROPIC_AUTH_TOKEN",
            default_api_key_env="ANTHROPIC_AUTH_TOKEN",
        ),
        # Claude Code's own --effort switch (adaptive-thinking effort level);
        # levels are the CLI's real set, verified against `claude --help`.
        thinking_channel="native_config",
        thinking_efforts=("default", "low", "medium", "high", "xhigh", "max"),
        enforces_web_search=True,
    )

    def executor_skill_prompt_location(self) -> str:
        return "./.claude/skills/<skill-id>/"

    def executor_skill_install_root(self, paths: Dict[str, Path], executor_backend: str) -> Path:
        return paths["workspace"] / ".claude" / "skills"

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        task = task_run.task
        logs = paths["logs"]
        claude_bin = ctx.bins["claude"]
        claude_prompt = build_executor_prompt(
            task_run, executor_skill_location=self.executor_skill_prompt_location()
        )
        allow_web = effective_web_search(ctx.web_search_mode, task.allow_web_search)
        if ctx.executor_backend == "docker":
            result = await run_claude_process_in_docker(
                claude_bin=claude_bin,
                docker_bin=ctx.docker_bin,
                docker_image=ctx.docker_image,
                workspace=paths["workspace"],
                prompt=claude_prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=ctx.model,
                allowed_tools=claude_executor_allowed_tools(allow_web),
                max_turns=ctx.claude_max_turns,
                base_env=ctx.base_env,
                effort=ctx.thinking_effort,
            )
        else:
            command = build_claude_print_command(
                claude_bin,
                cwd=paths["workspace"],
                model=ctx.model,
                permission_mode="acceptEdits",
                allowed_tools=claude_executor_allowed_tools(allow_web),
                max_turns=ctx.claude_max_turns,
                output_format="stream-json",
                effort=ctx.thinking_effort,
            )
            env = prepare_claude_env(
                paths["codex_home"] / "claude_executor", ctx.auth_mode, base_env=ctx.base_env
            )
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=claude_prompt,
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )

        def _post() -> None:
            write_claude_stream_final_output(logs / "events.jsonl", logs / "final.md")
            append_claude_compat_events(logs / "events.jsonl")

        return finalize_success(result, stderr_path=logs / "stderr.log", label="Claude", work=_post)

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
        command = build_claude_print_command(
            ctx.bins["claude"],
            cwd=judge_workspace,
            model=model,
            output_schema=schema_path,
            allowed_tools=CLAUDE_JUDGE_ALLOWED_TOOLS,
        )
        env = prepare_claude_env(
            judge_home_base.parent / f"{judge_home_base.name}_claude",
            ctx.auth_mode,
            base_env=ctx.base_env,
        )
        result = await run_codex_process(
            command,
            cwd=judge_workspace,
            prompt=append_thinking_instruction(base_prompt, ctx.thinking_effort),
            env=env,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )

        def _post() -> None:
            write_claude_final_output(events_path, judge_final_path, output_schema=schema_path)

        return finalize_success(result, stderr_path=stderr_path, label="Claude", work=_post)
