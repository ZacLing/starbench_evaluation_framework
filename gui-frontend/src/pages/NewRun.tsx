import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
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
import { AGENT_TO_FAMILY, FamilyIcon, ProviderIcon } from "@/components/brand"
import { ProviderModelPicker } from "@/components/model-picker"
import { ErrorNote } from "@/pages/Dashboard"
import {
  api,
  type AiProvider,
  type Contender,
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

const STEPS = ["Tasks", "Contenders", "Shared config", "Review & launch"]

interface ContenderDraft {
  key: string
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

/* Front-end mirror of providers.contender_settings: a provider reference
   fully determines runtime, auth mode, gateway flags, and env overrides. */
function providerSettings(provider: AiProvider) {
  const authMode = provider.auth === "cli_login" ? "global" : "env"
  if (provider.kind === "openai-compatible") {
    return {
      auth_mode: authMode,
      gateway: {
        opencode_provider: provider.id,
        opencode_base_url: provider.base_url || undefined,
        opencode_api_key_env: provider.api_key_env || undefined,
      },
      env: undefined,
    }
  }
  if (provider.kind === "anthropic" && provider.base_url) {
    return {
      auth_mode: authMode,
      gateway: {},
      env: {
        ANTHROPIC_BASE_URL: { value: provider.base_url },
        ANTHROPIC_AUTH_TOKEN: { from_env: provider.api_key_env || "ANTHROPIC_AUTH_TOKEN" },
      },
    }
  }
  return { auth_mode: authMode, gateway: {}, env: undefined }
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
  const libraries = useMemo(
    () => (tasklib.data?.libraries ?? []).filter((library) => library.exists),
    [tasklib.data],
  )
  const providers = providersQuery.data?.providers ?? []

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

  const addContender = (provider: AiProvider) => {
    contenderCounter += 1
    setContenders((current) => [
      ...current,
      {
        key: `c${contenderCounter}`,
        provider_id: provider.id,
        model: provider.models[0] ?? "",
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
      const provider = providers.find((item) => item.id === draft.provider_id)
      if (!provider) return []
      const settings = providerSettings(provider)
      return [
        {
          label: `${provider.name} ${draft.model || "default"}`.trim(),
          agent: provider.agent,
          model: draft.model.trim(),
          auth_mode: settings.auth_mode,
          thinking_effort: perFields.includes("thinking_effort") ? draft.thinking_effort : "none",
          ...settings.gateway,
          env: settings.env,
        },
      ]
    })
  }, [contenders, providers, perFields])

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

  if (tasklib.isPending || profilesQuery.isPending || providersQuery.isPending) {
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
          One task set, one judge, many contender models: comparable by construction.
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
          hasNonCodex={contenders.some((draft) => {
            const provider = providers.find((item) => item.id === draft.provider_id)
            return provider ? provider.agent !== "codex" : false
          })}
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

function StepContenders({
  providers,
  contenders,
  perFields,
  backend,
  onAdd,
  onUpdate,
  onRemove,
}: {
  providers: AiProvider[]
  contenders: ContenderDraft[]
  perFields: string[]
  backend: string
  onAdd: (provider: AiProvider) => void
  onUpdate: (key: string, patch: Partial<ContenderDraft>) => void
  onRemove: (key: string) => void
}) {
  return (
    <div className="grid gap-4">
      <Card>
        <CardContent className="grid gap-3">
          <div>
            <Label>Add contenders from your AI providers</Label>
            <p className="text-xs text-muted-foreground">
              Endpoint, credentials, and model catalog come from the provider; every contender
              runs the same tasks under the same judge.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {providers.map((provider) => (
              <button
                key={provider.id}
                type="button"
                onClick={() => onAdd(provider)}
                className="grid justify-items-center gap-1.5 rounded-md border p-3 text-center transition-colors hover:border-primary/50 hover:bg-accent/40"
              >
                <ProviderIcon provider={provider} size={24} />
                <span className="text-sm font-medium">{provider.name}</span>
                <span className="text-[11px] leading-tight text-muted-foreground">
                  {provider.models.length
                    ? `${provider.models.length} models`
                    : "no catalog yet"}
                  {provider.auth === "cli_login"
                    ? " · CLI login"
                    : provider.key_present
                      ? ""
                      : " · key missing"}
                </span>
                <span className="mt-0.5 inline-flex items-center gap-1 text-xs text-primary">
                  <Plus className="size-3" /> Add
                </span>
              </button>
            ))}
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
              perFields={perFields}
              backend={backend}
              onUpdate={(patch) => onUpdate(draft.key, patch)}
              onRemove={() => onRemove(draft.key)}
            />
          ))}
        </div>
      ) : (
        <p className="text-center text-sm text-muted-foreground">
          No contenders yet. Add at least one above.
        </p>
      )}
    </div>
  )
}

function ContenderCard({
  index,
  draft,
  providers,
  perFields,
  backend,
  onUpdate,
  onRemove,
}: {
  index: number
  draft: ContenderDraft
  providers: AiProvider[]
  perFields: string[]
  backend: string
  onUpdate: (patch: Partial<ContenderDraft>) => void
  onRemove: () => void
}) {
  const provider = providers.find((item) => item.id === draft.provider_id)
  const dockerDowngraded = backend === "docker" && provider?.agent !== "codex"
  return (
    <Card className="py-4">
      <CardContent className="grid gap-3 px-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">#{index + 1}</span>
          <ProviderModelPicker
            providerId={draft.provider_id}
            model={draft.model}
            onChange={({ provider: next, model }) =>
              onUpdate({ provider_id: next.id, model })
            }
          />
          {provider && (
            <Badge variant="outline" className="font-mono text-[11px] text-muted-foreground">
              {provider.agent}
            </Badge>
          )}
          {provider?.auth === "cli_login" && (
            <Badge variant="outline" className="text-[11px] text-muted-foreground">
              CLI login
            </Badge>
          )}
          {dockerDowngraded && (
            <Badge className="border-transparent bg-warn-soft text-[11px] text-warn-ink">
              runs locally — Docker is Codex-only
            </Badge>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="ml-auto size-7 text-muted-foreground hover:text-fail-ink"
            aria-label={`Remove contender ${index + 1}`}
            onClick={onRemove}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
        {perFields.includes("thinking_effort") && provider?.agent === "claude" && (
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
  hasNonCodex,
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
  hasNonCodex: boolean
}) {
  const queryClient = useQueryClient()
  const [saving, setSaving] = useState(false)
  const judgeProvider = providers.find(
    (item) => item.id === String(shared.evaluator_provider_id ?? ""),
  )

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
            <span className="text-sm font-semibold">Judge — shared across all contenders</span>
          </div>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label>Judge model (from a provider)</Label>
              <ProviderModelPicker
                providerId={judgeProvider?.id}
                model={String(shared.evaluator_model ?? "")}
                onChange={({ provider, model }) =>
                  setShared((current) => ({
                    ...current,
                    evaluator_provider_id: provider.id,
                    evaluator_agent: provider.agent,
                    evaluator_model: model,
                    evaluator_auth_mode: provider.auth === "cli_login" ? "global" : "env",
                    evaluator_gateway:
                      provider.kind === "openai-compatible"
                        ? {
                            opencode_provider: provider.id,
                            opencode_base_url: provider.base_url || undefined,
                            opencode_api_key_env: provider.api_key_env || undefined,
                          }
                        : null,
                  }))
                }
              />
              {judgeProvider && (
                <p className="text-xs text-muted-foreground">
                  Runtime <code className="font-mono">{judgeProvider.agent}</code> · credentials
                  from the {judgeProvider.name} provider
                </p>
              )}
            </div>
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
              <AlertTitle>Judge equals a contender</AlertTitle>
              <AlertDescription>
                {judgeConflicts} contender{judgeConflicts > 1 ? "s use" : " uses"} the same model
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
            {String(shared.executor_backend) === "docker" && (
              <div className="grid gap-1.5">
                <Label>Docker image</Label>
                <Input
                  className="font-mono"
                  value={String(shared.docker_image ?? "")}
                  onChange={(event) => setSharedField("docker_image", event.target.value)}
                />
              </div>
            )}
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
          {String(shared.executor_backend) === "docker" && hasNonCodex && (
            <Alert className="border-warn-ink/40 bg-warn-soft/60">
              <AlertTriangle className="size-4" />
              <AlertTitle>Docker applies to Codex contenders only</AlertTitle>
              <AlertDescription>
                The CLI currently supports Docker isolation for the Codex runtime; other
                contenders will run on this machine and are labeled accordingly.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      <Card className="py-4">
        <CardContent className="grid gap-2 px-4">
          <span className="text-sm font-semibold">Per-contender fields</span>
          <p className="text-xs text-muted-foreground">
            Which run-time knobs each contender sets individually. Endpoints and credentials
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
}: {
  expName: string
  setExpName: (name: string) => void
  taskCount: number
  tasksDir: string
  contenders: ContenderDraft[]
  shared: Partial<SharedConfig>
  plan: { plans: ExperimentPlanItem[] | null; error: string | null }
  judgeConflicts: number
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
              tasks × contenders{repeat > 1 ? ` × ${repeat} repeats` : ""} = {executions}{" "}
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
          hint={`${String(shared.evaluator_agent ?? "codex")} · ${String(shared.judge_mode ?? "single")} judge`}
          warn={judgeConflicts > 0 ? "same model as a contender" : undefined}
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
            The judge and a contender share the same model. Scores may be biased.
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
                  <FamilyIcon
                    family={AGENT_TO_FAMILY[item.agent] ?? "compat"}
                    model={item.model}
                    size={18}
                  />
                  <span className="text-sm font-medium">{item.label}</span>
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
