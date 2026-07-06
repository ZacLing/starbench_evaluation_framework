import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  CheckCircle2,
  DownloadCloud,
  KeyRound,
  MonitorCheck,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
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
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import {
  AGENT_LABELS,
  AgentIcon,
  compatibleProviders,
  ProviderIcon,
  runtimeFilters,
} from "@/components/brand"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type AiProvider, type CustomRuntime, type ProviderKind } from "@/lib/api"
import { fmtTime } from "@/lib/format"
import { cn } from "@/lib/utils"

const KIND_LABELS: Record<ProviderKind, string> = {
  anthropic: "Anthropic API",
  openai: "OpenAI API",
  google: "Google API",
  xai: "xAI API",
  "openai-compatible": "OpenAI-compatible endpoint",
}

/* Single-vendor services behind an OpenAI-compatible endpoint; everything
   else that is openai-compatible reads as an aggregator gateway. */
const VENDOR_HINTS = ["deepseek", "qwen", "kimi", "moonshot", "doubao", "zhipu", "glm", "minimax", "mistral"]

function isVendorApi(provider: AiProvider): boolean {
  if (provider.kind !== "openai-compatible") return true
  const id = `${provider.id} ${provider.name}`.toLowerCase()
  return VENDOR_HINTS.some((hint) => id.includes(hint))
}

function providerDescription(provider: AiProvider): string {
  if (provider.kind !== "openai-compatible") {
    return `Official ${KIND_LABELS[provider.kind].replace(" API", "")} API`
  }
  return isVendorApi(provider)
    ? "Vendor API, OpenAI-compatible"
    : "Gateway to many vendors' models"
}

interface RuntimeRef {
  id: string
  icon?: string
  label: string
}

type Draft = Omit<AiProvider, "agent" | "key_present">

export default function Providers() {
  const queryClient = useQueryClient()
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  const [editing, setEditing] = useState<Draft | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [refreshing, setRefreshing] = useState<string | null>(null)
  const [modelsFor, setModelsFor] = useState<AiProvider | null>(null)

  if (providersQuery.isPending) return <Skeleton className="h-96" />
  if (providersQuery.isError) return <ErrorNote message={(providersQuery.error as Error).message} />
  const payload = providersQuery.data
  const customRuntimes = (agentsQuery.data?.custom ?? []).filter(
    (agent): agent is CustomRuntime => !agent.error,
  )

  /* Which agents can run models from this provider — the decoupling matrix,
     drawn on the resource side. Filters come from /api/agents (single source). */
  const filterMap = runtimeFilters(agentsQuery.data)
  const runtimesFor = (provider: AiProvider): RuntimeRef[] => [
    ...Object.keys(AGENT_LABELS)
      .filter((runtime) => compatibleProviders(filterMap[runtime], [provider]).length > 0)
      .map((runtime) => ({ id: runtime, label: AGENT_LABELS[runtime] })),
    ...customRuntimes
      .filter((agent) => compatibleProviders(agent.provider_filter, [provider]).length > 0)
      .map((agent) => ({ id: agent.id, icon: agent.icon, label: agent.label ?? agent.spec_id })),
  ]

  const vendors = payload.providers.filter(isVendorApi)
  const gateways = payload.providers.filter((provider) => !isVendorApi(provider))

  const persist = async (next: Draft[], message: string) => {
    try {
      await api.saveProviders({ providers: next })
      queryClient.invalidateQueries({ queryKey: ["providers"] })
      toast.success(message)
      return true
    } catch (error) {
      toast.error((error as Error).message)
      return false
    }
  }

  const bare = (provider: AiProvider): Draft => ({
    id: provider.id,
    name: provider.name,
    kind: provider.kind,
    auth: provider.auth,
    base_url: provider.base_url,
    anthropic_base_url: provider.anthropic_base_url ?? "",
    gemini_base_url: provider.gemini_base_url ?? "",
    api_key_env: provider.api_key_env,
    models: provider.models,
    models_fetched_at: provider.models_fetched_at,
    models_source: provider.models_source,
  })

  const refreshModels = async (provider: AiProvider) => {
    setRefreshing(provider.id)
    try {
      await api.refreshProviderModels(provider.id)
      queryClient.invalidateQueries({ queryKey: ["providers"] })
      toast.success(`Model catalog for ${provider.name} refreshed.`)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setRefreshing(null)
    }
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">AI providers</h1>
          <p className="text-sm text-muted-foreground">
            Where models come from. Every agent runs models from any provider that speaks
            its protocol.
          </p>
        </div>
        <Button
          className="ml-auto"
          onClick={() => {
            setIsNew(true)
            setEditing({
              id: "",
              name: "",
              kind: "openai-compatible",
              auth: "api_key",
              base_url: "",
              anthropic_base_url: "",
              gemini_base_url: "",
              api_key_env: "OPENAI_API_KEY",
              models: [],
              models_fetched_at: null,
              models_source: null,
            })
          }}
        >
          <Plus /> Add provider
        </Button>
      </div>

      {(
        [
          ["Model vendors", vendors],
          ["Gateways", gateways],
        ] as const
      ).map(
        ([title, group]) =>
          group.length > 0 && (
            <section key={title} className="grid gap-3">
              <h2 className="text-sm font-semibold text-muted-foreground">{title}</h2>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {group.map((provider) => (
                  <ProviderCard
                    key={provider.id}
                    provider={provider}
                    runtimes={runtimesFor(provider)}
                    refreshing={refreshing === provider.id}
                    onRefresh={() => refreshModels(provider)}
                    onShowModels={() => setModelsFor(provider)}
                    onEdit={() => {
                      setIsNew(false)
                      setEditing(bare(provider))
                    }}
                  />
                ))}
              </div>
            </section>
          ),
      )}

      <ModelListDialog provider={modelsFor} onClose={() => setModelsFor(null)} />

      <ProviderEditor
        key={editing?.id ?? "__closed"}
        draft={editing}
        isNew={isNew}
        onClose={() => setEditing(null)}
        onSave={async (draft) => {
          if (isNew && payload.providers.some((item) => item.id === draft.id)) {
            toast.error(`Provider id ${draft.id} already exists.`)
            return
          }
          const next = isNew
            ? [...payload.providers.map(bare), draft]
            : payload.providers.map((item) => (item.id === draft.id ? draft : bare(item)))
          const ok = await persist(next, `Provider ${draft.name || draft.id} saved.`)
          if (ok) setEditing(null)
        }}
        onDelete={
          isNew || !editing
            ? undefined
            : async () => {
                const ok = await persist(
                  payload.providers.filter((item) => item.id !== editing.id).map(bare),
                  `Provider ${editing.name || editing.id} removed.`,
                )
                if (ok) setEditing(null)
              }
        }
      />
    </div>
  )
}

function ProviderCard({
  provider,
  runtimes,
  refreshing,
  onRefresh,
  onShowModels,
  onEdit,
}: {
  provider: AiProvider
  runtimes: RuntimeRef[]
  refreshing: boolean
  onRefresh: () => void
  onShowModels: () => void
  onEdit: () => void
}) {
  const modelCount = provider.models.length
  const fromCatalog = provider.models_source === "catalog"
  const fetchedHint = provider.models_fetched_at
    ? `${fromCatalog ? "public catalog" : "provider API"} · ${fmtTime(provider.models_fetched_at)}`
    : "not fetched yet"
  return (
    <Card className="py-4">
      <CardContent className="grid gap-2.5 px-4">
        <div className="flex items-center gap-2.5">
          <ProviderIcon provider={provider} size={22} />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{provider.name}</span>
          {provider.auth === "cli_login" ? (
            <Badge className="gap-1 border-transparent bg-accent text-accent-foreground">
              <MonitorCheck className="size-3" /> CLI login
            </Badge>
          ) : provider.key_present ? (
            <Badge className="gap-1 border-transparent bg-pass-soft text-pass-ink">
              <KeyRound className="size-3" /> key set
            </Badge>
          ) : (
            <Badge className="gap-1 border-transparent bg-warn-soft text-warn-ink">
              <KeyRound className="size-3" /> key missing
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{providerDescription(provider)}</p>
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>For</span>
          {runtimes.length ? (
            runtimes.map((runtime) => (
              <span key={runtime.id} title={runtime.label} className="inline-flex">
                <AgentIcon agent={runtime.id} icon={runtime.icon} size={16} />
              </span>
            ))
          ) : (
            <span className="text-warn-ink">no compatible agent</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {modelCount ? (
            <>
              <button
                type="button"
                className="text-xs text-foreground underline decoration-muted-foreground/50 underline-offset-2 hover:decoration-foreground"
                title={`Browse the model list (${fetchedHint})`}
                onClick={onShowModels}
              >
                {modelCount} model{modelCount === 1 ? "" : "s"}
              </button>
              {/* Where the list came from is a trust fact, not a tooltip: a
                  public-catalog list proves nothing about this key or endpoint. */}
              <span
                className={cn("text-[11px]", fromCatalog ? "text-warn-ink" : "text-muted-foreground")}
                title={
                  fromCatalog
                    ? "Names from the public Vercel AI Gateway catalog. This list does not verify your key or endpoint."
                    : "Listed by the provider's own models API using your key."
                }
              >
                {fromCatalog ? "public catalog — key not verified" : "from your API"}
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="size-7"
                aria-label={`Refresh models for ${provider.name}`}
                title={`Refresh the model list (${fetchedHint})`}
                disabled={refreshing}
                onClick={onRefresh}
              >
                <RefreshCw className={cn("size-3.5", refreshing && "animate-spin")} />
              </Button>
            </>
          ) : (
            <Button
              variant="outline"
              size="sm"
              className="h-7 gap-1.5 text-xs"
              disabled={refreshing}
              onClick={onRefresh}
            >
              {refreshing ? (
                <RefreshCw className="size-3.5 animate-spin" />
              ) : (
                <DownloadCloud className="size-3.5" />
              )}
              Fetch models
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className="ml-auto size-7"
            aria-label={`Edit ${provider.name}`}
            onClick={onEdit}
          >
            <Pencil className="size-3.5" />
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/* The model catalog is first-class content, not a statistic: click the count
   to browse and filter the actual list, with its provenance stated up top. */
function ModelListDialog({
  provider,
  onClose,
}: {
  provider: AiProvider | null
  onClose: () => void
}) {
  const [filter, setFilter] = useState("")
  const models = provider?.models ?? []
  const needle = filter.trim().toLowerCase()
  const visible = needle ? models.filter((model) => model.toLowerCase().includes(needle)) : models
  const fromCatalog = provider?.models_source === "catalog"
  return (
    <Dialog
      open={Boolean(provider)}
      onOpenChange={(open) => {
        if (!open) {
          setFilter("")
          onClose()
        }
      }}
    >
      <DialogContent className="max-h-[80vh] sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {provider && <ProviderIcon provider={provider} size={18} />}
            {provider?.name} models
          </DialogTitle>
          <DialogDescription className={fromCatalog ? "text-warn-ink" : undefined}>
            {fromCatalog
              ? "Names from the public Vercel AI Gateway catalog — this list does not verify your key or endpoint."
              : `Listed by the provider's models API${provider?.models_fetched_at ? ` · ${fmtTime(provider.models_fetched_at)}` : ""}.`}
          </DialogDescription>
        </DialogHeader>
        {models.length > 8 && (
          <Input
            placeholder={`Filter ${models.length} models…`}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
        )}
        <div className="max-h-[50vh] overflow-y-auto rounded-md border">
          {visible.length ? (
            <ul className="divide-y">
              {visible.map((model) => (
                <li key={model} className="px-3 py-1.5 font-mono text-xs">
                  {model}
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-3 py-4 text-center text-xs text-muted-foreground">
              No model matches “{filter}”.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ProviderEditor({
  draft,
  isNew,
  onClose,
  onSave,
  onDelete,
}: {
  draft: Draft | null
  isNew: boolean
  onClose: () => void
  onSave: (draft: Draft) => void
  onDelete?: () => void
}) {
  const [form, setForm] = useState<Draft | null>(null)
  const value = form ?? draft
  const set = (patch: Partial<Draft>) => setForm((existing) => ({ ...(existing ?? draft!), ...patch }))

  return (
    <Sheet
      open={Boolean(draft)}
      onOpenChange={(open) => {
        if (!open) {
          setForm(null)
          onClose()
        }
      }}
    >
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-lg">
        <SheetHeader className="border-b">
          <SheetTitle>{isNew ? "Add provider" : `Edit ${draft?.name ?? ""}`}</SheetTitle>
          <SheetDescription>
            Keys stay in environment variables; the model catalog is refreshed from the
            provider's own API.
          </SheetDescription>
        </SheetHeader>
        {value && (
          <div className="grid gap-4 p-4">
            <div className="grid gap-1.5">
              <Label>Id</Label>
              <Input
                className="font-mono"
                value={value.id}
                disabled={!isNew}
                placeholder="my-gateway"
                onChange={(event) => set({ id: event.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>Name</Label>
              <Input
                value={value.name}
                placeholder="My gateway"
                onChange={(event) => set({ name: event.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>Kind</Label>
              <Select
                value={value.kind}
                onValueChange={(kind) => set({ kind: kind as ProviderKind })}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(KIND_LABELS) as ProviderKind[]).map((kind) => (
                    <SelectItem key={kind} value={kind}>
                      {KIND_LABELS[kind]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Sets the wire protocol — which agents can run models from this provider.
              </p>
            </div>
            <div className="grid gap-1.5">
              <Label>Credentials</Label>
              <RadioGroup
                value={value.auth}
                onValueChange={(auth) => set({ auth: auth as Draft["auth"] })}
                className="grid gap-2"
              >
                <label
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-md border p-3",
                    value.auth === "api_key" ? "border-primary bg-accent/60" : "hover:border-primary/40",
                  )}
                >
                  <RadioGroupItem value="api_key" className="mt-0.5" />
                  <span>
                    <span className="block text-sm font-medium">API key</span>
                    <span className="block text-xs text-muted-foreground">
                      Read from an environment variable; enables catalog refresh from the API.
                    </span>
                  </span>
                </label>
                <label
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-md border p-3",
                    value.kind === "openai-compatible" && "cursor-not-allowed opacity-50",
                    value.auth === "cli_login" ? "border-primary bg-accent/60" : "hover:border-primary/40",
                  )}
                >
                  <RadioGroupItem
                    value="cli_login"
                    className="mt-0.5"
                    disabled={value.kind === "openai-compatible"}
                  />
                  <span>
                    <span className="block text-sm font-medium">Local CLI login</span>
                    <span className="block text-xs text-muted-foreground">
                      Uses the runtime CLI's own login on this machine; the catalog falls back
                      to a public vendor snapshot.
                    </span>
                  </span>
                </label>
              </RadioGroup>
            </div>
            <div className="grid gap-1.5">
              <Label>Base URL</Label>
              <Input
                className="font-mono"
                placeholder={
                  value.kind === "openai-compatible"
                    ? "https://ai-gateway.vercel.sh/v1"
                    : "empty = the provider's official endpoint"
                }
                value={value.base_url}
                onChange={(event) => set({ base_url: event.target.value })}
              />
              {value.kind === "anthropic" && value.base_url && (
                <p className="text-xs text-muted-foreground">
                  Injected as ANTHROPIC_BASE_URL for runs using this provider.
                </p>
              )}
            </div>
            {value.kind !== "anthropic" && (
              <div className="grid gap-1.5">
                <Label>Anthropic-compatible endpoint (optional)</Label>
                <Input
                  className="font-mono"
                  placeholder="https://api.deepseek.com/anthropic"
                  value={value.anthropic_base_url ?? ""}
                  onChange={(event) => set({ anthropic_base_url: event.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  If this provider exposes an Anthropic Messages endpoint, Claude Code can run
                  its models through it (injected as ANTHROPIC_BASE_URL).
                </p>
              </div>
            )}
            {value.kind !== "google" && (
              <div className="grid gap-1.5">
                <Label>Gemini-compatible endpoint (optional)</Label>
                <Input
                  className="font-mono"
                  placeholder="https://my-litellm-proxy.example"
                  value={value.gemini_base_url ?? ""}
                  onChange={(event) => set({ gemini_base_url: event.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  If this provider exposes a Gemini API endpoint, Gemini CLI can run its models
                  through it (injected as GOOGLE_GEMINI_BASE_URL).
                </p>
              </div>
            )}
            {value.auth === "api_key" && (
              <div className="grid gap-1.5">
                <Label>API key environment variable</Label>
                <Input
                  className="font-mono"
                  placeholder="OPENAI_API_KEY"
                  value={value.api_key_env}
                  onChange={(event) => set({ api_key_env: event.target.value })}
                />
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              The model catalog is not edited by hand: save, then use the refresh button on the
              provider card to pull the list from the API.
            </p>
            <div className="flex items-center gap-2 border-t pt-4">
              {onDelete && (
                <Button
                  variant="ghost"
                  className="text-muted-foreground hover:text-fail-ink"
                  onClick={onDelete}
                >
                  <Trash2 /> Remove
                </Button>
              )}
              <div className="ml-auto flex gap-2">
                <Button variant="outline" onClick={onClose}>
                  Cancel
                </Button>
                <Button
                  onClick={() => {
                    onSave(value)
                    setForm(null)
                  }}
                >
                  <CheckCircle2 /> Save provider
                </Button>
              </div>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
