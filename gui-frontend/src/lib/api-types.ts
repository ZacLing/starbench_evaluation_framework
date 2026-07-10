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
  cli?: RuntimeCli
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
  total: number
  judged: number
  passed: number
  inconclusive: number
  last_tested: string | null
  recent_refs: CoverageRunRef[]
}

export interface CoverageColumn {
  key: string
  agent: string
  model: string | null
  run_count: number
  rostered: boolean
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
  claude_max_turns?: number
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
  executor_skills?: string[]
  executor_auth_mode?: string
}

export interface Contender {
  agent: string
  provider_id: string
  model: string
  label?: string
  thinking_effort?: string
}
