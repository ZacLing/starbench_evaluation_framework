"""Pi adapter (pi.dev multi-provider coding agent).

Pi is headless-friendly: ``--mode json`` streams JSONL events to stdout and a
prompt piped on stdin is the whole initial message (``cli/initial-message.ts``).
Thinking rides the native ``--thinking <level>`` flag. Skills use pi's native
Agent Skills support, poisoning-proof: ``--no-skills`` kills discovery and each
installed executor skill is passed explicitly via ``--skill``.

Invariants:
- Auth mode is ``env`` only. The operator's ``~/.pi/agent/auth.json`` is a
  personal OAuth identity and must never carry benchmark traffic.
- ``PI_CODING_AGENT_DIR`` / ``PI_CODING_AGENT_SESSION_DIR`` / ``PI_OFFLINE`` /
  ``PI_SKIP_VERSION_CHECK`` are hard-set (not setdefault): isolation must
  survive injected base envs. In docker they point into the workspace mount
  (the container rootfs is read-only), same pattern as the siblings' HOME.
- Pi tool events map to ``command_execution`` only; a ``file_change`` mapping
  waits on live-stream verification of the tool-argument payload (an optional
  real-CLI smoke), so ``trace_summary.file_changes`` is empty for pi.

"改什么来这里": pi command shape, env isolation, provider flag wiring, docker.
"""

from __future__ import annotations

import uuid
from pathlib import Path, PurePosixPath
from typing import Dict, List, Sequence

from ..execution.docker import build_docker_agent_command, kill_container_on_timeout
from ..execution.parsers import normalize_pi_events, write_pi_final_output
from ..execution.process import run_cli_process, split_command
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import append_json_schema_instruction, build_executor_prompt
from .base import (
    ExecutorContext,
    InjectionChannel,
    JudgeContext,
    ProviderFilter,
    RuntimeAdapter,
    RuntimeInfo,
    RuntimeOption,
    finalize_success,
)

# Provider API-key env vars pi reads natively (docs/providers). A contender
# that injects any of these could reroute pi when it acts as judge; the two
# PI_* vars could redirect its config/session storage outright.
PI_JUDGE_SENSITIVE_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "PI_CODING_AGENT_DIR",
    "PI_CODING_AGENT_SESSION_DIR",
)

# Provider keys forwarded (by name, when present) into pi's container.
PI_DOCKER_ENV_WHITELIST = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
]

# In-container isolation home; lives inside the workspace mount because the
# container rootfs is read-only (same convention as the siblings' HOME).
_PI_CONTAINER_HOME = PurePosixPath("/workspace/.runner/pi_home")


def _require_env_auth(auth_mode: str) -> None:
    if auth_mode != "env":
        raise ValueError(
            "Pi agent supports --auth-mode env only; the operator's ~/.pi OAuth "
            "login must not carry benchmark traffic"
        )


def build_pi_command(
    pi_bin: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    thinking: str = "default",
    skill_paths: Sequence[Path] = (),
) -> List[str]:
    command = split_command(pi_bin)
    command.extend(["--mode", "json", "--no-skills"])
    for skill in skill_paths:
        command.extend(["--skill", str(skill)])
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    # pi's native reasoning switch; "default" (legacy "none") leaves the CLI
    # default alone. Levels: off|minimal|low|medium|high|xhigh|max.
    if thinking and thinking not in ("default", "none"):
        command.extend(["--thinking", thinking])
    return command


def prepare_pi_env(
    pi_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    _require_env_auth(auth_mode)
    # Deliberate divergence from the sibling adapters' ``os.environ.copy()``
    # fallback: with no base env supplied, pi starts from nothing rather than
    # from the operator's environment, so isolation never depends on the caller.
    env = dict(base_env) if base_env is not None else {}
    pi_home.mkdir(parents=True, exist_ok=True)
    env["PI_CODING_AGENT_DIR"] = str(pi_home)
    env["PI_CODING_AGENT_SESSION_DIR"] = str(pi_home / "sessions")
    env["PI_OFFLINE"] = "1"
    env["PI_SKIP_VERSION_CHECK"] = "1"
    return env


def _installed_skill_paths(install_root: Path) -> List[Path]:
    if not install_root.is_dir():
        return []
    return sorted(path for path in install_root.iterdir() if path.is_dir())


def _container_skill_paths(install_root: Path) -> List[PurePosixPath]:
    """Installed skills as the container sees them (workspace-mounted)."""
    return [
        PurePosixPath("/workspace/.starbench/executor_skills") / path.name
        for path in _installed_skill_paths(install_root)
    ]


def build_pi_docker_command(
    *,
    pi_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    auth_env: Dict[str, str],
    provider: str | None = None,
    model: str | None = None,
    thinking: str = "default",
    skill_paths: Sequence[PurePosixPath] = (),
    container_name: str | None = None,
) -> List[str]:
    inner_command = build_pi_command(
        pi_bin,
        provider=provider,
        model=model,
        thinking=thinking,
        skill_paths=skill_paths,
    )
    extra_env = {
        "HOME": str(_PI_CONTAINER_HOME),
        "PI_CODING_AGENT_DIR": str(_PI_CONTAINER_HOME / "agent"),
        "PI_CODING_AGENT_SESSION_DIR": str(_PI_CONTAINER_HOME / "agent" / "sessions"),
        "PI_OFFLINE": "1",
        "PI_SKIP_VERSION_CHECK": "1",
    }
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(PI_DOCKER_ENV_WHITELIST),
        auth_env=auth_env,
        container_name=container_name,
        extra_env=extra_env,
    )


async def run_pi_process_in_docker(
    *,
    pi_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    prompt: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    auth_mode: str,
    provider: str | None = None,
    model: str | None = None,
    thinking: str = "default",
    skill_paths: Sequence[PurePosixPath] = (),
    base_env: Dict[str, str] | None = None,
) -> ProcessResult:
    _require_env_auth(auth_mode)
    (workspace / ".runner" / "pi_home").mkdir(parents=True, exist_ok=True)
    auth_env = dict(base_env) if base_env is not None else {}
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_pi_docker_command(
        pi_bin=pi_bin,
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        auth_env=auth_env,
        provider=provider,
        model=model,
        thinking=thinking,
        skill_paths=skill_paths,
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
    kill_container_on_timeout(result, docker_bin, container_name)
    return result


class PiAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="pi",
        label="Pi",
        description="Multi-provider coding agent (pi.dev)",
        protocol="multi",
        bin="pi",
        docker_image="starbench-pi:latest",
        docker_env_whitelist=tuple(PI_DOCKER_ENV_WHITELIST),
        credential_env_keys=(),
        judge_sensitive_env=PI_JUDGE_SENSITIVE_ENV,
        default_executor_backend="local",
        provider_filter=ProviderFilter(kinds=("anthropic", "openai", "google", "xai")),
        injection=InjectionChannel(kind="pi_gateway"),
        thinking_channel="native_config",
        thinking_efforts=(
            "default",
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        options=(RuntimeOption(name="provider", type="string", role="both", surface="wiring"),),
    )

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        task = task_run.task
        logs = paths["logs"]
        prompt = build_executor_prompt(
            task_run, executor_skill_location=self.executor_skill_prompt_location()
        )
        install_root = self.executor_skill_install_root(paths, ctx.executor_backend)
        if ctx.executor_backend == "docker":
            result = await run_pi_process_in_docker(
                pi_bin="pi",
                docker_bin=ctx.docker_bin,
                docker_image=ctx.docker_image,
                workspace=paths["workspace"],
                prompt=prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                auth_mode=ctx.auth_mode,
                provider=ctx.options.get("provider"),
                model=ctx.model,
                thinking=ctx.thinking_effort,
                skill_paths=_container_skill_paths(install_root),
                base_env=ctx.base_env,
            )
        else:
            command = build_pi_command(
                ctx.bins["pi"],
                provider=ctx.options.get("provider"),
                model=ctx.model,
                thinking=ctx.thinking_effort,
                skill_paths=_installed_skill_paths(install_root),
            )
            env = prepare_pi_env(
                paths["agent_home"] / "pi_executor", ctx.auth_mode, base_env=ctx.base_env
            )
            result = await run_cli_process(
                command,
                cwd=paths["workspace"],
                prompt=prompt,
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )

        def _post() -> None:
            # Compat pass first: extraction raises on an empty turn and
            # finalize_success stops at the first exception, so a failed run
            # still keeps a readable trace (same order as opencode's _post).
            normalize_pi_events(logs / "events.jsonl")
            write_pi_final_output(logs / "events.jsonl", logs / "final.md")

        return finalize_success(result, stderr_path=logs / "stderr.log", label="Pi", work=_post)

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
        command = build_pi_command(
            ctx.bins["pi"],
            provider=ctx.options.get("provider"),
            model=model,
            thinking=ctx.thinking_effort,
        )
        env = prepare_pi_env(
            judge_home_base.parent / f"{judge_home_base.name}_pi",
            ctx.auth_mode,
            base_env=ctx.base_env,
        )
        result = await run_cli_process(
            command,
            cwd=judge_workspace,
            prompt=prompt,
            env=env,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )

        def _post() -> None:
            # Compat pass first (see run_executor): a judge turn that produced
            # no extractable JSON still leaves its trace behind.
            normalize_pi_events(events_path)
            write_pi_final_output(events_path, judge_final_path, output_schema=schema_path)

        return finalize_success(result, stderr_path=stderr_path, label="Pi", work=_post)
