import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ArrowLeft, ArrowRight, Loader2, Rocket } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { DirectoryPickerDialog } from "@/components/task-import"
import { AGENT_LABELS, runtimeFilters } from "@/components/brand"
import { ErrorNote } from "@/components/error-note"
import {
  api,
  type CreateExperimentPayload,
  type CustomRuntime,
  type ProviderFilter,
} from "@/lib/api"
import { NEW_RUN_STEPS } from "@/features/new-run/constants"
import { Stepper, ContractStatusBar, TaskFactsStrip } from "@/features/new-run/WizardChrome"
import { StepMode } from "@/features/new-run/steps/ModeStep"
import { StepTasks } from "@/features/new-run/steps/TasksStep"
import { StepContenders } from "@/features/new-run/steps/AgentsStep"
import { StepShared } from "@/features/new-run/steps/SharedConfigStep"
import { StepReview } from "@/features/new-run/steps/ReviewStep"
import { usePlanPreview } from "@/features/new-run/use-plan-preview"
import { useRunDraft, type RunPreset } from "@/features/new-run/use-run-draft"

export default function NewRun() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const preset = (location.state ?? {}) as RunPreset

  const tasklib = useQuery({ queryKey: ["tasklib"], queryFn: api.tasklib })
  const profilesQuery = useQuery({ queryKey: ["profiles"], queryFn: api.profiles })
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  const agentStatusQuery = useQuery({
    queryKey: ["agent-status"],
    // Fast path: local CLI probes only, no npm update check.
    queryFn: () => api.agentStatus(),
    enabled: agentsQuery.isSuccess,
    retry: false,
  })
  const agentStatusData = agentStatusQuery.data
  const agentStatusIsFetching = agentStatusQuery.isFetching
  const refetchAgentStatus = agentStatusQuery.refetch
  const agentStatusRetryCount = useRef(0)
  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: api.skills })
  const libraries = useMemo(
    () => (tasklib.data?.libraries ?? []).filter((library) => library.exists),
    [tasklib.data],
  )
  const recentLibraryDir = libraries[libraries.length - 1]?.dir
  const providers = providersQuery.data?.providers ?? []
  const agentStatuses = agentStatusQuery.data?.statuses ?? {}
  const customRuntimes = useMemo(
    () => (agentsQuery.data?.custom ?? []).filter((agent) => !agent.error),
    [agentsQuery.data],
  )
  const builtinCliPresent = useMemo(() => {
    const map: Record<string, boolean> = {}
    for (const agent of agentsQuery.data?.builtin ?? []) map[agent.id] = agent.cli.present
    return map
  }, [agentsQuery.data])
  const customByRuntime = useMemo(() => {
    const map: Record<string, CustomRuntime> = {}
    for (const agent of customRuntimes) map[agent.id] = agent
    return map
  }, [customRuntimes])
  const runtimeLabel = useCallback(
    (runtime: string) =>
      customByRuntime[runtime]?.label ??
      customByRuntime[runtime]?.spec_id ??
      AGENT_LABELS[runtime] ??
      runtime,
    [customByRuntime],
  )
  const dockerCapable = useCallback(
    (runtime: string) =>
      runtime.startsWith("custom:")
        ? Boolean(customByRuntime[runtime]?.docker_capable)
        : true,
    [customByRuntime],
  )
  /* Provider-compatibility filters, keyed by runtime id, from /api/agents. */
  const filterByRuntime = useMemo(() => runtimeFilters(agentsQuery.data), [agentsQuery.data])
  const filterFor = useCallback(
    (runtime: string): ProviderFilter | undefined => filterByRuntime[runtime],
    [filterByRuntime],
  )
  /* How --thinking-effort reaches each runtime (native switch vs prompt) and
     which levels its CLI really accepts, straight from the adapter registry
     via /api/agents. */
  const thinkingChannelFor = useCallback(
    (runtime: string): string =>
      runtime.startsWith("custom:")
        ? (customByRuntime[runtime]?.thinking_channel ?? "prompt")
        : (agentsQuery.data?.builtin.find((agent) => agent.id === runtime)?.thinking_channel ??
          "prompt"),
    [agentsQuery.data, customByRuntime],
  )
  const thinkingEffortsFor = useCallback(
    (runtime: string): string[] =>
      (runtime.startsWith("custom:")
        ? customByRuntime[runtime]?.thinking_efforts
        : agentsQuery.data?.builtin.find((agent) => agent.id === runtime)?.thinking_efforts) ?? [
        "default",
        "low",
        "medium",
        "high",
      ],
    [agentsQuery.data, customByRuntime],
  )

  const [step, setStep] = useState(0)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [preflightBlocked, setPreflightBlocked] = useState(false)
  const [savingProfile, setSavingProfile] = useState(false)
  const [installingAgentId, setInstallingAgentId] = useState<string | null>(null)

  const {
    mode,
    tasksDir,
    tasks,
    contenders,
    profileId,
    shared,
    perFields,
    expName,
    profiles: fullProfiles,
    rosteredProfiles,
    selectedProfile,
    launchProfileId,
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
    nextProfileId,
  } = useRunDraft({
    preset,
    ready: Boolean(profilesQuery.data && tasklib.data),
    profilesPayload: profilesQuery.data,
    libraries,
    providers,
    customByRuntime,
    filterFor,
    runtimeLabel,
  })

  useEffect(() => {
    const statuses = agentStatusData?.statuses
    if (!statuses || agentStatusIsFetching) return
    const hasRetryableLatestError = Object.values(statuses).some(
      (status) => status.present && Boolean(status.latest_error),
    )
    if (!hasRetryableLatestError) {
      agentStatusRetryCount.current = 0
      return
    }
    if (agentStatusRetryCount.current >= 2) return
    const retryTimer = window.setTimeout(() => {
      agentStatusRetryCount.current += 1
      refetchAgentStatus()
    }, 1500)
    return () => window.clearTimeout(retryTimer)
  }, [agentStatusData, agentStatusIsFetching, refetchAgentStatus])

  const installAgent = useCallback(
    async (agentId: string, label: string) => {
      setInstallingAgentId(agentId)
      try {
        const result = await api.installAgent(agentId)
        if (result.status === "installed") {
          toast.success(`${label} installed.`)
        } else {
          toast.error(`${label} install failed${result.stderr_tail ? `: ${result.stderr_tail}` : "."}`)
        }
        queryClient.invalidateQueries({ queryKey: ["agents"] })
        queryClient.invalidateQueries({ queryKey: ["agent-status"] })
      } catch (error) {
        toast.error((error as Error).message)
      } finally {
        setInstallingAgentId(null)
      }
    },
    [queryClient],
  )

  const previewPayload = useMemo<CreateExperimentPayload | null>(() => {
    if (!tasksDir || !contenders.length) return null
    return {
      name: expName.trim(),
      tasks_dir: effectiveTasksDir(),
      tasks,
      shared,
      contenders: apiContenders(),
      ...(launchProfileId ? { profile_id: launchProfileId } : {}),
    }
  }, [
    apiContenders,
    contenders.length,
    effectiveTasksDir,
    expName,
    launchProfileId,
    shared,
    tasks,
    tasksDir,
  ])
  const plan = usePlanPreview(previewPayload, step === NEW_RUN_STEPS.length - 1)

  if (
    tasklib.isPending ||
    profilesQuery.isPending ||
    providersQuery.isPending ||
    agentsQuery.isPending
  ) {
    return <Skeleton className="h-96" />
  }
  if (tasklib.isError) return <ErrorNote message={(tasklib.error as Error).message} />
  if (profilesQuery.isError) return <ErrorNote message={(profilesQuery.error as Error).message} />
  if (providersQuery.isError) return <ErrorNote message={(providersQuery.error as Error).message} />

  const activeLibrary = libraries.find((library) => library.dir === tasksDir)
  const libraryTasks = activeLibrary?.tasks ?? []
  const healthyTasks = libraryTasks.filter((task) => !task.error)
  /* The wizard requires an explicit task selection. The runner still supports
     an empty task list as "whole folder", but the GUI should not launch that
     ambiguous mode from this page. */
  const selectedTaskObjs = healthyTasks.filter((task) => tasks.includes(task.id))
  const taskCount = selectedTaskObjs.length
  const judgeConflicts = contenders.filter(
    (draft) =>
      draft.model.trim() &&
      draft.model.trim() === String(shared.evaluator_model ?? "").trim(),
  )

  /* Step gates. Mode (0) needs a resolvable choice; the original task/contender
     gates move one step later. */
  const canNext =
    step === 0
      ? mode === "custom" || (mode === "profile" && Boolean(selectedProfile?.roster?.length))
      : step === 1
        ? selectedTaskObjs.length > 0
        : step === 2
          ? contenders.length > 0
          : true

  /* Profile deviation is backend-owned and arrives with the dry-run plan. */
  const deviation = mode === "profile" ? plan.profileModifiedFields : []
  const deviated = mode === "profile" && plan.profileModified

  /* One create call, used by every launch exit. Passing profile_id makes the
     backend diff the effective payload against the profile and record any
     deviation in the run snapshot; omitting it launches bare. */
  const createAndGo = async (profileIdForLaunch?: string) => {
    if (selectedTaskObjs.length === 0) {
      setStep(1)
      throw new Error("Select at least one runnable task before continuing.")
    }
    const record = await api.launchBatch({
      name: expName.trim(),
      tasks_dir: effectiveTasksDir(),
      tasks,
      shared,
      contenders: apiContenders(),
      profile_id: profileIdForLaunch,
    })
    toast.success(`${record.id ?? expName} started: ${record.run_ids.length} runs.`)
    queryClient.invalidateQueries({ queryKey: ["runs"] })
    // One run reads best on its own page; several read best side by side.
    navigate(
      record.run_ids.length === 1
        ? `/runs/${encodeURIComponent(record.run_ids[0])}`
        : `/compare?runs=${encodeURIComponent(record.run_ids.join(","))}`,
    )
  }

  const primaryLaunch = async () => {
    setLaunching(true)
    try {
      await createAndGo(launchProfileId)
    } catch (error) {
      toast.error((error as Error).message)
      setLaunching(false)
    }
  }

  const updateProfileAndLaunch = async () => {
    if (!selectedProfile) return
    setLaunching(true)
    try {
      await persistCurrentProfile(selectedProfile.id, selectedProfile.name, false)
      await createAndGo(selectedProfile.id)
    } catch (error) {
      toast.error((error as Error).message)
      setLaunching(false)
    }
  }

  const saveAsNewProfileAndLaunch = async () => {
    setLaunching(true)
    try {
      const id = nextProfileId(expName)
      await persistCurrentProfile(id, expName.trim(), true)
      await createAndGo(id)
    } catch (error) {
      toast.error((error as Error).message)
      setLaunching(false)
    }
  }

  const saveConfigAsProfile = async () => {
    setSavingProfile(true)
    try {
      const id = nextProfileId(expName)
      await persistCurrentProfile(id, expName.trim(), true)
      toast.success(`Saved this configuration as profile "${expName.trim()}".`)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setSavingProfile(false)
    }
  }

  return (
    <div className="mx-auto grid w-full max-w-4xl gap-6 [&>*]:min-w-0">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight">New experiment</h1>
        <p className="max-w-[65ch] text-sm text-muted-foreground">
          One task set, one judge, many agents under test: comparable by construction.
        </p>
      </div>

      <Stepper current={step} onSelect={(target) => target < step && setStep(target)} />

      {step > 0 && mode === "profile" && selectedProfile && (
        <ContractStatusBar
          profileName={selectedProfile.name}
          rev={selectedProfile.rev}
          verified={Boolean(plan.plans)}
          checking={plan.loading}
          modified={deviated}
          fields={deviation}
        />
      )}

      {step > 1 && <TaskFactsStrip tasks={selectedTaskObjs} />}

      {step === 0 && (
        <StepMode
          mode={mode}
          profiles={fullProfiles}
          rosteredProfiles={rosteredProfiles}
          defaultProfileId={profilesQuery.data.default_profile_id}
          profileId={profileId}
          selectedProfile={selectedProfile}
          libraries={libraries}
          runtimeLabel={runtimeLabel}
          onChooseProfile={chooseProfile}
          onChooseCustom={chooseCustom}
        />
      )}
      {step === 1 && (
        <StepTasks
          libraries={libraries}
          tasksDir={tasksDir}
          tasks={tasks}
          setTasksDir={(dir) => {
            setTasksDir(dir)
            setTasks([])
          }}
          setTasks={setTasks}
          onOpenPicker={() => setPickerOpen(true)}
          onImported={() => queryClient.invalidateQueries({ queryKey: ["tasklib"] })}
          runtimeLabel={runtimeLabel}
        />
      )}
      {step === 2 && (
        <StepContenders
          providers={providers}
          customRuntimes={customRuntimes}
          customByRuntime={customByRuntime}
          builtinCliPresent={builtinCliPresent}
          agentStatuses={agentStatuses}
          statusLoading={agentStatusQuery.isPending || agentStatusQuery.isFetching}
          installingAgentId={installingAgentId}
          dockerCapable={dockerCapable}
          filterFor={filterFor}
          thinkingChannelFor={thinkingChannelFor}
          thinkingEffortsFor={thinkingEffortsFor}
          contenders={contenders}
          backend={String(shared.executor_backend ?? "local")}
          onAdd={addContender}
          onInstall={installAgent}
          onSetup={() => navigate("/agents")}
          onUpdate={updateContender}
          onRemove={removeContender}
        />
      )}
      {step === 3 && (
        <StepShared
          profiles={profilesQuery.data.profiles}
          persisted={Boolean(profilesQuery.data.persisted)}
          defaultProfileId={profilesQuery.data.default_profile_id}
          profileId={profileId}
          onSelectProfile={(id) => {
            const profile = profilesQuery.data!.profiles.find((item) => item.id === id)
            if (profile) {
              setProfileId(id)
              setShared(profile.shared)
              setPerFields(
                profile.per_contender_fields.length ? profile.per_contender_fields : ["model"],
              )
            }
          }}
          providers={providers}
          skills={skillsQuery.data}
          tasksDir={tasksDir}
          selectedTasks={selectedTaskObjs}
          shared={shared}
          setShared={setShared}
          setSharedField={setSharedField}
          perFields={perFields}
          setPerFields={setPerFields}
          judgeConflicts={judgeConflicts.length}
          customRuntimes={customRuntimes}
          customByRuntime={customByRuntime}
          filterFor={filterFor}
          runtimeLabel={runtimeLabel}
          localRuntimeNames={[
            ...new Set(
              contenders
                .filter((draft) => !dockerCapable(draft.runtime))
                .map((draft) => runtimeLabel(draft.runtime)),
            ),
          ]}
        />
      )}
      {step === 4 && (
        <StepReview
          expName={expName}
          setExpName={setExpName}
          taskCount={taskCount}
          tasksDir={tasksDir}
          contenders={contenders}
          shared={shared}
          plan={plan}
          judgeConflicts={judgeConflicts.length}
          runtimeLabel={runtimeLabel}
          onPreflightBlocked={setPreflightBlocked}
          mode={mode}
          profileName={selectedProfile?.name ?? null}
          profileRev={selectedProfile?.rev ?? null}
          deviated={deviated}
          launching={launching}
          savingProfile={savingProfile}
          onUpdateProfileLaunch={updateProfileAndLaunch}
          onSaveAsNewLaunch={saveAsNewProfileAndLaunch}
          onSaveConfigAsProfile={saveConfigAsProfile}
        />
      )}

      <div className="flex min-w-0 items-center justify-between gap-3">
        <Button variant="outline" disabled={step === 0} onClick={() => setStep(step - 1)}>
          <ArrowLeft /> Back
        </Button>
        {step === 4 && preflightBlocked && plan.plans && (
          <span className="text-right text-xs text-fail-ink">
            Launch is disabled until the readiness checks below pass.
          </span>
        )}
        {step < NEW_RUN_STEPS.length - 1 ? (
          <Button disabled={!canNext} onClick={() => setStep(step + 1)}>
            Next <ArrowRight />
          </Button>
        ) : (
          <Button
            disabled={!plan.plans || launching || savingProfile || preflightBlocked}
            onClick={primaryLaunch}
          >
            {launching ? <Loader2 className="animate-spin" /> : <Rocket />}
            {launching
              ? "Launching…"
              : mode === "profile" && deviated
                ? "Launch as ad-hoc test"
                : `Launch ${contenders.length} runs`}
          </Button>
        )}
      </div>

      <DirectoryPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        initialPath={recentLibraryDir}
        title="Choose a task folder"
        description="Pick a folder that contains task packages."
        onSelect={async (path) => {
          try {
            await api.registerTasksDir(path)
            await queryClient.invalidateQueries({ queryKey: ["tasklib"] })
            setTasksDir(path)
            setTasks([])
          } catch (error) {
            toast.error((error as Error).message)
          }
        }}
      />
    </div>
  )
}
