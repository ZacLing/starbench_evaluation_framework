import type { Profile } from "@/lib/api"
import type { LibraryRef } from "./types"

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

export function slugId(text: string): string {
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
