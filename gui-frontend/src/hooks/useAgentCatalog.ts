import { useCallback, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

import { api, type BuiltinRuntime, type CustomRuntime } from "@/lib/api"

/* One catalog for "what runtimes exist and what are they called" — fed by
   /api/agents, which the backend derives from the adapter registry. The only
   per-runtime knowledge that stays hardcoded in the frontend is the icon
   mapping in components/brand.tsx (React components cannot travel over JSON).
   While the query is loading, labels fall back to the raw id (honest absence,
   never an invented name). */
export function useAgentCatalog() {
  const query = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  const builtin = useMemo<BuiltinRuntime[]>(() => query.data?.builtin ?? [], [query.data])
  const custom = useMemo<CustomRuntime[]>(
    () => (query.data?.custom ?? []).filter((agent) => !agent.error),
    [query.data],
  )
  const byId = useMemo(() => {
    const map: Record<string, { label: string; note: string; dockerCapable: boolean }> = {}
    for (const agent of builtin)
      map[agent.id] = { label: agent.label, note: agent.note, dockerCapable: agent.docker_capable }
    for (const agent of custom)
      map[agent.id] = {
        label: agent.label ?? agent.spec_id,
        note: agent.description ?? "",
        dockerCapable: Boolean(agent.docker_capable),
      }
    return map
  }, [builtin, custom])
  const agentLabel = useCallback((id: string) => byId[id]?.label ?? id, [byId])
  const agentNote = useCallback((id: string) => byId[id]?.note ?? "", [byId])
  const dockerCapableFor = useCallback(
    (id: string) => byId[id]?.dockerCapable ?? !id.startsWith("custom:"),
    [byId],
  )
  const builtinIds = useMemo(() => builtin.map((agent) => agent.id), [builtin])
  return { query, builtin, custom, agentLabel, agentNote, dockerCapableFor, builtinIds }
}
