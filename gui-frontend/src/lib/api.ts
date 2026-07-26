/* Typed client for the StarBench Console API (src/starbench/gui/server.py). */

import type {
  AgentInstallResult,
  AgentStatusPayload,
  AgentTemplatesPayload,
  AgentsPayload,
  ArtifactPayload,
  ComparePayload,
  CoveragePayload,
  CreateExperimentPayload,
  CustomRuntime,
  CustomRuntimePayload,
  DeletedAgentPayload,
  ExperimentPlanResponse,
  ImportFile,
  ImportReport,
  Launch,
  LaunchBatchResponse,
  LaunchPayload,
  LaunchPlanResponse,
  LaunchesPayload,
  Meta,
  PreflightPayload,
  ProfilesPayload,
  ProviderCliStatusPayload,
  ProvidersPayload,
  RawEventsPage,
  RunDetail,
  RunLivePayload,
  RunsPayload,
  SaveProvidersPayload,
  SkillsPayload,
  TaskHistoryPayload,
  TaskLibrariesPayload,
  TaskPackageDetail,
  TaskRunDetail,
  TaskTracePayload,
} from "./api-types"

export type * from "./api-types"

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

function jsonBody(payload: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  runs: () => request<RunsPayload>("/api/runs"),
  run: (runId: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`),
  runLive: (runId: string) =>
    request<RunLivePayload>(`/api/runs/${encodeURIComponent(runId)}/live`),
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
  trace: (runId: string, taskRunId: string, offset: number, limit = 200) =>
    request<TaskTracePayload>(
      `/api/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(
        taskRunId,
      )}/trace?offset=${offset}&limit=${limit}`,
    ),
  artifact: (runId: string, taskRunId: string, path: string) =>
    request<ArtifactPayload>(
      `/api/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(
        taskRunId,
      )}/artifact?path=${encodeURIComponent(path)}`,
    ),
  coverage: (profileId?: string | null) =>
    request<CoveragePayload>(
      `/api/coverage${profileId ? `?profile=${encodeURIComponent(profileId)}` : ""}`,
    ),
  tasklib: () => request<TaskLibrariesPayload>("/api/tasklib"),
  taskHistory: () => request<TaskHistoryPayload>("/api/tasklib/history"),
  launches: () => request<LaunchesPayload>("/api/launches"),
  launch: (payload: LaunchPayload) => request<Launch>("/api/launch", jsonBody(payload)),
  planLaunch: (payload: LaunchPayload) =>
    request<LaunchPlanResponse>("/api/launch", jsonBody({ ...payload, dry_run: true })),
  stop: (runId: string) =>
    request<Launch>(`/api/launches/${encodeURIComponent(runId)}/stop`, { method: "POST" }),
  taskDetail: (dir: string, name: string) =>
    request<TaskPackageDetail>(
      `/api/tasklib/task?dir=${encodeURIComponent(dir)}&name=${encodeURIComponent(name)}`,
    ),
  importTasks: (targetDir: string, files: ImportFile[], dryRun: boolean) =>
    request<ImportReport>(
      "/api/tasks/import",
      jsonBody({ target_dir: targetDir, files, dry_run: dryRun }),
    ),
  preflight: (params: Record<string, string>) =>
    request<PreflightPayload>(`/api/preflight?${new URLSearchParams(params).toString()}`),
  agents: () => request<AgentsPayload>("/api/agents"),
  agentStatus: (checkUpdates = false) =>
    request<AgentStatusPayload>(
      `/api/agents/status${checkUpdates ? "?check_updates=1" : ""}`,
    ),
  agentTemplates: () => request<AgentTemplatesPayload>("/api/agents/templates"),
  skills: () => request<SkillsPayload>("/api/skills"),
  saveAgent: (payload: CustomRuntimePayload) =>
    request<CustomRuntime>("/api/agents", jsonBody(payload)),
  deleteAgent: (specId: string) =>
    request<DeletedAgentPayload>(
      `/api/agents/${encodeURIComponent(specId)}/delete`,
      jsonBody({}),
    ),
  installAgent: (agentId: string) =>
    request<AgentInstallResult>("/api/agents/install", jsonBody({ agent_id: agentId })),
  providers: () => request<ProvidersPayload>("/api/providers"),
  providerCliStatus: () => request<ProviderCliStatusPayload>("/api/providers/cli-status"),
  saveProviders: (payload: SaveProvidersPayload) =>
    request<ProvidersPayload>("/api/providers", jsonBody(payload)),
  refreshProviderModels: (id: string) =>
    request<ProvidersPayload>(
      `/api/providers/${encodeURIComponent(id)}/refresh-models`,
      jsonBody({}),
    ),
  profiles: () => request<ProfilesPayload>("/api/profiles"),
  saveProfiles: (payload: ProfilesPayload) =>
    request<ProfilesPayload>("/api/profiles", jsonBody(payload)),
  compare: (runIds: string[]) =>
    request<ComparePayload>(
      `/api/compare?runs=${encodeURIComponent(runIds.join(","))}`,
    ),
  planExperiment: (payload: CreateExperimentPayload) =>
    request<ExperimentPlanResponse>(
      "/api/launches",
      jsonBody({ ...payload, dry_run: true }),
    ),
  launchBatch: (payload: CreateExperimentPayload) =>
    request<LaunchBatchResponse>("/api/launches", jsonBody(payload)),
}
