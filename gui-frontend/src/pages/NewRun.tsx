import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  DownloadCloud,
  FolderSearch,
  Loader2,
  Plus,
  Rocket,
  Save,
  Scale,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { DirectoryPickerDialog, ImportDropzone } from "@/components/task-import"
import { TaskBadges } from "@/components/task-badges"
import { fmtDuration } from "@/lib/format"
import {
  AGENT_LABELS,
  AGENT_NOTES,
  AgentIcon,
  compatibleProviders,
  runtimeFilters,
} from "@/components/brand"
import { ProviderModelPicker } from "@/components/model-picker"
import { ErrorNote } from "@/pages/Dashboard"
import {
  api,
  type AgentRuntimeStatus,
  type AiProvider,
  type Contender,
  type CustomRuntime,
  type ExecutionEstimate,
  type PreflightCheck,
  type ExperimentPlanItem,
  type Profile,
  type ProviderFilter,
  type SharedConfig,
  type SkillsPayload,
  type TaskPackage,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const JUDGE_MODES = [
  { value: "single", label: "Single judge", note: "One session grades all rubrics. Fast." },
  { value: "parallel", label: "Per-rubric judges", note: "Independent judge per rubric. Strict." },
  { value: "both", label: "Both", note: "Run both to compare their agreement." },
]

/* Only true run-time knobs are per-contender; endpoints and credentials
   belong to providers (the resource side). Thinking effort is inherently
   per-agent (like the model choice), so it lives on the Claude Code cards
   directly rather than as a toggle here. */
const PER_FIELD_OPTIONS = [{ id: "model", label: "Model", locked: true }]

const STEPS = ["Tasks", "Agents", "Shared config", "Review & launch"]

/* A contender IS an agent runtime; provider+model is its configuration. */
const RUNTIMES = ["claude", "codex", "gemini", "grok", "opencode"] as const

interface ContenderDraft {
  key: string
  runtime: string
  provider_id: string
  model: string
  thinking_effort: string
}

function timestampName(prefix: string): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${prefix}_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(
    now.getHours(),
  )}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

/* Contenders and the judge are sent as pure references to a provider
   (`provider_id`); the backend resolves the auth mode, gateway flags, codex
   config overrides and env injection from the runtime's channel + the provider
   (see gui/injection.py). No wire-protocol knowledge lives in this view. */

let contenderCounter = 0

export default function NewRun() {
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const preset = (location.state ?? {}) as { tasksDir?: string; taskIds?: string[] }

  const tasklib = useQuery({ queryKey: ["tasklib"], queryFn: api.tasklib })
  const profilesQuery = useQuery({ queryKey: ["profiles"], queryFn: api.profiles })
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  const agentStatusQuery = useQuery({
    queryKey: ["agent-status"],
    queryFn: api.agentStatus,
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
        "none",
        "low",
        "medium",
        "high",
      ],
    [agentsQuery.data, customByRuntime],
  )

  const [step, setStep] = useState(0)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [launching, setLaunching] = useState(false)
  const [tasksDir, setTasksDir] = useState(preset.tasksDir ?? "")
  const [tasks, setTasks] = useState<string[]>(preset.taskIds ?? [])
  const [contenders, setContenders] = useState<ContenderDraft[]>([])
  const [profileId, setProfileId] = useState<string | null>(null)
  const [shared, setShared] = useState<Partial<SharedConfig>>({})
  const [perFields, setPerFields] = useState<string[]>(["model"])
  const [expName, setExpName] = useState(() => timestampName("exp"))
  const [preflightBlocked, setPreflightBlocked] = useState(false)
  const [installingAgentId, setInstallingAgentId] = useState<string | null>(null)

  useEffect(() => {
    if (!profilesQuery.data || profileId !== null) return
    const payload = profilesQuery.data
    const chosen =
      payload.profiles.find((profile) => profile.id === payload.default_profile_id) ??
      payload.profiles[0]
    if (chosen) {
      setProfileId(chosen.id)
      setShared(chosen.shared)
      setPerFields(chosen.per_contender_fields.length ? chosen.per_contender_fields : ["model"])
    }
  }, [profilesQuery.data, profileId])

  useEffect(() => {
    if (!tasksDir && libraries.length) {
      const withTasks = libraries.find((library) => library.tasks.length) ?? libraries[0]
      setTasksDir(withTasks.dir)
    }
  }, [libraries, tasksDir])

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

  const setSharedField = useCallback(
    (key: keyof SharedConfig, value: unknown) =>
      setShared((current) => ({ ...current, [key]: value })),
    [],
  )

  const addContender = (runtime: string) => {
    contenderCounter += 1
    const compatible = compatibleProviders(filterFor(runtime), providers, runtime)
    const provider = compatible.find((item) => item.models.length) ?? compatible[0]
    setContenders((current) => [
      ...current,
      {
        key: `c${contenderCounter}`,
        runtime,
        provider_id: provider?.id ?? "",
        model: provider?.models[0] ?? "",
        thinking_effort: "none",
      },
    ])
  }

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

  const updateContender = (key: string, patch: Partial<ContenderDraft>) =>
    setContenders((current) =>
      current.map((item) => (item.key === key ? { ...item, ...patch } : item)),
    )

  const apiContenders = useCallback((): Contender[] => {
    return contenders.flatMap((draft) => {
      const custom = customByRuntime[draft.runtime]
      const provider = providers.find((item) => item.id === draft.provider_id)
      const providerless = custom && (custom.protocol ?? "none") === "none"
      if (!provider && !providerless) return []
      /* A custom runtime without a model flag cannot receive a model choice. */
      const model = custom && !custom.model_flag ? "" : draft.model.trim()
      /* Pure reference: the backend resolves auth/gateway/env from provider_id. */
      return [
        {
          label: `${runtimeLabel(draft.runtime)} ${model || "default"}`.trim(),
          agent: draft.runtime,
          provider_id: draft.provider_id,
          model,
          /* Thinking effort is always sent; it only affects Claude Code. */
          thinking_effort: draft.thinking_effort,
        },
      ]
    })
  }, [contenders, providers, customByRuntime, runtimeLabel])

  /* Authoritative plan preview on the review step. */
  const [plan, setPlan] = useState<{
    plans: ExperimentPlanItem[] | null
    estimate: ExecutionEstimate | null
    error: string | null
  }>({
    plans: null,
    estimate: null,
    error: null,
  })
  const planTimer = useRef<ReturnType<typeof setTimeout>>(null)
  useEffect(() => {
    if (step !== 3 || !tasksDir || !contenders.length) return
    if (planTimer.current) clearTimeout(planTimer.current)
    planTimer.current = setTimeout(async () => {
      try {
        const result = await api.createExperiment({
          name: expName.trim(),
          tasks_dir: tasksDir,
          tasks,
          shared,
          contenders: apiContenders(),
          dry_run: true,
        })
        setPlan({
          plans: result.plans,
          estimate: result.execution_estimate ?? null,
          error: null,
        })
      } catch (error) {
        setPlan({ plans: null, estimate: null, error: (error as Error).message })
      }
    }, 350)
    return () => {
      if (planTimer.current) clearTimeout(planTimer.current)
    }
  }, [step, expName, tasksDir, tasks, shared, apiContenders, contenders.length])

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
  const brokenCount = libraryTasks.length - healthyTasks.length
  /* The tasks this experiment will actually run: the explicit selection, or
     every healthy package when nothing is checked. Broken packages are never
     runnable, so they never count. */
  const selectedTaskObjs = tasks.length
    ? healthyTasks.filter((task) => tasks.includes(task.id))
    : healthyTasks
  const taskCount = selectedTaskObjs.length
  const judgeConflicts = contenders.filter(
    (draft) =>
      draft.model.trim() &&
      draft.model.trim() === String(shared.evaluator_model ?? "").trim(),
  )

  const canNext =
    step === 0
      ? healthyTasks.length > 0 && (tasks.length > 0 || brokenCount === 0)
      : step === 1
        ? contenders.length > 0
        : true

  const launch = async () => {
    setLaunching(true)
    try {
      const record = await api.createExperiment({
        name: expName.trim(),
        tasks_dir: tasksDir,
        tasks,
        shared,
        contenders: apiContenders(),
      })
      toast.success(`Experiment ${record.name ?? expName} started: ${contenders.length} runs.`)
      queryClient.invalidateQueries({ queryKey: ["experiments"] })
      navigate(`/experiments/${encodeURIComponent(expName.trim())}`)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div className="mx-auto grid max-w-4xl gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">New experiment</h1>
        <p className="text-sm text-muted-foreground">
          One task set, one judge, many agents under test: comparable by construction.
        </p>
      </div>

      <Stepper current={step} onSelect={(target) => target < step && setStep(target)} />

      {step > 0 && <TaskFactsStrip tasks={selectedTaskObjs} />}

      {step === 0 && (
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
        />
      )}
      {step === 1 && (
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
          onRemove={(key) =>
            setContenders((current) => current.filter((item) => item.key !== key))
          }
        />
      )}
      {step === 2 && (
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
      {step === 3 && (
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
        />
      )}

      <div className="flex items-center justify-between gap-3">
        <Button variant="outline" disabled={step === 0} onClick={() => setStep(step - 1)}>
          <ArrowLeft /> Back
        </Button>
        {step === 3 && preflightBlocked && plan.plans && (
          <span className="text-right text-xs text-fail-ink">
            Launch is disabled until the readiness checks below pass.
          </span>
        )}
        {step < STEPS.length - 1 ? (
          <Button disabled={!canNext} onClick={() => setStep(step + 1)}>
            Next <ArrowRight />
          </Button>
        ) : (
          <Button disabled={!plan.plans || launching || preflightBlocked} onClick={launch}>
            {launching ? <Loader2 className="animate-spin" /> : <Rocket />}
            {launching ? "Launching…" : `Launch ${contenders.length} runs`}
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

/* ---------- stepper ---------- */

function Stepper({ current, onSelect }: { current: number; onSelect: (step: number) => void }) {
  return (
    <ol className="flex items-center gap-2">
      {STEPS.map((label, index) => {
        const done = index < current
        const active = index === current
        return (
          <li key={label} className="flex min-w-0 flex-1 items-center gap-2">
            <button
              type="button"
              disabled={index > current}
              onClick={() => onSelect(index)}
              className={cn(
                "flex min-w-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                active ? "font-semibold text-foreground" : "text-muted-foreground",
                done && "hover:text-foreground",
              )}
            >
              <span
                className={cn(
                  "grid size-6 shrink-0 place-content-center rounded-full border text-xs font-semibold",
                  active && "border-primary bg-primary text-primary-foreground",
                  done && "border-pass-ink/40 bg-pass-soft text-pass-ink",
                  !active && !done && "border-border bg-muted text-muted-foreground",
                )}
              >
                {done ? <Check className="size-3.5" /> : index + 1}
              </span>
              <span className="truncate">{label}</span>
            </button>
            {index < STEPS.length - 1 && <div className="h-px flex-1 bg-border" />}
          </li>
        )
      })}
    </ol>
  )
}

/* ---------- step 1: tasks ---------- */

function StepTasks({
  libraries,
  tasksDir,
  tasks,
  setTasksDir,
  setTasks,
  onOpenPicker,
  onImported,
}: {
  libraries: { dir: string; tasks: TaskPackage[] }[]
  tasksDir: string
  tasks: string[]
  setTasksDir: (dir: string) => void
  setTasks: (tasks: string[]) => void
  onOpenPicker: () => void
  onImported: () => void
}) {
  const library = libraries.find((item) => item.dir === tasksDir)
  return (
    <Card>
      <CardContent className="grid gap-5">
        <div className="grid gap-2">
          <Label>Task folder</Label>
          <div className="flex flex-wrap items-center gap-2">
            {libraries.map((item) => (
              <button
                key={item.dir}
                type="button"
                onClick={() => setTasksDir(item.dir)}
                className={cn(
                  "max-w-full truncate rounded-md border px-3 py-1.5 font-mono text-xs transition-colors",
                  item.dir === tasksDir
                    ? "border-primary bg-accent text-accent-foreground"
                    : "hover:border-primary/40",
                )}
                title={item.dir}
              >
                …/{item.dir.split("/").slice(-2).join("/")}
                <span className="ml-2 text-muted-foreground">{item.tasks.length}</span>
              </button>
            ))}
            <Button variant="outline" size="sm" onClick={onOpenPicker}>
              <FolderSearch /> Browse…
            </Button>
          </div>
        </div>

        {library && library.tasks.length > 0 ? (
          <div className="grid gap-2">
            <div className="flex items-baseline justify-between">
              <Label>Tasks to run</Label>
              <span className="text-xs text-muted-foreground">
                {tasks.length
                  ? `${tasks.length} of ${library.tasks.filter((task) => !task.error).length} selected`
                  : `all ${library.tasks.filter((task) => !task.error).length} runnable will run`}
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {library.tasks.map((task) => {
                const checked = tasks.includes(task.id)
                const broken = Boolean(task.error)
                return (
                  <label
                    key={task.dir_name}
                    className={cn(
                      "flex items-start gap-3 rounded-md border p-3 transition-colors",
                      broken
                        ? "cursor-not-allowed border-fail-ink/40 bg-fail-soft/30"
                        : checked
                          ? "cursor-pointer border-primary bg-accent/60"
                          : "cursor-pointer hover:border-primary/40",
                    )}
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={checked}
                      disabled={broken}
                      onCheckedChange={(value) =>
                        setTasks(
                          value ? [...tasks, task.id] : tasks.filter((id) => id !== task.id),
                        )
                      }
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-sm font-medium">
                        {task.id}
                      </span>
                      {broken ? (
                        <span className="block text-xs text-fail-ink">
                          Not runnable: {task.error}
                        </span>
                      ) : (
                        <>
                          <span className="block truncate text-xs text-muted-foreground">
                            {task.name} · {task.rubric_count} rubrics
                          </span>
                          {task.warning && (
                            <span className="block text-xs text-warn-ink">{task.warning}</span>
                          )}
                          <span className="mt-1 block">
                            <TaskBadges task={task} />
                          </span>
                        </>
                      )}
                    </span>
                  </label>
                )
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              Leave everything unchecked to run the whole folder.
            </p>
            {library.tasks.some((task) => task.error) && (
              <p className="text-xs text-warn-ink">
                This folder contains broken packages. Pick the tasks to run explicitly; the
                runner stops on a broken package when asked to run the whole folder.
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No task packages in this folder. Import one below or browse to another folder.
          </p>
        )}

        {tasksDir && <ImportDropzone compact targetDir={tasksDir} onImported={onImported} />}
      </CardContent>
    </Card>
  )
}

/* ---------- step 2: contenders (pure references to providers) ---------- */

interface RuntimeOption {
  id: string
  label: string
  note: string
  icon?: string
  protocol?: string | null
  cliMissing?: boolean
  localOnly?: boolean
}

function AgentPickerStatusLine({
  status,
  cliMissing,
  loading,
}: {
  status?: AgentRuntimeStatus
  cliMissing?: boolean
  loading: boolean
}) {
  if (loading && !status) {
    return (
      <span className="inline-flex items-center justify-center gap-1 text-[11px] text-muted-foreground">
        <Loader2 className="size-3 animate-spin" /> checking version
      </span>
    )
  }
  if (status?.present === false || cliMissing) {
    return <span className="text-[11px] text-muted-foreground">CLI missing</span>
  }
  if (!status) {
    return <span className="text-[11px] text-muted-foreground">version not checked</span>
  }
  const version = status.version ? `v${status.version}` : "version unavailable"
  const suffix =
    loading && status.latest_error
      ? "checking update"
      : status.update_available === true
      ? "update available"
      : status.update_available === false
        ? "latest"
        : status.latest_error
          ? "update check failed"
          : status.latest_version
            ? `latest v${status.latest_version}`
            : "update not checked"
  return (
    <span
      className={cn(
        "max-w-full truncate text-[11px]",
        status.update_available || status.latest_error ? "text-warn-ink" : "text-muted-foreground",
      )}
      title={[
        status.version_output,
        status.version_error,
        status.latest_version ? `latest v${status.latest_version}` : "",
        status.latest_error,
      ]
        .filter(Boolean)
        .join("\n")}
    >
      {version} · {suffix}
    </span>
  )
}

function StepContenders({
  providers,
  customRuntimes,
  customByRuntime,
  builtinCliPresent,
  agentStatuses,
  statusLoading,
  installingAgentId,
  dockerCapable,
  filterFor,
  thinkingChannelFor,
  thinkingEffortsFor,
  contenders,
  backend,
  onAdd,
  onInstall,
  onSetup,
  onUpdate,
  onRemove,
}: {
  providers: AiProvider[]
  customRuntimes: CustomRuntime[]
  customByRuntime: Record<string, CustomRuntime>
  builtinCliPresent: Record<string, boolean>
  agentStatuses: Record<string, AgentRuntimeStatus>
  statusLoading: boolean
  installingAgentId: string | null
  dockerCapable: (runtime: string) => boolean
  filterFor: (runtime: string) => ProviderFilter | undefined
  thinkingChannelFor: (runtime: string) => string
  thinkingEffortsFor: (runtime: string) => string[]
  contenders: ContenderDraft[]
  backend: string
  onAdd: (runtime: string) => void
  onInstall: (runtime: string, label: string) => void
  onSetup: (runtime: string) => void
  onUpdate: (key: string, patch: Partial<ContenderDraft>) => void
  onRemove: (key: string) => void
}) {
  const options: RuntimeOption[] = [
    ...RUNTIMES.map((runtime) => ({
      id: runtime,
      label: AGENT_LABELS[runtime],
      note: AGENT_NOTES[runtime],
      cliMissing: builtinCliPresent[runtime] === false,
    })),
    ...customRuntimes.map((agent) => ({
      id: agent.id,
      label: agent.label ?? agent.spec_id,
      note: agent.description || (agent.command ?? ""),
      icon: agent.icon,
      protocol: agent.protocol ?? "none",
      cliMissing: agent.cli ? !agent.cli.present : false,
      localOnly: !agent.docker_capable,
    })),
  ]
  return (
    <div className="grid gap-4">
      <Card>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap items-baseline gap-2">
            <Label>Add agents</Label>
            <p className="text-xs text-muted-foreground">
              The agents are the coding CLIs under test. Each one is configured with a
              model from your AI providers and runs the same tasks under the same judge.
            </p>
            <Link to="/agents" className="ml-auto text-xs text-primary hover:underline">
              Manage runtimes
            </Link>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-5">
            {options.map((option) => {
              const status = agentStatuses[option.id]
              const checking = statusLoading && !status
              const missing = !checking && (status?.present === false || option.cliMissing === true)
              const installable = missing && status?.installable === true
              const installing = installingAgentId === option.id
              const actionLabel = checking
                ? "Checking"
                : missing
                  ? installable
                    ? "Install"
                    : "Setup guide"
                  : "Add"
              const actionIcon = installing ? (
                <Loader2 className="size-3 animate-spin" />
              ) : checking ? (
                <Loader2 className="size-3 animate-spin" />
              ) : missing ? (
                installable ? (
                  <DownloadCloud className="size-3" />
                ) : (
                  <ArrowRight className="size-3" />
                )
              ) : (
                <Plus className="size-3" />
              )
              const disabled = installing || checking
              const actionTitle = checking
                ? "Checking the local CLI before this runtime can be added."
                : missing
                  ? installable && status?.package
                    ? status.package.install_command.join(" ")
                    : "Open Agents to configure this runtime."
                  : `Add ${option.label}`
              return (
                <button
                  key={option.id}
                  type="button"
                  disabled={disabled}
                  aria-label={`${actionLabel} ${option.label}`}
                  title={actionTitle}
                  onClick={() => {
                    if (missing) {
                      if (installable) {
                        onInstall(option.id, option.label)
                      } else {
                        onSetup(option.id)
                      }
                      return
                    }
                    onAdd(option.id)
                  }}
                  className={cn(
                    "group grid justify-items-center gap-1.5 rounded-md border p-3 text-center transition-[background-color,border-color,color,transform] disabled:cursor-wait disabled:hover:translate-y-0",
                    missing
                      ? "border-border bg-muted/35 text-muted-foreground hover:-translate-y-0.5 hover:border-primary/35 hover:bg-muted/55 hover:text-foreground"
                      : "hover:-translate-y-0.5 hover:border-primary/50 hover:bg-accent/40",
                  )}
                >
                  <AgentIcon agent={option.id} icon={option.icon} size={26} />
                  <span className="text-sm font-medium">{option.label}</span>
                  <span className="max-w-full truncate text-[11px] leading-tight text-muted-foreground">
                    {option.note}
                  </span>
                  <AgentPickerStatusLine
                    status={agentStatuses[option.id]}
                    cliMissing={option.cliMissing}
                    loading={statusLoading}
                  />
                  {option.localOnly && (
                    <span
                      className="text-[11px] text-warn-ink"
                      title="No Docker image in this runtime's spec — tasks execute directly on this machine."
                    >
                      local execution
                    </span>
                  )}
                  <span
                    className={cn(
                      "mt-0.5 inline-flex items-center gap-1 text-xs",
                      missing ? "text-muted-foreground group-hover:text-primary" : "text-primary",
                    )}
                  >
                    {actionIcon} {installing ? "Installing" : actionLabel}
                  </span>
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {contenders.length ? (
        <div className="grid gap-3">
          {contenders.map((draft, index) => (
            <ContenderCard
              key={draft.key}
              index={index}
              draft={draft}
              providers={providers}
              custom={customByRuntime[draft.runtime]}
              dockerCapable={dockerCapable(draft.runtime)}
              providerFilter={filterFor(draft.runtime)}
              thinkingChannel={thinkingChannelFor(draft.runtime)}
              thinkingEfforts={thinkingEffortsFor(draft.runtime)}
              backend={backend}
              onUpdate={(patch) => onUpdate(draft.key, patch)}
              onRemove={() => onRemove(draft.key)}
            />
          ))}
        </div>
      ) : (
        <p className="text-center text-sm text-muted-foreground">
          No agents yet. Add at least one runtime above.
        </p>
      )}
    </div>
  )
}

function ContenderCard({
  index,
  draft,
  providers,
  custom,
  dockerCapable,
  providerFilter,
  thinkingChannel,
  thinkingEfforts,
  backend,
  onUpdate,
  onRemove,
}: {
  index: number
  draft: ContenderDraft
  providers: AiProvider[]
  custom?: CustomRuntime
  dockerCapable: boolean
  providerFilter?: ProviderFilter
  thinkingChannel: string
  thinkingEfforts: string[]
  backend: string
  onUpdate: (patch: Partial<ContenderDraft>) => void
  onRemove: () => void
}) {
  const provider = providers.find((item) => item.id === draft.provider_id)
  const dockerDowngraded = backend === "docker" && !dockerCapable
  const ownLogin = custom ? (custom.protocol ?? "none") === "none" : false
  const hasCompatibleProvider =
    compatibleProviders(providerFilter, providers, draft.runtime).length > 0
  return (
    <Card className="py-4">
      <CardContent className="grid gap-3 px-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted-foreground">#{index + 1}</span>
          <span className="flex items-center gap-2">
            <AgentIcon agent={draft.runtime} icon={custom?.icon} size={22} />
            <span className="text-sm font-semibold">
              {custom ? (custom.label ?? custom.spec_id) : AGENT_LABELS[draft.runtime]}
            </span>
          </span>
          {custom?.cli && !custom.cli.present && (
            <Badge
              className="border-transparent bg-warn-soft text-[11px] text-warn-ink"
              title={`\`${custom.cli.bin}\` is not on PATH`}
            >
              CLI missing
            </Badge>
          )}
          {provider?.auth === "cli_login" && (
            <Badge variant="outline" className="text-[11px] text-muted-foreground">
              CLI login
            </Badge>
          )}
          {dockerDowngraded && (
            <Badge className="border-transparent bg-warn-soft text-[11px] text-warn-ink">
              runs locally — no Docker support
            </Badge>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="ml-auto size-7 text-muted-foreground hover:text-fail-ink"
            aria-label={`Remove agent ${index + 1}`}
            onClick={onRemove}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Label className="text-xs text-muted-foreground">Model</Label>
          {ownLogin ? (
            <span className="text-xs text-muted-foreground">
              Uses the CLI's own login and configuration on this machine.
            </span>
          ) : hasCompatibleProvider ? (
            <ProviderModelPicker
              providerFilter={providerFilter}
              runtimeId={draft.runtime}
              providerId={draft.provider_id}
              model={draft.model}
              onChange={({ provider: next, model }) =>
                onUpdate({ provider_id: next.id, model })
              }
            />
          ) : (
            <span className="text-xs text-warn-ink">
              No provider is configured for this runtime — add one on the AI providers page.
            </span>
          )}
        </div>
        {custom && !ownLogin && !custom.model_flag && (
          <p className="text-xs text-muted-foreground">
            This runtime has no model flag; the provider's endpoint and key are injected via $
            {custom.base_url_env || "—"} but the model choice stays with the CLI's config.
          </p>
        )}
        {draft.runtime === "codex" && provider && provider.kind !== "openai" && (
          <p className="text-xs text-muted-foreground">
            Routed through {provider.name}; the endpoint must support the OpenAI Responses API.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Label className="text-xs text-muted-foreground">Thinking effort</Label>
          <RadioGroup
            value={draft.thinking_effort}
            onValueChange={(value) => onUpdate({ thinking_effort: value })}
            className="flex flex-wrap gap-1.5"
          >
            {thinkingEfforts.map((effort) => (
              <label
                key={effort}
                className={cn(
                  "flex cursor-pointer items-center gap-1.5 rounded-md border px-2 py-1 text-xs",
                  draft.thinking_effort === effort
                    ? "border-primary bg-accent/60"
                    : "hover:border-primary/40",
                )}
              >
                <RadioGroupItem value={effort} className="size-3" />
                {effort}
              </label>
            ))}
          </RadioGroup>
          <span
            className="text-[11px] text-muted-foreground"
            title={
              thinkingChannel === "native_config"
                ? "Applied through the CLI's own reasoning switch (Claude Code --effort, Codex model_reasoning_effort, OpenCode --variant)."
                : "This runtime has no reasoning switch the runner controls; the effort is requested in the prompt."
            }
          >
            {thinkingChannel === "native_config" ? "native reasoning setting" : "prompt-level request"}
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

/* ---------- step 3: shared config (profile) ---------- */

function StepShared({
  profiles,
  persisted,
  defaultProfileId,
  profileId,
  onSelectProfile,
  providers,
  skills,
  tasksDir,
  selectedTasks,
  shared,
  setShared,
  setSharedField,
  perFields,
  setPerFields,
  judgeConflicts,
  customRuntimes,
  customByRuntime,
  filterFor,
  runtimeLabel,
  localRuntimeNames,
}: {
  profiles: Profile[]
  persisted: boolean
  defaultProfileId: string | null
  profileId: string | null
  onSelectProfile: (id: string) => void
  providers: AiProvider[]
  skills?: SkillsPayload
  tasksDir: string
  selectedTasks: TaskPackage[]
  shared: Partial<SharedConfig>
  setShared: React.Dispatch<React.SetStateAction<Partial<SharedConfig>>>
  setSharedField: (key: keyof SharedConfig, value: unknown) => void
  perFields: string[]
  setPerFields: (fields: string[]) => void
  judgeConflicts: number
  customRuntimes: CustomRuntime[]
  customByRuntime: Record<string, CustomRuntime>
  filterFor: (runtime: string) => ProviderFilter | undefined
  runtimeLabel: (runtime: string) => string
  localRuntimeNames: string[]
}) {
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)
  const judgeProvider = providers.find(
    (item) => item.id === String(shared.evaluator_provider_id ?? ""),
  )
  const judgeRuntime = String(shared.evaluator_agent ?? "codex")
  const judgeCustom = customByRuntime[judgeRuntime]
  const judgeOwnLogin = judgeCustom ? (judgeCustom.protocol ?? "none") === "none" : false

  const saveToProfile = async () => {
    if (!profileId) return
    setSaving(true)
    try {
      const next = profiles.map((profile) =>
        profile.id === profileId
          ? { ...profile, shared: shared, per_contender_fields: perFields }
          : profile,
      )
      await api.saveProfiles({
        default_profile_id: defaultProfileId ?? profileId,
        profiles: next,
      })
      queryClient.invalidateQueries({ queryKey: ["profiles"] })
      toast.success(`Profile "${profileId}" saved.`)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="grid gap-4">
      <Card className="py-4">
        <CardContent className="flex flex-wrap items-center gap-3 px-4">
          <Label className="text-sm">Profile</Label>
          <Select value={profileId ?? undefined} onValueChange={onSelectProfile}>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {profiles.map((profile) => (
                <SelectItem key={profile.id} value={profile.id}>
                  {profile.name}
                  {profile.id === defaultProfileId ? " (default)" : ""}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {!persisted && (
            <span className="text-xs text-muted-foreground">
              built-in defaults, not saved yet
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            disabled={saving || !profileId}
            onClick={saveToProfile}
          >
            <Save /> Save to profile
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="grid gap-5">
          <div className="flex items-center gap-2">
            <Scale className="size-4 text-live-ink" />
            <span className="text-sm font-semibold">Judge — shared across all agents</span>
          </div>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label>Judge runtime</Label>
              <Select
                value={judgeRuntime}
                onValueChange={(runtime) => {
                  const custom = customByRuntime[runtime]
                  setShared((current) => ({
                    ...current,
                    evaluator_agent: runtime,
                    evaluator_provider_id: undefined,
                    evaluator_model: "",
                    evaluator_auth_mode:
                      custom && (custom.protocol ?? "none") === "none" ? "global" : "env",
                    evaluator_gateway: null,
                    judge_env: null,
                  }))
                }}
              >
                <SelectTrigger className="w-64">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RUNTIMES.map((runtime) => (
                    <SelectItem key={runtime} value={runtime}>
                      <span className="flex items-center gap-2">
                        <AgentIcon agent={runtime} size={14} />
                        {AGENT_LABELS[runtime]}
                      </span>
                    </SelectItem>
                  ))}
                  {customRuntimes.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      <span className="flex items-center gap-2">
                        <AgentIcon agent={agent.id} icon={agent.icon} size={14} />
                        {agent.label ?? agent.spec_id}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                The judge is an agent too — scores are only as trustworthy as the runtime
                grading them.
              </p>
              {judgeCustom && judgeCustom.judge_args_inherited && (
                <p className="text-xs text-warn-ink">
                  This runtime declares no read-only judge mode (judge arguments equal the
                  executor arguments), so the judge could modify its grading workspace.
                  Prefer a runtime with a plan/read-only flag for judging.
                </p>
              )}
            </div>
            {judgeOwnLogin ? (
              <p className="text-xs text-muted-foreground">
                {runtimeLabel(judgeRuntime)} uses its own login and configuration; no provider
                applies.
              </p>
            ) : (
              <div className="grid gap-1.5">
                <Label>Judge model (from a provider)</Label>
                <ProviderModelPicker
                  providerFilter={filterFor(judgeRuntime)}
                  runtimeId={judgeRuntime}
                  filter={
                    judgeRuntime === "codex"
                      ? (provider) => provider.kind === "openai"
                      : undefined
                  }
                  providerId={judgeProvider?.id}
                  model={String(shared.evaluator_model ?? "")}
                  onChange={({ provider, model }) => {
                    /* Pure reference: the backend computes auth/gateway/judge_env
                       from evaluator_provider_id at plan time. */
                    setShared((current) => ({
                      ...current,
                      evaluator_agent: judgeRuntime,
                      evaluator_provider_id: provider.id,
                      evaluator_model: model,
                      evaluator_auth_mode: undefined,
                      evaluator_gateway: null,
                      judge_env: null,
                    }))
                  }}
                />
                {judgeRuntime === "codex" && (
                  <p className="text-xs text-muted-foreground">
                    The Codex judge runs on the official OpenAI endpoint only: codex gateway
                    overrides are process-wide and would also reroute Codex contenders.
                  </p>
                )}
                {judgeProvider && (
                  <p className="text-xs text-muted-foreground">
                    Credentials from the {judgeProvider.name} provider
                  </p>
                )}
              </div>
            )}
            <div className="grid max-w-52 gap-1.5">
              <Label htmlFor="judge-timeout">Judge timeout (s)</Label>
              <Input
                id="judge-timeout"
                type="number"
                min={1}
                placeholder="900"
                value={String(shared.evaluator_timeout_seconds ?? "")}
                onChange={(event) =>
                  setSharedField("evaluator_timeout_seconds", event.target.value)
                }
              />
            </div>
          </div>
          <RadioGroup
            value={String(shared.judge_mode ?? "single")}
            onValueChange={(value) => setSharedField("judge_mode", value)}
            className="grid gap-2 lg:grid-cols-3"
          >
            {JUDGE_MODES.map((mode) => (
              <label
                key={mode.value}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-md border p-3",
                  String(shared.judge_mode ?? "single") === mode.value
                    ? "border-primary bg-accent/60"
                    : "hover:border-primary/40",
                )}
              >
                <RadioGroupItem value={mode.value} className="mt-0.5" />
                <span>
                  <span className="block text-sm font-medium">{mode.label}</span>
                  <span className="block text-xs text-muted-foreground">{mode.note}</span>
                </span>
              </label>
            ))}
          </RadioGroup>
          {judgeConflicts > 0 && (
            <Alert className="border-warn-ink/40 bg-warn-soft/60">
              <AlertTriangle className="size-4" />
              <AlertTitle>Judge equals an agent under test</AlertTitle>
              <AlertDescription>
                {judgeConflicts} agent{judgeConflicts > 1 ? "s use" : " uses"} the same model
                as the judge. Self-grading biases scores; consider an independent judge.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-2">
        <h3 className="px-1 text-sm font-semibold text-muted-foreground">Research add-ons</h3>
        <PromptAssistanceBlock
          tasksDir={tasksDir}
          selectedTasks={selectedTasks}
          shared={shared}
          setShared={setShared}
          setSharedField={setSharedField}
        />
        <ExecutorSkillsBlock skills={skills} shared={shared} setShared={setShared} />
      </div>

      <Card>
        <CardContent className="grid gap-4">
          <span className="text-sm font-semibold">Environment & determinism — shared</span>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="grid gap-1.5">
              <Label>Where executors run</Label>
              <Select
                value={String(shared.executor_backend ?? "local")}
                onValueChange={(value) => setSharedField("executor_backend", value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="local">This machine</SelectItem>
                  <SelectItem value="docker">Docker sandbox</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label>Web search</Label>
              <Select
                value={String(shared.web_search_mode ?? "task")}
                onValueChange={(value) => setSharedField("web_search_mode", value)}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="task">Task default</SelectItem>
                  <SelectItem value="allow">Allow for all</SelectItem>
                  <SelectItem value="deny">Deny for all</SelectItem>
                </SelectContent>
              </Select>
              {String(shared.web_search_mode ?? "task") !== "task" && (
                <p className="text-xs text-warn-ink">
                  Enforced for Claude Code and Codex; other runtimes' own tooling
                  decides web access.
                </p>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label>Seed</Label>
              <Input
                type="number"
                placeholder="123"
                value={String(shared.seed ?? "")}
                onChange={(event) => setSharedField("seed", event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>Batch size</Label>
              <Input
                type="number"
                min={1}
                placeholder="1"
                value={String(shared.batch_size ?? "")}
                onChange={(event) => setSharedField("batch_size", event.target.value)}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>Repeat</Label>
              <Input
                type="number"
                min={1}
                placeholder="1"
                value={String(shared.repeat ?? "")}
                onChange={(event) => setSharedField("repeat", event.target.value)}
              />
            </div>
          </div>
          {String(shared.executor_backend) === "docker" && (
            <p className="text-xs text-muted-foreground">
              Each agent runs in its runtime's own container image
              (<code className="font-mono">starbench-*</code>; custom runtimes use the image
              from their spec). Build the images once with{" "}
              <code className="font-mono">make docker-images</code>. The judge always runs on
              this machine — isolation applies to the agents' execution phase.
            </p>
          )}
          {String(shared.executor_backend) === "docker" && localRuntimeNames.length > 0 && (
            <Alert className="border-warn-ink/40 bg-warn-soft/60">
              <AlertTriangle className="size-4" />
              <AlertTitle>Some agents will run without Docker</AlertTitle>
              <AlertDescription>
                Docker isolation covers every built-in runtime and custom runtimes with a
                Docker image in their spec. These agents run directly on this machine:{" "}
                {localRuntimeNames.join(", ")}.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      <Card className="py-4">
        <CardContent className="grid gap-2 px-4">
          <span className="text-sm font-semibold">Per-agent fields</span>
          <p className="text-xs text-muted-foreground">
            Which run-time knobs each agent sets individually. Endpoints and credentials
            always come from the provider.
          </p>
          <div className="flex flex-wrap gap-2">
            {PER_FIELD_OPTIONS.map((option) => {
              const checked = perFields.includes(option.id)
              return (
                <label
                  key={option.id}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 rounded-md border px-3 py-1.5 text-sm",
                    checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                    option.locked && "cursor-not-allowed opacity-70",
                  )}
                >
                  <Checkbox
                    checked={checked}
                    disabled={option.locked}
                    onCheckedChange={(value) =>
                      setPerFields(
                        value
                          ? [...perFields, option.id]
                          : perFields.filter((id) => id !== option.id),
                      )
                    }
                  />
                  {option.label}
                </label>
              )
            })}
          </div>
        </CardContent>
      </Card>

      <Card className="py-4">
        <CardContent className="px-4">
          <Collapsible>
            <CollapsibleTrigger className="group flex w-full items-center justify-between text-left">
              <span className="text-sm font-semibold">Advanced</span>
              <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            <CollapsibleContent className="grid gap-5 pt-4">
              <div className="grid max-w-52 gap-1.5">
                <Label htmlFor="judge-parallelism">Judge parallelism</Label>
                <Input
                  id="judge-parallelism"
                  type="number"
                  min={1}
                  placeholder="4"
                  value={String(shared.max_evaluator_parallel ?? "")}
                  onChange={(event) =>
                    setSharedField("max_evaluator_parallel", event.target.value)
                  }
                />
                <p className="text-xs text-muted-foreground">
                  How many rubric judges grade at once. Raising it finishes judging sooner but
                  is more likely to hit the judge provider's rate limit.
                </p>
              </div>
              <div className="grid max-w-52 gap-1.5">
                <Label htmlFor="claude-max-turns">Claude max turns</Label>
                <Input
                  id="claude-max-turns"
                  type="number"
                  min={1}
                  placeholder="unlimited"
                  value={String(shared.claude_max_turns ?? "")}
                  onChange={(event) => setSharedField("claude_max_turns", event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Caps how many turns a Claude Code agent may take on a task. Leave blank for no
                  cap. Only affects Claude Code agents.
                </p>
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor="extra-flags">Extra CLI flags</Label>
                <Input
                  id="extra-flags"
                  className="font-mono"
                  placeholder="--docker-bin podman"
                  value={String(shared.extra_args ?? "")}
                  onChange={(event) => setSharedField("extra_args", event.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Added to every run's command exactly as typed — an escape hatch for
                  engineering knobs that have no control of their own here.
                </p>
              </div>
            </CollapsibleContent>
          </Collapsible>
        </CardContent>
      </Card>
    </div>
  )
}

/* ---------- shared: prompt assistance (research) ---------- */

const INSTRUCTION_MODE_CARDS = [
  {
    value: "none",
    label: "None",
    note: "Baseline — the task runs exactly as written.",
  },
  {
    value: "select",
    label: "Selected steps",
    note: "Bundle the expert steps you pick into the prompt; one run per task.",
  },
  {
    value: "traverse",
    label: "Traverse",
    note: "One variant per expert step, to see each step's effect on its own.",
  },
  {
    value: "ablation",
    label: "Ablation",
    note: "Baseline + each step alone + all steps together; auto-generates a baseline comparison and a step-by-step uplift report.",
  },
] as const

/* Instruction ablation: a research sweep over a task's human_reference expert
   steps. This is the "Prompt assistance (research)" region; B4 will add a Rigor
   sub-section alongside Expert instructions, so the block is structured for two
   sub-sections. Only public step text is ever shown — the private `reasoning`
   never crosses the API (enforced backend-side). */
function PromptAssistanceBlock({
  tasksDir,
  selectedTasks,
  shared,
  setShared,
  setSharedField,
}: {
  tasksDir: string
  selectedTasks: TaskPackage[]
  shared: Partial<SharedConfig>
  setShared: React.Dispatch<React.SetStateAction<Partial<SharedConfig>>>
  setSharedField: (key: keyof SharedConfig, value: unknown) => void
}) {
  const mode = String(shared.instruction_mode ?? "none")
  const selectedSteps = shared.instruction_steps ?? []
  const repeat = Number(shared.repeat) || 1

  const tasksWithSteps = selectedTasks.filter((task) => task.has_human_reference)
  const tasksWithoutSteps = selectedTasks.filter((task) => !task.has_human_reference)
  // Only the baseline applies when no selected task ships any expert steps.
  const noExpertSteps = selectedTasks.length > 0 && tasksWithSteps.length === 0

  // Public step detail per step-bearing task; keys are stable per (dir, task) so
  // react-query caches across renders and steps rerender.
  const detailQueries = useQueries({
    queries: tasksWithSteps.map((task) => ({
      queryKey: ["tasklib-task", tasksDir, task.dir_name],
      queryFn: () => api.taskDetail(tasksDir, task.dir_name),
      enabled: Boolean(tasksDir),
      staleTime: 60_000,
    })),
  })
  const stepsLoading = detailQueries.some((query) => query.isPending)

  // Pool steps across the selected tasks, keyed by step id, tracking how many of
  // the step-bearing tasks contain each id. The runner requires a chosen step to
  // exist in EVERY selected task, so a step present in only some tasks (marked
  // in k/N) will make the run reject the tasks that lack it.
  const pooled = new Map<
    string,
    { step_id: string; step_type: string; instruction: string; inTasks: number }
  >()
  for (const query of detailQueries) {
    if (!query.data) continue
    for (const step of query.data.human_reference_steps) {
      const existing = pooled.get(step.step_id)
      if (existing) existing.inTasks += 1
      else pooled.set(step.step_id, { ...step, inTasks: 1 })
    }
  }
  const unionSteps = [...pooled.values()]
  const stepTaskCount = tasksWithSteps.length

  // If the task selection changed to one with no expert steps, don't leave a
  // stale step-requiring mode (or step choice) selected.
  useEffect(() => {
    if (noExpertSteps && mode !== "none") {
      setShared((current) => ({
        ...current,
        instruction_mode: "none",
        instruction_steps: [],
      }))
    }
  }, [noExpertSteps, mode, setShared])

  const setMode = (next: string) =>
    setShared((current) => ({
      ...current,
      instruction_mode: next,
      // Chosen steps only apply to select mode; drop them otherwise so ablation
      // and traverse always sweep the full step set.
      instruction_steps: next === "select" ? current.instruction_steps ?? [] : [],
    }))

  const toggleStep = (id: string, on: boolean) =>
    setShared((current) => {
      const chosen = new Set(current.instruction_steps ?? [])
      if (on) chosen.add(id)
      else chosen.delete(id)
      return { ...current, instruction_steps: [...chosen] }
    })

  const partialModeLabel =
    mode === "select" ? "Selected steps" : mode === "traverse" ? "Traverse" : "Ablation"

  // --- Rigor requirements (research). A parallel sub-section to Expert
  //     instructions: it restates selected rubric-level requirements as hard
  //     requirements in every agent's prompt. It's off by default (a controlled
  //     experiment, not part of the baseline benchmark score) and, unlike the
  //     instruction sweep, does not expand executor variants. All rigor text is
  //     public. ---
  const rigorEnabled = String(shared.rigor_mode ?? "none") === "select"
  const selectedRigors = shared.rigors ?? []

  const tasksWithRigors = selectedTasks.filter((task) => task.rigor_count > 0)
  const tasksWithoutRigors = selectedTasks.filter((task) => !task.rigor_count)
  const noRigors = selectedTasks.length > 0 && tasksWithRigors.length === 0

  // Public rigor detail per rigor-bearing task. Same query key as the step
  // queries above, so react-query serves both from one cache entry per task.
  const rigorDetailQueries = useQueries({
    queries: tasksWithRigors.map((task) => ({
      queryKey: ["tasklib-task", tasksDir, task.dir_name],
      queryFn: () => api.taskDetail(tasksDir, task.dir_name),
      enabled: Boolean(tasksDir),
      staleTime: 60_000,
    })),
  })
  const rigorsLoading = rigorDetailQueries.some((query) => query.isPending)

  // Pool rigors across the selected tasks, keyed by id, tracking how many of the
  // rigor-bearing tasks contain each id. The runner requires a chosen rigor to
  // exist in EVERY selected task, so one present in only some tasks (marked in
  // k/N) makes the run reject the tasks that lack it.
  const pooledRigors = new Map<
    string,
    { id: string; rubric_id: string; requirement: string; inTasks: number }
  >()
  for (const query of rigorDetailQueries) {
    if (!query.data) continue
    for (const rigor of query.data.rigors) {
      const existing = pooledRigors.get(rigor.id)
      if (existing) existing.inTasks += 1
      else pooledRigors.set(rigor.id, { ...rigor, inTasks: 1 })
    }
  }
  const unionRigors = [...pooledRigors.values()]
  const rigorTaskCount = tasksWithRigors.length

  // If the task selection changed to one with no rigors, don't leave rigor mode
  // (or a stale id choice) selected.
  useEffect(() => {
    if (noRigors && rigorEnabled) {
      setShared((current) => ({ ...current, rigor_mode: "none", rigors: [] }))
    }
  }, [noRigors, rigorEnabled, setShared])

  const setRigorEnabled = (on: boolean) =>
    setShared((current) => ({
      ...current,
      rigor_mode: on ? "select" : "none",
      rigors: on ? current.rigors ?? [] : [],
    }))

  const toggleRigor = (id: string, on: boolean) =>
    setShared((current) => {
      const chosen = new Set(current.rigors ?? [])
      if (on) chosen.add(id)
      else chosen.delete(id)
      return { ...current, rigors: [...chosen] }
    })

  /* Collapsed by default while inactive: research layers are additions, not
     required configuration, and the closed row states exactly what is on. */
  const assistActive = mode !== "none" || rigorEnabled
  const assistSummary = [
    mode === "none"
      ? "instructions off"
      : mode === "select"
        ? `instructions: selected steps (${selectedSteps.length})`
        : `instructions: ${mode}`,
    rigorEnabled ? `rigor: ${selectedRigors.length} requirement${selectedRigors.length === 1 ? "" : "s"}` : "rigor off",
  ].join(" · ")
  const [open, setOpen] = useState(assistActive)
  useEffect(() => {
    if (assistActive) setOpen(true)
  }, [assistActive])

  return (
    <Card className={open ? undefined : "py-3"}>
      <CardContent className="grid gap-4">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full flex-wrap items-center gap-2 text-left"
        >
          <Sparkles className="size-4 text-live-ink" />
          <span className="text-sm font-semibold">Prompt assistance (research)</span>
          {open ? (
            <span className="text-xs text-muted-foreground">
              Optional experiments that add expert guidance to the prompt. Shared across all
              agents, like the judge, so the comparison stays fair.
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">{assistSummary}</span>
          )}
          <span
            className={cn(
              "ml-auto size-1.5 rounded-full",
              assistActive ? "bg-live-ink" : "bg-muted-foreground/40",
            )}
            aria-hidden
          />
          <ChevronDown
            className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </button>
        {open && (
          <>

        {/* --- Expert instructions --- */}
        <div className="grid gap-3">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Expert instructions
          </span>

          {noExpertSteps ? (
            <p className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">
              None of the selected tasks ship expert steps (a{" "}
              <code className="font-mono">human_reference.json</code>), so only the baseline
              (None) applies. Add expert steps to a task to enable this experiment.
            </p>
          ) : (
            <>
              <div className="grid gap-2 sm:grid-cols-2">
                {INSTRUCTION_MODE_CARDS.map((card) => {
                  const active = mode === card.value
                  return (
                    <button
                      key={card.value}
                      type="button"
                      onClick={() => setMode(card.value)}
                      className={cn(
                        "grid gap-0.5 rounded-md border p-3 text-left transition-colors",
                        active ? "border-primary bg-accent/60" : "hover:border-primary/40",
                      )}
                    >
                      <span className="flex items-center gap-2 text-sm font-medium">
                        {active && <Check className="size-3.5 text-primary" />}
                        {card.label}
                        {card.value === "none" && (
                          <Badge variant="outline" className="text-[10px] text-muted-foreground">
                            default
                          </Badge>
                        )}
                      </span>
                      <span className="text-xs text-muted-foreground">{card.note}</span>
                    </button>
                  )
                })}
              </div>

              {/* Partial coverage: some selected tasks ship no expert steps. In any
                  step mode the runner rejects the whole run for those tasks. */}
              {tasksWithoutSteps.length > 0 && mode !== "none" && (
                <Alert className="border-warn-ink/40 bg-warn-soft/60">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>Some selected tasks have no expert steps</AlertTitle>
                  <AlertDescription>
                    {partialModeLabel} mode requires every selected task to ship expert steps.
                    The runner rejects the whole run for tasks that don't:{" "}
                    {tasksWithoutSteps.map((task) => task.id).join(", ")}. Remove them or switch
                    to None.
                  </AlertDescription>
                </Alert>
              )}

              {/* Selected mode: the step multi-selector, pooled across tasks. */}
              {mode === "select" && (
                <div className="grid gap-2">
                  <p className="text-xs text-muted-foreground">
                    Every chosen step must exist in each selected task. Steps below are pooled
                    across your selected tasks; one marked{" "}
                    <span className="text-warn-ink">in k/N</span> is missing from some, and the
                    run is rejected for any task that lacks a chosen step.
                  </p>
                  {stepsLoading ? (
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="size-3.5 animate-spin" /> Loading expert steps…
                    </p>
                  ) : unionSteps.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      No expert steps found in the selected tasks.
                    </p>
                  ) : (
                    <div className="grid gap-2">
                      {unionSteps.map((step) => {
                        const checked = selectedSteps.includes(step.step_id)
                        const partial = stepTaskCount > 1 && step.inTasks < stepTaskCount
                        return (
                          <label
                            key={step.step_id}
                            className={cn(
                              "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                              checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                            )}
                          >
                            <Checkbox
                              className="mt-0.5"
                              checked={checked}
                              onCheckedChange={(value) => toggleStep(step.step_id, value === true)}
                            />
                            <span className="grid min-w-0 gap-1">
                              <span className="flex flex-wrap items-center gap-2">
                                <code className="font-mono text-sm font-medium">
                                  {step.step_id}
                                </code>
                                {step.step_type && (
                                  <Badge
                                    variant="outline"
                                    className="text-[10px] uppercase tracking-wide text-muted-foreground"
                                  >
                                    {step.step_type}
                                  </Badge>
                                )}
                                {stepTaskCount > 1 && (
                                  <Badge
                                    variant="outline"
                                    className={cn(
                                      "text-[10px]",
                                      partial
                                        ? "border-warn-ink/50 text-warn-ink"
                                        : "text-muted-foreground",
                                    )}
                                  >
                                    in {step.inTasks}/{stepTaskCount}
                                  </Badge>
                                )}
                              </span>
                              <span
                                className="truncate text-xs text-muted-foreground"
                                title={step.instruction}
                              >
                                {step.instruction || "—"}
                              </span>
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Ablation: nudge repeat >= 3 for a stable uplift signal. */}
              {mode === "ablation" && (
                <Alert>
                  <Sparkles className="size-4" />
                  <AlertTitle>Repeat 3+ recommended</AlertTitle>
                  <AlertDescription className="flex flex-wrap items-center gap-2">
                    <span>
                      Ablation compares pass rates across variants; a few repeats smooth out
                      per-run noise so the uplift report is trustworthy.
                    </span>
                    {repeat < 3 && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setSharedField("repeat", 3)}
                      >
                        Set repeat to 3
                      </Button>
                    )}
                  </AlertDescription>
                </Alert>
              )}
            </>
          )}
        </div>

        {/* --- Rigor requirements --- */}
        <div className="grid gap-3 border-t pt-4">
          <div className="grid gap-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Rigor requirements
            </span>
            <p className="text-xs text-muted-foreground">
              Restates a few rubric requirements as hard requirements inside every agent's
              prompt. Use this for a controlled experiment — it is not part of the default
              benchmark score, so leave it off for a plain comparison.
            </p>
          </div>

          {noRigors ? (
            <p className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">
              None of the selected tasks ship rigor requirements (a{" "}
              <code className="font-mono">rigors.json</code>), so this experiment is
              unavailable. Add rigor requirements to a task to enable it.
            </p>
          ) : (
            <>
              <label
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                  rigorEnabled ? "border-primary bg-accent/60" : "hover:border-primary/40",
                )}
              >
                <Checkbox
                  className="mt-0.5"
                  checked={rigorEnabled}
                  onCheckedChange={(value) => setRigorEnabled(value === true)}
                />
                <span className="grid gap-0.5">
                  <span className="text-sm font-medium">Inject rigor requirements</span>
                  <span className="text-xs text-muted-foreground">
                    Off by default. When on, pick the requirements to restate below.
                  </span>
                </span>
              </label>

              {/* Partial coverage: some selected tasks ship no rigors. In select
                  mode the runner rejects the whole run for those tasks. */}
              {rigorEnabled && tasksWithoutRigors.length > 0 && (
                <Alert className="border-warn-ink/40 bg-warn-soft/60">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>Some selected tasks have no rigor requirements</AlertTitle>
                  <AlertDescription>
                    Rigor injection requires every selected task to ship rigor requirements.
                    The runner rejects the whole run for tasks that don't:{" "}
                    {tasksWithoutRigors.map((task) => task.id).join(", ")}. Remove them or turn
                    rigor injection off.
                  </AlertDescription>
                </Alert>
              )}

              {/* The requirement multi-selector, pooled across tasks. */}
              {rigorEnabled && (
                <div className="grid gap-2">
                  <p className="text-xs text-muted-foreground">
                    Every chosen requirement must exist in each selected task. Requirements
                    below are pooled across your selected tasks; one marked{" "}
                    <span className="text-warn-ink">in k/N</span> is missing from some, and the
                    run is rejected for any task that lacks a chosen requirement.
                  </p>
                  {rigorsLoading ? (
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="size-3.5 animate-spin" /> Loading rigor requirements…
                    </p>
                  ) : unionRigors.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      No rigor requirements found in the selected tasks.
                    </p>
                  ) : (
                    <div className="grid gap-2">
                      {unionRigors.map((rigor) => {
                        const checked = selectedRigors.includes(rigor.id)
                        const partial = rigorTaskCount > 1 && rigor.inTasks < rigorTaskCount
                        return (
                          <label
                            key={rigor.id}
                            className={cn(
                              "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                              checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                            )}
                          >
                            <Checkbox
                              className="mt-0.5"
                              checked={checked}
                              onCheckedChange={(value) => toggleRigor(rigor.id, value === true)}
                            />
                            <span className="grid min-w-0 gap-1">
                              <span className="flex flex-wrap items-center gap-2">
                                <code className="font-mono text-sm font-medium">{rigor.id}</code>
                                {rigor.rubric_id && (
                                  <Badge
                                    variant="outline"
                                    className="text-[10px] uppercase tracking-wide text-muted-foreground"
                                  >
                                    rubric {rigor.rubric_id}
                                  </Badge>
                                )}
                                {rigorTaskCount > 1 && (
                                  <Badge
                                    variant="outline"
                                    className={cn(
                                      "text-[10px]",
                                      partial
                                        ? "border-warn-ink/50 text-warn-ink"
                                        : "text-muted-foreground",
                                    )}
                                  >
                                    in {rigor.inTasks}/{rigorTaskCount}
                                  </Badge>
                                )}
                              </span>
                              <span
                                className="truncate text-xs text-muted-foreground"
                                title={rigor.requirement}
                              >
                                {rigor.requirement || "—"}
                              </span>
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- shared: executor skills ---------- */

/* Skills and groups are kept separate in `shared`: checking a group injects the
   whole group, and its members drop out of the individual list so a skill is
   never installed twice (which the runner rejects). */
function ExecutorSkillsBlock({
  skills,
  shared,
  setShared,
}: {
  skills?: SkillsPayload
  shared: Partial<SharedConfig>
  setShared: React.Dispatch<React.SetStateAction<Partial<SharedConfig>>>
}) {
  const selectedGroups = shared.executor_skill_groups ?? []
  const selectedSkills = shared.executor_skills ?? []
  const skillsActive = selectedGroups.length + selectedSkills.length > 0
  /* Hooks stay above the empty-library early return (rules of hooks). */
  const [open, setOpen] = useState(skillsActive)
  useEffect(() => {
    if (skillsActive) setOpen(true)
  }, [skillsActive])

  // Hidden entirely when the library is empty or unreadable — nothing to inject.
  if (!skills || skills.error || skills.skills.length === 0) return null
  const coveredByGroup = new Set<string>()
  for (const group of selectedGroups) {
    for (const id of skills.groups[group] ?? []) coveredByGroup.add(id)
  }
  const selectedTotal = new Set<string>([...coveredByGroup, ...selectedSkills])
  const groupNames = Object.keys(skills.groups)

  const toggleGroup = (group: string, on: boolean) =>
    setShared((current) => {
      const groups = new Set(current.executor_skill_groups ?? [])
      const individual = new Set(current.executor_skills ?? [])
      if (on) {
        groups.add(group)
        for (const id of skills.groups[group] ?? []) individual.delete(id)
      } else {
        groups.delete(group)
      }
      return {
        ...current,
        executor_skill_groups: [...groups],
        executor_skills: [...individual],
      }
    })

  const toggleSkill = (id: string, on: boolean) =>
    setShared((current) => {
      const individual = new Set(current.executor_skills ?? [])
      if (on) individual.add(id)
      else individual.delete(id)
      return { ...current, executor_skills: [...individual] }
    })

  const skillsSummary = skillsActive
    ? [
        selectedSkills.length
          ? `${selectedSkills.length} skill${selectedSkills.length === 1 ? "" : "s"}`
          : "",
        selectedGroups.length
          ? `${selectedGroups.length} group${selectedGroups.length === 1 ? "" : "s"}`
          : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : "none selected"

  return (
    <Card className={open ? undefined : "py-3"}>
      <CardContent className="grid gap-4">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full flex-wrap items-center gap-2 text-left"
        >
          <span className="text-sm font-semibold">Executor skills</span>
          {open ? (
            <span className="text-xs text-muted-foreground">
              Expert guidance installed into every agent's workspace for this run. Shared
              across all agents, like the judge, so the comparison stays fair.
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">{skillsSummary}</span>
          )}
          <span
            className={cn(
              "ml-auto size-1.5 rounded-full",
              skillsActive ? "bg-live-ink" : "bg-muted-foreground/40",
            )}
            aria-hidden
          />
          <ChevronDown
            className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </button>
        {open && (
          <>
        <div className="-mt-2 flex justify-end">
          <Link to="/skills" className="text-xs text-primary hover:underline">
            Browse the skill library
          </Link>
        </div>

        {groupNames.length > 0 && (
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Groups</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {groupNames.map((group) => {
                const members = skills.groups[group] ?? []
                const checked = selectedGroups.includes(group)
                return (
                  <label
                    key={group}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                      checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                    )}
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={checked}
                      onCheckedChange={(value) => toggleGroup(group, value === true)}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{group}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {members.length} skill{members.length === 1 ? "" : "s"}: {members.join(", ")}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        )}

        <div className="grid gap-2">
          <Label className="text-xs text-muted-foreground">Individual skills</Label>
          <div className="grid gap-2 sm:grid-cols-2">
            {skills.skills.map((skill) => {
              const inGroup = coveredByGroup.has(skill.id)
              const checked = inGroup || selectedSkills.includes(skill.id)
              return (
                <label
                  key={skill.id}
                  className={cn(
                    "flex items-start gap-3 rounded-md border p-3 transition-colors",
                    inGroup
                      ? "cursor-not-allowed opacity-70"
                      : "cursor-pointer hover:border-primary/40",
                    checked && "border-primary bg-accent/60",
                  )}
                >
                  <Checkbox
                    className="mt-0.5"
                    checked={checked}
                    disabled={inGroup}
                    onCheckedChange={(value) => toggleSkill(skill.id, value === true)}
                  />
                  <span className="min-w-0">
                    <span className="block truncate font-mono text-sm font-medium">{skill.id}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {inGroup ? "included via a selected group" : skill.description || "—"}
                    </span>
                  </span>
                </label>
              )
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {selectedTotal.size
              ? `${selectedTotal.size} skill${selectedTotal.size === 1 ? "" : "s"} selected`
              : "No skills selected — agents run without extra guidance."}
          </span>
          {[...selectedTotal].map((id) => (
            <Badge key={id} variant="outline" className="font-mono text-[11px] text-muted-foreground">
              {id}
            </Badge>
          ))}
        </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- step 4: review ---------- */

function StepReview({
  expName,
  setExpName,
  taskCount,
  tasksDir,
  contenders,
  shared,
  plan,
  judgeConflicts,
  runtimeLabel,
  onPreflightBlocked,
}: {
  expName: string
  setExpName: (name: string) => void
  taskCount: number
  tasksDir: string
  contenders: ContenderDraft[]
  shared: Partial<SharedConfig>
  plan: { plans: ExperimentPlanItem[] | null; estimate: ExecutionEstimate | null; error: string | null }
  judgeConflicts: number
  runtimeLabel: (runtime: string) => string
  onPreflightBlocked: (blocked: boolean) => void
}) {
  const repeat = Number(shared.repeat) || 1
  const planSkills = plan.plans?.[0]?.executor_skills ?? []
  // Prefer the backend's execution estimate (it accounts for the instruction
  // sweep's variant expansion); fall back to the simple product until the plan
  // preview returns.
  const estimate = plan.estimate
  const sweeps = estimate ? estimate.mode !== "none" : false
  const perContender = estimate?.per_contender ?? taskCount * repeat
  const totalExecutions = estimate?.total ?? perContender * contenders.length
  return (
    <div className="grid gap-4">
      <Card className="py-4">
        <CardContent className="grid gap-3 px-4 sm:grid-cols-[1fr_auto]">
          <div className="grid max-w-sm gap-1.5">
            <Label htmlFor="exp-name">Experiment name</Label>
            <Input
              id="exp-name"
              className="font-mono"
              value={expName}
              onChange={(event) => setExpName(event.target.value)}
            />
          </div>
          <div className="grid content-center justify-items-end gap-1 text-right">
            <span className="text-2xl font-semibold tabular-nums tracking-tight">
              {perContender} × {contenders.length}
            </span>
            <span className="text-xs text-muted-foreground">
              {sweeps ? "variant runs per agent" : "tasks per agent"} × agents ={" "}
              {totalExecutions} executions + judging
            </span>
            {estimate?.note && (
              <span className="max-w-xs text-[11px] text-muted-foreground">{estimate.note}</span>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-2 sm:grid-cols-3">
        <SummaryTile label="Tasks" value={`${taskCount}`} hint={shortenPath(tasksDir)} />
        <SummaryTile
          label="Judge"
          value={`${String(shared.evaluator_model ?? "") || "runtime default"}`}
          hint={`${runtimeLabel(String(shared.evaluator_agent ?? "codex"))} · ${String(shared.judge_mode ?? "single")} judge`}
          warn={judgeConflicts > 0 ? "same model as an agent" : undefined}
        />
        <SummaryTile
          label="Environment"
          value={String(shared.executor_backend ?? "local") === "docker" ? "Docker" : "Local"}
          hint={`seed ${shared.seed ?? "123"} · batch ${shared.batch_size ?? 1} · repeat ${repeat}`}
        />
      </div>

      {sweeps && estimate && (
        <Card className="py-4">
          <CardContent className="grid gap-2 px-4">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Instruction sweep
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="text-[11px] capitalize text-muted-foreground">
                {estimate.mode}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {perContender} variant run{perContender === 1 ? "" : "s"} per agent
                {(shared.instruction_steps?.length ?? 0) > 0
                  ? ` · steps ${shared.instruction_steps?.join(", ")}`
                  : ""}
              </span>
            </div>
            {estimate.note && (
              <span className="text-[11px] text-muted-foreground">{estimate.note}</span>
            )}
          </CardContent>
        </Card>
      )}

      {String(shared.rigor_mode ?? "none") === "select" &&
        (shared.rigors?.length ?? 0) > 0 && (
          <Card className="py-4">
            <CardContent className="grid gap-2 px-4">
              <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Rigor requirements
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="text-[11px] text-muted-foreground">
                  {shared.rigors?.length} requirement
                  {(shared.rigors?.length ?? 0) === 1 ? "" : "s"}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  restated in every agent's prompt · {shared.rigors?.join(", ")}
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">
                Controlled experiment — not part of the default benchmark score.
              </span>
            </CardContent>
          </Card>
        )}

      {planSkills.length > 0 && (
        <Card className="py-4">
          <CardContent className="grid gap-2 px-4">
            <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Executor skills
            </span>
            <div className="flex flex-wrap gap-1.5">
              {planSkills.map((id) => (
                <Badge
                  key={id}
                  variant="outline"
                  className="font-mono text-[11px] text-muted-foreground"
                >
                  {id}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {judgeConflicts > 0 && (
        <Alert className="border-warn-ink/40 bg-warn-soft/60">
          <AlertTriangle className="size-4" />
          <AlertTitle>Self-grading configuration</AlertTitle>
          <AlertDescription>
            The judge and an agent under test share the same model. Scores may be biased.
          </AlertDescription>
        </Alert>
      )}

      <PreflightPanel
        plans={plan.plans}
        shared={shared}
        runtimeLabel={runtimeLabel}
        onBlockedChange={onPreflightBlocked}
      />

      <Card className="gap-0 overflow-hidden py-0">
        <div className="border-b bg-muted/30 px-4 py-2.5 text-sm font-semibold">
          Runs that will launch
        </div>
        {plan.error ? (
          <p className="m-4 rounded-md border border-fail-ink/30 bg-fail-soft px-3 py-2 text-sm text-fail-ink">
            {plan.error}
          </p>
        ) : plan.plans ? (
          <div className="divide-y">
            {plan.plans.map((item) => (
              <div key={item.run_id} className="grid gap-1 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <AgentIcon agent={item.agent} size={18} />
                  <span className="text-sm font-medium">
                    {AGENT_LABELS[item.agent] ?? item.agent}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {item.model || "runtime default"}
                  </span>
                  <code className="font-mono text-xs text-muted-foreground">{item.run_id}</code>
                  <Badge variant="outline" className="text-[11px] text-muted-foreground">
                    {item.backend}
                  </Badge>
                  {item.backend_downgraded && (
                    <Badge className="border-transparent bg-warn-soft text-[11px] text-warn-ink">
                      Docker unavailable for this runtime
                    </Badge>
                  )}
                </div>
                {item.warnings?.length ? (
                  <div className="grid gap-0.5">
                    {item.warnings.map((warning, index) => (
                      <span
                        key={index}
                        className="inline-flex items-start gap-1 text-xs text-warn-ink"
                      >
                        <AlertTriangle className="mt-0.5 size-3 shrink-0" /> {warning}
                      </span>
                    ))}
                  </div>
                ) : null}
                <Collapsible>
                  <CollapsibleTrigger className="group flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                    <ChevronDown className="size-3 transition-transform group-data-[state=open]:rotate-180" />
                    command
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <pre className="mt-1 overflow-auto rounded-md border bg-muted/50 px-3 py-2 font-mono text-xs leading-relaxed whitespace-pre-wrap">
                      {["starbench-run", ...item.argv.slice(3)].join(" ")}
                    </pre>
                  </CollapsibleContent>
                </Collapsible>
              </div>
            ))}
          </div>
        ) : (
          <p className="flex items-center gap-2 px-4 py-4 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Building the launch plan…
          </p>
        )}
      </Card>
    </div>
  )
}

function SummaryTile({
  label,
  value,
  hint,
  warn,
}: {
  label: string
  value: string
  hint: string
  warn?: string
}) {
  return (
    <Card className="py-4">
      <CardContent className="grid gap-0.5 px-4">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </span>
        <span className="truncate font-mono text-lg font-semibold">{value}</span>
        <span className="truncate text-xs text-muted-foreground">{hint}</span>
        {warn && (
          <span className="mt-1 inline-flex items-center gap-1 text-xs text-warn-ink">
            <AlertTriangle className="size-3" /> {warn}
          </span>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- task facts strip (steps 2-4) ---------- */

/* The wizard-wide answer to "can these tasks use the web / how long can they
   run": facts owned by the task packages, summarized where run configuration
   happens so nobody hunts for a switch that does not exist. */
function TaskFactsStrip({ tasks }: { tasks: TaskPackage[] }) {
  if (!tasks.length) return null
  const webOn = tasks.filter((task) => task.allow_web_search === true).length
  const webOff = tasks.filter((task) => task.allow_web_search === false).length
  const maxTimeout = Math.max(0, ...tasks.map((task) => task.timeout_seconds ?? 0))
  const withSteps = tasks.filter((task) => task.has_human_reference).length
  const rigors = tasks.reduce((sum, task) => sum + (task.rigor_count ?? 0), 0)
  const webLabel =
    webOn === tasks.length
      ? "web search allowed"
      : webOn === 0
        ? webOff > 0
          ? "web search off"
          : "web search not declared"
        : `web search on ${webOn}/${tasks.length}`
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
      title="Facts set by the selected task packages, not by this run's configuration"
    >
      <span className="font-medium text-foreground">
        {tasks.length} task{tasks.length === 1 ? "" : "s"}
      </span>
      <span>{webLabel}</span>
      {maxTimeout > 0 && <span>up to {fmtDuration(maxTimeout)} each</span>}
      {withSteps > 0 && (
        <span>
          expert steps in {withSteps}/{tasks.length}
        </span>
      )}
      {rigors > 0 && (
        <span>
          {rigors} rigor requirement{rigors === 1 ? "" : "s"}
        </span>
      )}
      <span className="ml-auto hidden text-[11px] sm:inline">set by the task packages</span>
    </div>
  )
}

/* ---------- readiness checks (review step) ---------- */

/* Environment readiness, surfaced before Launch instead of after a dead run:
   CLI on PATH, credentials in the server environment, Docker images built.
   A hard failure disables Launch; the button lighting up is a promise. */
function PreflightPanel({
  plans,
  shared,
  runtimeLabel,
  onBlockedChange,
}: {
  plans: ExperimentPlanItem[] | null
  shared: Partial<SharedConfig>
  runtimeLabel: (runtime: string) => string
  onBlockedChange: (blocked: boolean) => void
}) {
  const paramSets = useMemo(() => {
    if (!plans) return [] as { key: string; agent: string; params: Record<string, string> }[]
    const map = new Map<string, { agent: string; params: Record<string, string> }>()
    for (const item of plans) {
      const key = [item.agent, item.backend, item.docker_image ?? "", item.executor_auth_mode ?? "env"].join("|")
      if (map.has(key)) continue
      map.set(key, {
        agent: item.agent,
        params: {
          executor_agent: item.agent,
          evaluator_agent: String(shared.evaluator_agent ?? "codex"),
          executor_backend: item.backend,
          docker_image: item.docker_image ?? "",
          executor_auth_mode: item.executor_auth_mode ?? "env",
          evaluator_auth_mode: String(shared.evaluator_auth_mode ?? "env"),
        },
      })
    }
    return [...map.entries()].map(([key, value]) => ({ key, ...value }))
  }, [plans, shared])

  const checksQuery = useQuery({
    queryKey: ["preflight", paramSets.map((set) => set.key).join(";")],
    enabled: paramSets.length > 0,
    queryFn: async () =>
      Promise.all(
        paramSets.map(async (set) => ({
          agent: set.agent,
          checks: (await api.preflight(set.params)).checks,
        })),
      ),
  })

  const groups = checksQuery.data ?? []
  const judgeChecks = groups[0]?.checks.filter((check) => check.id.startsWith("evaluator")) ?? []
  const hasFail = groups.some((group) => group.checks.some((check) => check.status === "fail"))
  const blocked = paramSets.length > 0 && (checksQuery.isPending || checksQuery.isError || hasFail)

  useEffect(() => {
    onBlockedChange(blocked)
  }, [blocked, onBlockedChange])

  if (!plans) return null

  return (
    <Card className="py-4">
      <CardContent className="grid gap-3 px-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Ready to run?</span>
          <span className="text-xs text-muted-foreground">
            CLI, credentials, and Docker checks on this machine
          </span>
          {checksQuery.isPending && paramSets.length > 0 && (
            <Loader2 className="ml-auto size-4 animate-spin text-muted-foreground" />
          )}
        </div>
        {checksQuery.isError && (
          <p className="text-xs text-fail-ink">
            Readiness checks failed to load: {(checksQuery.error as Error).message}
          </p>
        )}
        {groups.map((group) => (
          <div key={group.agent} className="grid gap-1">
            <span className="text-xs font-medium">{runtimeLabel(group.agent)}</span>
            {group.checks
              .filter((check) => !check.id.startsWith("evaluator"))
              .map((check) => (
                <PreflightRow key={`${group.agent}-${check.id}-${check.label}`} check={check} />
              ))}
          </div>
        ))}
        {judgeChecks.length > 0 && (
          <div className="grid gap-1">
            <span className="text-xs font-medium">
              Judge · {runtimeLabel(String(shared.evaluator_agent ?? "codex"))}
            </span>
            {judgeChecks.map((check) => (
              <PreflightRow key={`judge-${check.id}-${check.label}`} check={check} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function PreflightRow({ check }: { check: PreflightCheck }) {
  const icon =
    check.status === "ok" ? (
      <CheckCircle2 className="size-3.5 text-pass-ink" />
    ) : check.status === "warn" ? (
      <AlertTriangle className="size-3.5 text-warn-ink" />
    ) : (
      <XCircle className="size-3.5 text-fail-ink" />
    )
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span
        className={cn(
          "shrink-0 font-medium",
          check.status === "fail" && "text-fail-ink",
          check.status === "warn" && "text-warn-ink",
        )}
      >
        {check.label}
      </span>
      {check.hint && (
        <span className="min-w-0 break-all text-muted-foreground">{check.hint}</span>
      )}
    </div>
  )
}

function shortenPath(path: string): string {
  const parts = path.split("/")
  return parts.length > 3 ? `…/${parts.slice(-3).join("/")}` : path
}
