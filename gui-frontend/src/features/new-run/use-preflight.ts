import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { api, type ExperimentPlanItem, type PreflightCheck } from "@/lib/api"

export interface PreflightGroup {
  key: string
  agent: string
  checks: PreflightCheck[]
}

export function usePreflight(plans: ExperimentPlanItem[] | null) {
  const paramSets = useMemo(() => {
    if (!plans) return [] as { key: string; agent: string; params: Record<string, string> }[]
    const sets = new Map<string, { agent: string; params: Record<string, string> }>()
    for (const item of plans) {
      const params = {
        executor_agent: item.agent,
        evaluator_agent: item.evaluator_agent ?? "codex",
        executor_backend: item.backend,
        docker_image: item.docker_image ?? "",
        executor_auth_mode: item.executor_auth_mode ?? "env",
        evaluator_auth_mode: item.evaluator_auth_mode ?? "env",
        executor_bin: item.executor_bin ?? "",
        evaluator_bin: item.evaluator_bin ?? "",
        executor_opencode_api_key_env: item.executor_opencode_api_key_env ?? "",
        evaluator_opencode_api_key_env: item.evaluator_opencode_api_key_env ?? "",
        executor_env_keys: (item.executor_credential_env_keys ?? []).join(","),
        evaluator_env_keys: (item.evaluator_credential_env_keys ?? []).join(","),
      }
      const key = Object.entries(params)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, value]) => `${name}=${value}`)
        .join("|")
      if (!sets.has(key)) sets.set(key, { agent: item.agent, params })
    }
    return [...sets.entries()].map(([key, value]) => ({ key, ...value }))
  }, [plans])

  const query = useQuery({
    queryKey: ["preflight", paramSets.map((set) => set.key).join(";")],
    enabled: paramSets.length > 0,
    queryFn: async (): Promise<PreflightGroup[]> =>
      Promise.all(
        paramSets.map(async (set) => ({
          key: set.key,
          agent: set.agent,
          checks: (await api.preflight(set.params)).checks,
        })),
      ),
  })

  const groups = query.data ?? []
  const hasFailure = groups.some((group) =>
    group.checks.some((check) => check.status === "fail"),
  )
  const blocked = paramSets.length > 0 && (query.isPending || query.isError || hasFailure)

  return {
    groups,
    blocked,
    loading: query.isPending && paramSets.length > 0,
    error: query.error ? (query.error as Error).message : null,
  }
}
