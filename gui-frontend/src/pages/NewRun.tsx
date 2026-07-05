import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Link, useLocation, useNavigate } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  FolderSearch,
  Loader2,
  Plus,
  Rocket,
  Save,
  Scale,
  Trash2,
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
import { AGENT_LABELS, AGENT_NOTES, AgentIcon, compatibleProviders, DEFAULT_OPENAI_BASE_URLS } from "@/components/brand"
import { ProviderModelPicker } from "@/components/model-picker"
import { ErrorNote } from "@/pages/Dashboard"
import {
  api,
  type AiProvider,
  type Contender,
  type CustomRuntime,
  type ExperimentPlanItem,
  type Profile,
  type SharedConfig,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const JUDGE_MODES = [
  { value: "single", label: "Single judge", note: "One session grades all rubrics. Fast." },
  { value: "parallel", label: "Per-rubric judges", note: "Independent judge per rubric. Strict." },
  { value: "both", label: "Both", note: "Run both to compare their agreement." },
]

/* Only true run-time knobs are per-contender; endpoints and credentials
   belong to providers (the resource side). */
const PER_FIELD_OPTIONS = [
  { id: "model", label: "Model", locked: true },
  { id: "thinking_effort", label: "Claude thinking effort" },
]

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

/* A (runtime, provider) pair fully determines auth mode, gateway flags,
   codex config overrides, and env overrides — one channel per runtime:
   Claude Code and Gemini CLI take env vars, Codex takes config overrides in
   its bin prefix (endpoint must speak the OpenAI Responses API), OpenCode
   takes gateway flags. Grok Build has no override channel. */
interface ContenderSettings {
  auth_mode: string
  gateway: Record<string, string | undefined>
  codex_bin?: string
  env?: Record<string, { value?: string; from_env?: string }>
}

/* Endpoint the provider exposes for a given wire protocol. */
function providerEndpoint(protocol: string, provider: AiProvider): string {
  switch (protocol) {
    case "openai":
      return provider.base_url || DEFAULT_OPENAI_BASE_URLS[provider.kind] || ""
    case "anthropic":
      return provider.kind === "anthropic"
        ? provider.base_url
        : (provider.anthropic_base_url ?? "")
    case "gemini":
      return provider.kind === "google" ? provider.base_url : (provider.gemini_base_url ?? "")
    default:
      return ""
  }
}

function providerSettings(
  runtime: string,
  provider: AiProvider,
  custom?: CustomRuntime,
): ContenderSettings {
  const authMode = provider.auth === "cli_login" ? "global" : "env"
  if (runtime.startsWith("custom:") && custom) {
    /* Custom runtimes declare which env vars carry the endpoint and key. */
    const env: Record<string, { value?: string; from_env?: string }> = {}
    const endpoint = providerEndpoint(custom.protocol ?? "none", provider)
    if (custom.base_url_env && endpoint) env[custom.base_url_env] = { value: endpoint }
    if (custom.api_key_env && provider.api_key_env)
      env[custom.api_key_env] = { from_env: provider.api_key_env }
    return {
      auth_mode: authMode,
      gateway: {},
      env: Object.keys(env).length ? env : undefined,
    }
  }
  if (runtime === "opencode") {
    return {
      auth_mode: authMode,
      gateway: {
        opencode_provider: provider.id,
        opencode_base_url:
          provider.base_url || DEFAULT_OPENAI_BASE_URLS[provider.kind] || undefined,
        opencode_api_key_env: provider.api_key_env || undefined,
      },
    }
  }
  if (runtime === "codex" && provider.kind !== "openai" && provider.base_url) {
    /* Official codex config overrides; ids are SAFE_ID so values need no quoting. */
    const gw = provider.id.replace(/[^A-Za-z0-9_]/g, "_")
    return {
      auth_mode: authMode,
      gateway: {},
      codex_bin: [
        "codex",
        `-c model_provider=${gw}`,
        `-c model_providers.${gw}.name=${gw}`,
        `-c model_providers.${gw}.base_url=${provider.base_url}`,
        `-c model_providers.${gw}.env_key=${provider.api_key_env || "OPENAI_API_KEY"}`,
        `-c model_providers.${gw}.wire_api=responses`,
      ].join(" "),
    }
  }
  if (runtime === "claude") {
    const gatewayUrl =
      provider.kind === "anthropic" ? provider.base_url : provider.anthropic_base_url
    if (gatewayUrl) {
      return {
        auth_mode: authMode,
        gateway: {},
        env: {
          ANTHROPIC_BASE_URL: { value: gatewayUrl },
          ANTHROPIC_AUTH_TOKEN: { from_env: provider.api_key_env || "ANTHROPIC_AUTH_TOKEN" },
        },
      }
    }
  }
  if (runtime === "gemini") {
    const gatewayUrl =
      provider.kind === "google" ? provider.base_url : provider.gemini_base_url
    if (gatewayUrl) {
      return {
        auth_mode: authMode,
        gateway: {},
        env: {
          GOOGLE_GEMINI_BASE_URL: { value: gatewayUrl },
          GEMINI_API_KEY: { from_env: provider.api_key_env || "GEMINI_API_KEY" },
        },
      }
    }
  }
  return { auth_mode: authMode, gateway: {} }
}

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
  const libraries = useMemo(
    () => (tasklib.data?.libraries ?? []).filter((library) => library.exists),
    [tasklib.data],
  )
  const providers = providersQuery.data?.providers ?? []
  const customRuntimes = useMemo(
    () => (agentsQuery.data?.custom ?? []).filter((agent) => !agent.error),
    [agentsQuery.data],
  )
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

  const setSharedField = useCallback(
    (key: keyof SharedConfig, value: unknown) =>
      setShared((current) => ({ ...current, [key]: value })),
    [],
  )

  const addContender = (runtime: string) => {
    contenderCounter += 1
    const compatible = compatibleProviders(runtime, providers, customByRuntime[runtime]?.protocol)
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
      const settings: ContenderSettings = provider
        ? providerSettings(draft.runtime, provider, custom)
        : { auth_mode: "global", gateway: {} }
      /* A custom runtime without a model flag cannot receive a model choice. */
      const model = custom && !custom.model_flag ? "" : draft.model.trim()
      return [
        {
          label: `${runtimeLabel(draft.runtime)} ${model || "default"}`.trim(),
          agent: draft.runtime,
          model,
          auth_mode: settings.auth_mode,
          thinking_effort: perFields.includes("thinking_effort") ? draft.thinking_effort : "none",
          ...settings.gateway,
          codex_bin: settings.codex_bin,
          env: settings.env,
        },
      ]
    })
  }, [contenders, providers, perFields, customByRuntime, runtimeLabel])

  /* Authoritative plan preview on the review step. */
  const [plan, setPlan] = useState<{ plans: ExperimentPlanItem[] | null; error: string | null }>({
    plans: null,
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
        setPlan({ plans: result.plans, error: null })
      } catch (error) {
        setPlan({ plans: null, error: (error as Error).message })
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
  const taskCount = tasks.length || activeLibrary?.tasks.length || 0
  const judgeConflicts = contenders.filter(
    (draft) =>
      draft.model.trim() &&
      draft.model.trim() === String(shared.evaluator_model ?? "").trim(),
  )

  const canNext =
    step === 0
      ? Boolean(activeLibrary && activeLibrary.tasks.length)
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
          dockerCapable={dockerCapable}
          contenders={contenders}
          perFields={perFields}
          backend={String(shared.executor_backend ?? "local")}
          onAdd={addContender}
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
          shared={shared}
          setShared={setShared}
          setSharedField={setSharedField}
          perFields={perFields}
          setPerFields={setPerFields}
          judgeConflicts={judgeConflicts.length}
          customRuntimes={customRuntimes}
          customByRuntime={customByRuntime}
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
        />
      )}

      <div className="flex items-center justify-between">
        <Button variant="outline" disabled={step === 0} onClick={() => setStep(step - 1)}>
          <ArrowLeft /> Back
        </Button>
        {step < STEPS.length - 1 ? (
          <Button disabled={!canNext} onClick={() => setStep(step + 1)}>
            Next <ArrowRight />
          </Button>
        ) : (
          <Button disabled={!plan.plans || launching} onClick={launch}>
            {launching ? <Loader2 className="animate-spin" /> : <Rocket />}
            {launching ? "Launching…" : `Launch ${contenders.length} runs`}
          </Button>
        )}
      </div>

      <DirectoryPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
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
  libraries: { dir: string; tasks: { id: string; name: string; rubric_count: number }[] }[]
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
                  ? `${tasks.length} of ${library.tasks.length} selected`
                  : `all ${library.tasks.length} will run`}
              </span>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {library.tasks.map((task) => {
                const checked = tasks.includes(task.id)
                return (
                  <label
                    key={task.id}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                      checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                    )}
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={checked}
                      onCheckedChange={(value) =>
                        setTasks(
                          value ? [...tasks, task.id] : tasks.filter((id) => id !== task.id),
                        )
                      }
                    />
                    <span className="min-w-0">
                      <span className="block truncate font-mono text-sm font-medium">
                        {task.id}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {task.name} · {task.rubric_count} rubrics
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              Leave everything unchecked to run the whole folder.
            </p>
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

function StepContenders({
  providers,
  customRuntimes,
  customByRuntime,
  dockerCapable,
  contenders,
  perFields,
  backend,
  onAdd,
  onUpdate,
  onRemove,
}: {
  providers: AiProvider[]
  customRuntimes: CustomRuntime[]
  customByRuntime: Record<string, CustomRuntime>
  dockerCapable: (runtime: string) => boolean
  contenders: ContenderDraft[]
  perFields: string[]
  backend: string
  onAdd: (runtime: string) => void
  onUpdate: (key: string, patch: Partial<ContenderDraft>) => void
  onRemove: (key: string) => void
}) {
  const options: RuntimeOption[] = [
    ...RUNTIMES.map((runtime) => ({
      id: runtime,
      label: AGENT_LABELS[runtime],
      note: AGENT_NOTES[runtime],
    })),
    ...customRuntimes.map((agent) => ({
      id: agent.id,
      label: agent.label ?? agent.spec_id,
      note: agent.command ?? "",
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
              const compatible = compatibleProviders(option.id, providers, option.protocol)
              const modelCount = compatible.reduce((sum, item) => sum + item.models.length, 0)
              const ownLogin = option.protocol === "none"
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => onAdd(option.id)}
                  className="grid justify-items-center gap-1.5 rounded-md border p-3 text-center transition-colors hover:border-primary/50 hover:bg-accent/40"
                >
                  <AgentIcon agent={option.id} icon={option.icon} size={26} />
                  <span className="text-sm font-medium">{option.label}</span>
                  <span className="max-w-full truncate text-[11px] leading-tight text-muted-foreground">
                    {option.note}
                  </span>
                  <span className="text-[11px] text-muted-foreground">
                    {ownLogin
                      ? "own login / config"
                      : compatible.length
                        ? `${modelCount} models from ${compatible.length} provider${compatible.length > 1 ? "s" : ""}`
                        : "no provider configured"}
                  </span>
                  {option.localOnly && (
                    <span
                      className="text-[11px] text-warn-ink"
                      title="No Docker image in this runtime's spec — tasks execute directly on this machine."
                    >
                      local execution
                    </span>
                  )}
                  {option.cliMissing && (
                    <span className="text-[11px] text-warn-ink">CLI missing</span>
                  )}
                  <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-primary">
                    <Plus className="size-3" /> Add
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
              perFields={perFields}
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
  perFields,
  backend,
  onUpdate,
  onRemove,
}: {
  index: number
  draft: ContenderDraft
  providers: AiProvider[]
  custom?: CustomRuntime
  dockerCapable: boolean
  perFields: string[]
  backend: string
  onUpdate: (patch: Partial<ContenderDraft>) => void
  onRemove: () => void
}) {
  const provider = providers.find((item) => item.id === draft.provider_id)
  const dockerDowngraded = backend === "docker" && !dockerCapable
  const ownLogin = custom ? (custom.protocol ?? "none") === "none" : false
  const hasCompatibleProvider =
    compatibleProviders(draft.runtime, providers, custom?.protocol).length > 0
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
          {custom && (
            <Badge variant="outline" className="font-mono text-[11px] text-muted-foreground">
              custom:{custom.spec_id}
            </Badge>
          )}
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
              agent={draft.runtime}
              protocol={custom?.protocol}
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
        {perFields.includes("thinking_effort") && draft.runtime === "claude" && (
          <div className="flex items-center gap-2">
            <Label className="text-xs text-muted-foreground">Thinking effort</Label>
            <RadioGroup
              value={draft.thinking_effort}
              onValueChange={(value) => onUpdate({ thinking_effort: value })}
              className="flex flex-wrap gap-1.5"
            >
              {["none", "low", "medium", "high"].map((effort) => (
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
          </div>
        )}
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
  shared,
  setShared,
  setSharedField,
  perFields,
  setPerFields,
  judgeConflicts,
  customRuntimes,
  customByRuntime,
  runtimeLabel,
  localRuntimeNames,
}: {
  profiles: Profile[]
  persisted: boolean
  defaultProfileId: string | null
  profileId: string | null
  onSelectProfile: (id: string) => void
  providers: AiProvider[]
  shared: Partial<SharedConfig>
  setShared: React.Dispatch<React.SetStateAction<Partial<SharedConfig>>>
  setSharedField: (key: keyof SharedConfig, value: unknown) => void
  perFields: string[]
  setPerFields: (fields: string[]) => void
  judgeConflicts: number
  customRuntimes: CustomRuntime[]
  customByRuntime: Record<string, CustomRuntime>
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
                  agent={judgeRuntime}
                  protocol={judgeCustom?.protocol}
                  filter={
                    judgeRuntime === "codex"
                      ? (provider) => provider.kind === "openai"
                      : undefined
                  }
                  providerId={judgeProvider?.id}
                  model={String(shared.evaluator_model ?? "")}
                  onChange={({ provider, model }) => {
                    const settings = providerSettings(judgeRuntime, provider, judgeCustom)
                    setShared((current) => ({
                      ...current,
                      evaluator_agent: judgeRuntime,
                      evaluator_provider_id: provider.id,
                      evaluator_model: model,
                      evaluator_auth_mode: settings.auth_mode,
                      evaluator_gateway:
                        judgeRuntime === "opencode"
                          ? {
                              opencode_provider: String(
                                settings.gateway.opencode_provider ?? "",
                              ),
                              opencode_base_url: settings.gateway.opencode_base_url,
                              opencode_api_key_env: settings.gateway.opencode_api_key_env,
                            }
                          : null,
                      judge_env: settings.env ?? null,
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

      <Card>
        <CardContent className="grid gap-4">
          <span className="text-sm font-semibold">Environment & determinism — shared</span>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
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
    </div>
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
}: {
  expName: string
  setExpName: (name: string) => void
  taskCount: number
  tasksDir: string
  contenders: ContenderDraft[]
  shared: Partial<SharedConfig>
  plan: { plans: ExperimentPlanItem[] | null; error: string | null }
  judgeConflicts: number
  runtimeLabel: (runtime: string) => string
}) {
  const repeat = Number(shared.repeat) || 1
  const executions = taskCount * repeat * contenders.length
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
              {taskCount} × {contenders.length}
            </span>
            <span className="text-xs text-muted-foreground">
              tasks × agents{repeat > 1 ? ` × ${repeat} repeats` : ""} = {executions}{" "}
              executions + judging
            </span>
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

      {judgeConflicts > 0 && (
        <Alert className="border-warn-ink/40 bg-warn-soft/60">
          <AlertTriangle className="size-4" />
          <AlertTitle>Self-grading configuration</AlertTitle>
          <AlertDescription>
            The judge and an agent under test share the same model. Scores may be biased.
          </AlertDescription>
        </Alert>
      )}

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

function shortenPath(path: string): string {
  const parts = path.split("/")
  return parts.length > 3 ? `…/${parts.slice(-3).join("/")}` : path
}
