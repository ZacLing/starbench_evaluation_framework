"""Pi adapter (pi.dev multi-provider coding agent, host-local).

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
  survive injected base envs.
- Pi tool events map to ``command_execution`` only; a ``file_change`` mapping
  waits on live-stream verification of the tool-argument payload (an optional
  real-CLI smoke), so ``trace_summary.file_changes`` is empty for pi.

"改什么来这里": pi command shape, env isolation, provider flag wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

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
    if auth_mode != "env":
        raise ValueError(
            "Pi agent supports --auth-mode env only; the operator's ~/.pi OAuth "
            "login must not carry benchmark traffic"
        )
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


class PiAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="pi",
        label="Pi",
        description="Multi-provider coding agent (pi.dev)",
        protocol="multi",
        bin="pi",
        docker_image=None,
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
        if ctx.executor_backend != "local":
            raise ValueError("pi executor supports --executor-backend local only")
        prompt = build_executor_prompt(
            task_run, executor_skill_location=self.executor_skill_prompt_location()
        )
        command = build_pi_command(
            ctx.bins["pi"],
            provider=ctx.options.get("provider"),
            model=ctx.model,
            thinking=ctx.thinking_effort,
            skill_paths=_installed_skill_paths(
                self.executor_skill_install_root(paths, ctx.executor_backend)
            ),
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
