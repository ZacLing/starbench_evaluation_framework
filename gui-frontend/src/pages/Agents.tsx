import { useState } from "react"
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  AlertTriangle,
  CheckCircle2,
  Container,
  DownloadCloud,
  ExternalLink,
  Info,
  Laptop,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
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
import { Textarea } from "@/components/ui/textarea"
import { AgentIcon, CUSTOM_ICON_CHOICES, compatibleProviders } from "@/components/brand"
import { ErrorNote } from "@/components/error-note"
import {
  api,
  type AgentTemplate,
  type AgentRuntimeStatus,
  type AiProvider,
  type BuiltinRuntime,
  type CustomRuntime,
  type CustomRuntimePayload,
} from "@/lib/api"
import { cn } from "@/lib/utils"

const PROTOCOL_LABELS: Record<string, string> = {
  openai: "OpenAI protocol",
  anthropic: "Anthropic protocol",
  gemini: "Gemini protocol",
  xai: "xAI protocol",
  none: "own login / config",
}

const PARSER_NOTES: Record<string, string> = {
  "headless-json": "stdout is one JSON object; normalized into trace events",
  "jsonl-events": "stdout is a Codex-compatible JSONL event stream",
  text: "raw stdout is the final message; no command trace",
}

export default function Agents() {
  const queryClient = useQueryClient()
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  // The page paints from local CLI probes only; npm update checks hit the
  // network and run solely when the user clicks "Check updates".
  const [checkUpdates, setCheckUpdates] = useState(false)
  const agentStatusQuery = useQuery({
    queryKey: ["agent-status", checkUpdates],
    queryFn: () => api.agentStatus(checkUpdates),
    enabled: agentsQuery.isSuccess,
    retry: false,
    placeholderData: keepPreviousData,
  })
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const templatesQuery = useQuery({
    queryKey: ["agent-templates"],
    queryFn: api.agentTemplates,
    staleTime: Infinity,
  })
  const [editing, setEditing] = useState<Draft | null>(null)
  const [isNew, setIsNew] = useState(false)
  const [details, setDetails] = useState<BuiltinRuntime | null>(null)
  const [installingId, setInstallingId] = useState<string | null>(null)

  if (agentsQuery.isPending) return <Skeleton className="h-96" />
  if (agentsQuery.isError) return <ErrorNote message={(agentsQuery.error as Error).message} />
  const payload = agentsQuery.data
  const providers = providersQuery.data?.providers ?? []
  const templates = templatesQuery.data?.templates ?? []
  const statuses = agentStatusQuery.data?.statuses ?? {}

  const installAgent = async (agentId: string, label: string) => {
    setInstallingId(agentId)
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
      setInstallingId(null)
    }
  }

  const removeAgent = async (agent: CustomRuntime) => {
    try {
      await api.deleteAgent(agent.spec_id)
      queryClient.invalidateQueries({ queryKey: ["agents"] })
      toast.success(`Runtime ${agent.label ?? agent.spec_id} removed.`)
    } catch (error) {
      toast.error((error as Error).message)
    }
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <h1 className="text-xl font-semibold tracking-tight">Agents</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            The coding-agent CLIs that can compete or judge. Any headless CLI can be added
            as a runtime; runs execute in Docker whenever the runtime supports it.
          </p>
        </div>
        {/* One flex unit: the actions never split across rows when space runs out. */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            className="gap-1.5"
            onClick={() => {
              if (checkUpdates) agentStatusQuery.refetch()
              else setCheckUpdates(true)
            }}
            disabled={agentStatusQuery.isFetching}
          >
            <RefreshCw className={cn("size-4", agentStatusQuery.isFetching && "animate-spin")} />
            Check updates
          </Button>
          <Button
            className="gap-1.5"
            onClick={() => {
              setIsNew(true)
              setEditing(emptyDraft())
            }}
          >
            <Plus /> Add runtime
          </Button>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {payload.builtin.map((agent) => (
          <RuntimeCard
            key={agent.id}
            agentId={agent.id}
            label={agent.label}
            description={agent.note}
            protocol={agent.protocol}
            providerCount={compatibleProviders(agent.provider_filter, providers, agent.id).length}
            dockerImage={agent.docker_image}
            cli={agent.cli}
            status={statuses[agent.id]}
            statusLoading={agentStatusQuery.isPending || agentStatusQuery.isFetching}
            installing={installingId === agent.id}
            onInstall={() => installAgent(agent.id, agent.label)}
            actionLabel={`About ${agent.label}`}
            actionIcon="details"
            onAction={() => setDetails(agent)}
          />
        ))}
        {payload.custom.map((agent) =>
          agent.error ? (
            <Card key={agent.id} className="border-warn-ink/40 py-4">
              <CardContent className="grid gap-2 px-4">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="size-4 text-warn-ink" />
                  <span className="font-mono text-sm font-semibold">{agent.spec_id}</span>
                </div>
                <p className="text-xs text-warn-ink">{agent.error}</p>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {agent.source_path}
                </p>
              </CardContent>
            </Card>
          ) : (
            <RuntimeCard
              key={agent.id}
              agentId={agent.id}
              icon={agent.icon}
              label={agent.label ?? agent.spec_id}
              description={agent.description || (agent.command ?? "")}
              protocol={agent.protocol ?? "none"}
              providerCount={compatibleProviders(agent.provider_filter, providers, agent.id).length}
              dockerImage={agent.docker_image}
              cli={agent.cli}
              status={statuses[agent.id]}
              statusLoading={agentStatusQuery.isPending || agentStatusQuery.isFetching}
              installing={installingId === agent.id}
              onInstall={() => installAgent(agent.id, agent.label ?? agent.spec_id)}
              actionLabel={`Edit ${agent.label ?? agent.spec_id}`}
              actionIcon="edit"
              onAction={() => {
                setIsNew(false)
                setEditing(draftFromAgent(agent))
              }}
            />
          ),
        )}
      </div>

      <BuiltinDetails
        agent={details}
        providers={providers}
        status={details ? statuses[details.id] : undefined}
        installing={details ? installingId === details.id : false}
        onInstall={
          details
            ? () => installAgent(details.id, details.label)
            : undefined
        }
        onClose={() => setDetails(null)}
      />

      <RuntimeEditor
        key={editing ? `${isNew}-${editing.id || "new"}` : "__closed"}
        draft={editing}
        isNew={isNew}
        templates={templates}
        onClose={() => setEditing(null)}
        onSave={async (draft) => {
          if (isNew && payload.custom.some((agent) => agent.spec_id === draft.id.trim())) {
            toast.error(`Runtime id ${draft.id.trim()} already exists — edit it instead.`)
            return
          }
          try {
            await api.saveAgent(draftToPayload(draft))
            queryClient.invalidateQueries({ queryKey: ["agents"] })
            toast.success(`Runtime ${draft.label || draft.id} saved.`)
            setEditing(null)
          } catch (error) {
            toast.error((error as Error).message)
          }
        }}
        onDelete={
          isNew || !editing
            ? undefined
            : async () => {
                const agent = payload.custom.find((item) => item.spec_id === editing.id)
                if (agent && !agent.error) {
                  await removeAgent(agent)
                  setEditing(null)
                }
              }
        }
      />
    </div>
  )
}

/* One card for every runtime — same rows, same badges; the only difference
   is where the action leads (read-only details vs the editor). */
function RuntimeCard({
  agentId,
  icon,
  label,
  description,
  protocol,
  providerCount,
  dockerImage,
  cli,
  status,
  statusLoading,
  installing,
  onInstall,
  actionIcon,
  actionLabel,
  onAction,
}: {
  agentId: string
  icon?: string
  label: string
  description: string
  protocol: string
  providerCount: number
  dockerImage?: string | null
  cli?: { bin: string; present: boolean; path: string | null }
  status?: AgentRuntimeStatus
  statusLoading?: boolean
  installing?: boolean
  onInstall?: () => void
  actionIcon: "edit" | "details"
  actionLabel: string
  onAction: () => void
}) {
  const ownLogin = protocol === "none"
  const showInstall = status?.installable && status.present === false
  const showUpdate = status?.installable && status.update_available === true
  return (
    <Card className="py-4">
      <CardContent className="grid gap-2.5 px-4">
        <div className="flex items-center gap-2.5">
          <AgentIcon agent={agentId} icon={icon} size={22} />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{label}</span>
          <CliBadge cli={status ?? cli} />
        </div>
        <div className="grid gap-1 text-xs text-muted-foreground">
          <span className="truncate" title={description}>
            {description}
          </span>
          <span>
            {PROTOCOL_LABELS[protocol] ?? protocol}
            {!ownLogin &&
              ` · ${
                providerCount
                  ? `${providerCount} provider${providerCount > 1 ? "s" : ""}`
                  : "no provider configured"
              }`}
          </span>
          <VersionLine status={status} loading={statusLoading} />
        </div>
        <div className="flex items-center gap-1.5">
          <IsolationBadge dockerImage={dockerImage} />
          {(showInstall || showUpdate) && (
            <Button
              variant="outline"
              size="sm"
              className="ml-auto h-7 gap-1.5 text-xs"
              title={status?.package ? status.package.install_command.join(" ") : undefined}
              disabled={installing}
              onClick={onInstall}
            >
              {installing ? (
                <RefreshCw className="size-3.5 animate-spin" />
              ) : showUpdate ? (
                <RefreshCw className="size-3.5" />
              ) : (
                <DownloadCloud className="size-3.5" />
              )}
              {showUpdate ? "Update" : "Install"}
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            className={cn("size-7", !(showInstall || showUpdate) && "ml-auto")}
            aria-label={actionLabel}
            title={actionLabel}
            onClick={onAction}
          >
            {actionIcon === "edit" ? (
              <Pencil className="size-3.5" />
            ) : (
              <Info className="size-3.5" />
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function BuiltinDetails({
  agent,
  providers,
  status,
  installing,
  onInstall,
  onClose,
}: {
  agent: BuiltinRuntime | null
  providers: AiProvider[]
  status?: AgentRuntimeStatus
  installing?: boolean
  onInstall?: () => void
  onClose: () => void
}) {
  return (
    <Sheet open={Boolean(agent)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-md">
        {agent && (
          <>
            <SheetHeader className="border-b">
              <SheetTitle>
                <span className="flex items-center gap-2">
                  <AgentIcon agent={agent.id} size={20} />
                  {agent.label}
                </span>
              </SheetTitle>
              <SheetDescription>
                {agent.note}. Natively integrated: the runner implements this CLI's
                invocation, tracing, and sandboxing in code, so there is nothing to
                configure here — pick its provider and model when you set up an
                experiment.
              </SheetDescription>
            </SheetHeader>
            <dl className="grid gap-3 p-4 text-sm">
              <DetailRow label="Protocol">
                {PROTOCOL_LABELS[agent.protocol] ?? agent.protocol}
              </DetailRow>
              <DetailRow label="Compatible providers">
                {compatibleProviders(agent.provider_filter, providers, agent.id).length ||
                  "none configured"}
              </DetailRow>
              <DetailRow label="Docker image">
                <span className="font-mono text-xs">{agent.docker_image}</span>
              </DetailRow>
              <DetailRow label="CLI">
                <span className="font-mono text-xs">
                  {(status ?? agent.cli).present
                    ? ((status ?? agent.cli).path ?? (status ?? agent.cli).bin)
                    : `\`${(status ?? agent.cli).bin}\` not found on PATH`}
                </span>
              </DetailRow>
              <DetailRow label="Version">
                <VersionLine status={status} />
              </DetailRow>
              {status?.package && (
                <DetailRow label="Install">
                  <div className="grid gap-2">
                    <code className="break-all rounded bg-muted px-1.5 py-1 font-mono text-xs">
                      {status.package.install_command.join(" ")}
                    </code>
                    {(!status.present || status.update_available === true) && (
                      <Button
                        size="sm"
                        className="w-fit gap-1.5"
                        disabled={installing}
                        onClick={onInstall}
                      >
                        {installing ? (
                          <RefreshCw className="size-3.5 animate-spin" />
                        ) : status.update_available === true ? (
                          <RefreshCw className="size-3.5" />
                        ) : (
                          <DownloadCloud className="size-3.5" />
                        )}
                        {status.update_available === true ? "Update CLI" : "Install CLI"}
                      </Button>
                    )}
                  </div>
                </DetailRow>
              )}
            </dl>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] items-baseline gap-2">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function IsolationBadge({ dockerImage }: { dockerImage?: string | null }) {
  return dockerImage ? (
    <Badge variant="outline" className="gap-1 text-[11px]" title={dockerImage}>
      <Container className="size-3" /> Docker
    </Badge>
  ) : (
    <Badge
      className="gap-1 border-transparent bg-warn-soft text-[11px] text-warn-ink"
      title="No Docker image configured — tasks execute directly on this machine, without container isolation."
    >
      <Laptop className="size-3" /> local execution
    </Badge>
  )
}

function VersionLine({
  status,
  loading,
}: {
  status?: AgentRuntimeStatus
  loading?: boolean
}) {
  if (loading && !status) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px]">
        <RefreshCw className="size-3 animate-spin" /> checking versions
      </span>
    )
  }
  if (!status) return <span className="text-[11px]">version not checked</span>
  if (!status.present) {
    return (
      <span className="text-[11px]">
        not installed
        {status.package ? ` · ${status.package.manager} package ${status.package.name}` : ""}
      </span>
    )
  }
  const local = status.version ? `v${status.version}` : "version unavailable"
  const latest = status.latest_version ? `latest v${status.latest_version}` : null
  const update = status.update_available === true
  // Three distinct states, honestly labeled: the update check ran and found a
  // newer version ("update available"), it ran and failed ("update check
  // failed"), or it never ran (latest_error and latest_checked_at both null —
  // neutral "updates not checked", never a warning).
  const updatesNotChecked =
    status.installable && !status.latest_version && !status.latest_error && !status.latest_checked_at
  return (
    <span
      className={cn(
        "truncate text-[11px]",
        update ? "text-warn-ink" : "text-muted-foreground",
      )}
      title={[
        status.version_output,
        status.version_error,
        status.latest_error,
        status.package?.update_command.join(" "),
      ]
        .filter(Boolean)
        .join("\n")}
    >
      {local}
      {latest ? ` · ${latest}` : ""}
      {update ? " · update available" : ""}
      {status.latest_error ? " · update check failed" : ""}
      {updatesNotChecked ? " · updates not checked" : ""}
    </span>
  )
}

function CliBadge({
  cli,
}: {
  cli?: { bin: string; present: boolean; path: string | null; update_available?: boolean | null }
}) {
  if (!cli) return null
  if (cli.present && cli.update_available === true) {
    return (
      <Badge
        className="gap-1 border-transparent bg-warn-soft text-[11px] text-warn-ink"
        title={cli.path ?? undefined}
      >
        <RefreshCw className="size-3" /> update
      </Badge>
    )
  }
  return cli.present ? (
    <Badge
      className="gap-1 border-transparent bg-pass-soft text-[11px] text-pass-ink"
      title={cli.path ?? undefined}
    >
      <CheckCircle2 className="size-3" /> CLI found
    </Badge>
  ) : (
    <Badge
      className="gap-1 border-transparent bg-warn-soft text-[11px] text-warn-ink"
      title={`\`${cli.bin}\` is not on PATH`}
    >
      <AlertTriangle className="size-3" /> missing
    </Badge>
  )
}

/* ---------- editor ---------- */

interface Draft {
  id: string
  label: string
  description: string
  sourcePath?: string
  icon: string
  command: string
  argsText: string
  judgeSame: boolean
  judgeArgsText: string
  model_flag: string
  prompt_via: string
  prompt_flag: string
  parser: string
  protocol: string
  base_url_env: string
  api_key_env: string
  envText: string
  docker_image: string
  dockerEnvText: string
}

function emptyDraft(): Draft {
  return {
    id: "",
    label: "",
    description: "",
    icon: "",
    command: "",
    argsText: "",
    judgeSame: true,
    judgeArgsText: "",
    model_flag: "",
    prompt_via: "stdin",
    prompt_flag: "-p",
    parser: "text",
    protocol: "none",
    base_url_env: "",
    api_key_env: "",
    envText: "",
    docker_image: "",
    dockerEnvText: "",
  }
}

function draftFromAgent(agent: CustomRuntime): Draft {
  return {
    id: agent.spec_id,
    label: agent.label ?? "",
    description: agent.description ?? "",
    sourcePath: agent.source_path,
    icon: agent.icon ?? "",
    command: agent.command ?? "",
    argsText: (agent.args ?? []).join("\n"),
    judgeSame: agent.judge_args_inherited ?? true,
    judgeArgsText: (agent.judge_args ?? []).join("\n"),
    model_flag: agent.model_flag ?? "",
    prompt_via: agent.prompt_via ?? "stdin",
    prompt_flag: agent.prompt_flag ?? "-p",
    parser: agent.parser ?? "text",
    protocol: agent.protocol ?? "none",
    base_url_env: agent.base_url_env ?? "",
    api_key_env: agent.api_key_env ?? "",
    envText: Object.entries(agent.env ?? {})
      .map(([key, value]) => `${key}=${value}`)
      .join("\n"),
    docker_image: agent.docker_image ?? "",
    dockerEnvText: (agent.docker_env_passthrough ?? []).join("\n"),
  }
}

function draftFromTemplate(template: AgentTemplate): Draft {
  const spec = template.spec as Record<string, unknown>
  const list = (key: string) => ((spec[key] as string[] | undefined) ?? []).join("\n")
  const docker = (spec.docker ?? {}) as { image?: string; env_passthrough?: string[] }
  return {
    ...emptyDraft(),
    id: String(spec.id ?? ""),
    label: String(spec.label ?? template.title),
    description: String(spec.description ?? ""),
    icon: String(spec.icon ?? ""),
    command: String(spec.command ?? ""),
    argsText: list("args"),
    judgeSame: spec.judge_args === undefined,
    judgeArgsText: list("judge_args"),
    model_flag: String(spec.model_flag ?? ""),
    prompt_via: String(spec.prompt_via ?? "stdin"),
    prompt_flag: String(spec.prompt_flag ?? "-p"),
    parser: String(spec.parser ?? "text"),
    protocol: String(spec.protocol ?? "none"),
    base_url_env: String(spec.base_url_env ?? ""),
    api_key_env: String(spec.api_key_env ?? ""),
    docker_image: String(docker.image ?? ""),
    dockerEnvText: (docker.env_passthrough ?? []).join("\n"),
  }
}

function splitLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
}

function draftToPayload(draft: Draft): CustomRuntimePayload {
  const env: Record<string, string> = {}
  for (const line of splitLines(draft.envText)) {
    const eq = line.indexOf("=")
    if (eq > 0) env[line.slice(0, eq).trim()] = line.slice(eq + 1).trim()
  }
  return {
    id: draft.id.trim(),
    label: draft.label.trim() || undefined,
    description: draft.description.trim() || undefined,
    icon: draft.icon || undefined,
    command: draft.command.trim(),
    args: splitLines(draft.argsText),
    judge_args: draft.judgeSame ? null : splitLines(draft.judgeArgsText),
    model_flag: draft.model_flag.trim() || undefined,
    prompt_via: draft.prompt_via,
    prompt_flag: draft.prompt_flag,
    parser: draft.parser,
    env: Object.keys(env).length ? env : undefined,
    protocol: draft.protocol,
    base_url_env: draft.base_url_env.trim() || undefined,
    api_key_env: draft.api_key_env.trim() || undefined,
    docker_image: draft.docker_image.trim() || undefined,
    docker_env_passthrough: splitLines(draft.dockerEnvText),
  }
}

function RuntimeEditor({
  draft,
  isNew,
  templates,
  onClose,
  onSave,
  onDelete,
}: {
  draft: Draft | null
  isNew: boolean
  templates: AgentTemplate[]
  onClose: () => void
  onSave: (draft: Draft) => void
  onDelete?: () => void
}) {
  const [form, setForm] = useState<Draft | null>(null)
  const [templateId, setTemplateId] = useState("")
  const value = form ?? draft
  const set = (patch: Partial<Draft>) =>
    setForm((existing) => ({ ...(existing ?? draft!), ...patch }))
  const activeTemplate = templates.find((item) => item.template_id === templateId)

  return (
    <Sheet
      open={Boolean(draft)}
      onOpenChange={(open) => {
        if (!open) {
          setForm(null)
          setTemplateId("")
          onClose()
        }
      }}
    >
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-xl">
        <SheetHeader className="border-b">
          <SheetTitle>{isNew ? "Add runtime" : `Edit ${draft?.label || draft?.id}`}</SheetTitle>
          <SheetDescription>
            Saved as <code className="font-mono">runtimes/&lt;id&gt;.json</code> — the same
            file the command-line runner reads. Verify flags against the installed CLI's
            --help; they drift between versions.
          </SheetDescription>
        </SheetHeader>
        {value && (
          <div className="grid gap-4 p-4">
            {isNew && templates.length > 0 && (
              <div className="grid gap-1.5">
                <Label>Start from</Label>
                <Select
                  value={templateId || "blank"}
                  onValueChange={(next) => {
                    setTemplateId(next === "blank" ? "" : next)
                    const template = templates.find((item) => item.template_id === next)
                    setForm(template ? draftFromTemplate(template) : emptyDraft())
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="blank">Blank runtime</SelectItem>
                    {templates.map((template) => (
                      <SelectItem key={template.template_id} value={template.template_id}>
                        {template.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {activeTemplate && (
                  <p className="text-xs text-muted-foreground">
                    {activeTemplate.description}{" "}
                    <a
                      href={activeTemplate.docs_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-0.5 text-primary hover:underline"
                    >
                      docs <ExternalLink className="size-3" />
                    </a>
                  </p>
                )}
              </div>
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label>Id</Label>
                <Input
                  className="font-mono"
                  value={value.id}
                  disabled={!isNew}
                  placeholder="qwen-code"
                  onChange={(event) => set({ id: event.target.value })}
                />
              </div>
              <div className="grid gap-1.5">
                <Label>Display name</Label>
                <Input
                  value={value.label}
                  placeholder="Qwen Code"
                  onChange={(event) => set({ label: event.target.value })}
                />
              </div>
            </div>
            <div className="grid gap-1.5">
              <Label>Description</Label>
              <Input
                value={value.description}
                placeholder="Alibaba's coding agent (Qwen)"
                onChange={(event) => set({ description: event.target.value })}
              />
            </div>
            <div className="grid gap-1.5">
              <Label>Icon</Label>
              <Select value={value.icon || "generic"} onValueChange={(icon) => set({ icon: icon === "generic" ? "" : icon })}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CUSTOM_ICON_CHOICES.map((choice) => (
                    <SelectItem key={choice || "generic"} value={choice || "generic"}>
                      <span className="flex items-center gap-2">
                        <AgentIcon agent="custom:x" icon={choice} size={16} />
                        {choice || "generic"}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-1.5">
              <Label>Command</Label>
              <Input
                className="font-mono"
                value={value.command}
                placeholder="qwen"
                onChange={(event) => set({ command: event.target.value })}
              />
              <p className="text-xs text-muted-foreground">
                Executable or shell-like prefix (like --codex-bin), split with shell rules.
              </p>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label>Arguments (one per line)</Label>
                <Textarea
                  className="min-h-24 font-mono text-xs"
                  value={value.argsText}
                  placeholder={"--output-format\njson\n--yolo"}
                  onChange={(event) => set({ argsText: event.target.value })}
                />
              </div>
              <div className="grid content-start gap-1.5">
                <Label>Judge arguments</Label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={value.judgeSame}
                    onCheckedChange={(checked) => set({ judgeSame: checked === true })}
                  />
                  Same as executor arguments
                </label>
                {!value.judgeSame && (
                  <Textarea
                    className="min-h-16 font-mono text-xs"
                    value={value.judgeArgsText}
                    placeholder={"--output-format\njson\n--approval-mode\nplan"}
                    onChange={(event) => set({ judgeArgsText: event.target.value })}
                  />
                )}
                <p className="text-xs text-muted-foreground">
                  Point judge runs at the CLI's read-only/plan mode so judges cannot modify
                  the workspace.
                </p>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label>Model flag</Label>
                <Input
                  className="font-mono"
                  value={value.model_flag}
                  placeholder="-m"
                  onChange={(event) => set({ model_flag: event.target.value })}
                />
                <p className="text-xs text-muted-foreground">
                  Empty = the model choice is not passed on the command line.
                </p>
              </div>
              <div className="grid gap-1.5">
                <Label>Prompt delivery</Label>
                <RadioGroup
                  value={value.prompt_via}
                  onValueChange={(prompt_via) => set({ prompt_via })}
                  className="grid gap-1.5"
                >
                  <label className="flex items-center gap-2 text-sm">
                    <RadioGroupItem value="stdin" /> stdin (recommended)
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <RadioGroupItem value="arg" /> command-line argument
                  </label>
                </RadioGroup>
                {value.prompt_via === "arg" && (
                  <>
                    <Input
                      className="font-mono"
                      value={value.prompt_flag}
                      placeholder="-p (empty = positional argument)"
                      onChange={(event) => set({ prompt_flag: event.target.value })}
                    />
                    <p className="text-xs text-warn-ink">
                      Whole task prompt on the command line — very large prompts can exceed
                      the OS argument limit.
                    </p>
                  </>
                )}
              </div>
            </div>

            <div className="grid gap-1.5">
              <Label>Output parser</Label>
              <RadioGroup
                value={value.parser}
                onValueChange={(parser) => set({ parser })}
                className="grid gap-2"
              >
                {Object.entries(PARSER_NOTES).map(([parser, note]) => (
                  <label
                    key={parser}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-md border p-3",
                      value.parser === parser
                        ? "border-primary bg-accent/60"
                        : "hover:border-primary/40",
                    )}
                  >
                    <RadioGroupItem value={parser} className="mt-0.5" />
                    <span>
                      <span className="block font-mono text-sm font-medium">{parser}</span>
                      <span className="block text-xs text-muted-foreground">{note}</span>
                    </span>
                  </label>
                ))}
              </RadioGroup>
            </div>

            <div className="grid gap-1.5">
              <Label>AI providers</Label>
              <Select value={value.protocol} onValueChange={(protocol) => set({ protocol })}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">None — the CLI uses its own login/config</SelectItem>
                  <SelectItem value="openai">OpenAI protocol (OpenAI, gateways, OpenRouter…)</SelectItem>
                  <SelectItem value="anthropic">Anthropic protocol</SelectItem>
                  <SelectItem value="gemini">Gemini protocol</SelectItem>
                </SelectContent>
              </Select>
              {value.protocol !== "none" && (
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="grid gap-1.5">
                    <Label className="text-xs">Endpoint env var</Label>
                    <Input
                      className="font-mono"
                      value={value.base_url_env}
                      placeholder="OPENAI_BASE_URL"
                      onChange={(event) => set({ base_url_env: event.target.value })}
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label className="text-xs">API key env var</Label>
                    <Input
                      className="font-mono"
                      value={value.api_key_env}
                      placeholder="OPENAI_API_KEY"
                      onChange={(event) => set({ api_key_env: event.target.value })}
                    />
                  </div>
                  <p className="text-xs text-muted-foreground sm:col-span-2">
                    The console injects the selected provider's endpoint and key through
                    these variables at launch; keys never leave the server environment.
                  </p>
                </div>
              )}
            </div>

            <div className="grid gap-1.5">
              <Label>Static environment (KEY=value, one per line)</Label>
              <Textarea
                className="min-h-16 font-mono text-xs"
                value={value.envText}
                placeholder="MY_CLI_TELEMETRY=off"
                onChange={(event) => set({ envText: event.target.value })}
              />
            </div>

            <div className="grid gap-1.5">
              <Label>Docker image (optional)</Label>
              <Input
                className="font-mono"
                value={value.docker_image}
                placeholder="starbench-qwen:latest"
                onChange={(event) => set({ docker_image: event.target.value })}
              />
              {value.docker_image && (
                <>
                  <Label className="text-xs">Env passthrough into the container</Label>
                  <Textarea
                    className="min-h-16 font-mono text-xs"
                    value={value.dockerEnvText}
                    placeholder={"OPENAI_API_KEY\nOPENAI_BASE_URL"}
                    onChange={(event) => set({ dockerEnvText: event.target.value })}
                  />
                </>
              )}
              <p className="text-xs text-muted-foreground">
                With an image set, this runtime can execute inside Docker isolation.
              </p>
            </div>

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
                <Button onClick={() => onSave(value)}>
                  <CheckCircle2 /> Save runtime
                </Button>
              </div>
            </div>
            {value.sourcePath && (
              <p className="truncate font-mono text-[11px] text-muted-foreground" title={value.sourcePath}>
                {value.sourcePath}
              </p>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
