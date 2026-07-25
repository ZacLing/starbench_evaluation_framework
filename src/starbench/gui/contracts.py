"""Canonical API shapes shared by the console backend and its TypeScript client.

This module is the single definition of the core ``/api`` response/request
shapes. ``scripts/gen_api_types.py`` renders it into
``gui-frontend/src/lib/api-types.ts`` (committed, "GENERATED — do not edit"),
and ``lib/api.ts`` re-exports those generated types — so the front and back
ends cannot drift on a field name or nullability.

Scope: every JSON request and response crossing the Console ``/api`` boundary.
React-only view models remain local to their feature; wire fields never do.

Invariants:
- Import-safe on Python 3.9 (no ``typing.NotRequired``): optional fields use the
  base + ``total=False`` inheritance pattern so ``__optional_keys__`` is right.
- Mirror the wire JSON exactly — a value that is ``string | null`` on the wire is
  ``Optional[str]`` here; an absent-or-value field is an optional key.

改什么来这里: add or change a core API field, then run ``make gen-types``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

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
TaskRunOutcome = Literal[
    "agent_pass",
    "agent_fail",
    "inconclusive_judge",
    "inconclusive_executor",
    "invalid_task",
]
HswCellState = Literal["breached", "defended", "inconclusive", "untested"]
PreflightStatus = Literal["ok", "warn", "fail"]


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


class RuntimeOptionRow(TypedDict):
    """One runtime-specific knob declaration, serialized for /api/agents.

    Mirrors adapters.base.RuntimeOption verbatim so the frontend can
    auto-render controls: ``surface`` "user" knobs become form controls while
    "wiring" knobs are provider-derived transport values the console never
    renders. ``default`` is null when the knob is unset (the runtime CLI keeps
    its own default); ``choices`` is non-empty only for ``type`` "enum".
    """

    name: str
    type: str
    role: str
    surface: str
    label: str
    help: str
    default: Optional[Union[int, str, bool]]
    choices: List[str]


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
    # Whether the runner can enforce the run-level web-search override for this
    # runtime (registry fact: RuntimeInfo.enforces_web_search).
    enforces_web_search: bool
    # Runtime-specific knobs (adapters.base.RuntimeOption), serialized for the
    # frontend to auto-render. Empty for runtimes that declare none.
    options: List[RuntimeOptionRow]


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
    enforces_web_search: bool
    cli: RuntimeCli
    options: List[RuntimeOptionRow]


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


class ModelReasoning(TypedDict):
    """One model's published reasoning-effort table (from the runtime's own
    model catalog, e.g. Codex's models_cache.json). Levels are tier names in
    the CLI's own vocabulary; ``default_level`` is what runs when the launch
    says "default"."""

    levels: List[str]
    default_level: Optional[str]


class AiProvider(_AiProviderBase, total=False):
    anthropic_base_url: Optional[str]
    gemini_base_url: Optional[str]
    cli_status: CliAuthStatus
    # Per-model reasoning tables, present only when the provider's runtime
    # publishes them (currently: Codex CLI-login via its local models cache).
    model_reasoning: Dict[str, ModelReasoning]


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

    ``state`` is the backend-owned HSW interpretation: breached when any valid
    sample passes, defended when at least one valid sample exists and none pass,
    inconclusive when attempts exist but none are scoreable, and untested for a
    synthesized empty matrix intersection. ``inconclusive`` counts attempted
    measurements excluded from HSW scoring.
    ``last_tested`` is a timestamp recorded on disk (executor ``ended_at``,
    else the summary/status file's mtime); absent evidence is ``null``, never
    an estimate.
    """

    column_key: str
    state: HswCellState
    total: int
    judged: int
    passed: int
    inconclusive: int
    last_tested: Optional[str]
    recent_refs: List[CoverageRunRef]
    # Aggregates across every task-run sample in the cell. Rubric ratios come
    # from each run's own judge mode (passed/total rubrics); a task-run whose
    # judge produced no tallies contributes nothing — None means "no rubric
    # evidence", never a zero score. ``rubric_ratio_std`` is the population
    # standard deviation and needs >= 2 samples; ``duration_p95_seconds`` is
    # nearest-rank over executor durations. Executor status tallies partition
    # ``total`` (pending = no terminal status yet).
    rubric_samples: int
    rubric_ratio_mean: Optional[float]
    rubric_ratio_std: Optional[float]
    duration_mean_seconds: Optional[float]
    duration_p95_seconds: Optional[float]
    exec_success: int
    exec_failed: int
    exec_timeout: int
    exec_pending: int


class CoverageComboStats(TypedDict):
    """One contender column rolled up across all its cells: the combination
    panel, comparison table, and overview heatmap all read from here. Same
    honesty rules as ``CoverageCell``: None is absent evidence, never zero."""

    tasks_tested: int
    judged: int
    passed: int
    exec_pending: int
    rubric_samples: int
    rubric_ratio_mean: Optional[float]
    rubric_ratio_std: Optional[float]
    duration_p95_seconds: Optional[float]
    last_tested: Optional[str]


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
    stats: CoverageComboStats


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
# Task picker history (/api/tasklib/history)
# ---------------------------------------------------------------------------

class TaskHistoryConfig(TypedDict):
    """One observed launch configuration for a task. Counts come from task-run
    directories on disk; config fields are copied from ``run_config.json`` and
    may be null for older or partial runs."""

    executor_agent: Optional[str]
    executor_model: Optional[str]
    evaluator_agent: Optional[str]
    evaluator_model: Optional[str]
    judge_mode: Optional[str]
    executor_backend: Optional[str]
    instruction_mode: Optional[str]
    repeat: Optional[int]
    seed: Optional[int]
    thinking_effort: Optional[str]
    run_count: int
    task_run_count: int
    last_tested: Optional[str]


class TaskHistory(TypedDict):
    """Execution history for one task id in the selected task folder."""

    task_id: str
    run_count: int
    task_run_count: int
    last_tested: Optional[str]
    configs: List[TaskHistoryConfig]


class TaskHistoryPayload(TypedDict):
    tasks: Dict[str, TaskHistory]


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
    # Runtime-specific executor knobs (e.g. max_turns); names enforced at parse
    # time. Values are scalars; any credential is an env-var NAME, never a value.
    options: Dict[str, Union[int, str, bool]]


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
    # Judge-side option box (evaluator knobs plus gateway wiring) in effect for
    # this run; names enforced at parse time, values are scalars/env-var NAMES.
    evaluator_options: Dict[str, Union[int, str, bool]]


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
    judge_inconclusive: Dict[str, int]
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
    # The typed launch contract (run_plan.schema.json) this run starts from;
    # null when the launch rides the argv transport (free-form extra_args).
    run_plan: Optional[Dict[str, Any]]
    # Final, group-expanded skill ids injected into every contender (shared).
    executor_skills: List[str]
    # Auth mode the launch will use; the review-step preflight passes it
    # through so credential checks match reality.
    executor_auth_mode: str
    evaluator_agent: str
    evaluator_auth_mode: str
    executor_bin: str
    evaluator_bin: str
    # Role option boxes surfaced to the review step (wiring api_key_env NAMES
    # plus any user knobs); the boxes never carry key values.
    executor_options: Dict[str, Union[int, str, bool]]
    evaluator_options: Dict[str, Union[int, str, bool]]
    executor_credential_env_keys: List[str]
    evaluator_credential_env_keys: List[str]


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
    # Runtime-specific executor knobs the form posts (user knobs, e.g.
    # max_turns); gateway wiring is merged on top at plan time.
    options: Dict[str, Union[int, str, bool]]


# ---------------------------------------------------------------------------
# Remaining Console wire DTOs
# ---------------------------------------------------------------------------

class _ExecutorStatsBase(TypedDict):
    success: int
    failed: int
    timeout: int


class ExecutorStats(_ExecutorStatsBase, total=False):
    skipped: int
    pending: int


class JudgeCell(TypedDict):
    outcome: Optional[TaskRunOutcome]
    overall_pass: Optional[bool]
    passed_count: Optional[int]
    total_count: Optional[int]
    missing: int
    fail_fast_failures: int
    error: Optional[str]


class _RunOverviewBase(TypedDict):
    run_id: str
    status: RunStatus
    task_count: int
    executor_stats: ExecutorStats
    judge_passes: Dict[str, int]
    judge_totals: Dict[str, int]
    judge_inconclusive: Dict[str, int]
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


class RunOverview(_RunOverviewBase, total=False):
    profile: Optional[RunProfileRef]
    # Launch batch this run was started with (runs launched together share
    # it); null for bare/CLI runs.
    batch: Optional[str]


class TaskRow(TypedDict):
    run_task_id: str
    task_id: Optional[str]
    instruction_variant: Optional[str]
    executor_status: Optional[str]
    executor_duration_seconds: Optional[float]
    executor_timed_out: Optional[bool]
    judges: Dict[str, Optional[JudgeCell]]
    evaluated: bool


class ProgressTotals(TypedDict):
    executors: int
    evaluators: int


class ProgressSnapshot(TypedDict):
    totals: ProgressTotals
    executor_done: int
    evaluator_done: int
    executor_stats: ExecutorStats
    evaluator_stats: ExecutorStats
    active_executors: List[str]
    event_count: int


class AblationDelta(TypedDict):
    overall_pass_rate_delta: Optional[float]
    mean_rubric_pass_rate_delta: Optional[float]


class _AblationGroupBase(TypedDict):
    task_id: str
    judge_mode: str
    instruction_variant: str
    runs: int
    overall_pass_count: int
    overall_pass_rate: Optional[float]
    mean_rubric_pass_rate: Optional[float]


class AblationGroup(_AblationGroupBase, total=False):
    attempts: int
    inconclusive: int
    delta_vs_baseline: AblationDelta


class AblationPayload(TypedDict):
    groups: List[AblationGroup]


class RunDetail(RunOverview):
    config: Optional[Dict[str, Any]]
    tasks: List[TaskRow]
    progress: Optional[ProgressSnapshot]
    ablation: Optional[AblationPayload]


class RubricResult(TypedDict):
    rubric_id: str
    answer: Optional[bool]
    expected: bool
    passed: Optional[bool]
    fail_fast: bool
    evidence: str


class _JudgeAggregateBase(TypedDict):
    mode: str
    outcome: TaskRunOutcome
    overall_pass: Optional[bool]
    passed_count: int
    total_count: int
    missing: List[str]
    fail_fast_failures: List[str]
    results: List[RubricResult]


class JudgeAggregate(_JudgeAggregateBase, total=False):
    error: str


class ExecutorStatus(TypedDict, total=False):
    command: List[str]
    status: str
    exit_code: Optional[int]
    timed_out: bool
    started_at: str
    ended_at: str
    duration_seconds: float


class TraceTextItem(TypedDict, total=False):
    id: str
    text: Optional[str]


class TraceCommandExecution(TypedDict, total=False):
    id: str
    command: str
    status: str
    exit_code: Optional[int]
    aggregated_output: Optional[str]


class TraceFileChange(TypedDict, total=False):
    id: str
    status: str
    changes: Any


class TraceSummary(TypedDict):
    thread_id: Optional[str]
    event_type_counts: Dict[str, int]
    item_type_counts: Dict[str, int]
    reasoning_items: List[TraceTextItem]
    agent_messages: List[TraceTextItem]
    command_executions: List[TraceCommandExecution]
    file_changes: List[TraceFileChange]
    usage: Optional[Dict[str, Any]]


class _ArtifactManifestEntryBase(TypedDict):
    path: str
    kind: str


class ArtifactManifestEntry(_ArtifactManifestEntryBase, total=False):
    size_bytes: int
    sha256: str


class ArtifactManifest(TypedDict):
    outputs_dir: str
    file_count: int
    entries: List[ArtifactManifestEntry]


class JudgeTaskResult(TypedDict):
    aggregate: JudgeAggregate
    status: Optional[ExecutorStatus]


class TaskRunDetail(TypedDict):
    run_id: str
    run_task_id: str
    task_id: Optional[str]
    instruction_variant: Optional[str]
    executor: Optional[ExecutorStatus]
    executor_timing: Optional[Dict[str, Any]]
    judges: Dict[str, JudgeTaskResult]
    rubric_questions: Dict[str, str]
    trace_summary: Optional[TraceSummary]
    artifact_manifest: Optional[ArtifactManifest]
    outputs_listing: Optional[OutputsListing]
    variant_group: List[VariantSibling]
    final_message: Optional[str]
    stderr_tail: Optional[str]
    raw_event_count: int
    evaluated: bool


class TasksDirMeta(TypedDict):
    dir: str
    exists: bool


class Meta(TypedDict):
    runs_dir: str
    cwd: str
    runtimes_dir: str
    skills_dir: str
    tasks_dirs: List[TasksDirMeta]
    agents: List[str]
    judge_modes: List[str]
    auth_modes: List[str]
    backends: List[str]
    thinking_efforts: List[str]


class _TaskPackageBase(TypedDict):
    id: str
    dir_name: str
    name: str
    rubric_count: int
    timeout_seconds: Optional[int]
    allow_web_search: Optional[bool]
    rigor_count: int
    has_human_reference: bool


class TaskPackage(_TaskPackageBase, total=False):
    error: Optional[str]
    warning: Optional[str]


class TaskLibrary(TypedDict):
    dir: str
    exists: bool
    tasks: List[TaskPackage]


class TaskLibrariesPayload(TypedDict):
    libraries: List[TaskLibrary]


class DockerCleanup(TypedDict):
    matched: List[str]
    stopped: List[str]
    killed: List[str]
    errors: List[str]


class Launch(TypedDict):
    run_id: str
    state: Optional[str]
    argv: List[str]
    # Null until the process is actually spawned: prepared reservations and
    # failed launches surface through the same shape.
    pid: Optional[int]
    pgid: Optional[int]
    started_at: Optional[str]
    log_path: str
    running: bool
    exit_code: Optional[int]
    docker_cleanup: Optional[DockerCleanup]
    error: Optional[str]


class RunsPayload(TypedDict):
    runs: List[RunOverview]


class LaunchesPayload(TypedDict):
    launches: List[Launch]


class RawEventsPage(TypedDict):
    events: List[Dict[str, Any]]
    offset: int
    total: int
    next_offset: Optional[int]


class _LaunchPayloadBase(TypedDict):
    run_id: str
    tasks_dir: str
    tasks: List[str]
    executor_agent: str
    executor_model: str
    executor_backend: str
    docker_image: str
    auth_mode: str
    thinking_effort: str
    web_search: str
    evaluator_agent: str
    evaluator_model: str
    judge_mode: str
    evaluator_timeout_seconds: str
    seed: str
    batch_size: str
    repeat: str
    extra_args: str


class LaunchPayload(_LaunchPayloadBase, total=False):
    dry_run: bool


class LaunchPlanResponse(TypedDict):
    argv: List[str]
    dry_run: Literal[True]


class DirListingEntry(TypedDict):
    name: str
    path: str
    task_count: int
    is_task_package: bool


class DirListing(TypedDict):
    path: str
    parent: Optional[str]
    task_count: int
    dirs: List[DirListingEntry]


class ImportFile(TypedDict):
    path: str
    content_b64: str


class ImportReportTask(TypedDict, total=False):
    id: str
    name: str
    rubric_count: int


class _ImportReportBase(TypedDict):
    valid: bool
    errors: List[str]
    warnings: List[str]
    task: ImportReportTask
    file_count: int


class ImportReport(_ImportReportBase, total=False):
    installed_to: str


class TaskRubricDetail(TypedDict):
    id: str
    fail_fast: bool
    expected: bool
    question: str


class TaskPackageDetail(TypedDict):
    dir: str
    dir_name: str
    id: str
    name: str
    timeout_seconds: Optional[int]
    allow_web_search: Optional[bool]
    prompt: Optional[str]
    rubrics: List[TaskRubricDetail]
    human_reference_steps: List[HumanReferenceStepDetail]
    human_reference_step_count: int
    rigors: List[RigorDetail]
    rigor_count: int


class PreflightCheck(TypedDict):
    id: str
    label: str
    status: PreflightStatus
    hint: str


class PreflightPayload(TypedDict):
    checks: List[PreflightCheck]


class EnvSource(TypedDict, total=False):
    value: str
    from_env: str


class GatewayConfig(TypedDict, total=False):
    # Judge gateway wiring, keyed by the opencode adapter's declared option
    # names; folded into the evaluator option box at plan time.
    provider: str
    base_url: str
    api_key_env: str


class SharedConfig(TypedDict, total=False):
    evaluator_agent: str
    evaluator_model: str
    evaluator_auth_mode: str
    judge_mode: str
    evaluator_timeout_seconds: Optional[Union[int, str]]
    executor_backend: str
    docker_image: str
    executor_auth_mode: str
    seed: Optional[Union[int, str]]
    batch_size: Optional[Union[int, str]]
    repeat: Optional[Union[int, str]]
    max_evaluator_parallel: Optional[Union[int, str]]
    web_search_mode: str
    extra_args: str
    executor_skills: List[str]
    executor_skill_groups: List[str]
    instruction_mode: str
    instruction_steps: List[str]
    rigor_mode: str
    rigors: List[str]
    evaluator_provider_id: str
    evaluator_gateway: Optional[GatewayConfig]
    # Judge-side runtime option box the form posts directly (user knobs);
    # gateway wiring is merged on top of it at plan time.
    evaluator_options: Dict[str, Union[int, str, bool]]
    judge_env: Optional[Dict[str, EnvSource]]


class _RosterEntryBase(TypedDict):
    agent: str


class RosterEntry(_RosterEntryBase, total=False):
    model: str
    label: str
    provider_id: str
    thinking_effort: str
    # Per-contender runtime option box (e.g. {"max_turns": 30}); persisted with
    # the profile so saved/migrated contenders keep their knobs.
    options: Dict[str, Union[int, str, bool]]


class ProfileTaskSet(TypedDict):
    tasks_dir: str
    task_ids: List[str]


class _ProfileBase(TypedDict):
    id: str
    name: str
    shared: SharedConfig
    per_contender_fields: List[str]


class Profile(_ProfileBase, total=False):
    rev: int
    roster: List[RosterEntry]
    task_set: ProfileTaskSet


class _ProfilesPayloadBase(TypedDict):
    default_profile_id: Optional[str]
    profiles: List[Profile]


class ProfilesPayload(_ProfilesPayloadBase, total=False):
    persisted: bool


class AgentTemplate(TypedDict):
    template_id: str
    title: str
    docs_url: str
    description: str
    spec: Dict[str, Any]


class AgentTemplatesPayload(TypedDict):
    templates: List[AgentTemplate]


class _CustomRuntimePayloadBase(TypedDict):
    id: str
    command: str
    args: List[str]
    prompt_via: str
    parser: str
    protocol: str


class CustomRuntimePayload(_CustomRuntimePayloadBase, total=False):
    label: str
    description: str
    icon: str
    judge_args: Optional[List[str]]
    model_flag: str
    prompt_flag: str
    env: Dict[str, str]
    base_url_env: str
    api_key_env: str
    docker_image: str
    docker_env_passthrough: List[str]


class _ProviderWriteBase(TypedDict):
    id: str
    name: str
    kind: ProviderKind
    auth: AuthKind
    base_url: str
    api_key_env: str
    models: List[str]
    models_fetched_at: Optional[str]
    models_source: Optional[ModelsSource]


class ProviderWrite(_ProviderWriteBase, total=False):
    anthropic_base_url: Optional[str]
    gemini_base_url: Optional[str]


class SaveProvidersPayload(TypedDict):
    providers: List[ProviderWrite]


class DeletedAgentPayload(TypedDict):
    deleted: str


class MatrixCell(TypedDict):
    passed: int
    total: int


class MatrixRubric(TypedDict):
    id: str
    question: str
    # Keyed by run_id.
    cells: Dict[str, MatrixCell]


class MatrixTask(TypedDict):
    task_id: str
    rubrics: List[MatrixRubric]


class CompareRunRow(TypedDict):
    run_id: str
    # Null when the run directory no longer exists: comparison URLs are
    # long-lived and a vanished run renders as an honest hole.
    run: Optional[RunOverview]


class ComparePayload(TypedDict):
    runs: List[CompareRunRow]
    matrix: List[MatrixTask]


class _CreateExperimentPayloadBase(TypedDict):
    name: str
    tasks_dir: str
    tasks: List[str]
    shared: SharedConfig
    contenders: List[Contender]


class CreateExperimentPayload(_CreateExperimentPayloadBase, total=False):
    profile_id: str


class ExperimentPlanResponse(TypedDict):
    name: str
    shared: SharedConfig
    plans: List[ExperimentPlanItem]
    execution_estimate: ExecutionEstimate
    profile_modified: bool
    profile_modified_fields: List[str]
    dry_run: Literal[True]


class LaunchBatchResponse(TypedDict):
    id: str
    run_ids: List[str]
    launches: List[Launch]


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
    "TaskRunOutcome",
    "HswCellState",
    "PreflightStatus",
    "RuntimeCli",
    "AgentPackage",
    "AgentRuntimeStatus",
    "AgentStatusPayload",
    "AgentInstallResult",
    "ProviderFilter",
    "RuntimeOptionRow",
    "BuiltinRuntime",
    "CustomRuntime",
    "AgentsPayload",
    "CliAuthStatus",
    "ModelReasoning",
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
    "CoverageComboStats",
    "CoverageColumn",
    "CoverageRow",
    "CoverageProfile",
    "CoveragePayload",
    "TaskHistoryConfig",
    "TaskHistory",
    "TaskHistoryPayload",
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
    "ExecutorStats",
    "JudgeCell",
    "RunOverview",
    "TaskRow",
    "ProgressTotals",
    "ProgressSnapshot",
    "AblationDelta",
    "AblationGroup",
    "AblationPayload",
    "RunDetail",
    "RubricResult",
    "JudgeAggregate",
    "ExecutorStatus",
    "TraceTextItem",
    "TraceCommandExecution",
    "TraceFileChange",
    "TraceSummary",
    "ArtifactManifestEntry",
    "ArtifactManifest",
    "JudgeTaskResult",
    "TaskRunDetail",
    "TasksDirMeta",
    "Meta",
    "TaskPackage",
    "TaskLibrary",
    "TaskLibrariesPayload",
    "DockerCleanup",
    "Launch",
    "RunsPayload",
    "LaunchesPayload",
    "RawEventsPage",
    "LaunchPayload",
    "LaunchPlanResponse",
    "DirListingEntry",
    "DirListing",
    "ImportFile",
    "ImportReportTask",
    "ImportReport",
    "TaskRubricDetail",
    "TaskPackageDetail",
    "PreflightCheck",
    "PreflightPayload",
    "EnvSource",
    "GatewayConfig",
    "SharedConfig",
    "RosterEntry",
    "ProfileTaskSet",
    "Profile",
    "ProfilesPayload",
    "AgentTemplate",
    "AgentTemplatesPayload",
    "CustomRuntimePayload",
    "ProviderWrite",
    "SaveProvidersPayload",
    "DeletedAgentPayload",
    "MatrixCell",
    "MatrixRubric",
    "MatrixTask",
    "CompareRunRow",
    "ComparePayload",
    "CreateExperimentPayload",
    "ExperimentPlanResponse",
    "LaunchBatchResponse",
]
