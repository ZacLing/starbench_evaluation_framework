import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  CheckCircle2,
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
import { ProviderIcon } from "@/components/brand"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type AiProvider, type ProviderKind } from "@/lib/api"
import { fmtTime } from "@/lib/format"
import { cn } from "@/lib/utils"

const KIND_LABELS: Record<ProviderKind, string> = {
  anthropic: "Anthropic API (Claude Code runtime)",
  openai: "OpenAI API (Codex runtime)",
  google: "Google API (Gemini CLI runtime)",
  xai: "xAI API (Grok Build runtime)",
  "openai-compatible": "OpenAI-compatible gateway (OpenCode runtime)",
}

type Draft = Omit<AiProvider, "agent" | "key_present">

export default function Providers() {
  const queryClient = useQueryClient()
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const [editing, setEditing] = useState<Draft | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [refreshing, setRefreshing] = useState<string | null>(null)

  if (providersQuery.isPending) return <Skeleton className="h-96" />
  if (providersQuery.isError) return <ErrorNote message={(providersQuery.error as Error).message} />
  const payload = providersQuery.data

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
            Endpoints, credentials, and model catalogs — the resource side of every experiment
            {payload.persisted ? "" : " (built-in presets, saved on first edit)"}
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

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {payload.providers.map((provider) => (
          <Card key={provider.id} className="py-4">
            <CardContent className="grid gap-2.5 px-4">
              <div className="flex items-center gap-2.5">
                <ProviderIcon provider={provider} size={22} />
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">
                  {provider.name}
                </span>
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
              <div className="grid gap-1 text-xs text-muted-foreground">
                <span>{KIND_LABELS[provider.kind]}</span>
                {provider.base_url && (
                  <span className="truncate font-mono" title={provider.base_url}>
                    {provider.base_url}
                  </span>
                )}
                {provider.anthropic_base_url && (
                  <span className="truncate" title={provider.anthropic_base_url}>
                    Claude Code ready ·{" "}
                    <span className="font-mono">{provider.anthropic_base_url}</span>
                  </span>
                )}
                {provider.auth === "api_key" && (
                  <span className="font-mono">${provider.api_key_env || "—"}</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {provider.models.length} model{provider.models.length === 1 ? "" : "s"}
                  {provider.models_fetched_at &&
                    ` · ${provider.models_source === "catalog" ? "catalog snapshot" : "from API"} ${fmtTime(provider.models_fetched_at)}`}
                </span>
                <div className="ml-auto flex gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label={`Refresh models for ${provider.name}`}
                    title="Refresh the model catalog from the provider's API"
                    disabled={refreshing === provider.id}
                    onClick={() => refreshModels(provider)}
                  >
                    <RefreshCw
                      className={cn("size-3.5", refreshing === provider.id && "animate-spin")}
                    />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7"
                    aria-label={`Edit ${provider.name}`}
                    onClick={() => {
                      setIsNew(false)
                      setEditing(bare(provider))
                    }}
                  >
                    <Pencil className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 text-muted-foreground hover:text-fail-ink"
                    aria-label={`Delete ${provider.name}`}
                    onClick={() =>
                      persist(
                        payload.providers.filter((item) => item.id !== provider.id).map(bare),
                        `Provider ${provider.name} removed.`,
                      )
                    }
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

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
      />
    </div>
  )
}

function ProviderEditor({
  draft,
  isNew,
  onClose,
  onSave,
}: {
  draft: Draft | null
  isNew: boolean
  onClose: () => void
  onSave: (draft: Draft) => void
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
                Decides which agent runtime executes models from this provider.
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
            <div className="flex justify-end gap-2 border-t pt-4">
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
        )}
      </SheetContent>
    </Sheet>
  )
}
