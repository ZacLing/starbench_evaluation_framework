import type { AiProvider, ModelReasoning, Profile } from "@/lib/api"
import type { LibraryRef } from "./types"

/* "default" = leave the runtime/model default alone. Legacy drafts and
   profiles spell it "none"; canonicalEffort folds that in one place. */
export const DEFAULT_EFFORT = "default"

export function canonicalEffort(value: string | undefined | null): string {
  return !value || value === "none" ? DEFAULT_EFFORT : value
}

/* The model's own published effort table (from the runtime's model catalog,
   surfaced on the provider). Null → the UI falls back to the runtime's
   declared level set. */
export function modelEffortTable(
  provider: AiProvider | undefined,
  model: string | undefined,
): ModelReasoning | null {
  if (!provider || !model) return null
  return provider.model_reasoning?.[model] ?? null
}

/* The options the effort picker offers for one contender: the model's own
   table when it publishes one, otherwise the runtime declaration. "default"
   is always offered first. */
export function effortOptions(
  provider: AiProvider | undefined,
  model: string | undefined,
  runtimeEfforts: string[],
): { efforts: string[]; catalog: ModelReasoning | null } {
  const catalog = modelEffortTable(provider, model)
  if (!catalog) return { efforts: runtimeEfforts.map(canonicalEffort), catalog: null }
  return { efforts: [DEFAULT_EFFORT, ...catalog.levels], catalog }
}

export function resolveLibraryDir(
  tasksDir: string,
  libraries: LibraryRef[],
): LibraryRef | undefined {
  if (!tasksDir) return undefined
  return (
    libraries.find((library) => library.dir === tasksDir) ??
    libraries.find((library) => library.dir.endsWith("/" + tasksDir)) ??
    libraries.find(
      (library) => library.dir.split("/").pop() === tasksDir.split("/").pop(),
    )
  )
}

export function timestampName(prefix: string): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${prefix}_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(
    now.getHours(),
  )}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

function slugId(text: string): string {
  const slug = text
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[^a-z0-9]+/, "")
    .replace(/-+$/g, "")
  return slug || timestampName("profile")
}

export function deviationLabel(dimension: string): string {
  const labels: Record<string, string> = {
    roster: "agents",
    task_set: "task set",
    evaluator_model: "judge model",
    evaluator_agent: "judge runtime",
    evaluator_timeout_seconds: "judge timeout",
    judge_mode: "judge mode",
    batch_size: "batch size",
    max_evaluator_parallel: "judge parallelism",
    web_search_mode: "web search",
    claude_max_turns: "max turns",
  }
  return labels[dimension] ?? dimension.replace(/_/g, " ")
}

export function uniqueProfileId(profiles: Profile[], base: string): string {
  const ids = new Set(profiles.map((profile) => profile.id))
  const root = slugId(base)
  if (!ids.has(root)) return root
  let counter = 2
  while (ids.has(`${root}-${counter}`)) counter += 1
  return `${root}-${counter}`
}

let contenderCounter = 0

export function nextContenderKey(): string {
  contenderCounter += 1
  return `c${contenderCounter}`
}

export function shortenPath(path: string): string {
  const parts = path.split("/")
  return parts.length > 3 ? `…/${parts.slice(-3).join("/")}` : path
}
