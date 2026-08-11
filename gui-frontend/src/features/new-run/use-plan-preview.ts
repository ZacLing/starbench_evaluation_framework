import { useEffect, useRef, useState } from "react"
import { api, type CreateExperimentPayload } from "@/lib/api"
import type { PlanPreview } from "./types"

const EMPTY_PREVIEW: PlanPreview = {
  plans: null,
  estimate: null,
  profileModified: false,
  profileModifiedFields: [],
  error: null,
  loading: false,
}

export function usePlanPreview(
  payload: CreateExperimentPayload | null,
  enabled: boolean,
): PlanPreview {
  const [preview, setPreview] = useState<PlanPreview>(EMPTY_PREVIEW)
  const requestVersion = useRef(0)

  useEffect(() => {
    requestVersion.current += 1
    const version = requestVersion.current
    if (!enabled || !payload) {
      setPreview(EMPTY_PREVIEW)
      return
    }

    // Invalidate the previous plan immediately. A stale, formerly valid plan
    // must never keep Launch enabled while the edited draft is being checked.
    setPreview({ ...EMPTY_PREVIEW, loading: true })
    const timer = window.setTimeout(async () => {
      try {
        const result = await api.planExperiment(payload)
        if (version !== requestVersion.current) return
        setPreview({
          plans: result.plans,
          estimate: result.execution_estimate,
          profileModified: result.profile_modified,
          profileModifiedFields: result.profile_modified_fields,
          error: null,
          loading: false,
        })
      } catch (error) {
        if (version !== requestVersion.current) return
        setPreview({
          ...EMPTY_PREVIEW,
          error: (error as Error).message,
        })
      }
    }, 350)

    return () => window.clearTimeout(timer)
  }, [enabled, payload])

  return preview
}
