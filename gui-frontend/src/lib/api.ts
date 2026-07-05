/* Typed client for the StarBench Console API (src/starbench/gui/server.py). */

export interface ExecutorStats {
  success: number
  failed: number
  timeout: number
  pending?: number
}

export interface JudgeCell {
  overall_pass: boolean | null
  passed_count: number | null
  total_count: number | null
  missing: number
  fail_fast_failures: number
}

export interface RunOverview {
  run_id: string
  status: "complete" | "running" | "interrupted"
  task_count: number
  executor_stats: ExecutorStats
  judge_passes: { single: number; parallel: number }
  judge_totals: { single: number; parallel: number }
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
}

export interface TaskRow {
  run_task_id: string
  task_id: string | null
  instruction_variant: string | null
  executor_status: string | null
  executor_duration_seconds: number | null
  executor_timed_out: boolean | null
  judges: Partial<Record<"single" | "parallel", JudgeCell | null>>
  evaluated: boolean
}

export interface ProgressSnapshot {
  totals: { executors: number; evaluators: number }
  executor_done: number
  evaluator_done: number
  executor_stats: ExecutorStats
  evaluator_stats: ExecutorStats
  active_executors: string[]
  event_count: number
}

export interface AblationGroup {
  task_id: string
  judge_mode: string
  instruction_variant: string
  runs: number
  overall_pass_count: number
  overall_pass_rate: number | null
  mean_rubric_pass_rate: number | null
  delta_vs_baseline?: {
    overall_pass_rate_delta: number | null
    mean_rubric_pass_rate_delta: number | null
  }
}

export interface RunDetail extends RunOverview {
  config: Record<string, unknown> | null
  tasks: TaskRow[]
  progress: ProgressSnapshot | null
  ablation: { groups: AblationGroup[] } | null
}

export interface RubricResult {
  rubric_id: string
  answer: boolean | null
  expected: boolean
  passed: boolean
  fail_fast: boolean
  evidence: string
}

export interface JudgeAggregate {
  mode: string
  overall_pass: boolean
  passed_count: number
  total_count: number
  missing: string[]
  fail_fast_failures: string[]
  results: RubricResult[]
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

export interface TraceSummary {
  thread_id: string | null
  event_type_counts: Record<string, number>
  item_type_counts: Record<string, number>
  reasoning_items: { id?: string; text?: string | null }[]
  agent_messages: { id?: string; text?: string | null }[]
  command_executions: {
    id?: string
    command?: string
    status?: string
    exit_code?: number | null
    aggregated_output?: string | null
  }[]
  file_changes: { id?: string; status?: string; changes?: unknown }[]
  usage: Record<string, unknown> | null
}

export interface ArtifactManifest {
  outputs_dir: string
  file_count: number
  entries: { path: string; kind: string; size_bytes?: number; sha256?: string }[]
}

export interface TaskRunDetail {
  run_id: string
  run_task_id: string
  task_id: string | null
  instruction_variant: string | null
  executor: ExecutorStatus | null
  executor_timing: Record<string, unknown> | null
  judges: Partial<
    Record<"single" | "parallel", { aggregate: JudgeAggregate; status: ExecutorStatus | null }>
  >
  rubric_questions: Record<string, string>
  trace_summary: TraceSummary | null
  artifact_manifest: ArtifactManifest | null
  final_message: string | null
  stderr_tail: string | null
  raw_event_count: number
  evaluated: boolean
}

export interface Meta {
  runs_dir: string
  cwd: string
  tasks_dirs: { dir: string; exists: boolean }[]
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
  has_human_reference: boolean
}

export interface TaskLibrary {
  dir: string
  exists: boolean
  tasks: TaskPackage[]
}

export interface Launch {
  run_id: string
  argv: string[]
  pid: number
  started_at: string
  log_path: string
  running: boolean
  exit_code: number | null
}

export interface RawEventsPage {
  events: Record<string, unknown>[]
  offset: number
  total: number
  next_offset: number | null
}

export interface LaunchPayload {
  dry_run?: boolean
  run_id: string
  tasks_dir: string
  tasks: string[]
  executor_agent: string
  executor_model: string
  executor_backend: string
  docker_image: string
  auth_mode: string
  claude_thinking_effort: string
  evaluator_agent: string
  evaluator_model: string
  judge_mode: string
  evaluator_timeout_seconds: string
  seed: string
  batch_size: string
  repeat: string
  extra_args: string
}

export interface DirListing {
  path: string
  parent: string | null
  task_count: number
  dirs: { name: string; path: string; task_count: number; is_task_package: boolean }[]
}

export interface ImportFile {
  path: string
  content_b64: string
}

export interface ImportReport {
  valid: boolean
  errors: string[]
  warnings: string[]
  task: { id?: string; name?: string; rubric_count?: number }
  file_count: number
  installed_to?: string
}

export interface TaskPackageDetail {
  dir: string
  dir_name: string
  id: string
  name: string
  timeout_seconds: number | null
  allow_web_search: boolean | null
  prompt: string | null
  rubrics: {
    id: string
    fail_fast: boolean
    expected: boolean
    question: string
  }[]
  human_reference_steps: number
}

export interface PreflightCheck {
  id: string
  label: string
  status: "ok" | "warn" | "fail"
  hint: string
}

export interface SharedConfig {
  evaluator_agent: string
  evaluator_model: string
  evaluator_auth_mode: string
  judge_mode: string
  evaluator_timeout_seconds: number | string | null
  executor_backend: string
  docker_image: string
  executor_auth_mode: string
  seed: number | string | null
  batch_size: number | string | null
  repeat: number | string | null
  extra_args?: string
  evaluator_provider_id?: string
  evaluator_gateway?: {
    opencode_provider?: string
    opencode_base_url?: string
    opencode_api_key_env?: string
  } | null
  judge_env?: Record<string, { value?: string; from_env?: string }> | null
}

export interface Profile {
  id: string
  name: string
  shared: Partial<SharedConfig>
  per_contender_fields: string[]
}

export interface ProfilesPayload {
  default_profile_id: string | null
  profiles: Profile[]
  persisted?: boolean
}

export interface Contender {
  label: string
  agent: string
  model: string
  auth_mode: string
  thinking_effort?: string
  opencode_provider?: string
  opencode_base_url?: string
  opencode_api_key_env?: string
  codex_bin?: string
  env?: Record<string, { value?: string; from_env?: string }>
}

export type RuntimeProtocol = "openai" | "anthropic" | "gemini" | "xai" | "none"

export interface RuntimeCli {
  bin: string
  present: boolean
  path: string | null
}

export interface BuiltinRuntime {
  id: string
  label: string
  note: string
  protocol: RuntimeProtocol
  docker_capable: boolean
  docker_image: string
  builtin: true
  cli: RuntimeCli
}

export interface CustomRuntime {
  id: string
  spec_id: string
  builtin: false
  label?: string
  description?: string
  icon?: string
  protocol?: RuntimeProtocol
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
  cli?: RuntimeCli
  source_path: string
  error: string | null
}

export interface AgentsPayload {
  runtimes_dir: string
  builtin: BuiltinRuntime[]
  custom: CustomRuntime[]
}

export interface AgentTemplate {
  template_id: string
  title: string
  docs_url: string
  description: string
  spec: Record<string, unknown>
}

export interface CustomRuntimePayload {
  id: string
  label?: string
  description?: string
  icon?: string
  command: string
  args: string[]
  judge_args?: string[] | null
  model_flag?: string
  prompt_via: string
  prompt_flag?: string
  parser: string
  env?: Record<string, string>
  protocol: string
  base_url_env?: string
  api_key_env?: string
  docker_image?: string
  docker_env_passthrough?: string[]
}

export type ProviderKind = "anthropic" | "openai" | "google" | "xai" | "openai-compatible"

export interface AiProvider {
  id: string
  name: string
  kind: ProviderKind
  auth: "api_key" | "cli_login"
  base_url: string
  anthropic_base_url?: string | null
  gemini_base_url?: string | null
  api_key_env: string
  models: string[]
  models_fetched_at: string | null
  models_source: "api" | "catalog" | null
  agent: string
  key_present: boolean
}

export interface ProvidersPayload {
  providers: AiProvider[]
  persisted?: boolean
}

export interface ExperimentPlanItem {
  label: string
  agent: string
  model: string
  run_id: string
  backend: string
  backend_downgraded: boolean
  docker_image?: string
  argv: string[]
}

export interface ExperimentRecord {
  id: string
  created_at: string
  tasks_dir: string
  tasks: string[]
  shared: Partial<SharedConfig>
  contenders: {
    label: string
    agent: string
    agent_label?: string
    model: string
    run_id: string
    backend: string
    backend_downgraded: boolean
  }[]
  run_ids: string[]
}

export interface ExperimentSummary extends ExperimentRecord {
  runs: (RunOverview | { run_id: string; status: "missing" })[]
}

export interface MatrixCell {
  passed: number
  total: number
}

export interface ExperimentDetail extends ExperimentRecord {
  contenders: (ExperimentRecord["contenders"][number] & { run: RunOverview | null })[]
  matrix: {
    task_id: string
    rubrics: { id: string; question: string; cells: Record<string, MatrixCell> }[]
  }[]
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  let payload: unknown = null
  try {
    payload = await response.json()
  } catch {
    /* non-JSON error body */
  }
  if (!response.ok) {
    const message =
      payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error: unknown }).error)
        : `${response.status} ${response.statusText}`
    throw new Error(message)
  }
  return payload as T
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  runs: () => request<{ runs: RunOverview[] }>("/api/runs"),
  run: (runId: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`),
  task: (runId: string, taskRunId: string) =>
    request<TaskRunDetail>(
      `/api/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(taskRunId)}`,
    ),
  events: (runId: string, taskRunId: string, offset: number, limit = 100) =>
    request<RawEventsPage>(
      `/api/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(
        taskRunId,
      )}/events?offset=${offset}&limit=${limit}`,
    ),
  tasklib: () => request<{ libraries: TaskLibrary[] }>("/api/tasklib"),
  launches: () => request<{ launches: Launch[] }>("/api/launches"),
  launch: (payload: LaunchPayload) =>
    request<Launch & { argv: string[]; dry_run?: boolean }>("/api/launch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  stop: (runId: string) =>
    request<Launch>(`/api/launches/${encodeURIComponent(runId)}/stop`, { method: "POST" }),
  browse: (path?: string | null) =>
    request<DirListing>(`/api/fs/list${path ? `?path=${encodeURIComponent(path)}` : ""}`),
  registerTasksDir: (dir: string) =>
    request<{ libraries: TaskLibrary[] }>("/api/tasklib/dirs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir }),
    }),
  taskDetail: (dir: string, name: string) =>
    request<TaskPackageDetail>(
      `/api/tasklib/task?dir=${encodeURIComponent(dir)}&name=${encodeURIComponent(name)}`,
    ),
  importTasks: (targetDir: string, files: ImportFile[], dryRun: boolean) =>
    request<ImportReport>("/api/tasks/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_dir: targetDir, files, dry_run: dryRun }),
    }),
  preflight: (params: Record<string, string>) =>
    request<{ checks: PreflightCheck[] }>(
      `/api/preflight?${new URLSearchParams(params).toString()}`,
    ),
  agents: () => request<AgentsPayload>("/api/agents"),
  agentTemplates: () => request<{ templates: AgentTemplate[] }>("/api/agents/templates"),
  saveAgent: (payload: CustomRuntimePayload) =>
    request<CustomRuntime>("/api/agents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  deleteAgent: (specId: string) =>
    request<{ deleted: string }>(`/api/agents/${encodeURIComponent(specId)}/delete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),
  providers: () => request<ProvidersPayload>("/api/providers"),
  saveProviders: (payload: { providers: Omit<AiProvider, "agent" | "key_present">[] }) =>
    request<ProvidersPayload>("/api/providers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  refreshProviderModels: (id: string) =>
    request<ProvidersPayload>(`/api/providers/${encodeURIComponent(id)}/refresh-models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    }),
  profiles: () => request<ProfilesPayload>("/api/profiles"),
  saveProfiles: (payload: ProfilesPayload) =>
    request<ProfilesPayload>("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  experiments: () => request<{ experiments: ExperimentSummary[] }>("/api/experiments"),
  experiment: (id: string) =>
    request<ExperimentDetail>(`/api/experiments/${encodeURIComponent(id)}`),
  createExperiment: (payload: {
    name: string
    tasks_dir: string
    tasks: string[]
    shared: Partial<SharedConfig>
    contenders: Contender[]
    dry_run?: boolean
  }) =>
    request<{ name: string; plans: ExperimentPlanItem[]; dry_run?: boolean } & Partial<ExperimentRecord>>(
      "/api/experiments",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    ),
}
