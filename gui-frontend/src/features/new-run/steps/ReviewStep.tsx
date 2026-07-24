import { AlertTriangle, ChevronDown, Loader2, PencilLine, Plus, Save } from "lucide-react"
import { AgentIcon } from "@/components/brand"
import { useAgentCatalog } from "@/hooks/useAgentCatalog"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { SharedConfig } from "@/lib/api"
import { shortenPath } from "../helpers"
import { PreflightPanel } from "../PreflightPanel"
import type { ContenderDraft, PlanPreview, WizardMode } from "../types"

export function StepReview({
  expName,
  setExpName,
  taskCount,
  tasksDir,
  contenders,
  shared,
  plan,
  judgeConflicts,
  runtimeLabel,
  onPreflightBlocked,
  mode,
  profileName,
  profileRev,
  deviated,
  launching,
  savingProfile,
  onUpdateProfileLaunch,
  onSaveAsNewLaunch,
  onSaveConfigAsProfile,
}: {
  expName: string
  setExpName: (name: string) => void
  taskCount: number
  tasksDir: string
  contenders: ContenderDraft[]
  shared: Partial<SharedConfig>
  plan: PlanPreview
  judgeConflicts: number
  runtimeLabel: (runtime: string) => string
  onPreflightBlocked: (blocked: boolean) => void
  mode: WizardMode
  profileName: string | null
  profileRev: number | null
  deviated: boolean
  launching: boolean
  savingProfile: boolean
  onUpdateProfileLaunch: () => void
  onSaveAsNewLaunch: () => void
  onSaveConfigAsProfile: () => void
}) {
  const { agentLabel } = useAgentCatalog()
  const busy = launching || savingProfile
  const nextRev = profileRev !== null ? profileRev + 1 : null
  const repeat = Number(shared.repeat) || 1
  const planSkills = plan.plans?.[0]?.executor_skills ?? []
  // Prefer the backend's execution estimate (it accounts for the instruction
  // sweep's variant expansion); fall back to the simple product until the plan
  // preview returns.
  const estimate = plan.estimate
  const sweeps = estimate ? estimate.mode !== "none" : false
  const perContender = estimate?.per_contender ?? taskCount * repeat
  const totalExecutions = estimate?.total ?? perContender * contenders.length
  return (
    <div className="grid gap-4">
      {/* Contract provenance: what these runs will be attributed to on disk. */}
      {mode === "profile" && profileName && (
        <p className="text-[13px] leading-5 text-muted-foreground">
          Launching under <span className="font-medium text-foreground">{profileName}</span>
          {profileRev !== null && (
            <>
              <span className="text-border"> · </span>
              <span className="font-mono">rev {profileRev}</span>
            </>
          )}
        </p>
      )}
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
              {perContender} × {contenders.length}
            </span>
            <span className="text-xs text-muted-foreground">
              {sweeps ? "variant runs per agent" : "tasks per agent"} × agents ={" "}
              {totalExecutions} executions + judging
            </span>
            {estimate?.note && (
              <span className="max-w-xs text-[11px] text-muted-foreground">{estimate.note}</span>
            )}
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

      {sweeps && estimate && (
        <Card className="py-4">
          <CardContent className="grid gap-2 px-4">
            <span className="text-xs font-semibold text-muted-foreground">
              Instruction sweep
            </span>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="text-[11px] capitalize text-muted-foreground">
                {estimate.mode}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {perContender} variant run{perContender === 1 ? "" : "s"} per agent
                {(shared.instruction_steps?.length ?? 0) > 0
                  ? ` · steps ${shared.instruction_steps?.join(", ")}`
                  : ""}
              </span>
            </div>
            {estimate.note && (
              <span className="text-[11px] text-muted-foreground">{estimate.note}</span>
            )}
          </CardContent>
        </Card>
      )}

      {String(shared.rigor_mode ?? "none") === "select" &&
        (shared.rigors?.length ?? 0) > 0 && (
          <Card className="py-4">
            <CardContent className="grid gap-2 px-4">
              <span className="text-xs font-semibold text-muted-foreground">
                Rigor requirements
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="text-[11px] text-muted-foreground">
                  {shared.rigors?.length} requirement
                  {(shared.rigors?.length ?? 0) === 1 ? "" : "s"}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  restated in every agent's prompt · {shared.rigors?.join(", ")}
                </span>
              </div>
              <span className="text-[11px] text-muted-foreground">
                Controlled experiment — not part of the default benchmark score.
              </span>
            </CardContent>
          </Card>
        )}

      {planSkills.length > 0 && (
        <Card className="py-4">
          <CardContent className="grid gap-2 px-4">
            <span className="text-xs font-semibold text-muted-foreground">
              Executor skills
            </span>
            <div className="flex flex-wrap gap-1.5">
              {planSkills.map((id) => (
                <Badge
                  key={id}
                  variant="outline"
                  className="font-mono text-[11px] text-muted-foreground"
                >
                  {id}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {judgeConflicts > 0 && (
        <Alert className="border-warn-ink/40 bg-warn-soft/60">
          <AlertTriangle className="size-4" />
          <AlertTitle>Self-grading configuration</AlertTitle>
          <AlertDescription>
            The judge and an agent under test share the same model. Scores may be biased.
          </AlertDescription>
        </Alert>
      )}

      <PreflightPanel
        plans={plan.plans}
        runtimeLabel={runtimeLabel}
        onBlockedChange={onPreflightBlocked}
      />

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
                    {agentLabel(item.agent)}
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
                {item.warnings?.length ? (
                  <div className="grid gap-0.5">
                    {item.warnings.map((warning, index) => (
                      <span
                        key={index}
                        className="inline-flex items-start gap-1 text-xs text-warn-ink"
                      >
                        <AlertTriangle className="mt-0.5 size-3 shrink-0" /> {warning}
                      </span>
                    ))}
                  </div>
                ) : null}
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

      {/* Launch exits beyond the primary. Profile mode: the primary button is an
          ad-hoc test when the config deviates; these persist the deviation into
          the contract instead. Custom mode: capture the bare config as a
          reusable profile. */}
      {mode === "profile" && deviated && (
        <Card className="gap-0 border-warn-ink/30 bg-warn-soft/25 py-4">
          <CardContent className="grid gap-3 px-4">
            <div className="flex items-start gap-2.5">
              <PencilLine className="mt-0.5 size-4 shrink-0 text-warn-ink" aria-hidden />
              <div className="grid gap-1">
                <span className="text-sm font-medium">
                  This configuration deviates from {profileName}
                </span>
                <p className="max-w-prose text-[13px] leading-5 text-muted-foreground">
                  This launches an ad-hoc test: the deviation is recorded in the run&rsquo;s
                  snapshot but not saved to the profile. To make it the contract instead:
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2 pl-[26px]">
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !plan.plans}
                onClick={onUpdateProfileLaunch}
              >
                <Save />
                {profileRev !== null && nextRev !== null
                  ? `Update profile (rev ${profileRev}→${nextRev}) & launch`
                  : "Update profile & launch"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || !plan.plans}
                onClick={onSaveAsNewLaunch}
              >
                <Plus /> Save as new profile & launch
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {mode === "custom" && (
        <Card className="py-4">
          <CardContent className="flex flex-wrap items-center justify-between gap-3 px-4">
            <div className="grid min-w-0 gap-0.5">
              <span className="text-sm font-medium">Reuse this configuration?</span>
              <p className="text-[13px] leading-5 text-muted-foreground">
                Save it as a profile so future runs launch under the same contract.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              disabled={busy || !contenders.length}
              onClick={onSaveConfigAsProfile}
            >
              {savingProfile ? <Loader2 className="animate-spin" /> : <Save />} Save this
              configuration as a profile
            </Button>
          </CardContent>
        </Card>
      )}
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
        <span className="text-xs font-semibold text-muted-foreground">
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

/* ---------- task facts strip (steps 2-4) ---------- */

/* The wizard-wide answer to "can these tasks use the web / how long can they
   run": facts owned by the task packages, summarized where run configuration
   happens so nobody hunts for a switch that does not exist. */
