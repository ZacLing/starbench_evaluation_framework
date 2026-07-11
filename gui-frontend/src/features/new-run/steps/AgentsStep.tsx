import { ArrowRight, DownloadCloud, Loader2, Plus, Trash2 } from "lucide-react"
import { Link } from "react-router-dom"
import {
  AGENT_LABELS,
  AGENT_NOTES,
  AgentIcon,
  compatibleProviders,
} from "@/components/brand"
import { Hint } from "@/components/hint"
import { ProviderModelPicker } from "@/components/model-picker"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import type {
  AgentRuntimeStatus,
  AiProvider,
  CustomRuntime,
  ProviderFilter,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { BUILTIN_RUNTIMES } from "../constants"
import type { ContenderDraft, RuntimeOption } from "../types"

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

export function StepContenders({
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
    ...BUILTIN_RUNTIMES.map((runtime) => ({
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
                    <span className="text-[11px] text-warn-ink">
                      local execution — no Docker image, runs on this machine
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
          <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
            {thinkingChannel === "native_config" ? "native reasoning setting" : "prompt-level request"}
            <Hint>
              {thinkingChannel === "native_config"
                ? "Applied through the CLI's own reasoning switch (Claude Code --effort, Codex model_reasoning_effort, OpenCode --variant)."
                : "This runtime has no reasoning switch the runner controls; the effort is requested in the prompt."}
            </Hint>
          </span>
        </div>
      </CardContent>
    </Card>
  )
}

