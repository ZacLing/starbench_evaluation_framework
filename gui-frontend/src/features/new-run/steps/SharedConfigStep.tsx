import { useState, type Dispatch, type SetStateAction } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, ChevronDown, Save, Scale, SlidersHorizontal, Sparkles } from "lucide-react"
import { toast } from "sonner"
import { AGENT_LABELS, AgentIcon } from "@/components/brand"
import { CredentialStatus } from "@/components/credential-status"
import { ProviderModelPicker } from "@/components/model-picker"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
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
import {
  api,
  type AiProvider,
  type CustomRuntime,
  type Profile,
  type ProviderFilter,
  type SharedConfig,
  type SkillsPayload,
  type TaskPackage,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { BUILTIN_RUNTIMES, JUDGE_MODES, PER_FIELD_OPTIONS } from "../constants"
import { ExecutorSkillsBlock } from "./ExecutorSkillsBlock"
import { PromptAssistanceBlock } from "./PromptAssistanceBlock"

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
  return <CredentialStatus provider={provider} />
}

export function StepShared({
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
  setShared: Dispatch<SetStateAction<Partial<SharedConfig>>>
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
                      {BUILTIN_RUNTIMES.map((runtime) => (
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
