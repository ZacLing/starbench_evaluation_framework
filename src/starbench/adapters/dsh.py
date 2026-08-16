"""DeepSeek Harness adapter (dsh — DeepSeek's Cordis-plugin coding harness).

dsh is a plugin *composition*, not a flag-driven CLI. The launcher owns three
things — ``--profile <name>``, repeatable ``--patch <file>`` overlays, and the
config dumps — and hands everything after its own flags to the booted profile's
app (``@deepseek-ai/dsh/args``). The one-shot app is
``dsh --profile headless "<task>"``: the task is a **positional argument**, not
stdin, stdout is the last non-empty assistant text as plain text, stderr stays
empty on success, and the exit code is 0 only when the final ``turn/end`` reason
is ``completed`` (``@deepseek-ai/dsh-headless``).

Everything else a benchmark run needs to pin — which provider route and model
answer, where the durable session log lands, whether telemetry runs — is
configuration, so this adapter writes two files into each run's own dsh home
and points the launcher at them:

- ``<dsh_home>/settings.yaml`` — the user settings document. Its
  ``llm-pi-ai:`` / ``llm-deepseek:`` section activates the chosen provider
  route and names the env var its key comes from. Only the variable *name* is
  ever written; the key itself resolves per request through dsh's credential
  seam (JSON content: JSON is valid YAML, and the repo carries no YAML writer).
- ``<dsh_home>/starbench.patch.yml`` — a ``--patch`` overlay, the last layer
  before the launcher's own telemetry switch, pinning ``agent-default-model``
  to this run's route+model and ``session-persistence-jsonl`` to a readable log
  inside the run directory. A patch replaces the whole ``config`` of the row it
  targets (``@deepseek-ai/cordis-plugin-include``), so each row is restated in
  full; a patch whose row is absent warns and is skipped, never fails the boot.

Invariants:
- Auth mode is ``env`` only, like pi: the operator's ``~/.dsh`` login and
  ``$DSH_HOME/.credentials.yaml`` must never carry benchmark traffic.
- **Telemetry is off three ways.** dsh mirrors every session-log event —
  assistant text included, with no redaction rule mounted — onto an OTLP
  endpoint when its ``session-telemetry-otel`` row runs. ``dsh-base`` 0.1.x
  ships that row mounted-but-``DISABLED`` and gated on ``DSH_TELEMETRY_MODE``,
  while 0.0.x shipped it *on* under the row id ``telemetry-otel``, which the
  launcher's ``DSH_TELEMETRY_DISABLED`` switch (keyed on the newer id) does not
  reach. So: ``DSH_TELEMETRY_DISABLED`` and ``DSH_TELEMETRY_MODE`` are hard-set
  (not setdefault), any injected ``DSH_TELEMETRY_OTLP_URL`` is dropped, and the
  patch overlay disables *both* row ids outright. The overlay is the load-
  bearing one — it does not depend on which dsh version is installed.
- ``DSH_HOME`` / ``DSH_PERMISSION_MODE`` are hard-set for the same reason
  isolation is hard-set in pi: a contender's injected base env must not decide
  where dsh reads its config or how far its sandbox reaches. ``DSH_TOOLS_MODE``
  is dropped so tool presentation is the composition's default, not a
  contender's choice. In docker the home and the session root live inside the
  workspace mount (the container rootfs is read-only), same pattern as pi's.
- The judge runs host-local and read-only (``DSH_PERMISSION_MODE=read-only``);
  the executor gets ``workspace-write`` locally and ``danger-full-access`` in
  the container, where the container itself is the sandbox (Codex's stance).
- Thinking rides the settings document, not a flag: ``llm-deepseek`` accepts
  ``off|high|max`` and ``llm-pi-ai`` accepts pi-ai's seven levels, so this
  runtime declares only the intersection (``default|off|high|max``). The other
  four pi-ai tiers would be rejected with ``UNSUPPORTED_REASONING_EFFORT`` on a
  DeepSeek route, so they are deliberately not offered.

"改什么来这里": dsh command shape, generated settings/patch files, env isolation,
provider routing, docker.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Mapping

from ..execution.docker import build_docker_agent_command, kill_container_on_timeout
from ..execution.parsers import normalize_dsh_events, write_dsh_final_output
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

# Env vars a contender could use to reroute or wiretap dsh when it judges: the
# provider keys each route reads, DeepSeek's own key and endpoint override
# (``llm-deepseek`` falls back to $DEEPSEEK_BASE_URL when its config names no
# baseURL), the config root, and the three telemetry switches.
DSH_JUDGE_SENSITIVE_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DSH_HOME",
    "DSH_TELEMETRY_DISABLED",
    "DSH_TELEMETRY_MODE",
    "DSH_TELEMETRY_OTLP_URL",
)

# Provider keys forwarded (by name, when present) into dsh's container. Endpoint
# overrides are not forwarded: an endpoint this run should use is written into
# the generated settings document, never inherited from the ambient env.
DSH_DOCKER_ENV_WHITELIST = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
]

# dsh's own default provider route: ``dsh-base``'s ``agent-default-model`` row
# ships ``provider: deepseek-official`` (the route ``@deepseek-ai/dsh-llm-deepseek``
# registers). Used when a run names a model but no route.
DSH_DEFAULT_PROVIDER_ROUTE = "deepseek-official"

# The two telemetry row ids dsh has shipped (0.1.x renamed 0.0.x's
# ``telemetry-otel``). Disabling both covers either installed version; the one
# that is absent warns in the loader and is skipped.
DSH_TELEMETRY_ROW_IDS = ("session-telemetry-otel", "telemetry-otel")

# Generated per run inside the run's dsh home.
DSH_PATCH_FILENAME = "starbench.patch.yml"
DSH_SETTINGS_FILENAME = "settings.yaml"

# In-container isolation root; inside the workspace mount because the container
# rootfs is read-only (same convention as pi's ``_PI_CONTAINER_HOME``).
_DSH_CONTAINER_ROOT = PurePosixPath("/workspace/.runner/dsh")
_DSH_CONTAINER_HOME = _DSH_CONTAINER_ROOT / "home"
_DSH_CONTAINER_SESSIONS = _DSH_CONTAINER_ROOT / "sessions"

_GENERATED_NOTE = (
    "# Generated per run by StarBench; do not edit. JSON is valid YAML.\n"
)


def _require_env_auth(auth_mode: str) -> None:
    if auth_mode != "env":
        raise ValueError(
            "DeepSeek Harness supports --auth-mode env only; the operator's "
            "~/.dsh login must not carry benchmark traffic"
        )


def _write_yaml_document(path: Path, payload: Any) -> None:
    """Write a YAML document as JSON (a valid YAML subset) with a header note."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _GENERATED_NOTE + json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_dsh_command(
    dsh_bin: str,
    *,
    prompt: str,
    patch_file: str,
) -> List[str]:
    """``dsh --profile headless --patch <file> "<task>"``.

    Launcher flags come first by construction: the first token the launcher does
    not recognize starts the app's arguments, and the headless app reads its
    task from the positional it finds there.
    """
    command = split_command(dsh_bin)
    command.extend(["--profile", "headless"])
    command.extend(["--patch", patch_file])
    command.append(prompt)
    return command


def build_dsh_settings(
    *,
    provider: str | None = None,
    api_key_env: str | None = None,
    base_url: str | None = None,
    thinking: str = "default",
) -> Dict[str, Any]:
    """The settings document activating one provider route for this run.

    Two adapters, two section shapes (both verified against their package
    READMEs). ``deepseek-official`` is ``@deepseek-ai/dsh-llm-deepseek``'s single
    route, whose whole section *is* the profile; every other route belongs to
    ``@deepseek-ai/dsh-llm-pi-ai``, which is mounted dormant and registers a
    route the moment its ``providers`` dict names one — which is why a pi-ai
    route is written even when there is nothing to configure on it.

    A key is never written, only the *name* of the env var holding it.
    """
    route = provider or DSH_DEFAULT_PROVIDER_ROUTE
    reasoning = thinking if thinking and thinking not in ("default", "none") else None
    if route == DSH_DEFAULT_PROVIDER_ROUTE:
        section: Dict[str, Any] = {}
        if api_key_env:
            section["apiKeyEnv"] = api_key_env
        if base_url:
            section["baseURL"] = base_url
        if reasoning:
            section["reasoningEffort"] = reasoning
        return {"llm-deepseek": section} if section else {}
    profile: Dict[str, Any] = {}
    if api_key_env:
        profile["apiKeyEnv"] = api_key_env
    if base_url:
        profile["baseURL"] = base_url
    if reasoning:
        profile["reasoning"] = reasoning
    return {"llm-pi-ai": {"providers": {route: profile}}}


def build_dsh_patch(
    *,
    session_root: str,
    provider: str | None = None,
    model: str | None = None,
) -> List[Dict[str, Any]]:
    """The ``--patch`` overlay: model routing, session log, telemetry off.

    ``agent-default-model``'s config requires both ``provider`` and ``model``
    and a patch replaces the row's config wholesale, so the row is only stated
    when this run names a model; otherwise dsh keeps its own default pair.
    ``session-persistence-jsonl`` has no default root at all, and its defaults
    are zstd frames with packed chunk runs — restated here as a plain readable
    JSONL inside the run directory.
    """
    rows: List[Dict[str, Any]] = []
    if model:
        rows.append(
            {
                "id": "agent-default-model",
                "config": {"provider": provider or DSH_DEFAULT_PROVIDER_ROUTE, "model": model},
            }
        )
    rows.append(
        {
            "id": "session-persistence-jsonl",
            "config": {"root": session_root, "compression": "none", "packChunks": False},
        }
    )
    rows.extend({"id": row_id, "disabled": True} for row_id in DSH_TELEMETRY_ROW_IDS)
    return rows


def write_dsh_config(
    dsh_home: Path,
    *,
    session_root: str,
    provider: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
    base_url: str | None = None,
    thinking: str = "default",
) -> Path:
    """Materialize this run's settings + patch overlay; return the patch path.

    ``session_root`` is a string because the docker path writes container-side
    paths into a file that lives on the host.
    """
    dsh_home.mkdir(parents=True, exist_ok=True)
    settings = build_dsh_settings(
        provider=provider, api_key_env=api_key_env, base_url=base_url, thinking=thinking
    )
    settings_path = dsh_home / DSH_SETTINGS_FILENAME
    if settings:
        _write_yaml_document(settings_path, settings)
    elif settings_path.exists():
        # An empty document is the absence of a section; never leave a stale one.
        settings_path.unlink()
    patch_path = dsh_home / DSH_PATCH_FILENAME
    _write_yaml_document(
        patch_path, build_dsh_patch(session_root=session_root, provider=provider, model=model)
    )
    return patch_path


def prepare_dsh_env(
    dsh_home: Path,
    auth_mode: str,
    *,
    permission_mode: str,
    base_env: Dict[str, str] | None = None,
) -> Dict[str, str]:
    """The run env for a host-local dsh process.

    Same deliberate divergence from the sibling adapters' ``os.environ.copy()``
    fallback that pi makes: with no base env supplied, dsh starts from nothing,
    so isolation never depends on the caller.
    """
    _require_env_auth(auth_mode)
    env = dict(base_env) if base_env is not None else {}
    dsh_home.mkdir(parents=True, exist_ok=True)
    env.update(_dsh_isolation_env(str(dsh_home), permission_mode))
    for key in ("DSH_TELEMETRY_OTLP_URL", "DSH_TOOLS_MODE"):
        env.pop(key, None)
    return env


def _dsh_isolation_env(dsh_home: str, permission_mode: str) -> Dict[str, str]:
    """The vars that must hold whatever the caller's environment says."""
    return {
        "DSH_HOME": dsh_home,
        "DSH_PERMISSION_MODE": permission_mode,
        # Any non-empty value opts out; "DISABLED" is the 0.1.x mode vocabulary.
        "DSH_TELEMETRY_DISABLED": "1",
        "DSH_TELEMETRY_MODE": "DISABLED",
    }


def build_dsh_docker_command(
    *,
    dsh_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    auth_env: Dict[str, str],
    prompt: str,
    container_name: str | None = None,
) -> List[str]:
    inner_command = build_dsh_command(
        dsh_bin,
        prompt=prompt,
        patch_file=str(_DSH_CONTAINER_HOME / DSH_PATCH_FILENAME),
    )
    extra_env = {
        "HOME": str(_DSH_CONTAINER_ROOT),
        **_dsh_isolation_env(str(_DSH_CONTAINER_HOME), "danger-full-access"),
    }
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(DSH_DOCKER_ENV_WHITELIST),
        auth_env=auth_env,
        container_name=container_name,
        extra_env=extra_env,
    )


async def run_dsh_process_in_docker(
    *,
    dsh_bin: str,
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
    api_key_env: str | None = None,
    base_url: str | None = None,
    thinking: str = "default",
    base_env: Dict[str, str] | None = None,
) -> ProcessResult:
    _require_env_auth(auth_mode)
    host_root = workspace / ".runner" / "dsh"
    write_dsh_config(
        host_root / "home",
        session_root=str(_DSH_CONTAINER_SESSIONS),
        provider=provider,
        model=model,
        api_key_env=api_key_env,
        base_url=base_url,
        thinking=thinking,
    )
    (host_root / "sessions").mkdir(parents=True, exist_ok=True)
    auth_env = dict(base_env) if base_env is not None else {}
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_dsh_docker_command(
        dsh_bin=dsh_bin,
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        auth_env=auth_env,
        prompt=prompt,
        container_name=container_name,
    )
    result = await run_cli_process(
        command,
        cwd=workspace,
        # dsh takes its task on the command line; nothing is read from stdin.
        prompt="",
        env=auth_env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
    )
    kill_container_on_timeout(result, docker_bin, container_name)
    return result


def _option_text(options: Mapping[str, object], name: str) -> str | None:
    value = options.get(name)
    text = str(value) if value is not None else ""
    return text or None


class DshAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="dsh",
        label="DeepSeek Harness",
        description="DeepSeek's plugin-composed coding harness (dsh)",
        protocol="multi",
        bin="dsh",
        docker_image="starbench-dsh:latest",
        docker_env_whitelist=tuple(DSH_DOCKER_ENV_WHITELIST),
        credential_env_keys=(),
        judge_sensitive_env=DSH_JUDGE_SENSITIVE_ENV,
        default_executor_backend="local",
        # Four native kinds ride dsh's pi-ai twin; openai-compatible rides the
        # native DeepSeek adapter, whose chat-completions route takes a
        # bring-your-own baseURL (DeepSeek's own API is exactly that route).
        provider_filter=ProviderFilter(
            kinds=("anthropic", "openai", "google", "xai", "openai-compatible")
        ),
        injection=InjectionChannel(kind="dsh_gateway"),
        # Both routes read the effort from the settings document, not a flag —
        # a real switch, not a prompt request. Only the levels every supported
        # route accepts are declared (see the module docstring).
        thinking_channel="native_config",
        thinking_efforts=("default", "off", "high", "max"),
        options=(
            RuntimeOption(name="provider", type="string", role="both", surface="wiring"),
            RuntimeOption(name="base_url", type="string", role="both", surface="wiring"),
            RuntimeOption(name="api_key_env", type="string", role="both", surface="wiring"),
        ),
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
        stdout_path = logs / "dsh_stdout.log"
        if ctx.executor_backend == "docker":
            session_root = paths["workspace"] / ".runner" / "dsh" / "sessions"
            result = await run_dsh_process_in_docker(
                dsh_bin="dsh",
                docker_bin=ctx.docker_bin,
                docker_image=ctx.docker_image,
                workspace=paths["workspace"],
                prompt=prompt,
                stdout_path=stdout_path,
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                auth_mode=ctx.auth_mode,
                provider=_option_text(ctx.options, "provider"),
                model=ctx.model,
                api_key_env=_option_text(ctx.options, "api_key_env"),
                base_url=_option_text(ctx.options, "base_url"),
                thinking=ctx.thinking_effort,
                base_env=ctx.base_env,
            )
        else:
            session_root = logs / "dsh_sessions"
            patch_path = write_dsh_config(
                paths["agent_home"] / "dsh_executor",
                session_root=str(session_root),
                provider=_option_text(ctx.options, "provider"),
                model=ctx.model,
                api_key_env=_option_text(ctx.options, "api_key_env"),
                base_url=_option_text(ctx.options, "base_url"),
                thinking=ctx.thinking_effort,
            )
            command = build_dsh_command(
                ctx.bins["dsh"], prompt=prompt, patch_file=str(patch_path)
            )
            env = prepare_dsh_env(
                paths["agent_home"] / "dsh_executor",
                ctx.auth_mode,
                permission_mode="workspace-write",
                base_env=ctx.base_env,
            )
            result = await run_cli_process(
                command,
                cwd=paths["workspace"],
                prompt="",
                env=env,
                stdout_path=stdout_path,
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )

        def _post() -> None:
            # Compat pass first: extraction raises on an empty turn and
            # finalize_success stops at the first exception, so a failed run
            # still keeps a readable trace (same order as pi's _post).
            normalize_dsh_events(session_root, logs / "events.jsonl")
            write_dsh_final_output(stdout_path, logs / "final.md")

        return finalize_success(
            result, stderr_path=logs / "stderr.log", label="DeepSeek Harness", work=_post
        )

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
        dsh_home = judge_home_base.parent / f"{judge_home_base.name}_dsh"
        session_root = events_path.parent / f"{events_path.stem}_dsh_sessions"
        stdout_path = events_path.parent / f"{events_path.stem}_dsh_stdout.log"
        patch_path = write_dsh_config(
            dsh_home,
            session_root=str(session_root),
            provider=_option_text(ctx.options, "provider"),
            model=model,
            api_key_env=_option_text(ctx.options, "api_key_env"),
            base_url=_option_text(ctx.options, "base_url"),
            thinking=ctx.thinking_effort,
        )
        command = build_dsh_command(ctx.bins["dsh"], prompt=prompt, patch_file=str(patch_path))
        env = prepare_dsh_env(
            dsh_home,
            ctx.auth_mode,
            # The judge reads evidence; it never needs to write one.
            permission_mode="read-only",
            base_env=ctx.base_env,
        )
        result = await run_cli_process(
            command,
            cwd=judge_workspace,
            prompt="",
            env=env,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )

        def _post() -> None:
            # Compat pass first (see run_executor): a judge turn that produced
            # no extractable JSON still leaves its trace behind.
            normalize_dsh_events(session_root, events_path)
            write_dsh_final_output(stdout_path, judge_final_path, output_schema=schema_path)

        return finalize_success(
            result, stderr_path=stderr_path, label="DeepSeek Harness", work=_post
        )
