import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  AlertTriangle,
  CheckCircle2,
  Container,
  ExternalLink,
  Laptop,
  Pencil,
  Plus,
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
import { ErrorNote } from "@/pages/Dashboard"
import {
  api,
  type AgentTemplate,
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
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers })
  const templatesQuery = useQuery({
    queryKey: ["agent-templates"],
    queryFn: api.agentTemplates,
    staleTime: Infinity,
  })
  const [editing, setEditing] = useState<Draft | null>(null)
  const [isNew, setIsNew] = useState(false)

  if (agentsQuery.isPending) return <Skeleton className="h-96" />
  if (agentsQuery.isError) return <ErrorNote message={(agentsQuery.error as Error).message} />
  const payload = agentsQuery.data
  const providers = providersQuery.data?.providers ?? []
  const templates = templatesQuery.data?.templates ?? []

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
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Agents</h1>
          <p className="text-sm text-muted-foreground">
            The coding-agent CLIs that can compete or judge. Editable runtimes are{" "}
            <code className="font-mono text-xs">runtimes/&lt;id&gt;.json</code> specs shared
            with the CLI.
          </p>
        </div>
        <Button
          className="ml-auto"
          onClick={() => {
            setIsNew(true)
            setEditing(emptyDraft())
          }}
        >
          <Plus /> Add runtime
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {payload.builtin.map((agent) => (
          <BuiltinCard
            key={agent.id}
            agent={agent}
            providerCount={compatibleProviders(agent.id, providers).length}
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
            <CustomCard
              key={agent.id}
              agent={agent}
              providerCount={compatibleProviders(agent.id, providers, agent.protocol).length}
              onEdit={() => {
                setIsNew(false)
                setEditing(draftFromAgent(agent))
              }}
              onDelete={() => removeAgent(agent)}
            />
          ),
        )}
      </div>
      <p className="font-mono text-xs text-muted-foreground">
        spec runtimes: {payload.runtimes_dir}
      </p>

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
      />
    </div>
  )
}

function BuiltinCard({
  agent,
  providerCount,
}: {
  agent: BuiltinRuntime
  providerCount: number
}) {
  return (
    <Card className="py-4">
      <CardContent className="grid gap-2.5 px-4">
        <div className="flex items-center gap-2.5">
          <AgentIcon agent={agent.id} size={22} />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">{agent.label}</span>
          <CliBadge cli={agent.cli} />
        </div>
        <div className="grid gap-1 text-xs text-muted-foreground">
          <span>{agent.note}</span>
          <span>
            {PROTOCOL_LABELS[agent.protocol] ?? agent.protocol} ·{" "}
            {providerCount
              ? `${providerCount} provider${providerCount > 1 ? "s" : ""}`
              : "no provider configured"}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="outline" className="text-[11px]">
            built-in
          </Badge>
          {agent.docker_capable && (
            <Badge variant="outline" className="gap-1 text-[11px]" title={agent.docker_image}>
              <Container className="size-3" /> Docker
            </Badge>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function CustomCard({
  agent,
  providerCount,
  onEdit,
  onDelete,
}: {
  agent: CustomRuntime
  providerCount: number
  onEdit: () => void
  onDelete: () => void
}) {
  const commandLine = [agent.command, ...(agent.args ?? [])].join(" ")
  return (
    <Card className="py-4">
      <CardContent className="grid gap-2.5 px-4">
        <div className="flex items-center gap-2.5">
          <AgentIcon agent={agent.id} icon={agent.icon} size={22} />
          <span className="min-w-0 flex-1 truncate text-sm font-semibold">
            {agent.label ?? agent.spec_id}
          </span>
          <CliBadge cli={agent.cli} />
        </div>
        <div className="grid gap-1 text-xs text-muted-foreground">
          <span className="truncate font-mono" title={commandLine}>
            {commandLine}
          </span>
          <span>
            {PROTOCOL_LABELS[agent.protocol ?? "none"]}
            {agent.protocol !== "none" && agent.base_url_env
              ? ` via $${agent.base_url_env}`
              : ""}{" "}
            ·{" "}
            {agent.protocol === "none"
              ? "no provider needed"
              : providerCount
                ? `${providerCount} provider${providerCount > 1 ? "s" : ""}`
                : "no provider configured"}
          </span>
          <span>
            parser <code className="font-mono">{agent.parser}</code> · prompt via{" "}
            <code className="font-mono">
              {agent.prompt_via === "arg"
                ? agent.prompt_flag
                  ? `${agent.prompt_flag} <arg>`
                  : "positional arg"
                : "stdin"}
            </code>
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge
            variant="outline"
            className="font-mono text-[11px]"
            title={`CLI: --executor-agent ${agent.id}`}
          >
            {agent.spec_id}
          </Badge>
          {agent.docker_image ? (
            <Badge variant="outline" className="gap-1 text-[11px]" title={agent.docker_image}>
              <Container className="size-3" /> Docker
            </Badge>
          ) : (
            <Badge
              className="gap-1 border-transparent bg-warn-soft text-[11px] text-warn-ink"
              title="No Docker image in this spec — tasks execute directly on this machine, without container isolation."
            >
              <Laptop className="size-3" /> local execution
            </Badge>
          )}
          <div className="ml-auto flex gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              aria-label={`Edit ${agent.label ?? agent.spec_id}`}
              onClick={onEdit}
            >
              <Pencil className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="size-7 text-muted-foreground hover:text-fail-ink"
              aria-label={`Delete ${agent.label ?? agent.spec_id}`}
              onClick={onDelete}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function CliBadge({ cli }: { cli?: { bin: string; present: boolean; path: string | null } }) {
  if (!cli) return null
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
}: {
  draft: Draft | null
  isNew: boolean
  templates: AgentTemplate[]
  onClose: () => void
  onSave: (draft: Draft) => void
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
            spec the CLI reads. Verify flags against the installed CLI's --help; they drift
            between versions.
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

            <div className="flex justify-end gap-2 border-t pt-4">
              <Button variant="outline" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={() => onSave(value)}>
                <CheckCircle2 /> Save runtime
              </Button>
            </div>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
