/* GENERATED — do not edit.
 * Source: src/starbench/gui/contracts.py — regenerate with `make gen-types`.
 */

export type ProviderKind = "anthropic" | "openai" | "google" | "xai" | "openai-compatible"

export type RuntimeProtocol = "openai" | "anthropic" | "gemini" | "xai" | "none"

export type AuthKind = "api_key" | "cli_login"

export type ModelsSource = "api" | "catalog" | "cli_cache"

export type CliAuthStatusKind = "ok" | "api_key" | "warn" | "fail" | "unknown"

export type PackageManager = "npm"

export type AgentInstallStatusKind = "installed" | "failed"

export type ThinkingChannel = "native_config" | "prompt"

export type WebSearchMode = "task" | "allow" | "deny"

export type TaskRunOutcome = "agent_pass" | "agent_fail" | "inconclusive_judge" | "inconclusive_executor" | "invalid_task"

export type HswCellState = "breached" | "defended" | "inconclusive" | "untested"

export type PreflightStatus = "ok" | "warn" | "fail"

export interface RuntimeCli {
  bin: string
  present: boolean
  path: string | null
}

export interface AgentPackage {
  manager: "npm"
  name: string
  install_command: string[]
  update_command: string[]
  docs_url: string
}

export interface AgentRuntimeStatus {
  id: string
  bin: string
  present: boolean
  path: string | null
  version: string | null
  version_output: string | null
  version_error: string | null
  package: AgentPackage | null
  latest_version: string | null
  latest_checked_at: string | null
  latest_error: string | null
  update_available: boolean | null
  installable: boolean
}

export interface AgentStatusPayload {
  statuses: Record<string, AgentRuntimeStatus>
}

export interface AgentInstallResult {
  id: string
  command: string[]
  status: "installed" | "failed"
  exit_code: number | null
  stdout_tail: string
  stderr_tail: string
}

export interface ProviderFilter {
  kinds: string[]
  accepts_anthropic_endpoint: boolean
  accepts_gemini_endpoint: boolean
}

export interface RuntimeOptionRow {
  name: string
  type: string
  role: string
  surface: string
  label: string
  help: string
  default: number | string | boolean | null
  choices: string[]
}

export interface BuiltinRuntime {
  id: string
  label: string
  note: string
  protocol: "openai" | "anthropic" | "gemini" | "xai" | "none"
  docker_capable: boolean
  docker_image: string
  builtin: true
  cli: RuntimeCli
  provider_filter: ProviderFilter
  thinking_channel: "native_config" | "prompt"
  thinking_efforts: string[]
  enforces_web_search: boolean
  options: RuntimeOptionRow[]
}

export interface CustomRuntime {
  id: string
  spec_id: string
  builtin: false
  source_path: string
  error: string | null
  label?: string
  description?: string
  icon?: string
  protocol?: "openai" | "anthropic" | "gemini" | "xai" | "none"
  provider_filter?: ProviderFilter
  base_url_env?: string
  api_key_env?: string
  command?: string
  args?: string[]
  judge_args?: string[]
  judge_args_inherited?: boolean
  model_flag?: string | null
  prompt_via?: string
  prompt_flag?: string
  parser?: string
  env?: Record<string, string>
  docker_image?: string | null
  docker_env_passthrough?: string[]
  docker_capable?: boolean
  thinking_channel?: "native_config" | "prompt"
  thinking_efforts?: string[]
  enforces_web_search?: boolean
  cli?: RuntimeCli
  options?: RuntimeOptionRow[]
}

export interface AgentsPayload {
  runtimes_dir: string
  builtin: BuiltinRuntime[]
  custom: CustomRuntime[]
}

export interface CliAuthStatus {
  agent: string
  label: string
  cli_present: boolean
  cli_path: string | null
  status: "ok" | "api_key" | "warn" | "fail" | "unknown"
  message: string
}

export interface ModelReasoning {
  levels: string[]
  default_level: string | null
}

export interface AiProvider {
  id: string
  name: string
  kind: "anthropic" | "openai" | "google" | "xai" | "openai-compatible"
  auth: "api_key" | "cli_login"
  base_url: string
  api_key_env: string
  models: string[]
  models_fetched_at: string | null
  models_source: "api" | "catalog" | "cli_cache" | null
  agent: string
  key_present: boolean
  anthropic_base_url?: string | null
  gemini_base_url?: string | null
  cli_status?: CliAuthStatus
  model_reasoning?: Record<string, ModelReasoning>
}

export interface ProvidersPayload {
  providers: AiProvider[]
  persisted?: boolean
}

export interface ProviderCliStatusPayload {
  statuses: Record<string, CliAuthStatus>
}

export interface Skill {
  id: string
  description: string
  source_path: string
  file_count: number
  size_bytes: number
  sha256: string | null
  leakage_level: string | null
  groups: string[]
}

export interface SkillsPayload {
  root: string
  skills: Skill[]
  groups: Record<string, string[]>
  error?: string
}

export interface HumanReferenceStepDetail {
  step_id: string
  step_type: string
  instruction: string
}

export interface RigorDetail {
  id: string
  rubric_id: string
  requirement: string
}

export interface ExecutionEstimate {
  per_contender: number
  total: number
  mode: string
  note: string
}

export type RunStatus = "complete" | "running" | "interrupted"

export type RunLiveState = "pending" | "executing" | "judging" | "done" | "failed"

export type ExecutorSecondsSource = "measured" | "elapsed"

export interface RunLiveEvent {
  type: string
  summary: string
}

export interface RunLiveTask {
  run_task_id: string
  state: "pending" | "executing" | "judging" | "done" | "failed"
  executor_status: string | null
  executor_seconds: number | null
  executor_seconds_source: "measured" | "elapsed" | null
}

export interface RunLiveCurrent {
  run_task_id: string
  task_id: string | null
  started_at: string | null
  elapsed_seconds: number | null
  events: RunLiveEvent[]
}

export interface RunLiveEta {
  estimated_remaining_seconds: number | null
  average_executor_seconds: number | null
  completed_sample_count: number
  remaining_task_count: number
}

export interface RunLivePayload {
  run_id: string
  status: "complete" | "running" | "interrupted"
  generated_at: string
  tasks: RunLiveTask[]
  current: RunLiveCurrent | null
  eta: RunLiveEta
}

export type TraceEntryType = "reasoning" | "command" | "file_change" | "message" | "lifecycle" | "other"

export interface TraceEntry {
  index: number
  type: "reasoning" | "command" | "file_change" | "message" | "lifecycle" | "other"
  title: string
  body: string
  seconds_offset: number | null
  truncated: boolean
}

export interface TaskTracePayload {
  run_id: string
  run_task_id: string
  entries: TraceEntry[]
  offset: number
  total: number
  next_offset: number | null
  has_events: boolean
}

export interface ArtifactPayload {
  path: string
  size_bytes: number
  is_binary: boolean
  truncated: boolean
  content: string | null
}

export interface VariantSibling {
  run_task_id: string
  instruction_variant: string | null
  evaluated: boolean
}

export interface OutputsListingEntry {
  path?: string
  kind?: string
  size_bytes?: number | null
}

export interface OutputsListing {
  outputs_dir: string
  file_count: number
  entries: OutputsListingEntry[]
  truncated: boolean
}

export interface CoverageRunRef {
  run_id: string
  run_task_id: string
}

export interface CoverageCell {
  column_key: string
  state: "breached" | "defended" | "inconclusive" | "untested"
  total: number
  judged: number
  passed: number
  inconclusive: number
  last_tested: string | null
  recent_refs: CoverageRunRef[]
  rubric_samples: number
  rubric_ratio_mean: number | null
  rubric_ratio_std: number | null
  duration_mean_seconds: number | null
  duration_p95_seconds: number | null
  exec_success: number
  exec_failed: number
  exec_timeout: number
  exec_pending: number
}

export interface CoverageComboStats {
  tasks_tested: number
  judged: number
  passed: number
  exec_pending: number
  rubric_samples: number
  rubric_ratio_mean: number | null
  rubric_ratio_std: number | null
  duration_p95_seconds: number | null
  last_tested: string | null
}

export interface CoverageColumn {
  key: string
  agent: string
  model: string | null
  run_count: number
  rostered: boolean
  stats: CoverageComboStats
}

export interface CoverageRow {
  task_id: string
  in_library: boolean
  breached: boolean
  tested_columns: number
  cells: CoverageCell[]
}

export interface CoverageProfile {
  id: string
  name: string
  rev: number
}

export interface CoveragePayload {
  columns: CoverageColumn[]
  rows: CoverageRow[]
  runs_scanned: number
  profile: CoverageProfile | null
  generated_at: string
}

export interface TaskHistoryConfig {
  executor_agent: string | null
  executor_model: string | null
  evaluator_agent: string | null
  evaluator_model: string | null
  judge_mode: string | null
  executor_backend: string | null
  instruction_mode: string | null
  repeat: number | null
  seed: number | null
  thinking_effort: string | null
  run_count: number
  task_run_count: number
  last_tested: string | null
}

export interface TaskHistory {
  task_id: string
  run_count: number
  task_run_count: number
  last_tested: string | null
  configs: TaskHistoryConfig[]
}

export interface TaskHistoryPayload {
  tasks: Record<string, TaskHistory>
}

export interface ProfileSnapshotProfile {
  id: string
  rev: number
  name: string
}

export interface ProfileSnapshotContender {
  agent: string
  model: string
  label?: string
  thinking_effort?: string
  auth_mode?: string
  provider_id?: string
  base_url?: string
  api_key_env?: string
  options?: Record<string, number | string | boolean>
}

export interface ProfileSnapshotInstrument {
  evaluator_agent: string
  evaluator_model: string
  evaluator_auth_mode: string
  judge_mode: string
  evaluator_timeout_seconds?: number
}

export interface ProfileSnapshotExecution {
  seed: number
  batch_size: number
  repeat: number
  executor_backend: string
  executor_auth_mode: string
  max_evaluator_parallel?: number
  web_search?: "task" | "allow" | "deny"
  evaluator_options?: Record<string, number | string | boolean>
}

export interface ProfileSnapshotTaskSet {
  tasks_dir: string
  task_ids: string[]
}

export interface ProfileSnapshot {
  schema_version: number
  captured_at: string
  profile: ProfileSnapshotProfile
  contender: ProfileSnapshotContender
  roster: ProfileSnapshotContender[]
  instrument: ProfileSnapshotInstrument
  execution: ProfileSnapshotExecution
  task_set: ProfileSnapshotTaskSet
  modified?: boolean
  modified_fields?: string[]
}

export interface RunProfileRef {
  id: string
  rev: number
  modified: boolean
}

export interface RunRow {
  run_id: string
  status: "complete" | "running" | "interrupted"
  task_count: number
  executor_stats: Record<string, number>
  judge_passes: Record<string, number>
  judge_totals: Record<string, number>
  judge_inconclusive: Record<string, number>
  judge_mode: string | null
  executor_agent: string | null
  executor_model: string | null
  evaluator_agent: string | null
  evaluator_model: string | null
  executor_backend: string | null
  seed: number | null
  instruction_mode: string | null
  started_at: string | null
  ended_at: string | null
  has_ablation: boolean
  profile: RunProfileRef | null
}

export interface ExperimentPlanItem {
  label: string
  agent: string
  model: string
  run_id: string
  backend: string
  backend_downgraded: boolean
  warnings: string[]
  argv: string[]
  docker_image?: string
  run_plan?: Record<string, unknown> | null
  executor_skills?: string[]
  executor_auth_mode?: string
  evaluator_agent?: string
  evaluator_auth_mode?: string
  executor_bin?: string
  evaluator_bin?: string
  executor_options?: Record<string, number | string | boolean>
  evaluator_options?: Record<string, number | string | boolean>
  executor_credential_env_keys?: string[]
  evaluator_credential_env_keys?: string[]
}

export interface Contender {
  agent: string
  provider_id: string
  model: string
  label?: string
  thinking_effort?: string
  options?: Record<string, number | string | boolean>
}

export interface ExecutorStats {
  success: number
  failed: number
  timeout: number
  skipped?: number
  pending?: number
}

export interface JudgeCell {
  outcome: "agent_pass" | "agent_fail" | "inconclusive_judge" | "inconclusive_executor" | "invalid_task" | null
  overall_pass: boolean | null
  passed_count: number | null
  total_count: number | null
  missing: number
  fail_fast_failures: number
  error: string | null
}

export interface RunOverview {
  run_id: string
  status: "complete" | "running" | "interrupted"
  task_count: number
  executor_stats: ExecutorStats
  judge_passes: Record<string, number>
  judge_totals: Record<string, number>
  judge_inconclusive: Record<string, number>
  judge_mode: string | null
  executor_agent: string | null
  executor_model: string | null
  evaluator_agent: string | null
  evaluator_model: string | null
  executor_backend: string | null
  seed: number | null
  instruction_mode: string | null
  started_at: string | null
  ended_at: string | null
  has_ablation: boolean
  profile?: RunProfileRef | null
  batch?: string | null
}

export interface TaskRow {
  run_task_id: string
  task_id: string | null
  instruction_variant: string | null
  executor_status: string | null
  executor_duration_seconds: number | null
  executor_timed_out: boolean | null
  judges: Record<string, JudgeCell | null>
  evaluated: boolean
}

export interface ProgressTotals {
  executors: number
  evaluators: number
}

export interface ProgressSnapshot {
  totals: ProgressTotals
  executor_done: number
  evaluator_done: number
  executor_stats: ExecutorStats
  evaluator_stats: ExecutorStats
  active_executors: string[]
  event_count: number
}

export interface AblationDelta {
  overall_pass_rate_delta: number | null
  mean_rubric_pass_rate_delta: number | null
}

export interface AblationGroup {
  task_id: string
  judge_mode: string
  instruction_variant: string
  runs: number
  overall_pass_count: number
  overall_pass_rate: number | null
  mean_rubric_pass_rate: number | null
  attempts?: number
  inconclusive?: number
  delta_vs_baseline?: AblationDelta
}

export interface AblationPayload {
  groups: AblationGroup[]
}

export interface RunDetail {
  run_id: string
  status: "complete" | "running" | "interrupted"
  task_count: number
  executor_stats: ExecutorStats
  judge_passes: Record<string, number>
  judge_totals: Record<string, number>
  judge_inconclusive: Record<string, number>
  judge_mode: string | null
  executor_agent: string | null
  executor_model: string | null
  evaluator_agent: string | null
  evaluator_model: string | null
  executor_backend: string | null
  seed: number | null
  instruction_mode: string | null
  started_at: string | null
  ended_at: string | null
  has_ablation: boolean
  profile?: RunProfileRef | null
  batch?: string | null
  config: Record<string, unknown> | null
  tasks: TaskRow[]
  progress: ProgressSnapshot | null
  ablation: AblationPayload | null
}

export interface RubricResult {
  rubric_id: string
  answer: boolean | null
  expected: boolean
  passed: boolean | null
  fail_fast: boolean
  evidence: string
}

export interface JudgeAggregate {
  mode: string
  outcome: "agent_pass" | "agent_fail" | "inconclusive_judge" | "inconclusive_executor" | "invalid_task"
  overall_pass: boolean | null
  passed_count: number
  total_count: number
  missing: string[]
  fail_fast_failures: string[]
  results: RubricResult[]
  error?: string
}

export interface ExecutorStatus {
  command?: string[]
  status?: string
  exit_code?: number | null
  timed_out?: boolean
  started_at?: string
  ended_at?: string
  duration_seconds?: number
}

export interface TraceTextItem {
  id?: string
  text?: string | null
}

export interface TraceCommandExecution {
  id?: string
  command?: string
  status?: string
  exit_code?: number | null
  aggregated_output?: string | null
}

export interface TraceFileChange {
  id?: string
  status?: string
  changes?: unknown
}

export interface TraceSummary {
  thread_id: string | null
  event_type_counts: Record<string, number>
  item_type_counts: Record<string, number>
  reasoning_items: TraceTextItem[]
  agent_messages: TraceTextItem[]
  command_executions: TraceCommandExecution[]
  file_changes: TraceFileChange[]
  usage: Record<string, unknown> | null
}

export interface ArtifactManifestEntry {
  path: string
  kind: string
  size_bytes?: number
  sha256?: string
}

export interface ArtifactManifest {
  outputs_dir: string
  file_count: number
  entries: ArtifactManifestEntry[]
}

export interface JudgeTaskResult {
  aggregate: JudgeAggregate
  status: ExecutorStatus | null
}

export interface TaskRunDetail {
  run_id: string
  run_task_id: string
  task_id: string | null
  instruction_variant: string | null
  executor: ExecutorStatus | null
  executor_timing: Record<string, unknown> | null
  judges: Record<string, JudgeTaskResult>
  rubric_questions: Record<string, string>
  trace_summary: TraceSummary | null
  artifact_manifest: ArtifactManifest | null
  outputs_listing: OutputsListing | null
  variant_group: VariantSibling[]
  final_message: string | null
  stderr_tail: string | null
  raw_event_count: number
  evaluated: boolean
}

export interface TasksDirMeta {
  dir: string
  exists: boolean
}

export interface Meta {
  runs_dir: string
  cwd: string
  runtimes_dir: string
  skills_dir: string
  tasks_dirs: TasksDirMeta[]
  agents: string[]
  judge_modes: string[]
  auth_modes: string[]
  backends: string[]
  thinking_efforts: string[]
}

export interface TaskPackage {
  id: string
  dir_name: string
  name: string
  rubric_count: number
  timeout_seconds: number | null
  allow_web_search: boolean | null
  rigor_count: number
  has_human_reference: boolean
  error?: string | null
  warning?: string | null
}

export interface TaskLibrary {
  dir: string
  exists: boolean
  tasks: TaskPackage[]
}

export interface TaskLibrariesPayload {
  libraries: TaskLibrary[]
}

export interface DockerCleanup {
  matched: string[]
  stopped: string[]
  killed: string[]
  errors: string[]
}

export interface Launch {
  run_id: string
  state: string | null
  argv: string[]
  pid: number | null
  pgid: number | null
  started_at: string | null
  log_path: string
  running: boolean
  exit_code: number | null
  docker_cleanup: DockerCleanup | null
  error: string | null
}

export interface RunsPayload {
  runs: RunOverview[]
}

export interface LaunchesPayload {
  launches: Launch[]
}

export interface RawEventsPage {
  events: Record<string, unknown>[]
  offset: number
  total: number
  next_offset: number | null
}

export interface LaunchPayload {
  run_id: string
  tasks_dir: string
  tasks: string[]
  executor_agent: string
  executor_model: string
  executor_backend: string
  docker_image: string
  auth_mode: string
  thinking_effort: string
  web_search: string
  evaluator_agent: string
  evaluator_model: string
  judge_mode: string
  evaluator_timeout_seconds: string
  seed: string
  batch_size: string
  repeat: string
  extra_args: string
  dry_run?: boolean
}

export interface LaunchPlanResponse {
  argv: string[]
  dry_run: true
}

export interface DirListingEntry {
  name: string
  path: string
  task_count: number
  is_task_package: boolean
}

export interface DirListing {
  path: string
  parent: string | null
  task_count: number
  dirs: DirListingEntry[]
}

export interface ImportFile {
  path: string
  content_b64: string
}

export interface ImportReportTask {
  id?: string
  name?: string
  rubric_count?: number
}

export interface ImportReport {
  valid: boolean
  errors: string[]
  warnings: string[]
  task: ImportReportTask
  file_count: number
  installed_to?: string
}

export interface TaskRubricDetail {
  id: string
  fail_fast: boolean
  expected: boolean
  question: string
}

export interface TaskPackageDetail {
  dir: string
  dir_name: string
  id: string
  name: string
  timeout_seconds: number | null
  allow_web_search: boolean | null
  prompt: string | null
  rubrics: TaskRubricDetail[]
  human_reference_steps: HumanReferenceStepDetail[]
  human_reference_step_count: number
  rigors: RigorDetail[]
  rigor_count: number
}

export interface PreflightCheck {
  id: string
  label: string
  status: "ok" | "warn" | "fail"
  hint: string
}

export interface PreflightPayload {
  checks: PreflightCheck[]
}

export interface EnvSource {
  value?: string
  from_env?: string
}

export interface GatewayConfig {
  provider?: string
  base_url?: string
  api_key_env?: string
}

export interface SharedConfig {
  evaluator_agent?: string
  evaluator_model?: string
  evaluator_auth_mode?: string
  judge_mode?: string
  evaluator_timeout_seconds?: number | string | null
  executor_backend?: string
  docker_image?: string
  executor_auth_mode?: string
  seed?: number | string | null
  batch_size?: number | string | null
  repeat?: number | string | null
  max_evaluator_parallel?: number | string | null
  web_search_mode?: string
  extra_args?: string
  executor_skills?: string[]
  executor_skill_groups?: string[]
  instruction_mode?: string
  instruction_steps?: string[]
  rigor_mode?: string
  rigors?: string[]
  evaluator_provider_id?: string
  evaluator_gateway?: GatewayConfig | null
  evaluator_options?: Record<string, number | string | boolean>
  judge_env?: Record<string, EnvSource> | null
}

export interface RosterEntry {
  agent: string
  model?: string
  label?: string
  provider_id?: string
  thinking_effort?: string
  options?: Record<string, number | string | boolean>
}

export interface ProfileTaskSet {
  tasks_dir: string
  task_ids: string[]
}

export interface Profile {
  id: string
  name: string
  shared: SharedConfig
  per_contender_fields: string[]
  rev?: number
  roster?: RosterEntry[]
  task_set?: ProfileTaskSet
}

export interface ProfilesPayload {
  default_profile_id: string | null
  profiles: Profile[]
  persisted?: boolean
}

export interface AgentTemplate {
  template_id: string
  title: string
  docs_url: string
  description: string
  spec: Record<string, unknown>
}

export interface AgentTemplatesPayload {
  templates: AgentTemplate[]
}

export interface CustomRuntimePayload {
  id: string
  command: string
  args: string[]
  prompt_via: string
  parser: string
  protocol: string
  label?: string
  description?: string
  icon?: string
  judge_args?: string[] | null
  model_flag?: string
  prompt_flag?: string
  env?: Record<string, string>
  base_url_env?: string
  api_key_env?: string
  docker_image?: string
  docker_env_passthrough?: string[]
}

export interface ProviderWrite {
  id: string
  name: string
  kind: "anthropic" | "openai" | "google" | "xai" | "openai-compatible"
  auth: "api_key" | "cli_login"
  base_url: string
  api_key_env: string
  models: string[]
  models_fetched_at: string | null
  models_source: "api" | "catalog" | "cli_cache" | null
  anthropic_base_url?: string | null
  gemini_base_url?: string | null
}

export interface SaveProvidersPayload {
  providers: ProviderWrite[]
}

export interface DeletedAgentPayload {
  deleted: string
}

export interface MatrixCell {
  passed: number
  total: number
}

export interface MatrixRubric {
  id: string
  question: string
  cells: Record<string, MatrixCell>
}

export interface MatrixTask {
  task_id: string
  rubrics: MatrixRubric[]
}

export interface CompareRunRow {
  run_id: string
  run: RunOverview | null
}

export interface ComparePayload {
  runs: CompareRunRow[]
  matrix: MatrixTask[]
}

export interface CreateExperimentPayload {
  name: string
  tasks_dir: string
  tasks: string[]
  shared: SharedConfig
  contenders: Contender[]
  profile_id?: string
}

export interface ExperimentPlanResponse {
  name: string
  shared: SharedConfig
  plans: ExperimentPlanItem[]
  execution_estimate: ExecutionEstimate
  profile_modified: boolean
  profile_modified_fields: string[]
  dry_run: true
}

export interface LaunchBatchResponse {
  id: string
  run_ids: string[]
  launches: Launch[]
}
