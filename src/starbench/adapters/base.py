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

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Mapping, Tuple

from ..execution.process import mark_failed
from ..runner.models import ProcessResult, TaskRunSpec


OPTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class RuntimeOption:
    """One runtime-specific knob, declared by the adapter that owns it.

    ``surface`` constrains the GUI only: "user" knobs are auto-rendered as
    form controls; "wiring" knobs are transport values the console computes
    from the selected AI provider and never renders. CLI/plan input treats
    both alike (a standalone CLI user has no console to fill wiring for
    them). ``default=None`` means "not set": the knob is omitted and the
    runtime CLI keeps its own default behaviour.
    """

    name: str
    type: str  # "integer" | "string" | "boolean" | "enum"
    role: str = "executor"  # "executor" | "evaluator" | "both"
    surface: str = "user"  # "user" | "wiring"
    label: str = ""
    help: str = ""
    default: object = None
    choices: Tuple[str, ...] = ()


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


def _describe_options(options) -> str:
    return ", ".join(f"{o.name} ({o.type})" for o in options)


def resolve_runtime_options(
    adapter: "RuntimeAdapter", role: str, raw: Mapping[str, object]
) -> Dict[str, object]:
    """Validate and coerce one role's option box against the adapter's declarations.

    The single implementation both transports share: CLI ``--<role>-option``
    pairs and run_plan v2 boxes funnel through here, so the two entries cannot
    drift. Raises ValueError with the messages the design spec fixes verbatim.
    """
    agent_id = adapter.info.id
    declared = {o.name: o for o in adapter.info.options if o.role in (role, "both")}
    resolved: Dict[str, object] = {}
    for key, value in dict(raw).items():
        option = declared.get(key)
        if option is None:
            available = (
                f"its declared {role}-side options: {_describe_options(declared.values())}"
                if declared
                else f"it declares no {role}-side options"
            )
            raise ValueError(f'{agent_id} has no option named "{key}" ({available}).')
        resolved[key] = _coerce_option(agent_id, option, value)
    for option in declared.values():
        if option.name not in resolved and option.default is not None:
            resolved[option.name] = option.default
    return resolved


def _coerce_option(agent_id: str, option: "RuntimeOption", value: object) -> object:
    if option.type == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(
                f'{agent_id} option {option.name} expects an integer, got "{value}".'
            )
        try:
            return int(value)
        except ValueError:
            raise ValueError(
                f'{agent_id} option {option.name} expects an integer, got "{value}".'
            )
    if option.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(
            f'{agent_id} option {option.name} expects true or false, got "{value}".'
        )
    if option.type == "enum":
        text = str(value)
        if text not in option.choices:
            raise ValueError(
                f'{agent_id} option {option.name} must be one of '
                f'{", ".join(option.choices)}; got "{value}".'
            )
        return text
    return str(value)


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
    # The effort levels this runtime actually accepts ("default" = leave the
    # CLI's default alone; legacy inputs may still spell it "none"). Native
    # runtimes declare their CLI's real level set; prompt runtimes get the
    # three instruction tiers. The orchestrator rejects a level outside this
    # set instead of quietly passing it on.
    thinking_efforts: Tuple[str, ...] = ("default", "low", "medium", "high")
    # Whether the runner can actually enforce the run-level --web-search
    # override for this runtime (Claude Code's tool allowlist, Codex's
    # --search flag). Runtimes without an enforcement hook leave web access
    # to their own tooling; planning warns instead of pretending.
    enforces_web_search: bool = False
    # Runtime-specific knobs (see RuntimeOption). Empty for runtimes with none.
    options: Tuple["RuntimeOption", ...] = ()

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
