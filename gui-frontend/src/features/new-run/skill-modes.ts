import type { SharedConfig } from "@/lib/api"

export type SkillMode = "off" | "available" | "required"

export function getSkillMode(
  config: Partial<SharedConfig>,
  id: string,
  coveredByGroup: boolean,
): SkillMode {
  if ((config.required_executor_skills ?? []).includes(id)) return "required"
  if (coveredByGroup || (config.executor_skills ?? []).includes(id)) return "available"
  return "off"
}

export function setSkillMode(
  config: Partial<SharedConfig>,
  id: string,
  requestedMode: SkillMode,
  coveredByGroup: boolean,
): Partial<SharedConfig> {
  const available = new Set(config.executor_skills ?? [])
  const required = new Set(config.required_executor_skills ?? [])
  const mode = requestedMode === "off" && coveredByGroup ? "available" : requestedMode

  available.delete(id)
  required.delete(id)
  if (mode === "required") required.add(id)
  if (mode === "available" && !coveredByGroup) available.add(id)

  return {
    ...config,
    executor_skills: [...available],
    required_executor_skills: [...required],
  }
}
