import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { compatibleProviders } from "@/components/brand"
import {
  api,
  type AiProvider,
  type Contender,
  type CustomRuntime,
  type Profile,
  type ProfilesPayload,
  type ProviderFilter,
  type RosterEntry,
  type SharedConfig,
} from "@/lib/api"
import {
  nextContenderKey,
  resolveLibraryDir,
  timestampName,
  uniqueProfileId,
} from "./helpers"
import type { ContenderDraft, LibraryRef, WizardMode } from "./types"

export interface RunPreset {
  tasksDir?: string
  taskIds?: string[]
}

interface UseRunDraftOptions {
  preset: RunPreset
  ready: boolean
  profilesPayload?: ProfilesPayload
  libraries: LibraryRef[]
  providers: AiProvider[]
  customByRuntime: Record<string, CustomRuntime>
  filterFor: (runtime: string) => ProviderFilter | undefined
  runtimeLabel: (runtime: string) => string
}

export function useRunDraft({
  preset,
  ready,
  profilesPayload,
  libraries,
  providers,
  customByRuntime,
  filterFor,
  runtimeLabel,
}: UseRunDraftOptions) {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<WizardMode>("profile")
  const [tasksDir, setTasksDir] = useState(preset.tasksDir ?? "")
  const [tasks, setTasks] = useState<string[]>(preset.taskIds ?? [])
  const [contenders, setContenders] = useState<ContenderDraft[]>([])
  const [profileId, setProfileId] = useState<string | null>(null)
  const [shared, setShared] = useState<Partial<SharedConfig>>({})
  const [perFields, setPerFields] = useState<string[]>(["model"])
  const [expName, setExpName] = useState(() => timestampName("exp"))

  const profiles = useMemo(() => profilesPayload?.profiles ?? [], [profilesPayload])
  const rosteredProfiles = useMemo(
    () => profiles.filter((profile) => (profile.roster?.length ?? 0) > 0),
    [profiles],
  )
  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === profileId) ?? null,
    [profiles, profileId],
  )

  const appliedProfileRef = useRef<string | null>(null)
  const applyProfile = useCallback(
    (profile: Profile) => {
      const taskSet = profile.task_set
      if (taskSet?.tasks_dir) {
        const library = resolveLibraryDir(taskSet.tasks_dir, libraries)
        if (library) {
          setTasksDir(library.dir)
          const runnable = new Set(
            library.tasks.filter((task) => !task.error).map((task) => task.id),
          )
          setTasks((taskSet.task_ids ?? []).filter((id) => runnable.has(id)))
        }
      }
      setContenders(
        (profile.roster ?? []).map((entry) => {
          const pinned =
            entry.provider_id && providers.some((provider) => provider.id === entry.provider_id)
          const providerId = pinned
            ? entry.provider_id!
            : compatibleProviders(filterFor(entry.agent), providers, entry.agent)[0]?.id ??
              entry.provider_id ??
              ""
          return {
            key: nextContenderKey(),
            runtime: entry.agent,
            provider_id: providerId,
            model: entry.model ?? "",
            thinking_effort: entry.thinking_effort ?? "none",
          }
        }),
      )
      setShared(profile.shared ?? {})
      setPerFields(
        profile.per_contender_fields?.length ? profile.per_contender_fields : ["model"],
      )
      appliedProfileRef.current = profile.id
    },
    [filterFor, libraries, providers],
  )

  const chooseProfile = useCallback(
    (id: string) => {
      const profile = profiles.find((item) => item.id === id)
      if (!profile) return
      setMode("profile")
      setProfileId(id)
      applyProfile(profile)
    },
    [applyProfile, profiles],
  )

  const chooseCustom = useCallback(() => {
    setMode("custom")
    if (appliedProfileRef.current !== null) {
      setContenders([])
      appliedProfileRef.current = null
    }
  }, [])

  const initialized = useRef(false)
  useEffect(() => {
    if (initialized.current || !ready || !profilesPayload) return
    initialized.current = true
    const chosen =
      rosteredProfiles.find(
        (profile) => profile.id === profilesPayload.default_profile_id,
      ) ??
      rosteredProfiles[0] ??
      profiles.find((profile) => profile.id === profilesPayload.default_profile_id) ??
      profiles[0]
    if (!chosen) return
    const hasPreset = Boolean(preset.tasksDir || preset.taskIds?.length)
    const initialMode: WizardMode = !hasPreset && rosteredProfiles.length ? "profile" : "custom"
    setMode(initialMode)
    setProfileId(chosen.id)
    if (initialMode === "profile") {
      applyProfile(chosen)
    } else {
      setShared(chosen.shared)
      setPerFields(
        chosen.per_contender_fields?.length ? chosen.per_contender_fields : ["model"],
      )
    }
  }, [applyProfile, preset.taskIds, preset.tasksDir, profiles, profilesPayload, ready, rosteredProfiles])

  useEffect(() => {
    if (!tasksDir && libraries.length) {
      const withTasks = libraries.find((library) => library.tasks.length) ?? libraries[0]
      setTasksDir(withTasks.dir)
    }
  }, [libraries, tasksDir])

  const effectiveTasksDir = useCallback(() => {
    if (mode === "profile" && selectedProfile?.task_set) {
      const library = resolveLibraryDir(selectedProfile.task_set.tasks_dir, libraries)
      if (library?.dir === tasksDir) return selectedProfile.task_set.tasks_dir
    }
    return tasksDir
  }, [libraries, mode, selectedProfile, tasksDir])

  const setSharedField = useCallback(
    (key: keyof SharedConfig, value: unknown) =>
      setShared((current) => ({ ...current, [key]: value })),
    [],
  )

  const addContender = useCallback(
    (runtime: string) => {
      const compatible = compatibleProviders(filterFor(runtime), providers, runtime)
      const provider = compatible.find((item) => item.models.length) ?? compatible[0]
      setContenders((current) => [
        ...current,
        {
          key: nextContenderKey(),
          runtime,
          provider_id: provider?.id ?? "",
          model: provider?.models[0] ?? "",
          thinking_effort: "none",
        },
      ])
    },
    [filterFor, providers],
  )

  const updateContender = useCallback((key: string, patch: Partial<ContenderDraft>) => {
    setContenders((current) =>
      current.map((item) => (item.key === key ? { ...item, ...patch } : item)),
    )
  }, [])

  const removeContender = useCallback((key: string) => {
    setContenders((current) => current.filter((item) => item.key !== key))
  }, [])

  const apiContenders = useCallback((): Contender[] => {
    return contenders.flatMap((draft) => {
      const custom = customByRuntime[draft.runtime]
      const provider = providers.find((item) => item.id === draft.provider_id)
      const providerless = custom && (custom.protocol ?? "none") === "none"
      if (!provider && !providerless) return []
      const model = custom && !custom.model_flag ? "" : draft.model.trim()
      return [
        {
          label: `${runtimeLabel(draft.runtime)} ${model || "default"}`.trim(),
          agent: draft.runtime,
          provider_id: draft.provider_id,
          model,
          thinking_effort: draft.thinking_effort,
        },
      ]
    })
  }, [contenders, customByRuntime, providers, runtimeLabel])

  const profileFromDraft = useCallback(
    (id: string, name: string): Profile => {
      const roster: RosterEntry[] = contenders.map((draft) => ({
        agent: draft.runtime,
        ...(draft.model.trim() ? { model: draft.model.trim() } : {}),
        ...(draft.provider_id ? { provider_id: draft.provider_id } : {}),
        ...(draft.thinking_effort && draft.thinking_effort !== "none"
          ? { thinking_effort: draft.thinking_effort }
          : {}),
      }))
      const profile: Profile = {
        id,
        name,
        shared,
        per_contender_fields: perFields.length ? perFields : ["model"],
        roster,
      }
      const keepStored =
        mode === "profile" &&
        selectedProfile?.task_set &&
        resolveLibraryDir(selectedProfile.task_set.tasks_dir, libraries)?.dir === tasksDir
      const storedDir = keepStored ? selectedProfile.task_set!.tasks_dir : tasksDir
      if (storedDir) profile.task_set = { tasks_dir: storedDir, task_ids: tasks }
      return profile
    },
    [contenders, libraries, mode, perFields, selectedProfile, shared, tasks, tasksDir],
  )

  const persistCurrentProfile = useCallback(
    async (id: string, name: string, asNew: boolean) => {
      const target = profileFromDraft(id, name)
      const next = asNew
        ? [...profiles, target]
        : profiles.map((profile) => (profile.id === target.id ? target : profile))
      await api.saveProfiles({
        default_profile_id: profilesPayload?.default_profile_id ?? null,
        profiles: next,
      })
      await queryClient.invalidateQueries({ queryKey: ["profiles"] })
    },
    [profileFromDraft, profiles, profilesPayload?.default_profile_id, queryClient],
  )

  return {
    mode,
    tasksDir,
    tasks,
    contenders,
    profileId,
    shared,
    perFields,
    expName,
    profiles,
    rosteredProfiles,
    selectedProfile,
    launchProfileId: mode === "profile" && profileId ? profileId : undefined,
    setTasksDir,
    setTasks,
    setProfileId,
    setShared,
    setPerFields,
    setExpName,
    chooseProfile,
    chooseCustom,
    effectiveTasksDir,
    setSharedField,
    addContender,
    updateContender,
    removeContender,
    apiContenders,
    persistCurrentProfile,
    nextProfileId: (base: string) => uniqueProfileId(profiles, base),
  }
}
