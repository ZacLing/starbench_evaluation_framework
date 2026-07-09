import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  DownloadCloud,
  FolderSearch,
  Layers,
  Loader2,
  PencilLine,
  Plus,
  Rocket,
  Save,
  Scale,
  SlidersHorizontal,
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
  ProviderIcon,
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
  type ProfilesPayload,
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

/* Step 0 ("Mode") frames the launch before any configuration: instantiate a
   saved measurement contract, or configure a bare run by hand. The four
   original steps follow unchanged. */
const STEPS = ["Mode", "Tasks", "Agents", "Shared config", "Review & launch"]

type WizardMode = "profile" | "custom"

/* A contender IS an agent runtime; provider+model is its configuration. */
const RUNTIMES = ["claude", "codex", "gemini", "grok", "opencode"] as const

interface ContenderDraft {
  key: string
  runtime: string
  provider_id: string
  model: string
  thinking_effort: string
}

/* The generated `Profile` in api.ts types only the fields the wizard's shared
   step reads (id/name/shared/per_contender_fields). A profile on disk also
   carries a server-assigned `rev` and the two blocks that make it a launchable
   measurement contract: `roster` (the contender columns) and `task_set`. We
   read the payload structurally here — the same convention Profiles.tsx uses —
   rather than widening the generated contract. */
interface RosterEntry {
  agent: string
  model?: string
  label?: string
  provider_id?: string
  thinking_effort?: string
}
interface TaskSet {
  tasks_dir: string
  task_ids: string[]
}
interface FullProfile {
  id: string
  name: string
  rev?: number
  shared: Partial<SharedConfig>
  per_contender_fields: string[]
  roster?: RosterEntry[]
  task_set?: TaskSet
}

interface LibraryRef {
  dir: string
  tasks: TaskPackage[]
}

/* Resolve a profile's (often repo-relative, e.g. "examples/tasks") tasks_dir to
   a known library without rewriting the stored value: exact match, then a path
   suffix, then the trailing folder name. Mirrors Profiles.tsx. */
function resolveLibraryDir(tasksDir: string, libraries: LibraryRef[]): LibraryRef | undefined {
  if (!tasksDir) return undefined
  return (
    libraries.find((l) => l.dir === tasksDir) ??
    libraries.find((l) => l.dir.endsWith("/" + tasksDir)) ??
    libraries.find((l) => l.dir.split("/").pop() === tasksDir.split("/").pop())
  )
}

/* The wizard runs a local, advisory copy of the backend's deviation diff so it
   can label the launch (ad-hoc vs faithful) before the plan returns. The
   backend in gui/experiments.py stays the single source of truth — it recomputes
   this on launch and is what actually annotates the snapshot. Keep the three
   comparisons below aligned with `_roster_comparison_key`,
   `_SHARED_CONTRACT_DEFAULTS`, and `_task_set_deviates`. */
const SHARED_CONTRACT_DEFAULTS: Record<string, string | number | null> = {
  evaluator_agent: "codex",
  evaluator_model: null,
  evaluator_auth_mode: null,
  judge_mode: "single",
  evaluator_timeout_seconds: 900,
  seed: 123,
  batch_size: 1,
  repeat: 1,
  executor_backend: "local",
  executor_auth_mode: "env",
  max_evaluator_parallel: 4,
  web_search_mode: "task",
  claude_max_turns: null,
}

function normalizedShared(value: unknown, def: string | number | null): string | number | null {
  if (value === null || value === undefined || (typeof value === "string" && !value.trim()))
    return def
  if (typeof value === "number") return value
  const text = String(value).trim()
  return /^-?\d+$/.test(text) ? parseInt(text, 10) : text
}

function rosterKey(entry: {
  agent?: string
  model?: string
  provider_id?: string
  thinking_effort?: string
}): string {
  return [
    entry.agent ?? "",
    (entry.model ?? "").trim(),
    entry.provider_id ?? "",
    entry.thinking_effort || "none",
  ].join("::")
}

function sameMultiset(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const x = [...a].sort()
  const y = [...b].sort()
  return x.every((value, index) => value === y[index])
}

function timestampName(prefix: string): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, "0")
  return `${prefix}_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(
    now.getHours(),
  )}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

/* A filesystem-safe profile id (SAFE_ID: starts alnum, then alnum/._-). */
function slugId(text: string): string {
  const slug = text
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[^a-z0-9]+/, "")
    .replace(/-+$/g, "")
  return slug || timestampName("profile")
}

/* Human-readable name for a deviating dimension, for the "modified" mark. */
function deviationLabel(dim: string): string {
  const named: Record<string, string> = {
    roster: "roster",
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
  return named[dim] ?? dim.replace(/_/g, " ")
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
        "none",
        "low",
        "medium",
        "high",
      ],
    [agentsQuery.data, customByRuntime],
  )

  const [step, setStep] = useState(0)
  const [mode, setMode] = useState<WizardMode>("profile")
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
  const [savingProfile, setSavingProfile] = useState(false)
  const [installingAgentId, setInstallingAgentId] = useState<string | null>(null)

  /* The profiles payload, read at its full on-disk shape (roster/task_set/rev). */
  const fullProfiles = useMemo(
    () => (profilesQuery.data?.profiles ?? []) as unknown as FullProfile[],
    [profilesQuery.data],
  )
  const rosteredProfiles = useMemo(
    () => fullProfiles.filter((profile) => (profile.roster?.length ?? 0) > 0),
    [fullProfiles],
  )
  const selectedProfile = useMemo(
    () => fullProfiles.find((profile) => profile.id === profileId) ?? null,
    [fullProfiles, profileId],
  )

  /* Instantiate a contract into the wizard: pre-check its task set, pre-generate
     one contender per roster column, and prefill the shared config. Each block
     stays editable afterward — the deviation diff below then flags what moved. */
  const appliedProfileRef = useRef<string | null>(null)
  const applyProfile = useCallback(
    (profile: FullProfile) => {
      const ts = profile.task_set
      if (ts?.tasks_dir) {
        const lib = resolveLibraryDir(ts.tasks_dir, libraries)
        if (lib) {
          setTasksDir(lib.dir)
          const healthy = new Set(lib.tasks.filter((task) => !task.error).map((task) => task.id))
          setTasks((ts.task_ids ?? []).filter((id) => healthy.has(id)))
        }
      }
      setContenders(
        (profile.roster ?? []).map((entry) => {
          contenderCounter += 1
          const pinnedExists =
            entry.provider_id && providers.some((item) => item.id === entry.provider_id)
          const provider = pinnedExists
            ? entry.provider_id!
            : compatibleProviders(filterFor(entry.agent), providers, entry.agent)[0]?.id ??
              entry.provider_id ??
              ""
          return {
            key: `c${contenderCounter}`,
            runtime: entry.agent,
            provider_id: provider,
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
    [libraries, providers, filterFor],
  )

  const chooseProfile = useCallback(
    (id: string) => {
      const profile = fullProfiles.find((item) => item.id === id)
      if (!profile) return
      setMode("profile")
      setProfileId(id)
      applyProfile(profile)
    },
    [fullProfiles, applyProfile],
  )

  const chooseCustom = useCallback(() => {
    setMode("custom")
    /* A custom launch is bare — it carries no roster contract. Drop any roster a
       profile prefilled so the Agents step starts from the operator's choices. */
    if (appliedProfileRef.current !== null) {
      setContenders([])
      appliedProfileRef.current = null
    }
  }, [])

  /* One-time init once profiles and libraries are both loaded: pick the initial
     profile (default, else the first with a roster) and the starting mode. A
     targeted "run these tasks" entry (location.state preset) keeps the operator's
     task choice and starts Custom. */
  const initRef = useRef(false)
  useEffect(() => {
    if (initRef.current) return
    if (!profilesQuery.data || !tasklib.data) return
    initRef.current = true
    const payload = profilesQuery.data
    const rostered = fullProfiles.filter((profile) => (profile.roster?.length ?? 0) > 0)
    const chosen =
      rostered.find((profile) => profile.id === payload.default_profile_id) ??
      rostered[0] ??
      fullProfiles.find((profile) => profile.id === payload.default_profile_id) ??
      fullProfiles[0]
    if (!chosen) return
    const hasPreset = Boolean(preset.tasksDir || preset.taskIds?.length)
    const startMode: WizardMode = !hasPreset && rostered.length ? "profile" : "custom"
    setMode(startMode)
    setProfileId(chosen.id)
    if (startMode === "profile") {
      applyProfile(chosen)
    } else {
      /* Custom parity with the previous flow: seed the shared config from the
         chosen profile so the Shared step is not blank. */
      setShared(chosen.shared)
      setPerFields(chosen.per_contender_fields?.length ? chosen.per_contender_fields : ["model"])
    }
  }, [profilesQuery.data, tasklib.data, fullProfiles, applyProfile, preset.tasksDir, preset.taskIds])

  /* The tasks_dir the launch reports. When a profile launch still points at the
     library its task_set names, send the profile's stored (often repo-relative)
     string so the backend's string-level task_set diff reads faithful rather
     than flagging the absolute path as a deviation. */
  const effectiveTasksDir = useCallback((): string => {
    if (mode === "profile" && selectedProfile?.task_set) {
      const lib = resolveLibraryDir(selectedProfile.task_set.tasks_dir, libraries)
      if (lib && lib.dir === tasksDir) return selectedProfile.task_set.tasks_dir
    }
    return tasksDir
  }, [mode, selectedProfile, libraries, tasksDir])

  const launchProfileId = mode === "profile" && profileId ? profileId : undefined

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
    if (step !== 4 || !tasksDir || !contenders.length) return
    if (planTimer.current) clearTimeout(planTimer.current)
    planTimer.current = setTimeout(async () => {
      try {
        const result = await api.createExperiment({
          name: expName.trim(),
          tasks_dir: effectiveTasksDir(),
          tasks,
          shared,
          contenders: apiContenders(),
          profile_id: launchProfileId,
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
  }, [step, expName, tasksDir, tasks, shared, apiContenders, contenders.length, effectiveTasksDir, launchProfileId])

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

  /* Advisory deviation diff (profile mode only), mirroring the backend's
     authoritative comparison so the launch can be labelled ad-hoc vs faithful
     before the plan returns. The backend recomputes and records the real one. */
  const deviation: string[] = (() => {
    if (mode !== "profile" || !selectedProfile?.roster?.length) return []
    const dims: string[] = []
    if (!sameMultiset(apiContenders().map(rosterKey), (selectedProfile.roster ?? []).map(rosterKey)))
      dims.push("roster")
    const ts = selectedProfile.task_set
    if (ts) {
      if (effectiveTasksDir() !== (ts.tasks_dir ?? "")) {
        dims.push("task_set")
      } else {
        const lib = resolveLibraryDir(ts.tasks_dir, libraries)
        const healthyIds = new Set((lib?.tasks ?? []).filter((t) => !t.error).map((t) => t.id))
        const baseline = ts.task_ids?.length
          ? ts.task_ids.filter((id) => healthyIds.has(id))
          : [...healthyIds]
        if (!sameMultiset(baseline, selectedTaskObjs.map((t) => t.id))) dims.push("task_set")
      }
    }
    const ps = (selectedProfile.shared ?? {}) as Record<string, unknown>
    const cs = shared as Record<string, unknown>
    for (const key of Object.keys(SHARED_CONTRACT_DEFAULTS)) {
      const def = SHARED_CONTRACT_DEFAULTS[key]
      if (normalizedShared(cs[key], def) !== normalizedShared(ps[key], def)) dims.push(key)
    }
    return dims
  })()
  const deviated = deviation.length > 0

  /* One create call, used by every launch exit. Passing profile_id makes the
     backend diff the effective payload against the profile and record any
     deviation in the run snapshot; omitting it launches bare. */
  const createAndGo = async (profileIdForLaunch?: string) => {
    if (selectedTaskObjs.length === 0) {
      setStep(1)
      throw new Error("Select at least one runnable task before continuing.")
    }
    const record = await api.createExperiment({
      name: expName.trim(),
      tasks_dir: effectiveTasksDir(),
      tasks,
      shared,
      contenders: apiContenders(),
      profile_id: profileIdForLaunch,
    })
    toast.success(`Experiment ${record.name ?? expName} started: ${contenders.length} runs.`)
    queryClient.invalidateQueries({ queryKey: ["experiments"] })
    queryClient.invalidateQueries({ queryKey: ["runs"] })
    navigate(`/experiments/${encodeURIComponent(expName.trim())}`)
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

  /* Build a full profile object from the current wizard configuration. */
  const wizardProfile = (id: string, name: string): FullProfile => {
    const roster: RosterEntry[] = contenders.map((draft) => {
      const entry: RosterEntry = { agent: draft.runtime }
      if (draft.model.trim()) entry.model = draft.model.trim()
      if (draft.provider_id) entry.provider_id = draft.provider_id
      if (draft.thinking_effort && draft.thinking_effort !== "none")
        entry.thinking_effort = draft.thinking_effort
      return entry
    })
    const profile: FullProfile = {
      id,
      name,
      shared,
      per_contender_fields: perFields.length ? perFields : ["model"],
      roster,
    }
    /* Keep the profile's stored dir string when the launch still points at the
       library it names; otherwise store the current one. */
    const keepStored =
      mode === "profile" &&
      selectedProfile?.task_set &&
      resolveLibraryDir(selectedProfile.task_set.tasks_dir, libraries)?.dir === tasksDir
    const storedDir = keepStored ? selectedProfile!.task_set!.tasks_dir : tasksDir
    if (storedDir) profile.task_set = { tasks_dir: storedDir, task_ids: tasks }
    return profile
  }

  /* saveProfiles replaces the whole file, so send every existing profile with
     the target updated or appended. The server recomputes each rev by content. */
  const persistProfile = async (target: FullProfile, asNew: boolean) => {
    const next = asNew
      ? [...fullProfiles, target]
      : fullProfiles.map((profile) => (profile.id === target.id ? target : profile))
    await api.saveProfiles({
      default_profile_id: profilesQuery.data?.default_profile_id ?? null,
      profiles: next as unknown as ProfilesPayload["profiles"],
    })
    await queryClient.invalidateQueries({ queryKey: ["profiles"] })
  }

  const uniqueProfileId = (base: string): string => {
    const ids = new Set(fullProfiles.map((profile) => profile.id))
    const root = slugId(base)
    if (!ids.has(root)) return root
    let counter = 2
    while (ids.has(`${root}-${counter}`)) counter += 1
    return `${root}-${counter}`
  }

  const updateProfileAndLaunch = async () => {
    if (!selectedProfile) return
    setLaunching(true)
    try {
      await persistProfile(wizardProfile(selectedProfile.id, selectedProfile.name), false)
      await createAndGo(selectedProfile.id)
    } catch (error) {
      toast.error((error as Error).message)
      setLaunching(false)
    }
  }

  const saveAsNewProfileAndLaunch = async () => {
    setLaunching(true)
    try {
      const id = uniqueProfileId(expName)
      await persistProfile(wizardProfile(id, expName.trim()), true)
      await createAndGo(id)
    } catch (error) {
      toast.error((error as Error).message)
      setLaunching(false)
    }
  }

  const saveConfigAsProfile = async () => {
    setSavingProfile(true)
    try {
      const id = uniqueProfileId(expName)
      await persistProfile(wizardProfile(id, expName.trim()), true)
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
          deviated={deviated}
          dims={deviation}
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
          onRemove={(key) =>
            setContenders((current) => current.filter((item) => item.key !== key))
          }
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
        {step < STEPS.length - 1 ? (
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

/* ---------- stepper ---------- */

function Stepper({ current, onSelect }: { current: number; onSelect: (step: number) => void }) {
  return (
    <div className="-mx-1 min-w-0 overflow-x-auto px-1 pb-1">
      <ol className="flex min-w-max items-center gap-2 sm:min-w-0">
        {STEPS.map((label, index) => {
          const done = index < current
          const active = index === current
          return (
            <li key={label} className="flex min-w-0 flex-none items-center gap-2 sm:flex-1">
              <button
                type="button"
                disabled={index > current}
                onClick={() => onSelect(index)}
                className={cn(
                  "flex min-w-0 shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors sm:shrink",
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
              {index < STEPS.length - 1 && (
                <div className="h-px w-10 flex-none bg-border sm:flex-1" />
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

/* ---------- contract status (steps 1-4, profile mode) ---------- */

/* A quiet, persistent reminder of the contract the wizard is building under,
   and whether the current configuration still matches it. The mark is muted by
   design — deviating from a profile is a legitimate ad-hoc test, not an error. */
function ContractStatusBar({
  profileName,
  rev,
  deviated,
  dims,
}: {
  profileName: string
  rev?: number
  deviated: boolean
  dims: string[]
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
      <span className="text-muted-foreground">
        Under{" "}
        <span className="font-medium text-foreground">{profileName}</span>
        {rev !== undefined && (
          <>
            <span className="text-border"> · </span>
            <span className="font-mono">rev {rev}</span>
          </>
        )}
      </span>
      {deviated ? (
        <span
          className="inline-flex items-center gap-1.5 rounded-md bg-warn-soft px-2 py-0.5 font-medium text-warn-ink"
          title={`Deviates from the profile at: ${dims.map(deviationLabel).join(", ")}`}
        >
          <PencilLine className="size-3.5 shrink-0" aria-hidden />
          modified
          <span className="font-normal text-warn-ink/80">
            · {dims.length} change{dims.length === 1 ? "" : "s"}
          </span>
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <Check className="size-3.5 shrink-0 text-pass" aria-hidden />
          matches the contract
        </span>
      )}
    </div>
  )
}

/* ---------- step 0: mode ---------- */

/* The launch's first decision: instantiate a saved measurement contract, or
   configure a bare run by hand. This gate exists so a run's provenance is a
   deliberate choice, not an accident of which fields were left at defaults. */
function StepMode({
  mode,
  profiles,
  rosteredProfiles,
  defaultProfileId,
  profileId,
  selectedProfile,
  libraries,
  runtimeLabel,
  onChooseProfile,
  onChooseCustom,
}: {
  mode: WizardMode
  profiles: FullProfile[]
  rosteredProfiles: FullProfile[]
  defaultProfileId: string | null
  profileId: string | null
  selectedProfile: FullProfile | null
  libraries: LibraryRef[]
  runtimeLabel: (runtime: string) => string
  onChooseProfile: (id: string) => void
  onChooseCustom: () => void
}) {
  const hasRostered = rosteredProfiles.length > 0
  const profileActive = mode === "profile"
  const customActive = mode === "custom"
  const enterProfile = () => {
    if (!hasRostered || profileActive) return
    const target = profileId ?? rosteredProfiles[0]?.id
    if (target) onChooseProfile(target)
  }
  return (
    <div role="radiogroup" aria-label="Launch mode" className="grid gap-3 sm:grid-cols-2">
      {/* From a profile */}
      {hasRostered ? (
        <div
          role="radio"
          aria-checked={profileActive}
          tabIndex={0}
          onClick={enterProfile}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault()
              enterProfile()
            }
          }}
          className={cn(
            "flex cursor-pointer flex-col gap-3 rounded-xl border bg-card p-5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            profileActive
              ? "border-primary ring-1 ring-primary"
              : "hover:border-primary/40",
          )}
        >
          <div className="flex items-center gap-2.5">
            <span
              className={cn(
                "grid size-8 shrink-0 place-content-center rounded-lg",
                profileActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
              )}
            >
              <Layers className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold">From a profile</div>
              <div className="text-xs text-muted-foreground">
                Reuse a saved measurement contract
              </div>
            </div>
          </div>
          <p className="text-[13px] leading-5 text-muted-foreground">
            Its roster, task set, and judge prefill the wizard, so these runs land as
            comparable columns in the coverage matrix.
          </p>
          <div onClick={(event) => event.stopPropagation()}>
            <Select value={profileId ?? undefined} onValueChange={onChooseProfile}>
              <SelectTrigger className="w-full" aria-label="Profile">
                <SelectValue placeholder="Choose a profile" />
              </SelectTrigger>
              <SelectContent>
                {rosteredProfiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.name}
                    {profile.id === defaultProfileId ? " (default)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {selectedProfile && (
            <ContractSummary
              profile={selectedProfile}
              libraries={libraries}
              runtimeLabel={runtimeLabel}
            />
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/30 p-5">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-content-center rounded-lg bg-muted text-muted-foreground">
              <Layers className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-muted-foreground">From a profile</div>
              <div className="text-xs text-muted-foreground">No contract to reuse yet</div>
            </div>
          </div>
          <p className="text-[13px] leading-5 text-muted-foreground">
            {profiles.length
              ? "No saved profile declares a roster, so none can prefill a comparable run."
              : "No profiles are saved yet."}{" "}
            Define one and its roster in Setup.
          </p>
          <Link
            to="/profiles"
            className="inline-flex w-fit items-center gap-1 text-sm font-medium text-primary hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Create a profile <ArrowUpRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      )}

      {/* Custom */}
      <div
        role="radio"
        aria-checked={customActive}
        tabIndex={0}
        onClick={onChooseCustom}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            onChooseCustom()
          }
        }}
        className={cn(
          "flex cursor-pointer flex-col gap-3 rounded-xl border bg-card p-5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          customActive ? "border-primary ring-1 ring-primary" : "hover:border-primary/40",
        )}
      >
        <div className="flex items-center gap-2.5">
          <span
            className={cn(
              "grid size-8 shrink-0 place-content-center rounded-lg",
              customActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
            )}
          >
            <SlidersHorizontal className="size-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold">Custom</div>
            <div className="text-xs text-muted-foreground">Configure everything by hand</div>
          </div>
        </div>
        <p className="text-[13px] leading-5 text-muted-foreground">
          Pick the tasks, agents, and judge yourself. This launches a bare run: no contract
          snapshot, and it will not fill a coverage-matrix column.
        </p>
      </div>
    </div>
  )
}

/* One-line summary of a profile's measurement contract, for the mode card. */
function ContractSummary({
  profile,
  libraries,
  runtimeLabel,
}: {
  profile: FullProfile
  libraries: LibraryRef[]
  runtimeLabel: (runtime: string) => string
}) {
  const rosterCount = profile.roster?.length ?? 0
  const judgeAgent = String(profile.shared.evaluator_agent ?? "codex")
  const judgeModel = String(profile.shared.evaluator_model ?? "") || "runtime default"
  const repeat = Number(profile.shared.repeat) || 1
  const ts = profile.task_set
  const taskCount = ts?.task_ids?.length ?? 0
  const lib = ts ? resolveLibraryDir(ts.tasks_dir, libraries) : undefined
  const dirLabel = ts ? (lib ? shortenPath(lib.dir) : ts.tasks_dir) : null
  const facts: string[] = [
    `${rosterCount} contender${rosterCount === 1 ? "" : "s"}`,
    `${runtimeLabel(judgeAgent)} · ${judgeModel} judge`,
    `×${repeat} repeat`,
  ]
  if (ts) {
    facts.push(taskCount ? `${taskCount} task${taskCount === 1 ? "" : "s"}` : "no explicit tasks")
  }
  return (
    <div className="mt-1 flex flex-col gap-1 rounded-lg bg-muted/50 px-3 py-2.5 text-[13px] leading-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
        {facts.map((fact, index) => (
          <span key={index} className="flex items-center gap-2">
            {index > 0 && <span className="text-border" aria-hidden>·</span>}
            <span>{fact}</span>
          </span>
        ))}
      </div>
      {dirLabel && (
        <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
          <span className="truncate" title={ts?.tasks_dir}>{dirLabel}</span>
          {profile.rev !== undefined && (
            <>
              <span className="text-border" aria-hidden>·</span>
              <span>rev {profile.rev}</span>
            </>
          )}
        </div>
      )}
    </div>
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
  const runnableTasks = library?.tasks.filter((task) => !task.error) ?? []
  const selectedRunnableCount = tasks.filter((id) =>
    runnableTasks.some((task) => task.id === id),
  ).length
  const requiresTaskSelection = runnableTasks.length > 0 && selectedRunnableCount === 0
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
              <span
                className={cn(
                  "text-xs",
                  requiresTaskSelection ? "font-medium text-warn-ink" : "text-muted-foreground",
                )}
              >
                {selectedRunnableCount} of {runnableTasks.length} runnable selected
              </span>
            </div>
            {runnableTasks.length === 0 ? (
              <Alert className="border-warn-ink/40 bg-warn-soft/60">
                <AlertTriangle className="size-4" />
                <AlertTitle>No runnable tasks in this folder</AlertTitle>
                <AlertDescription>
                  Fix the broken task packages, import valid ones, or choose another task
                  folder before continuing.
                </AlertDescription>
              </Alert>
            ) : requiresTaskSelection ? (
              <Alert className="border-warn-ink/40 bg-warn-soft/60">
                <AlertTriangle className="size-4" />
                <AlertTitle>Select at least one task</AlertTitle>
                <AlertDescription>
                  The experiment needs an explicit task set so the run snapshot is
                  reproducible and comparable.
                </AlertDescription>
              </Alert>
            ) : null}
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
              Only selected runnable task packages will run.
            </p>
            {library.tasks.some((task) => task.error) && (
              <p className="text-xs text-warn-ink">
                This folder contains broken packages. They are disabled here until fixed.
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

function JudgeCredentialStatus({
  provider,
  authMode,
}: {
  provider?: AiProvider
  authMode?: string
}) {
  if (!provider) {
    return (
      <div className="flex min-h-9 min-w-0 flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Explicit credentials</span>
        <span className="font-mono">{authMode || "env"}</span>
        <span className="min-w-0 break-words">
          No provider reference is attached to this judge model.
        </span>
      </div>
    )
  }

  const mode = provider.auth === "cli_login" ? "global" : "env"
  const keyLabel = provider.api_key_env || "API key env"

  return (
    <div className="flex min-h-9 min-w-0 flex-wrap items-center gap-2 rounded-md border bg-muted/40 px-3 text-xs">
      <ProviderIcon provider={provider} size={14} />
      <span className="font-medium text-foreground">{provider.name}</span>
      <span className="font-mono text-muted-foreground">{mode}</span>
      {provider.auth === "api_key" ? (
        <span
          className={cn(
            "rounded px-1.5 py-0.5 font-mono text-[11px]",
            provider.key_present
              ? "bg-pass-soft text-pass-ink"
              : "bg-warn-soft text-warn-ink",
          )}
        >
          {keyLabel} {provider.key_present ? "set" : "missing"}
        </span>
      ) : (
        <span className="rounded bg-live-soft px-1.5 py-0.5 text-[11px] text-live-ink">
          CLI login
        </span>
      )}
    </div>
  )
}

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
    <div className="grid min-w-0 gap-4">
      <Card className="min-w-0 py-0">
        <CardContent className="flex flex-wrap items-center gap-3 p-3 sm:px-4">
          <div className="grid min-w-0 gap-0.5">
            <span className="text-xs font-medium text-muted-foreground">Profile contract</span>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Select value={profileId ?? undefined} onValueChange={onSelectProfile}>
                <SelectTrigger className="w-full sm:w-64">
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
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="sm:ml-auto"
            disabled={saving || !profileId}
            onClick={saveToProfile}
          >
            <Save /> Save to profile
          </Button>
        </CardContent>
      </Card>

      <Card className="min-w-0 overflow-hidden py-0">
        <CardContent className="p-0">
          <div className="grid min-w-0 lg:grid-cols-[minmax(0,1.15fr)_minmax(21rem,0.85fr)]">
            <section className="grid min-w-0 gap-4 p-4 sm:p-5">
              <div className="flex items-start gap-2">
                <Scale className="mt-0.5 size-4 text-live-ink" />
                <div className="grid gap-0.5">
                  <span className="text-sm font-semibold">Judge</span>
                  <span className="text-xs text-muted-foreground">
                    Shared across all agents. The judge is an agent too.
                  </span>
                </div>
              </div>

              <div className="grid min-w-0 gap-3 sm:grid-cols-2">
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
                    <SelectTrigger className="w-full">
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
                </div>

                <div className="grid gap-1.5">
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

                <div className="grid min-w-0 gap-1.5 sm:col-span-2">
                  <Label>{judgeOwnLogin ? "Judge credentials" : "Judge model"}</Label>
                  {judgeOwnLogin ? (
                    <div className="flex min-h-9 items-center rounded-md border bg-muted/40 px-3 text-sm text-muted-foreground">
                      {runtimeLabel(judgeRuntime)} uses its own login and configuration.
                    </div>
                  ) : (
                    <div className="grid min-w-0 gap-2">
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
                      <JudgeCredentialStatus
                        provider={judgeProvider}
                        authMode={String(shared.evaluator_auth_mode ?? "env")}
                      />
                      {judgeRuntime === "codex" && (
                        <p className="text-xs text-muted-foreground">
                          Codex judge uses the official OpenAI endpoint; gateway overrides are
                          process-wide and would also reroute Codex agents under test.
                        </p>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {judgeCustom && judgeCustom.judge_args_inherited && (
                <Alert className="border-warn-ink/40 bg-warn-soft/60">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>Judge can modify its workspace</AlertTitle>
                  <AlertDescription>
                    This runtime declares no read-only judge mode. Prefer a runtime with a
                    plan/read-only flag for judging.
                  </AlertDescription>
                </Alert>
              )}

              <RadioGroup
                value={String(shared.judge_mode ?? "single")}
                onValueChange={(value) => setSharedField("judge_mode", value)}
                className="grid gap-2 xl:grid-cols-3"
              >
                {JUDGE_MODES.map((mode) => (
                  <label
                    key={mode.value}
                    className={cn(
                      "flex cursor-pointer items-start gap-2.5 rounded-md border p-2.5",
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
                    {judgeConflicts} agent{judgeConflicts > 1 ? "s use" : " uses"} the same
                    model as the judge. Self-grading biases scores; consider an independent
                    judge.
                  </AlertDescription>
                </Alert>
              )}
            </section>

            <section className="grid min-w-0 content-start gap-5 border-t p-4 sm:p-5 lg:border-t-0 lg:border-l">
              <div className="flex items-start gap-2">
                <SlidersHorizontal className="mt-0.5 size-4 text-muted-foreground" />
                <div className="grid gap-0.5">
                  <span className="text-sm font-semibold">Run controls</span>
                  <span className="text-xs text-muted-foreground">
                    Execution environment and deterministic scheduling.
                  </span>
                </div>
              </div>

              <div className="grid min-w-0 gap-3 sm:grid-cols-2">
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

              {String(shared.web_search_mode ?? "task") !== "task" && (
                <p className="text-xs text-warn-ink">
                  Web-search override is enforced for Claude Code and Codex; other runtimes'
                  own tooling decides access.
                </p>
              )}

              {String(shared.executor_backend) === "docker" && (
                <p className="text-xs text-muted-foreground">
                  Each agent runs in its runtime's own container image. Build images once with{" "}
                  <code className="font-mono">make docker-images</code>. The judge still runs
                  on this machine.
                </p>
              )}
              {String(shared.executor_backend) === "docker" && localRuntimeNames.length > 0 && (
                <Alert className="border-warn-ink/40 bg-warn-soft/60">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>Some agents will run without Docker</AlertTitle>
                  <AlertDescription>
                    Docker isolation covers built-in runtimes and custom runtimes with a Docker
                    image. These agents run directly on this machine:{" "}
                    {localRuntimeNames.join(", ")}.
                  </AlertDescription>
                </Alert>
              )}

              <div className="grid min-w-0 gap-2 border-t pt-4">
                <span className="text-sm font-semibold">Per-agent fields</span>
                <p className="text-xs text-muted-foreground">
                  Run-time knobs each agent sets individually. Endpoints and credentials always
                  come from the provider.
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
              </div>

              <Collapsible>
                <CollapsibleTrigger className="group flex w-full items-center justify-between border-t pt-4 text-left">
                  <span className="text-sm font-semibold">Advanced</span>
                  <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
                </CollapsibleTrigger>
                <CollapsibleContent className="grid gap-4 pt-4">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="grid gap-1.5">
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
                        More parallel judges finish sooner but may hit provider rate limits.
                      </p>
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor="claude-max-turns">Claude max turns</Label>
                      <Input
                        id="claude-max-turns"
                        type="number"
                        min={1}
                        placeholder="unlimited"
                        value={String(shared.claude_max_turns ?? "")}
                        onChange={(event) =>
                          setSharedField("claude_max_turns", event.target.value)
                        }
                      />
                      <p className="text-xs text-muted-foreground">
                        Only affects Claude Code agents. Blank means no cap.
                      </p>
                    </div>
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
                      Added to every run command exactly as typed.
                    </p>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </section>
          </div>
        </CardContent>
      </Card>

      <section className="grid gap-2">
        <div className="flex items-center gap-2 px-1">
          <Sparkles className="size-4 text-muted-foreground" />
          <h3 className="text-sm font-semibold text-muted-foreground">Research add-ons</h3>
        </div>
        <div className="grid min-w-0 gap-3">
          <PromptAssistanceBlock
            tasksDir={tasksDir}
            selectedTasks={selectedTasks}
            shared={shared}
            setShared={setShared}
            setSharedField={setSharedField}
          />
          <ExecutorSkillsBlock skills={skills} shared={shared} setShared={setShared} />
        </div>
      </section>
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
  mode,
  profileName,
  profileRev,
  deviated,
  launching,
  savingProfile,
  onUpdateProfileLaunch,
  onSaveAsNewLaunch,
  onSaveConfigAsProfile,
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
  mode: WizardMode
  profileName: string | null
  profileRev: number | null
  deviated: boolean
  launching: boolean
  savingProfile: boolean
  onUpdateProfileLaunch: () => void
  onSaveAsNewLaunch: () => void
  onSaveConfigAsProfile: () => void
}) {
  const busy = launching || savingProfile
  const nextRev = profileRev !== null ? profileRev + 1 : null
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
      {/* Contract provenance: what these runs will be attributed to on disk. */}
      {mode === "profile" && profileName && (
        <p className="text-[13px] leading-5 text-muted-foreground">
          Launching under <span className="font-medium text-foreground">{profileName}</span>
          {profileRev !== null && (
            <>
              <span className="text-border"> · </span>
              <span className="font-mono">rev {profileRev}</span>
            </>
          )}
        </p>
      )}
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

      {/* Launch exits beyond the primary. Profile mode: the primary button is an
          ad-hoc test when the config deviates; these persist the deviation into
          the contract instead. Custom mode: capture the bare config as a
          reusable profile. */}
      {mode === "profile" && deviated && (
        <Card className="gap-0 border-warn-ink/30 bg-warn-soft/25 py-4">
          <CardContent className="grid gap-3 px-4">
            <div className="flex items-start gap-2.5">
              <PencilLine className="mt-0.5 size-4 shrink-0 text-warn-ink" aria-hidden />
              <div className="grid gap-1">
                <span className="text-sm font-medium">
                  This configuration deviates from {profileName}
                </span>
                <p className="max-w-prose text-[13px] leading-5 text-muted-foreground">
                  This launches an ad-hoc test: the deviation is recorded in the run&rsquo;s
                  snapshot but not saved to the profile. To make it the contract instead:
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pl-[26px]">
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !plan.plans}
                onClick={onUpdateProfileLaunch}
              >
                <Save />
                {profileRev !== null && nextRev !== null
                  ? `Update profile (rev ${profileRev}→${nextRev}) & launch`
                  : "Update profile & launch"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !plan.plans}
                onClick={onSaveAsNewLaunch}
              >
                <Plus /> Save as new profile & launch
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {mode === "custom" && (
        <Card className="py-4">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 px-4">
            <div className="grid min-w-0 gap-0.5">
              <span className="text-sm font-medium">Reuse this configuration?</span>
              <p className="text-[13px] leading-5 text-muted-foreground">
                Save it as a profile so future runs launch under the same contract.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !contenders.length}
              onClick={onSaveConfigAsProfile}
            >
              {savingProfile ? <Loader2 className="animate-spin" /> : <Save />} Save this
              configuration as a profile
            </Button>
          </CardContent>
        </Card>
      )}
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
      className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
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
