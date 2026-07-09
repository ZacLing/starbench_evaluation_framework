"""Canonical API shapes shared by the console backend and its TypeScript client.

This module is the single definition of the core ``/api`` response/request
shapes. ``scripts/gen_api_types.py`` renders it into
``gui-frontend/src/lib/api-types.ts`` (committed, "GENERATED — do not edit"),
and ``lib/api.ts`` re-exports those generated types — so the front and back
ends cannot drift on a field name or nullability.

Scope: the shapes P2 touches (agents + experiment planning + their providers).
Other routes still type themselves by hand in ``api.ts``; migrate them here when
you next touch them.

Invariants:
- Import-safe on Python 3.9 (no ``typing.NotRequired``): optional fields use the
  base + ``total=False`` inheritance pattern so ``__optional_keys__`` is right.
- Mirror the wire JSON exactly — a value that is ``string | null`` on the wire is
  ``Optional[str]`` here; an absent-or-value field is an optional key.

改什么来这里: add or change a core API field, then run ``make gen-types``.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# Enumerations (rendered as TS string-literal unions)
# ---------------------------------------------------------------------------

ProviderKind = Literal["anthropic", "openai", "google", "xai", "openai-compatible"]
RuntimeProtocol = Literal["openai", "anthropic", "gemini", "xai", "none"]
AuthKind = Literal["api_key", "cli_login"]
ModelsSource = Literal["api", "catalog", "cli_cache"]
CliAuthStatusKind = Literal["ok", "api_key", "warn", "fail", "unknown"]
PackageManager = Literal["npm"]
AgentInstallStatusKind = Literal["installed", "failed"]
# How --thinking-effort reaches a runtime: a real reasoning switch on the CLI
# itself, or a prompt-level instruction.
ThinkingChannel = Literal["native_config", "prompt"]
# Run-level web-search override; "task" follows each task package's flag.
WebSearchMode = Literal["task", "allow", "deny"]


# ---------------------------------------------------------------------------
# Runtimes (/api/agents)
# ---------------------------------------------------------------------------

class RuntimeCli(TypedDict):
    bin: str
    present: bool
    path: Optional[str]


class AgentPackage(TypedDict):
    manager: PackageManager
    name: str
    install_command: List[str]
    update_command: List[str]
    docs_url: str


class AgentRuntimeStatus(TypedDict):
    id: str
    bin: str
    present: bool
    path: Optional[str]
    version: Optional[str]
    version_output: Optional[str]
    version_error: Optional[str]
    package: Optional[AgentPackage]
    latest_version: Optional[str]
    latest_checked_at: Optional[str]
    latest_error: Optional[str]
    update_available: Optional[bool]
    installable: bool


class AgentStatusPayload(TypedDict):
    statuses: Dict[str, AgentRuntimeStatus]


class AgentInstallResult(TypedDict):
    id: str
    command: List[str]
    status: AgentInstallStatusKind
    exit_code: Optional[int]
    stdout_tail: str
    stderr_tail: str


class ProviderFilter(TypedDict):
    """Wire-protocol compatibility matrix a runtime uses to filter providers."""

    kinds: List[str]
    accepts_anthropic_endpoint: bool
    accepts_gemini_endpoint: bool


class BuiltinRuntime(TypedDict):
    id: str
    label: str
    note: str
    protocol: RuntimeProtocol
    docker_capable: bool
    docker_image: str
    builtin: Literal[True]
    cli: RuntimeCli
    provider_filter: ProviderFilter
    thinking_channel: ThinkingChannel
    # The effort levels this runtime's CLI actually accepts ("none" first).
    thinking_efforts: List[str]


class _CustomRuntimeBase(TypedDict):
    id: str
    spec_id: str
    builtin: Literal[False]
    source_path: str
    error: Optional[str]


class CustomRuntime(_CustomRuntimeBase, total=False):
    label: str
    description: str
    icon: str
    protocol: RuntimeProtocol
    provider_filter: ProviderFilter
    base_url_env: str
    api_key_env: str
    command: str
    args: List[str]
    judge_args: List[str]
    judge_args_inherited: bool
    model_flag: Optional[str]
    prompt_via: str
    prompt_flag: str
    parser: str
    env: Dict[str, str]
    docker_image: Optional[str]
    docker_env_passthrough: List[str]
    docker_capable: bool
    thinking_channel: ThinkingChannel
    thinking_efforts: List[str]
    cli: RuntimeCli


class AgentsPayload(TypedDict):
    runtimes_dir: str
    builtin: List[BuiltinRuntime]
    custom: List[CustomRuntime]


# ---------------------------------------------------------------------------
# AI providers (/api/providers)
# ---------------------------------------------------------------------------

class _AiProviderBase(TypedDict):
    id: str
    name: str
    kind: ProviderKind
    auth: AuthKind
    base_url: str
    api_key_env: str
    models: List[str]
    models_fetched_at: Optional[str]
    models_source: Optional[ModelsSource]
    agent: str
    key_present: bool


class CliAuthStatus(TypedDict):
    agent: str
    label: str
    cli_present: bool
    cli_path: Optional[str]
    status: CliAuthStatusKind
    message: str


class AiProvider(_AiProviderBase, total=False):
    anthropic_base_url: Optional[str]
    gemini_base_url: Optional[str]
    cli_status: CliAuthStatus


class _ProvidersPayloadBase(TypedDict):
    providers: List[AiProvider]


class ProvidersPayload(_ProvidersPayloadBase, total=False):
    persisted: bool


class ProviderCliStatusPayload(TypedDict):
    statuses: Dict[str, CliAuthStatus]


# ---------------------------------------------------------------------------
# Executor skills (/api/skills)
# ---------------------------------------------------------------------------

class Skill(TypedDict):
    id: str
    description: str
    source_path: str
    file_count: int
    size_bytes: int
    sha256: Optional[str]
    leakage_level: Optional[str]
    groups: List[str]


class _SkillsPayloadBase(TypedDict):
    root: str
    skills: List[Skill]
    # Group name -> the skill ids it bundles.
    groups: Dict[str, List[str]]


class SkillsPayload(_SkillsPayloadBase, total=False):
    # Present only when the library on disk could not be read.
    error: str


# ---------------------------------------------------------------------------
# Instruction ablation (task detail + experiment plan)
# ---------------------------------------------------------------------------

class HumanReferenceStepDetail(TypedDict):
    """One public expert step from a task's ``human_reference.json``.

    PRIVACY RED LINE: only these three public fields ever cross the wire. The
    step's ``reasoning`` (the private expert trace) is loaded by the runner for
    metadata validation but MUST NEVER appear in any API response. Do not add a
    ``reasoning`` key here — ``gui.data.read_human_reference_steps`` is the single
    reasoning-free reader and the test suite asserts the text never leaks.
    """

    step_id: str
    step_type: str
    instruction: str


class RigorDetail(TypedDict):
    """One public rigor requirement from a task's ``rigors.json``.

    Every field here is executor-facing content the runner injects verbatim into
    the prompt (a restated rubric-level requirement), so unlike
    ``HumanReferenceStepDetail`` there is no private field to withhold —
    ``gui.data.read_rigors`` returns all three.
    """

    id: str
    rubric_id: str
    requirement: str


class ExecutionEstimate(TypedDict):
    """How many executor variants an instruction sweep expands into before launch.

    ``per_contender`` = Σ per-task variants × repeat; ``total`` = that × the
    number of contenders. ``note`` is a plain-language summary of the variant
    construction for the Review billing.
    """

    per_contender: int
    total: int
    mode: str
    note: str


# ---------------------------------------------------------------------------
# Run live view (/api/runs/<id>/live)
# ---------------------------------------------------------------------------

RunStatus = Literal["complete", "running", "interrupted"]
# Per-task lane phase, derived from progress events + on-disk artifacts:
# pending → executing → judging → done, with failed for executor failure/timeout.
RunLiveState = Literal["pending", "executing", "judging", "done", "failed"]
# Where a lane's executor_seconds came from: "measured" is the recorded
# duration on disk; "elapsed" is wall-clock since executor start (still running).
ExecutorSecondsSource = Literal["measured", "elapsed"]


class RunLiveEvent(TypedDict):
    """One summarized task event: its type plus a one-line excerpt.

    Deliberately tiny — the raw event payload (which can carry huge tool
    outputs) never crosses this boundary; ``gui.data._live_event_summary`` is
    the single reducer.
    """

    type: str
    summary: str


class RunLiveTask(TypedDict):
    run_task_id: str
    state: RunLiveState
    executor_status: Optional[str]
    executor_seconds: Optional[float]
    executor_seconds_source: Optional[ExecutorSecondsSource]


class RunLiveCurrent(TypedDict):
    """The most recently started, still-executing task and its event tail."""

    run_task_id: str
    task_id: Optional[str]
    started_at: Optional[str]
    elapsed_seconds: Optional[float]
    events: List[RunLiveEvent]


class RunLiveEta(TypedDict):
    """Remaining-time *estimate*: average measured executor duration × remaining.

    ``estimated_remaining_seconds`` stays ``None`` until at least two executor
    durations exist — with fewer samples the console says "estimating" instead
    of inventing a number.
    """

    estimated_remaining_seconds: Optional[float]
    average_executor_seconds: Optional[float]
    completed_sample_count: int
    remaining_task_count: int


class RunLivePayload(TypedDict):
    run_id: str
    status: RunStatus
    generated_at: str
    tasks: List[RunLiveTask]
    current: Optional[RunLiveCurrent]
    eta: RunLiveEta


# ---------------------------------------------------------------------------
# Trace replay + deliverables (task run detail, R2)
# ---------------------------------------------------------------------------

# Normalized timeline entry kinds. "other" is the honest-degradation bucket:
# anything the normalizer does not recognize keeps its raw JSON as the body.
TraceEntryType = Literal[
    "reasoning", "command", "file_change", "message", "lifecycle", "other"
]


class TraceEntry(TypedDict):
    """One events.jsonl line, normalized. Index = physical line position, so
    anchors stay stable and line up with the raw-events pagination.

    ``seconds_offset`` is filled only when events carry parseable timestamps
    (most runtimes emit none — absent is ``null``, never estimated).
    ``truncated`` marks a body cut at the per-entry cap.
    """

    index: int
    type: TraceEntryType
    title: str
    body: str
    seconds_offset: Optional[float]
    truncated: bool


class TaskTracePayload(TypedDict):
    run_id: str
    run_task_id: str
    entries: List[TraceEntry]
    offset: int
    total: int
    next_offset: Optional[int]
    # False = logs/events.jsonl does not exist (run captured no event stream);
    # the UI must say so instead of showing an empty timeline.
    has_events: bool


class ArtifactPayload(TypedDict):
    """One delivered file under workspace/outputs/.

    ``content`` is null for binaries (NUL byte in the head) and for files over
    the size cap; ``truncated`` marks the over-cap case so the UI can say
    "too large to render" instead of silently showing nothing.
    """

    path: str
    size_bytes: int
    is_binary: bool
    truncated: bool
    content: Optional[str]


class VariantSibling(TypedDict):
    """A task run in the same run sharing this task's base task id (an
    ablation variant or a repeat). Derived from each sibling's recorded
    task_summary/manifest identity, never by parsing directory names."""

    run_task_id: str
    instruction_variant: Optional[str]
    evaluated: bool


class OutputsListingEntry(TypedDict, total=False):
    path: str
    kind: str
    size_bytes: Optional[int]


class OutputsListing(TypedDict):
    """Fallback Deliverables tree for runs without artifact_manifest.json:
    a direct listing of workspace/outputs/ taken now (no hashes)."""

    outputs_dir: str
    file_count: int
    entries: List[OutputsListingEntry]
    truncated: bool


# ---------------------------------------------------------------------------
# Coverage matrix (/api/coverage)
# ---------------------------------------------------------------------------

class CoverageRunRef(TypedDict):
    """Drill-down anchor: one task run contributing to a coverage cell."""

    run_id: str
    run_task_id: str


class CoverageCell(TypedDict):
    """One (task, executor config) intersection, aggregated over all variants
    and repeats on disk. HSW semantics: ``passed > 0`` means some configuration
    solved the task — the task is breached, which is bad news for the bench.

    ``last_tested`` is a timestamp recorded on disk (executor ``ended_at``,
    else the summary/status file's mtime); absent evidence is ``null``, never
    an estimate.
    """

    column_key: str
    total: int
    judged: int
    passed: int
    last_tested: Optional[str]
    recent_refs: List[CoverageRunRef]


class CoverageColumn(TypedDict):
    """An executor configuration in the matrix: a roster-declared contender,
    a config observed in run configs on disk (``executor_agent`` ×
    ``executor_model``), or both. ``agent`` degrades to "unknown" when a run's
    config is missing or unreadable. ``rostered`` is True when the active
    profile's roster names this column: a rostered column with zero cells is a
    hole in the coverage denominator; an unrostered column ran but is not part
    of the declared measurement set."""

    key: str
    agent: str
    model: Optional[str]
    run_count: int
    rostered: bool


class CoverageRow(TypedDict):
    """One task: library ∪ observed. A library task never run has zero cells —
    the visible gap is the point. ``in_library`` is False for tasks that were
    run but no longer exist in the registered task directories."""

    task_id: str
    in_library: bool
    breached: bool
    tested_columns: int
    cells: List[CoverageCell]


class CoverageProfile(TypedDict):
    """The profile whose roster defines this matrix's denominator. ``rev`` pins
    the revision read from disk. Null on the payload when no profile carries a
    roster — the matrix then falls back to pure disk induction."""

    id: str
    name: str
    rev: int


class CoveragePayload(TypedDict):
    columns: List[CoverageColumn]
    rows: List[CoverageRow]
    runs_scanned: int
    # The roster source, or null when no profile on disk declares a roster and
    # the columns are derived purely from runs.
    profile: Optional[CoverageProfile]
    # When this payload was assembled (describes the assembly, not the runs).
    generated_at: str


# ---------------------------------------------------------------------------
# Profile snapshot (run detail): the measurement contract a run was launched
# under. Mirrors schemas/starbench/v1/profile_snapshot.schema.json — the file
# system copy (<run>/profile_snapshot.json) is the truth; absent file = null.
# ---------------------------------------------------------------------------

class ProfileSnapshotProfile(TypedDict):
    """Identity of the profile at launch; ``rev`` pins its revision then."""

    id: str
    rev: int
    name: str


class _ProfileSnapshotContenderBase(TypedDict):
    agent: str
    model: str


class ProfileSnapshotContender(_ProfileSnapshotContenderBase, total=False):
    """A contender/roster entry, self-contained: provider references resolve
    to inline values. ``api_key_env`` is the NAME of an environment variable —
    the contract has no field for secret material, ever."""

    label: str
    thinking_effort: str
    auth_mode: str
    provider_id: str
    base_url: str
    api_key_env: str


class _ProfileSnapshotInstrumentBase(TypedDict):
    evaluator_agent: str
    evaluator_model: str
    evaluator_auth_mode: str
    judge_mode: str


class ProfileSnapshotInstrument(_ProfileSnapshotInstrumentBase, total=False):
    evaluator_timeout_seconds: int


class _ProfileSnapshotExecutionBase(TypedDict):
    seed: int
    batch_size: int
    repeat: int
    executor_backend: str
    executor_auth_mode: str


class ProfileSnapshotExecution(_ProfileSnapshotExecutionBase, total=False):
    max_evaluator_parallel: int
    web_search: WebSearchMode
    claude_max_turns: int


class ProfileSnapshotTaskSet(TypedDict):
    """The task list as resolved at launch (selectors expanded)."""

    tasks_dir: str
    task_ids: List[str]


class _ProfileSnapshotBase(TypedDict):
    schema_version: int
    captured_at: str
    profile: ProfileSnapshotProfile
    contender: ProfileSnapshotContender
    roster: List[ProfileSnapshotContender]
    instrument: ProfileSnapshotInstrument
    execution: ProfileSnapshotExecution
    task_set: ProfileSnapshotTaskSet


class ProfileSnapshot(_ProfileSnapshotBase, total=False):
    """Every value is the EFFECTIVE launch configuration; ``profile`` cites the
    comparison baseline. ``modified: true`` marks an ad-hoc launch that
    deviated from that baseline, and ``modified_fields`` names the deviating
    dimensions ("roster", "task_set", or shared key names like "repeat").
    Both keys are absent on launches that matched the profile — and on every
    snapshot written before the deviation record existed."""

    modified: bool
    modified_fields: List[str]


# ---------------------------------------------------------------------------
# Run listing (/api/runs): one row per run directory (gui.data.run_overview);
# the run detail payload extends this shape.
# ---------------------------------------------------------------------------

class RunProfileRef(TypedDict):
    """Profile marker on a run row, soft-read from the run's
    profile_snapshot.json: which profile (at which rev) the run cites, and
    whether the launch deviated from it (``modified`` = an ad-hoc test).
    A missing or unreadable snapshot yields null on the row, never an error."""

    id: str
    rev: int
    modified: bool


class RunRow(TypedDict):
    run_id: str
    status: RunStatus
    task_count: int
    # success / failed / timeout / pending counters.
    executor_stats: Dict[str, int]
    # Judge tallies keyed by mode ("single" / "parallel").
    judge_passes: Dict[str, int]
    judge_totals: Dict[str, int]
    judge_mode: Optional[str]
    executor_agent: Optional[str]
    executor_model: Optional[str]
    evaluator_agent: Optional[str]
    evaluator_model: Optional[str]
    executor_backend: Optional[str]
    seed: Optional[int]
    instruction_mode: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    has_ablation: bool
    # The measurement contract this run cites, or null for bare runs (and for
    # unreadable snapshots — soft failure).
    profile: Optional[RunProfileRef]


# ---------------------------------------------------------------------------
# Experiments (/api/experiments)
# ---------------------------------------------------------------------------

class _ExperimentPlanItemBase(TypedDict):
    label: str
    agent: str
    model: str
    run_id: str
    backend: str
    backend_downgraded: bool
    # Advisory notices (e.g. a contender var also read by the judge, now safe
    # because executor and judge run under isolated env scopes). Never fatal.
    warnings: List[str]
    argv: List[str]


class ExperimentPlanItem(_ExperimentPlanItemBase, total=False):
    docker_image: str
    # Final, group-expanded skill ids injected into every contender (shared).
    executor_skills: List[str]
    # Auth mode the launch will use; the review-step preflight passes it
    # through so credential checks match reality.
    executor_auth_mode: str


class _ContenderBase(TypedDict):
    """A contender in the reference shape: a runtime pointing at a provider.

    The backend resolves ``provider_id`` against the AI providers and computes
    the concrete auth/gateway/env at plan time (see ``gui.injection``).
    """

    agent: str
    provider_id: str
    model: str


class Contender(_ContenderBase, total=False):
    label: str
    thinking_effort: str


# Ordered list the code generator renders (aliases first, then interfaces in
# dependency order). Names not listed here are internal helpers.
GENERATED_TYPES = [
    "ProviderKind",
    "RuntimeProtocol",
    "AuthKind",
    "ModelsSource",
    "CliAuthStatusKind",
    "PackageManager",
    "AgentInstallStatusKind",
    "ThinkingChannel",
    "WebSearchMode",
    "RuntimeCli",
    "AgentPackage",
    "AgentRuntimeStatus",
    "AgentStatusPayload",
    "AgentInstallResult",
    "ProviderFilter",
    "BuiltinRuntime",
    "CustomRuntime",
    "AgentsPayload",
    "CliAuthStatus",
    "AiProvider",
    "ProvidersPayload",
    "ProviderCliStatusPayload",
    "Skill",
    "SkillsPayload",
    "HumanReferenceStepDetail",
    "RigorDetail",
    "ExecutionEstimate",
    "RunStatus",
    "RunLiveState",
    "ExecutorSecondsSource",
    "RunLiveEvent",
    "RunLiveTask",
    "RunLiveCurrent",
    "RunLiveEta",
    "RunLivePayload",
    "TraceEntryType",
    "TraceEntry",
    "TaskTracePayload",
    "ArtifactPayload",
    "VariantSibling",
    "OutputsListingEntry",
    "OutputsListing",
    "CoverageRunRef",
    "CoverageCell",
    "CoverageColumn",
    "CoverageRow",
    "CoverageProfile",
    "CoveragePayload",
    "ProfileSnapshotProfile",
    "ProfileSnapshotContender",
    "ProfileSnapshotInstrument",
    "ProfileSnapshotExecution",
    "ProfileSnapshotTaskSet",
    "ProfileSnapshot",
    "RunProfileRef",
    "RunRow",
    "ExperimentPlanItem",
    "Contender",
]
