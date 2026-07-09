import { useMemo, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  AlertTriangle,
  Columns3,
  Copy,
  Library,
  ListChecks,
  Pencil,
  Plus,
  Repeat,
  Ruler,
  Scale,
  SlidersHorizontal,
  Star,
  Trash2,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import {
  AgentIcon,
  compatibleProviders,
  ProviderIcon,
  runtimeFilters,
} from "@/components/brand"
import { Hint } from "@/components/hint"
import { ProviderModelPicker } from "@/components/model-picker"
import { ErrorNote } from "@/pages/Dashboard"
import {
  api,
  type AgentsPayload,
  type AiProvider,
  type Meta,
  type ProfilesPayload,
  type SharedConfig,
  type TaskLibrary,
} from "@/lib/api"
import { shortDir } from "@/lib/format"
import { cn } from "@/lib/utils"

/* ---------- profile shape ----------
   The generated `Profile` in api.ts only types the fields the New-experiment
   wizard reads (id/name/shared/per_contender_fields). A profile on disk can
   also carry a server-assigned `rev` and the two blocks that make it a full,
   launchable measurement contract: `roster` (the executor agent columns) and
   `task_set`. We type them here and read the payload structurally rather than
   editing the generated contract. */
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

interface FullProfilesPayload {
  default_profile_id: string | null
  profiles: FullProfile[]
  persisted?: boolean
}

/* Editor state: a profile plus the two flags that decide whether the optional
   `roster`/`task_set` keys are written at all, so a profile that never declared
   them is not given empty ones by accident. */
interface Draft extends FullProfile {
  hasRoster: boolean
  hasTaskSet: boolean
}

const PER_CONTENDER_FIELDS: { id: string; label: string; hint: string }[] = [
  { id: "model", label: "Model", hint: "each agent picks its own model id" },
  { id: "credentials", label: "Credentials", hint: "each agent wires its own key" },
  { id: "gateway", label: "Gateway", hint: "per-agent endpoint override" },
  { id: "thinking_effort", label: "Reasoning", hint: "per-agent reasoning level" },
]

const NUMERIC_SHARED: (keyof SharedConfig)[] = [
  "seed",
  "batch_size",
  "repeat",
  "evaluator_timeout_seconds",
  "max_evaluator_parallel",
  "claude_max_turns",
]

/* Runtimes that can be judge or executor: built-ins plus custom specs that
   loaded cleanly. Errored custom specs are dropped, not shown as choices. */
interface RuntimeRef {
  id: string
  label: string
  icon?: string | null
  thinking_channel?: "native_config" | "prompt"
  thinking_efforts?: string[]
}

function runtimeRefs(agents?: AgentsPayload): RuntimeRef[] {
  return [
    ...(agents?.builtin ?? []).map((r) => ({
      id: r.id,
      label: r.label,
      thinking_channel: r.thinking_channel,
      thinking_efforts: r.thinking_efforts,
    })),
    ...(agents?.custom ?? [])
      .filter((r) => !r.error)
      .map((r) => ({
        id: r.id,
        label: r.label ?? r.spec_id,
        icon: r.icon,
        thinking_channel: r.thinking_channel,
        thinking_efforts: r.thinking_efforts,
      })),
  ]
}

/* Self-describing enum options: the raw value stays the visible word (it is
   what run configs and snapshots record), the plain-language meaning rides
   next to it in the dropdown. Vocabulary matches the wizard and the run
   detail card; unknown values fall back to the bare word. */
const JUDGE_MODE_GLOSS: Record<string, string> = {
  single: "one judge sees all rubrics per task",
  parallel: "one judge per rubric, independently",
  both: "runs both modes",
}

const AUTH_MODE_GLOSS: Record<string, string> = {
  global: "the host CLI's own login",
  env: "API key from environment variables",
  "copy-auth": "copied CLI login",
}

const BACKEND_GLOSS: Record<string, string> = {
  local: "runs directly on this machine",
  docker: "each task isolated in its own container",
}

const RUNTIME_DEFAULT = "__runtime_default__"
const THINKING_DEFAULT = "none"

function GlossSelectItem({ value, gloss }: { value: string; gloss?: string }) {
  return (
    <SelectItem value={value}>
      <span className="flex flex-col items-start gap-0.5">
        <span>{value}</span>
        {gloss && <span className="text-xs text-muted-foreground">{gloss}</span>}
      </span>
    </SelectItem>
  )
}

function runtimeLabelOf(refs: RuntimeRef[], id: string | undefined): string {
  if (!id) return "–"
  return refs.find((r) => r.id === id)?.label ?? id
}

function thinkingEffortsOf(refs: RuntimeRef[], id: string | undefined): string[] {
  return refs.find((r) => r.id === id)?.thinking_efforts ?? ["none", "low", "medium", "high"]
}

function ProfileSummaryStrip({ value }: { value: Draft }) {
  const rosterCount = value.roster?.length ?? 0
  const taskText = value.hasTaskSet
    ? `${value.task_set?.task_ids?.length || "all"} tasks`
    : "tasks chosen at launch"
  const judge = String(value.shared.evaluator_agent ?? "?")
  const judgeModel = value.shared.evaluator_model
    ? ` · ${value.shared.evaluator_model}`
    : ""

  return (
    <div className="border-b bg-muted/40 px-4 py-3 sm:px-5">
      <div className="flex flex-wrap items-center gap-2">
        <SummaryPill
          label="Executors"
          value={`${rosterCount} agent${rosterCount === 1 ? "" : "s"}`}
        />
        <SummaryPill label="Tasks" value={taskText} />
        <SummaryPill label="Judge" value={`${judge}${judgeModel}`} mono />
        <SummaryPill label="Repeat" value={`×${numValue(value.shared.repeat) || "1"}`} mono />
        <SummaryPill label="Seed" value={String(numValue(value.shared.seed) || "–")} mono />
      </div>
    </div>
  )
}

function SummaryPill({
  label,
  value,
  mono,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-xs">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className={cn("min-w-0 truncate font-medium text-foreground", mono && "font-mono")}>
        {value}
      </span>
    </span>
  )
}

/* Resolve a profile's tasks_dir (often a repo-relative string like
   "examples/tasks") to a known library, without rewriting the stored value:
   exact match first, then a path suffix, then the trailing folder name. */
function resolveLibrary(
  tasksDir: string,
  libraries: TaskLibrary[],
): TaskLibrary | undefined {
  if (!tasksDir) return undefined
  return (
    libraries.find((l) => l.dir === tasksDir) ??
    libraries.find((l) => l.dir.endsWith("/" + tasksDir)) ??
    libraries.find((l) => l.dir.split("/").pop() === tasksDir.split("/").pop())
  )
}

function toDraft(profile: FullProfile): Draft {
  return {
    id: profile.id,
    name: profile.name,
    rev: profile.rev,
    shared: { ...profile.shared },
    per_contender_fields: [...(profile.per_contender_fields ?? [])],
    roster: (profile.roster ?? []).map((e) => ({ ...e })),
    task_set: profile.task_set
      ? { tasks_dir: profile.task_set.tasks_dir, task_ids: [...profile.task_set.task_ids] }
      : undefined,
    hasRoster: profile.roster !== undefined,
    hasTaskSet: profile.task_set !== undefined,
  }
}

function newDraft(): Draft {
  return {
    id: "",
    name: "",
    shared: {
      evaluator_agent: "codex",
      evaluator_model: "",
      evaluator_auth_mode: "env",
      judge_mode: "single",
      evaluator_timeout_seconds: 900,
      executor_backend: "local",
      executor_auth_mode: "env",
      seed: 123,
      batch_size: 1,
      repeat: 1,
    },
    per_contender_fields: ["model", "credentials", "gateway"],
    roster: [],
    hasRoster: true,
    hasTaskSet: false,
  }
}

/* A draft minus the editor-only flags, with the optional blocks written only
   when declared and numeric fields coerced so an unchanged save round-trips to
   the same content (the server bumps `rev` on any content change). */
function fromDraft(draft: Draft): FullProfile {
  const shared: Record<string, unknown> = { ...draft.shared }
  for (const key of NUMERIC_SHARED) {
    const value = shared[key]
    if (value !== undefined && value !== null && value !== "") {
      const n = Math.trunc(Number(value))
      if (Number.isFinite(n)) shared[key] = n
    }
  }
  const roster = (draft.roster ?? []).map((entry) => {
    const out: RosterEntry = { agent: entry.agent }
    if (entry.model) out.model = entry.model
    if (entry.provider_id) out.provider_id = entry.provider_id
    if (entry.label) out.label = entry.label
    if (entry.thinking_effort && entry.thinking_effort !== THINKING_DEFAULT)
      out.thinking_effort = entry.thinking_effort
    return out
  })
  const profile: FullProfile = {
    id: draft.id.trim(),
    name: draft.name.trim(),
    shared: shared as Partial<SharedConfig>,
    per_contender_fields: draft.per_contender_fields,
  }
  if (draft.hasRoster || roster.length > 0) profile.roster = roster
  if (draft.hasTaskSet && draft.task_set?.tasks_dir) {
    profile.task_set = { tasks_dir: draft.task_set.tasks_dir, task_ids: draft.task_set.task_ids }
  }
  return profile
}

export default function Profiles() {
  const queryClient = useQueryClient()
  const profilesQuery = useQuery({
    queryKey: ["profiles"],
    queryFn: async () => (await api.profiles()) as unknown as FullProfilesPayload,
  })
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const tasklibQuery = useQuery({ queryKey: ["tasklib"], queryFn: api.tasklib })
  const metaQuery = useQuery({ queryKey: ["meta"], queryFn: api.meta })

  const [editing, setEditing] = useState<Draft | null>(null)
  const [isNew, setIsNew] = useState(false)
  /* The id of the profile a non-new edit replaces (its id field is locked, so
     this equals editing.id, but keeping it explicit guards a rename). */
  const [editingOriginalId, setEditingOriginalId] = useState<string | null>(null)

  const refs = useMemo(() => runtimeRefs(agentsQuery.data), [agentsQuery.data])
  const filters = useMemo(() => runtimeFilters(agentsQuery.data), [agentsQuery.data])

  if (profilesQuery.isPending) return <Skeleton className="h-96" />
  if (profilesQuery.isError)
    return <ErrorNote message={(profilesQuery.error as Error).message} />

  const payload = profilesQuery.data
  const profiles = payload.profiles
  const persisted = Boolean(payload.persisted)
  const providers = providersQuery.data?.providers ?? []
  const libraries = (tasklibQuery.data?.libraries ?? []).filter((l) => l.exists)
  const meta = metaQuery.data
  /* The wizard uses default_profile_id, falling back to the first profile when
     none is set. We render the same effective default rather than invent one. */
  const effectiveDefaultId = payload.default_profile_id ?? profiles[0]?.id ?? null
  const explicitDefault = payload.default_profile_id !== null

  const profilesJsonPath = meta ? `${meta.runs_dir}/profiles.json` : null

  const persistAll = async (next: FullProfile[], defaultId: string | null, message: string) => {
    await api.saveProfiles({
      default_profile_id: defaultId,
      profiles: next,
    } as unknown as ProfilesPayload)
    await queryClient.invalidateQueries({ queryKey: ["profiles"] })
    toast.success(message)
  }

  const openEdit = (profile: FullProfile) => {
    setIsNew(false)
    setEditingOriginalId(profile.id)
    setEditing(toDraft(profile))
  }

  const openNew = () => {
    setIsNew(true)
    setEditingOriginalId(null)
    setEditing(newDraft())
  }

  const openDuplicate = (profile: FullProfile) => {
    let id = `${profile.id}-copy`
    let n = 2
    while (profiles.some((p) => p.id === id)) id = `${profile.id}-copy-${n++}`
    setIsNew(true)
    setEditingOriginalId(null)
    setEditing({ ...toDraft(profile), id, name: `${profile.name} (copy)`, rev: undefined })
  }

  const makeDefault = async (profile: FullProfile) => {
    try {
      await persistAll(
        profiles,
        profile.id,
        `"${profile.name || profile.id}" is now the default for new experiments.`,
      )
    } catch (error) {
      toast.error((error as Error).message)
    }
  }

  const removeProfile = async (profile: FullProfile) => {
    const next = profiles.filter((p) => p.id !== profile.id)
    const nextDefault =
      payload.default_profile_id === profile.id ? null : payload.default_profile_id
    try {
      await persistAll(next, nextDefault, `Profile "${profile.name || profile.id}" removed.`)
    } catch (error) {
      toast.error((error as Error).message)
    }
  }

  /* Save from the editor. Client guards throw so the Sheet shows them inline,
     the same channel as the server's own validation (fail closed). */
  const saveDraft = async (draft: Draft) => {
    const id = draft.id.trim()
    if (!id) throw new Error("Give the profile an id.")
    if (!/^[A-Za-z0-9._-]+$/.test(id))
      throw new Error("Profile id may use letters, digits, dot, underscore and hyphen only.")
    if (!draft.name.trim()) throw new Error("Give the profile a name.")
    if (isNew && profiles.some((p) => p.id === id))
      throw new Error(`A profile with id "${id}" already exists.`)

    const built = fromDraft({ ...draft, id })
    const next = isNew
      ? [...profiles, built]
      : profiles.map((p) => (p.id === editingOriginalId ? built : p))
    await persistAll(next, payload.default_profile_id, `Profile "${built.name}" saved.`)
    setEditing(null)
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1 basis-72">
          <h1 className="text-xl font-semibold tracking-tight">Profiles</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            A profile is a measurement contract: the executor agents it runs, the judge and
            settings it measures with, and the tasks it runs. Every run launched from a
            profile carries a frozen snapshot of the contract as it stood at launch.
          </p>
        </div>
        <Button className="ml-auto" onClick={openNew}>
          <Plus /> New profile
        </Button>
      </div>

      {!persisted && (
        <Card className="border-live-ink/30 bg-live-soft/40 py-3">
          <CardContent className="flex items-start gap-2 px-4">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-live-ink" />
            <p className="text-xs text-live-ink">
              These are the built-in templates. Nothing is on disk yet, so
              <code className="mx-1 font-mono">profiles.json</code>
              is created the first time you save one.
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3">
        {profiles.map((profile) => (
          <ProfileCard
            key={profile.id}
            profile={profile}
            refs={refs}
            isDefault={profile.id === effectiveDefaultId}
            explicitDefault={explicitDefault}
            canDelete={persisted && profiles.length > 1}
            libraries={libraries}
            onEdit={() => openEdit(profile)}
            onDuplicate={() => openDuplicate(profile)}
            onMakeDefault={profile.id === effectiveDefaultId ? undefined : () => makeDefault(profile)}
            onDelete={() => removeProfile(profile)}
          />
        ))}
      </div>

      {profilesJsonPath && (
        <p className="truncate font-mono text-[11px] text-muted-foreground" title={profilesJsonPath}>
          Contracts · {shortDir(profilesJsonPath)}
        </p>
      )}

      <ProfileEditor
        key={editing ? (isNew ? "__new" : editingOriginalId) : "__closed"}
        draft={editing}
        isNew={isNew}
        refs={refs}
        providers={providers}
        filters={filters}
        libraries={libraries}
        meta={meta}
        canDelete={!isNew && persisted && profiles.length > 1}
        onClose={() => setEditing(null)}
        onSave={saveDraft}
        onDelete={
          isNew || !editing
            ? undefined
            : () => {
                const target = profiles.find((p) => p.id === editingOriginalId)
                if (target) removeProfile(target)
                setEditing(null)
              }
        }
      />
    </div>
  )
}

/* ---------- list row ---------- */

function ProfileCard({
  profile,
  refs,
  isDefault,
  explicitDefault,
  canDelete,
  libraries,
  onEdit,
  onDuplicate,
  onMakeDefault,
  onDelete,
}: {
  profile: FullProfile
  refs: RuntimeRef[]
  isDefault: boolean
  explicitDefault: boolean
  canDelete: boolean
  libraries: TaskLibrary[]
  onEdit: () => void
  onDuplicate: () => void
  onMakeDefault?: () => void
  onDelete: () => void
}) {
  const shared = profile.shared
  const roster = profile.roster ?? []
  const repeat = shared.repeat ?? 1
  const taskSet = profile.task_set
  const lib = taskSet ? resolveLibrary(taskSet.tasks_dir, libraries) : undefined
  const taskCount = taskSet
    ? taskSet.task_ids.length > 0
      ? `${taskSet.task_ids.length} task${taskSet.task_ids.length === 1 ? "" : "s"}`
      : lib
        ? `all ${lib.tasks.length} tasks`
        : "all tasks"
    : null

  return (
    <Card className="py-0">
      <CardContent className="grid gap-4 p-4">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
          <span className="text-base font-semibold tracking-tight">{profile.name}</span>
          <span className="font-mono text-xs text-muted-foreground">{profile.id}</span>
          {profile.rev !== undefined && (
            <span
              className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
              title="Server-assigned revision. It bumps when the contract's content changes; run snapshots cite it."
            >
              rev {profile.rev}
            </span>
          )}
          {isDefault && (
            <Badge
              className="gap-1 border-transparent bg-accent text-accent-foreground"
              title={
                explicitDefault
                  ? "Pre-fills the New experiment wizard."
                  : "First profile; pre-fills New experiment until you set a default."
              }
            >
              <Star className="size-3" fill="currentColor" /> Default
            </Badge>
          )}
          <div className="ml-auto flex items-center gap-1">
            {onMakeDefault && (
              <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={onMakeDefault}>
                <Star /> Make default
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onDuplicate}>
              <Copy /> Duplicate
            </Button>
            <Button variant="outline" size="sm" onClick={onEdit}>
              <Pencil /> Edit
            </Button>
          </div>
        </div>

        <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
          <ContractCell icon={Columns3} label="Executors">
            {roster.length === 0 ? (
              <span className="text-muted-foreground">No agents yet</span>
            ) : (
              <div className="flex flex-col gap-1">
                <span className="text-sm">
                  {roster.length} agent{roster.length === 1 ? "" : "s"}
                </span>
                <div className="flex flex-wrap gap-1">
                  {roster.map((entry, index) => (
                    <span
                      key={index}
                      className="inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5"
                      title={`${runtimeLabelOf(refs, entry.agent)}${entry.model ? ` · ${entry.model}` : ""}`}
                    >
                      <AgentIcon agent={entry.agent} size={13} />
                      <span className="font-mono text-[11px]">{entry.model ?? entry.agent}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </ContractCell>

          <ContractCell icon={Scale} label="Instrument">
            <div className="flex items-center gap-1.5">
              <AgentIcon agent={String(shared.evaluator_agent ?? "")} size={15} />
              <span className="truncate">
                {runtimeLabelOf(refs, shared.evaluator_agent)}
                {shared.evaluator_model ? (
                  <span className="font-mono text-muted-foreground"> · {shared.evaluator_model}</span>
                ) : null}
              </span>
            </div>
            <span className="text-xs text-muted-foreground">
              {shared.judge_mode ?? "single"} judge
            </span>
          </ContractCell>

          <ContractCell icon={SlidersHorizontal} label="Execution">
            <div className="flex items-center gap-1.5">
              <span
                className="inline-flex items-center gap-0.5 rounded bg-accent px-1.5 py-0.5 font-mono text-accent-foreground"
                title="Repeats per cell. A single execution is a sample, not a score."
              >
                <Repeat className="size-3" /> ×{repeat}
              </span>
            </div>
            <span className="font-mono text-xs text-muted-foreground">
              seed {shared.seed ?? "–"} · batch {shared.batch_size ?? "–"} · {shared.executor_backend ?? "local"}
            </span>
          </ContractCell>

          <ContractCell icon={Library} label="Task set">
            {taskSet ? (
              <>
                <span className="truncate font-mono text-[13px]" title={taskSet.tasks_dir}>
                  {shortDir(taskSet.tasks_dir)}
                </span>
                <span className="text-xs text-muted-foreground">{taskCount}</span>
              </>
            ) : (
              <span className="text-muted-foreground">Chosen at launch</span>
            )}
          </ContractCell>
        </div>

        {(profile.per_contender_fields.length > 0 || canDelete) && (
          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            {profile.per_contender_fields.length > 0 && (
              <>
                <span className="text-[11px] text-muted-foreground">Per agent:</span>
                {profile.per_contender_fields.map((field) => (
                  <Badge key={field} variant="outline" className="text-[11px] text-muted-foreground">
                    {PER_CONTENDER_FIELDS.find((f) => f.id === field)?.label ?? field}
                  </Badge>
                ))}
              </>
            )}
            {canDelete && (
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto text-muted-foreground hover:text-fail-ink"
                onClick={onDelete}
              >
                <Trash2 /> Delete
              </Button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ContractCell({
  icon: Icon,
  label,
  children,
}: {
  icon: typeof Columns3
  label: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-1.5">
      <span className="flex items-center gap-1.5 text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        <Icon className="size-3.5" /> {label}
      </span>
      <div className="grid gap-0.5 text-sm">{children}</div>
    </div>
  )
}

/* ---------- editor ---------- */

function ProfileEditor({
  draft,
  isNew,
  refs,
  providers,
  filters,
  libraries,
  meta,
  canDelete,
  onClose,
  onSave,
  onDelete,
}: {
  draft: Draft | null
  isNew: boolean
  refs: RuntimeRef[]
  providers: AiProvider[]
  filters: Record<string, { kinds: string[]; accepts_anthropic_endpoint: boolean; accepts_gemini_endpoint: boolean }>
  libraries: TaskLibrary[]
  meta?: Meta
  canDelete: boolean
  onClose: () => void
  onSave: (draft: Draft) => Promise<void>
  onDelete?: () => void
}) {
  const [form, setForm] = useState<Draft | null>(draft)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const value = form ?? draft

  if (!value) {
    return (
      <Sheet open={false} onOpenChange={() => onClose()}>
        <SheetContent />
      </Sheet>
    )
  }

  const patch = (next: Partial<Draft>) => setForm({ ...value, ...next })
  const patchShared = (next: Partial<SharedConfig>) =>
    setForm({ ...value, shared: { ...value.shared, ...next } })

  const judgeModes = meta?.judge_modes ?? ["single", "parallel"]
  const authModes = meta?.auth_modes ?? ["env", "global"]
  const backends = meta?.backends ?? ["local", "docker"]

  const providersFor = (agent: string): AiProvider[] => {
    const filter = filters[agent]
    const compatible = compatibleProviders(filter, providers, agent)
    return compatible.length > 0 ? compatible : providers
  }
  const defaultThinkingEffort = (agent: string) => {
    const efforts = thinkingEffortsOf(refs, agent)
    return efforts.includes(THINKING_DEFAULT) ? THINKING_DEFAULT : efforts[0] ?? THINKING_DEFAULT
  }
  const normalizeThinkingEffort = (agent: string, effort?: string) => {
    const efforts = thinkingEffortsOf(refs, agent)
    return effort && efforts.includes(effort) ? effort : defaultThinkingEffort(agent)
  }

  const setRoster = (roster: RosterEntry[]) => patch({ roster, hasRoster: true })
  const updateRoster = (index: number, next: Partial<RosterEntry>) =>
    setRoster((value.roster ?? []).map((entry, i) => (i === index ? { ...entry, ...next } : entry)))
  const addContender = () => {
    const agent = refs[0]?.id ?? "claude"
    const provider = providersFor(agent)[0]?.id
    setRoster([
      ...(value.roster ?? []),
      {
        agent,
        model: "",
        provider_id: provider,
        thinking_effort: defaultThinkingEffort(agent),
      },
    ])
  }
  const removeContender = (index: number) =>
    setRoster((value.roster ?? []).filter((_, i) => i !== index))

  const taskSet = value.task_set
  const matchedLib = taskSet ? resolveLibrary(taskSet.tasks_dir, libraries) : undefined
  const libSelectValue = matchedLib ? matchedLib.dir : taskSet?.tasks_dir ? "__unmatched" : undefined

  const submit = async () => {
    setSaving(true)
    setError(null)
    try {
      await onSave(value)
    } catch (submitError) {
      setError((submitError as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet
      open={Boolean(draft)}
      onOpenChange={(open) => {
        if (!open) {
          setForm(null)
          setError(null)
          onClose()
        }
      }}
    >
      <SheetContent className="w-full gap-0 overflow-hidden p-0 sm:max-w-5xl">
        <SheetHeader className="border-b">
          <SheetTitle className="flex items-center gap-2">
            <Ruler className="size-4 text-primary" />
            {isNew ? "New profile" : `Edit ${draft?.name ?? ""}`}
          </SheetTitle>
          <SheetDescription>
            {isNew
              ? "Define the contract this profile measures. It is saved to profiles.json when you save."
              : "Edits apply to future runs only. Runs already launched keep their frozen snapshot."}
          </SheetDescription>
        </SheetHeader>

        <ProfileSummaryStrip value={value} />

        <div className="flex-1 overflow-y-auto">
          <div className="grid gap-6 p-4 sm:p-5">
          {/* identity */}
          <section className="grid gap-3">
            <div className="grid gap-1.5 sm:grid-cols-[1fr_auto] sm:items-end sm:gap-3">
              <div className="grid gap-1.5">
                <Label htmlFor="profile-name">Name</Label>
                <Input
                  id="profile-name"
                  value={value.name}
                  placeholder="Frontier sweep"
                  onChange={(event) => patch({ name: event.target.value })}
                />
              </div>
              {value.rev !== undefined && (
                <span
                  className="mb-1 self-center rounded bg-muted px-2 py-1 font-mono text-xs text-muted-foreground sm:mb-2"
                  title="Server-assigned. It bumps when the contract's content changes; you cannot edit it."
                >
                  rev {value.rev}
                </span>
              )}
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="profile-id">Id</Label>
              <Input
                id="profile-id"
                className="font-mono"
                value={value.id}
                disabled={!isNew}
                placeholder="frontier-sweep"
                onChange={(event) => patch({ id: event.target.value })}
              />
              {!isNew && (
                <p className="text-xs text-muted-foreground">
                  The id is fixed once created; run snapshots reference it.
                </p>
              )}
            </div>
          </section>

          {/* executors */}
          <section className="grid gap-3">
            <SectionHeading icon={Columns3} title="Executors">
              The agents this profile runs. Each row becomes one coverage column.
            </SectionHeading>
            {(value.roster ?? []).length === 0 ? (
              <p className="rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
                No agents yet. Add the agent × model cells you want to measure.
              </p>
            ) : (
              <div className="overflow-hidden rounded-lg border">
                <div className="hidden grid-cols-[2.25rem_minmax(9rem,0.8fr)_minmax(12rem,1fr)_minmax(13rem,1fr)_minmax(8rem,0.55fr)_2.5rem] gap-2 border-b bg-muted/50 px-3 py-2 text-[11px] font-medium text-muted-foreground lg:grid">
                  <span>#</span>
                  <span>Agent</span>
                  <span>Provider</span>
                  <span>Model</span>
                  <span>Reasoning</span>
                  <span className="sr-only">Actions</span>
                </div>
                <div className="divide-y">
                  {(value.roster ?? []).map((entry, index) => {
                    const rosterProviders = providersFor(entry.agent)
                    const provider = rosterProviders.find((item) => item.id === entry.provider_id)
                    const thinkingEfforts = thinkingEffortsOf(refs, entry.agent)
                    const thinkingValue = normalizeThinkingEffort(
                      entry.agent,
                      entry.thinking_effort,
                    )
                    return (
                      <div
                        key={index}
                        className="grid gap-3 px-3 py-3 lg:grid-cols-[2.25rem_minmax(9rem,0.8fr)_minmax(12rem,1fr)_minmax(13rem,1fr)_minmax(8rem,0.55fr)_2.5rem] lg:items-center lg:gap-2"
                      >
                        <div className="flex items-center justify-between lg:block">
                          <span className="font-mono text-xs text-muted-foreground">
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="text-muted-foreground hover:text-fail-ink lg:hidden"
                            aria-label={`Remove agent ${index + 1}`}
                            onClick={() => removeContender(index)}
                          >
                            <Trash2 />
                          </Button>
                        </div>

                        <Field label="Agent" className="gap-1 lg:[&>div:first-child]:sr-only">
                          <Select
                            value={entry.agent}
                            onValueChange={(agent) => {
                              const nextProvider = providersFor(agent)[0]
                              updateRoster(index, {
                                agent,
                                provider_id: nextProvider?.id,
                                model: nextProvider?.models[0] ?? "",
                                thinking_effort: normalizeThinkingEffort(
                                  agent,
                                  entry.thinking_effort,
                                ),
                              })
                            }}
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {refs.map((ref) => (
                                <SelectItem key={ref.id} value={ref.id}>
                                  <span className="flex items-center gap-2">
                                    <AgentIcon agent={ref.id} icon={ref.icon} size={15} /> {ref.label}
                                  </span>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </Field>

                        <Field label="Provider" className="gap-1 lg:[&>div:first-child]:sr-only">
                          <Select
                            value={entry.provider_id}
                            disabled={rosterProviders.length === 0}
                            onValueChange={(providerId) => {
                              const nextProvider = rosterProviders.find((item) => item.id === providerId)
                              if (nextProvider) {
                                updateRoster(index, {
                                  provider_id: nextProvider.id,
                                  model: nextProvider.models[0] ?? "",
                                })
                              }
                            }}
                          >
                            <SelectTrigger className="w-full">
                              <SelectValue placeholder="Provider…" />
                            </SelectTrigger>
                            <SelectContent>
                              {rosterProviders.map((item) => (
                                <SelectItem key={item.id} value={item.id}>
                                  <span className="flex items-center gap-2">
                                    <ProviderIcon provider={item} size={14} />
                                    <span className="min-w-0 truncate">{item.name}</span>
                                    {item.auth === "api_key" && !item.key_present && (
                                      <span className="text-xs text-warn-ink">· key missing</span>
                                    )}
                                  </span>
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </Field>

                        <Field label="Model" className="gap-1 lg:[&>div:first-child]:sr-only">
                          <Select
                            value={entry.model || RUNTIME_DEFAULT}
                            disabled={!provider && !entry.model}
                            onValueChange={(model) => {
                              updateRoster(index, {
                                model: model === RUNTIME_DEFAULT ? "" : model,
                              })
                            }}
                          >
                            <SelectTrigger className="w-full font-mono text-xs">
                              <SelectValue placeholder="Model…" />
                            </SelectTrigger>
                            <SelectContent>
                              {(provider?.models ?? []).map((model) => (
                                <SelectItem key={model} value={model} className="font-mono text-xs">
                                  {model}
                                </SelectItem>
                              ))}
                              {entry.model && (!provider || !provider.models.includes(entry.model)) && (
                                <SelectItem value={entry.model} className="font-mono text-xs">
                                  {entry.model}{" "}
                                  <span className="font-sans text-muted-foreground">
                                    {provider ? "· not in catalog" : "· stored value"}
                                  </span>
                                </SelectItem>
                              )}
                              <SelectItem value={RUNTIME_DEFAULT} className="text-xs text-muted-foreground">
                                (runtime default)
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </Field>

                        <Field label="Reasoning" className="gap-1 lg:[&>div:first-child]:sr-only">
                          <Select
                            value={thinkingValue}
                            onValueChange={(thinking_effort) => {
                              updateRoster(index, { thinking_effort })
                            }}
                          >
                            <SelectTrigger className="w-full font-mono text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {thinkingEfforts.map((effort) => (
                                <SelectItem key={effort} value={effort} className="font-mono text-xs">
                                  {effort}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </Field>

                        <Button
                          variant="ghost"
                          size="icon"
                          className="hidden text-muted-foreground hover:text-fail-ink lg:inline-flex"
                          aria-label={`Remove agent ${index + 1}`}
                          onClick={() => removeContender(index)}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
            <div>
              <Button variant="outline" size="sm" onClick={addContender}>
                <Plus /> Add agent
              </Button>
            </div>
          </section>

          {/* instrument */}
          <section className="grid gap-3">
            <SectionHeading icon={Scale} title="Instrument">
              The judge and how it scores, shared across every agent.
            </SectionHeading>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label="Evaluator runtime"
                gloss="the judge is an agent too"
                hint="Scores are only as trustworthy as the runtime grading them; pick the judge as deliberately as the executor agents."
              >
                <Select
                  value={String(value.shared.evaluator_agent ?? "")}
                  onValueChange={(evaluator_agent) => patchShared({ evaluator_agent })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {refs.map((ref) => (
                      <SelectItem key={ref.id} value={ref.id}>
                        <span className="flex items-center gap-2">
                          <AgentIcon agent={ref.id} icon={ref.icon} size={15} /> {ref.label}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Evaluator model" className="sm:col-span-2">
                <ProviderModelPicker
                  providerFilter={filters[String(value.shared.evaluator_agent ?? "")]}
                  runtimeId={String(value.shared.evaluator_agent ?? "")}
                  filter={
                    value.shared.evaluator_agent === "codex"
                      ? (provider) => provider.kind === "openai"
                      : undefined
                  }
                  providerId={
                    String(value.shared.evaluator_provider_id ?? "") ||
                    // Older profiles stored only the model id: infer the provider
                    // whose catalog carries it so the picker starts usable.
                    providersFor(String(value.shared.evaluator_agent ?? "")).find((provider) =>
                      provider.models.includes(String(value.shared.evaluator_model ?? "")),
                    )?.id
                  }
                  model={String(value.shared.evaluator_model ?? "")}
                  onChange={({ provider, model }) =>
                    patchShared({ evaluator_provider_id: provider.id, evaluator_model: model })
                  }
                />
              </Field>
              <Field label="Judge mode">
                <Select
                  value={String(value.shared.judge_mode ?? "single")}
                  onValueChange={(judge_mode) => patchShared({ judge_mode })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue>{String(value.shared.judge_mode ?? "single")}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {judgeModes.map((mode) => (
                      <GlossSelectItem key={mode} value={mode} gloss={JUDGE_MODE_GLOSS[mode]} />
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field
                label="Judge timeout (s)"
                gloss="per judge invocation"
                hint="A judge that exceeds it records no verdict for that task; the executor's work is kept."
              >
                <Input
                  type="number"
                  className="font-mono"
                  value={numValue(value.shared.evaluator_timeout_seconds)}
                  onChange={(event) => patchShared({ evaluator_timeout_seconds: event.target.value })}
                />
              </Field>
              <Field label="Evaluator credentials">
                <Select
                  value={String(value.shared.evaluator_auth_mode ?? "env")}
                  onValueChange={(evaluator_auth_mode) => patchShared({ evaluator_auth_mode })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue>{String(value.shared.evaluator_auth_mode ?? "env")}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {authModes.map((mode) => (
                      <GlossSelectItem key={mode} value={mode} gloss={AUTH_MODE_GLOSS[mode]} />
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
          </section>

          {/* execution */}
          <section className="grid gap-3">
            <SectionHeading icon={SlidersHorizontal} title="Execution">
              How each cell is run. Repeat is the measurement's backbone.
            </SectionHeading>
            <div className="rounded-lg border bg-accent/40 p-3">
              <Label htmlFor="profile-repeat" className="flex items-center gap-1.5">
                <Repeat className="size-3.5 text-accent-foreground" /> Repeats per cell
              </Label>
              <div className="mt-1.5 flex items-center gap-3">
                <Input
                  id="profile-repeat"
                  type="number"
                  min={1}
                  className="w-24 font-mono text-base"
                  value={numValue(value.shared.repeat)}
                  onChange={(event) => patchShared({ repeat: event.target.value })}
                />
                <p className="text-xs text-accent-foreground/90">
                  A single execution is a sample, not a score. Frontier sweeps repeat each cell
                  so pass rates mean something.
                </p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field
                label="Seed"
                gloss="schedules, not weights"
                hint="Fixes task shuffle, batch grouping, and judge launch order so a rerun schedules identically. It does not make model outputs deterministic."
              >
                <Input
                  type="number"
                  className="font-mono"
                  value={numValue(value.shared.seed)}
                  onChange={(event) => patchShared({ seed: event.target.value })}
                />
              </Field>
              <Field
                label="Batch size"
                gloss="tasks at once"
                hint="How many executor tasks run concurrently for each agent; 1 runs them one by one."
              >
                <Input
                  type="number"
                  min={1}
                  className="font-mono"
                  value={numValue(value.shared.batch_size)}
                  onChange={(event) => patchShared({ batch_size: event.target.value })}
                />
              </Field>
              <Field label="Executor backend">
                <Select
                  value={String(value.shared.executor_backend ?? "local")}
                  onValueChange={(executor_backend) => patchShared({ executor_backend })}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue>{String(value.shared.executor_backend ?? "local")}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {backends.map((backend) => (
                      <GlossSelectItem key={backend} value={backend} gloss={BACKEND_GLOSS[backend]} />
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            </div>
          </section>

          {/* task set */}
          <section className="grid gap-3">
            <SectionHeading icon={Library} title="Task set">
              The tasks this contract runs. Pin them here, or leave it open and choose at launch.
            </SectionHeading>
            <label className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={value.hasTaskSet}
                onCheckedChange={(checked) =>
                  patch({
                    hasTaskSet: Boolean(checked),
                    task_set: checked
                      ? value.task_set ?? { tasks_dir: libraries[0]?.dir ?? "", task_ids: [] }
                      : value.task_set,
                  })
                }
              />
              Pin a task set to this profile
            </label>
            {value.hasTaskSet && (
              <div className="grid gap-3">
                <Field label="Tasks directory">
                  <Select
                    value={libSelectValue}
                    onValueChange={(dir) => {
                      if (dir === "__unmatched") return
                      const lib = libraries.find((l) => l.dir === dir)
                      const validIds = new Set(lib?.tasks.map((t) => t.id) ?? [])
                      patch({
                        task_set: {
                          tasks_dir: dir,
                          task_ids: (value.task_set?.task_ids ?? []).filter((id) => validIds.has(id)),
                        },
                      })
                    }}
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Choose a task library" />
                    </SelectTrigger>
                    <SelectContent>
                      {taskSet && !matchedLib && taskSet.tasks_dir && (
                        <SelectItem value="__unmatched" disabled>
                          {taskSet.tasks_dir} · not in the task library
                        </SelectItem>
                      )}
                      {libraries.map((lib) => (
                        <SelectItem key={lib.dir} value={lib.dir}>
                          {shortDir(lib.dir)} · {lib.tasks.length} task{lib.tasks.length === 1 ? "" : "s"}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                {matchedLib ? (
                  <div className="grid gap-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">
                        {(taskSet?.task_ids.length ?? 0) === 0
                          ? "None selected runs every task in the directory."
                          : `${taskSet?.task_ids.length} of ${matchedLib.tasks.length} selected.`}
                      </span>
                      {(taskSet?.task_ids.length ?? 0) > 0 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-auto px-1 py-0 text-xs text-muted-foreground"
                          onClick={() =>
                            patch({ task_set: { tasks_dir: taskSet!.tasks_dir, task_ids: [] } })
                          }
                        >
                          Select all
                        </Button>
                      )}
                    </div>
                    <div className="grid gap-1 rounded-md border p-2">
                      {matchedLib.tasks.length === 0 ? (
                        <span className="px-1 py-2 text-xs text-muted-foreground">
                          This directory has no task packages.
                        </span>
                      ) : (
                        matchedLib.tasks.map((task) => {
                          const checked =
                            (taskSet?.task_ids.length ?? 0) === 0 ||
                            (taskSet?.task_ids ?? []).includes(task.id)
                          const explicit = (taskSet?.task_ids ?? []).includes(task.id)
                          return (
                            <label
                              key={task.id}
                              className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-muted/60"
                            >
                              <Checkbox
                                checked={explicit || (taskSet?.task_ids.length ?? 0) === 0}
                                onCheckedChange={(next) => {
                                  const current = taskSet?.task_ids ?? []
                                  /* Empty means "all"; the first explicit pick
                                     materializes the full list minus/plus this one. */
                                  const base =
                                    current.length === 0
                                      ? matchedLib.tasks.map((t) => t.id)
                                      : current
                                  const ids = next
                                    ? Array.from(new Set([...base, task.id]))
                                    : base.filter((id) => id !== task.id)
                                  patch({
                                    task_set: { tasks_dir: taskSet!.tasks_dir, task_ids: ids },
                                  })
                                }}
                              />
                              <span className="font-mono text-[13px]">{task.id}</span>
                              {!explicit && checked && (
                                <span className="text-[11px] text-muted-foreground">(all)</span>
                              )}
                            </label>
                          )
                        })
                      )}
                    </div>
                  </div>
                ) : (
                  taskSet?.tasks_dir && (
                    <div className="grid gap-1 rounded-md border border-warn-ink/30 bg-warn-soft/40 p-2">
                      <span className="flex items-center gap-1.5 text-xs text-warn-ink">
                        <AlertTriangle className="size-3.5" /> Directory not in the task library
                      </span>
                      {taskSet.task_ids.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                          {taskSet.task_ids.map((id) => (
                            <Badge key={id} variant="outline" className="font-mono text-[11px]">
                              {id}
                            </Badge>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                )}
              </div>
            )}
          </section>

          {/* per-agent fields */}
          <section className="grid gap-3">
            <SectionHeading icon={ListChecks} title="Per-agent fields">
              Checked: each agent sets its own value at launch. Unchecked: locked by this
              profile for everyone.
            </SectionHeading>
            <div className="grid gap-2 sm:grid-cols-2">
              {PER_CONTENDER_FIELDS.map((field) => {
                const checked = value.per_contender_fields.includes(field.id)
                return (
                  <label
                    key={field.id}
                    className={cn(
                      "flex cursor-pointer items-start gap-2.5 rounded-md border p-2.5",
                      checked ? "border-primary bg-accent/50" : "hover:border-primary/40",
                    )}
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={checked}
                      onCheckedChange={(next) =>
                        patch({
                          per_contender_fields: next
                            ? [...value.per_contender_fields, field.id]
                            : value.per_contender_fields.filter((id) => id !== field.id),
                        })
                      }
                    />
                    <span>
                      <span className="block text-sm font-medium">{field.label}</span>
                      <span className="block text-xs text-muted-foreground">{field.hint}</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </section>

          {error && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-fail-ink/30 bg-fail-soft/50 px-3 py-2.5"
            >
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-fail-ink" />
              <div className="grid gap-0.5">
                <span className="text-sm font-medium text-fail-ink">This profile was not saved</span>
                <span className="text-xs text-fail-ink/90">{error}</span>
              </div>
            </div>
          )}

          </div>
        </div>

        <div className="flex items-center gap-2 border-t bg-background px-4 py-3 sm:px-5">
          {canDelete && onDelete && (
            <Button
              variant="ghost"
              className="text-muted-foreground hover:text-fail-ink"
              onClick={onDelete}
            >
              <Trash2 /> Delete
            </Button>
          )}
          <div className="ml-auto flex gap-2">
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={saving} onClick={submit}>
              {saving ? "Saving…" : isNew ? "Create profile" : "Save profile"}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}

function SectionHeading({
  icon: Icon,
  title,
  children,
}: {
  icon: typeof Columns3
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="grid gap-0.5">
      <span className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="size-4 text-muted-foreground" /> {title}
      </span>
      <p className="text-xs text-muted-foreground">{children}</p>
    </div>
  )
}

/* Two-tier field help: `gloss` is the inline essential meaning (always
   visible, never hover-gated); `hint` is the secondary why/when behind a
   focusable question mark. */
function Field({
  label,
  gloss,
  hint,
  children,
  className,
}: {
  label: string
  gloss?: string
  hint?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      <div className="flex items-baseline gap-1.5">
        <Label>{label}</Label>
        {gloss && <span className="text-xs text-muted-foreground">{gloss}</span>}
        {hint && <Hint>{hint}</Hint>}
      </div>
      {children}
    </div>
  )
}

/* Numeric shared fields are edited as text so an empty box does not snap to 0;
   the value is coerced back to an int on save. */
function numValue(value: unknown): string | number {
  if (value === null || value === undefined) return ""
  return value as string | number
}
