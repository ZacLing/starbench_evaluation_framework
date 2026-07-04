import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { CheckCircle2, CloudDownload, KeyRound, Loader2, Pencil, Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import { Textarea } from "@/components/ui/textarea"
import { ProviderIcon } from "@/components/brand"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type AiProvider, type ProviderKind } from "@/lib/api"

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
    base_url: provider.base_url,
    api_key_env: provider.api_key_env,
    models: provider.models,
  })

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">AI providers</h1>
          <p className="text-sm text-muted-foreground">
            Endpoints, credentials, and model catalogs used by the experiment wizard
            {payload.persisted ? "" : " — built-in presets, saved on first edit"}
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
              base_url: "",
              api_key_env: "OPENAI_API_KEY",
              models: [],
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
                {provider.key_present ? (
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
                <span className="font-mono">${provider.api_key_env || "—"}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">
                  {provider.models.length} model{provider.models.length === 1 ? "" : "s"}
                </span>
                <div className="ml-auto flex gap-1">
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
          const others = payload.providers.map(bare).filter((item) => item.id !== draft.id)
          if (isNew && payload.providers.some((item) => item.id === draft.id)) {
            toast.error(`Provider id ${draft.id} already exists.`)
            return
          }
          const ok = await persist(
            isNew ? [...payload.providers.map(bare), draft] : [...others, draft].sort(
              (a, b) =>
                payload.providers.findIndex((p) => p.id === a.id) -
                payload.providers.findIndex((p) => p.id === b.id),
            ),
            `Provider ${draft.name || draft.id} saved.`,
          )
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
  const [importing, setImporting] = useState(false)

  const set = (patch: Partial<Draft>) =>
    setForm((existing) => ({ ...(existing ?? draft!), ...patch }))

  const value = form ?? draft

  const importCatalog = async () => {
    if (!value) return
    setImporting(true)
    try {
      const catalog = await api.vercelCatalog()
      let models = catalog.models
      if (value.kind !== "openai-compatible") {
        const creator =
          value.kind === "anthropic"
            ? "anthropic"
            : value.kind === "openai"
              ? "openai"
              : value.kind === "google"
                ? "google"
                : "xai"
        models = catalog.models
          .filter((model) => model.startsWith(`${creator}/`))
          .map((model) => model.slice(creator.length + 1))
      }
      if (!models.length) {
        toast.error("No catalog models match this provider kind.")
        return
      }
      const merged = Array.from(new Set([...(value.models ?? []), ...models]))
      set({ models: merged })
      toast.success(`Imported ${models.length} models from the Vercel AI Gateway catalog.`)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setImporting(false)
    }
  }

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
            Keys stay in environment variables; the console stores only the variable name.
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
            <div className="grid gap-1.5">
              <Label>API key environment variable</Label>
              <Input
                className="font-mono"
                placeholder="OPENAI_API_KEY"
                value={value.api_key_env}
                onChange={(event) => set({ api_key_env: event.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <div className="flex items-center justify-between">
                <Label>Models (one per line)</Label>
                <Button variant="outline" size="sm" disabled={importing} onClick={importCatalog}>
                  {importing ? <Loader2 className="animate-spin" /> : <CloudDownload />}
                  Import from Vercel AI Gateway
                </Button>
              </div>
              <Textarea
                className="min-h-40 font-mono text-xs"
                value={value.models.join("\n")}
                placeholder={"gpt-5.5\nanthropic/claude-opus-4.8"}
                onChange={(event) => set({ models: event.target.value.split("\n") })}
              />
            </div>
            <div className="flex justify-end gap-2 border-t pt-4">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  onSave({
                    ...value,
                    models: value.models.map((model) => model.trim()).filter(Boolean),
                  })
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
