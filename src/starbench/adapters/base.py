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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Tuple

from ..execution.process import mark_failed
from ..runner.models import ProcessResult, TaskRunSpec


@dataclass(frozen=True)
class ProviderFilter:
    """Which AI providers a runtime can drive, decided by wire protocol.

    Mirrors the frontend ``brand.tsx`` ``compatibleProviders`` switch exactly so
    the GUI can filter providers from this record instead of re-implementing the
    matrix: a provider matches when its ``kind`` is in ``kinds``, or when the
    runtime accepts a bring-your-own endpoint that the provider exposes
    (``anthropic_base_url`` / ``gemini_base_url``). Note ``codex`` is not simply
    "protocol openai": it accepts openai / openai-compatible but not xai, while
    ``opencode`` and custom openai runtimes do accept xai — the filter is stated
    per runtime, not derived from the protocol string.
    """

    kinds: Tuple[str, ...] = ()
    accepts_anthropic_endpoint: bool = False
    accepts_gemini_endpoint: bool = False


@dataclass(frozen=True)
class InjectionChannel:
    """How a (runtime, provider) pair is wired at launch.

    This is the single fact the backend needs to reproduce the logic that used
    to live in the frontend ``providerSettings()``. ``kind`` selects the channel:

    - ``codex_config``     provider overrides baked into the ``codex`` bin prefix
    - ``anthropic_env``    ANTHROPIC_BASE_URL / token env vars (Claude Code)
    - ``gemini_env``       GOOGLE_GEMINI_BASE_URL / key env vars (Gemini CLI)
    - ``opencode_gateway`` ``--opencode-provider/base-url/api-key-env`` flags
    - ``spec_env``         env vars named by a custom spec (``base_url_env`` etc.)
    - ``none``             no override channel at all (Grok Build)

    ``base_url_var`` / ``api_key_var`` name the env vars the env channels set;
    ``default_api_key_env`` is the fallback token source when the provider names
    no ``api_key_env`` of its own.
    """

    kind: str = "none"
    base_url_var: str = ""
    api_key_var: str = ""
    default_api_key_env: str = ""


def provider_filter_for_protocol(protocol: str) -> ProviderFilter:
    """Derive a custom runtime's provider filter from its declared protocol.

    Matches the custom-runtime branch of ``brand.tsx`` ``compatibleProviders``:
    an ``openai`` custom runtime accepts xai (unlike the built-in ``codex``).
    """
    if protocol == "openai":
        return ProviderFilter(kinds=("openai-compatible", "openai", "xai"))
    if protocol == "anthropic":
        return ProviderFilter(kinds=("anthropic",), accepts_anthropic_endpoint=True)
    if protocol == "gemini":
        return ProviderFilter(kinds=("google",), accepts_gemini_endpoint=True)
    return ProviderFilter()  # "none": the CLI uses its own login/config


@dataclass(frozen=True)
class RuntimeInfo:
    """Static facts about a runtime — the single source of truth.

    ``docker_env_whitelist``: env keys forwarded (by name) into the runtime's
    container. ``credential_env_keys``: env vars the preflight check treats as
    this runtime's API credentials. ``judge_sensitive_env``: env vars that, if a
    contender injects them, would reroute this runtime when it acts as judge.
    ``provider_filter``: which providers this runtime can drive (GUI reads it via
    ``/api/agents``). ``injection``: how a chosen provider is wired in at launch
    (the backend replaces the old frontend ``providerSettings()`` from it).
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
    provider_filter: ProviderFilter = field(default_factory=ProviderFilter)
    injection: InjectionChannel = field(default_factory=InjectionChannel)
    # How --thinking-effort reaches this runtime: "native_config" (a real
    # reasoning switch on the CLI itself — Claude's --effort, Codex's
    # model_reasoning_effort, OpenCode's --variant) or "prompt" (an instruction
    # appended to the prompt — a request, not a guarantee). Surfaced in the GUI
    # so nobody mistakes a prompt-level request for a native switch.
    thinking_channel: str = "prompt"

    @property
    def docker_capable(self) -> bool:
        return self.docker_image is not None


@dataclass(frozen=True)
class ExecutorContext:
    """Everything an adapter needs to run the executor side of a task.

    ``base_env`` is the environment the adapter builds its run env on top of —
    the executor's scoped base (clean ambient + executor-only overrides) computed
    by the orchestrator (see ``runner.env_scope``). Adapters use it instead of
    ``os.environ.copy()`` so a contender's injected endpoint/credentials never
    leak into the judge run. Standalone CLI runs pass the ambient environment,
    so behaviour is unchanged.
    """

    base_env: Dict[str, str]
    bins: Dict[str, str]
    docker_bin: str
    docker_image: str
    executor_backend: str
    auth_mode: str
    model: str | None
    thinking_effort: str
    claude_max_turns: int | None
    opencode_provider: str | None
    opencode_base_url: str | None
    opencode_api_key_env: str | None
    # Run-level web-search override: "task" defers to task.allow_web_search,
    # "allow"/"deny" force it for runtimes that enforce web access (Claude's
    # tool allowlist, Codex's --search). Runtimes without an enforcement hook
    # ignore it — their own tooling decides.
    web_search_mode: str = "task"


@dataclass(frozen=True)
class JudgeContext:
    """Everything an adapter needs to run the judge side of a task.

    ``base_env`` is the judge's scoped base env (clean ambient + judge-only
    overrides); see :class:`ExecutorContext` and ``runner.env_scope``.
    """

    base_env: Dict[str, str]
    bins: Dict[str, str]
    auth_mode: str
    model: str | None
    thinking_effort: str
    opencode_provider: str | None
    opencode_base_url: str | None
    opencode_api_key_env: str | None


def effective_web_search(mode: str, task_allow: bool) -> bool:
    """Resolve the run-level web-search override against the task's own flag."""
    if mode == "allow":
        return True
    if mode == "deny":
        return False
    return task_allow


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
