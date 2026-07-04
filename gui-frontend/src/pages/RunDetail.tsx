import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ChevronDown, OctagonX } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  ExecBadge,
  StatusBadge,
  VariantBadge,
  VerdictBadge,
} from "@/components/verdict"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type RunDetail as RunDetailData } from "@/lib/api"
import { fmtDelta, fmtDuration, fmtRate, fmtTime, percent, spanBetween } from "@/lib/format"

export default function RunDetail() {
  const { runId = "" } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2500 : false),
  })
  const launchesQuery = useQuery({
    queryKey: ["launches"],
    queryFn: api.launches,
    enabled: runQuery.data?.status === "running",
    refetchInterval: 5000,
  })
  const stopMutation = useMutation({
    mutationFn: () => api.stop(runId),
    onSuccess: () => {
      toast.success(`Sent stop signal to ${runId}.`)
      queryClient.invalidateQueries({ queryKey: ["run", runId] })
    },
    onError: (error: Error) => toast.error(error.message),
  })

  if (runQuery.isPending) return <Skeleton className="h-96" />
  if (runQuery.isError) return <ErrorNote message={(runQuery.error as Error).message} />

  const run = runQuery.data
  const stoppable = launchesQuery.data?.launches.some(
    (launch) => launch.run_id === runId && launch.running,
  )
  const singleJudged = run.tasks.filter((task) => task.judges.single)
  const singlePassed = singleJudged.filter((task) => task.judges.single?.overall_pass)
  const hasParallel = run.tasks.some((task) => task.judges.parallel)
  const execDone =
    run.executor_stats.success + run.executor_stats.failed + run.executor_stats.timeout

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h1 className="break-all font-mono text-xl font-semibold tracking-tight">{run.run_id}</h1>
          <p className="text-sm text-muted-foreground">
            Started {fmtTime(run.started_at)} ·{" "}
            {spanBetween(run.started_at, run.ended_at, run.status === "running")} ·{" "}
            {describeConfig(run)}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <StatusBadge status={run.status} />
          {stoppable && (
            <Button
              variant="outline"
              size="sm"
              className="text-fail-ink hover:bg-fail-soft"
              disabled={stopMutation.isPending}
              onClick={() => stopMutation.mutate()}
            >
              <OctagonX /> Stop run
            </Button>
          )}
        </div>
      </div>

      {run.status === "running" && run.progress && <ProgressCard progress={run.progress} />}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <SummaryCard
          label="Tasks passed"
          value={
            singleJudged.length ? `${singlePassed.length}/${singleJudged.length}` : "–"
          }
          hint={
            singleJudged.length
              ? `${fmtRate(percent(singlePassed.length, singleJudged.length))} single-judge pass rate`
              : "no judge results yet"
          }
          progress={percent(singlePassed.length, singleJudged.length)}
        />
        <SummaryCard
          label="Executors"
          value={`${run.executor_stats.success}/${execDone || run.task_count}`}
          hint={[
            run.executor_stats.failed ? `${run.executor_stats.failed} failed` : null,
            run.executor_stats.timeout ? `${run.executor_stats.timeout} timeout` : null,
            run.executor_stats.pending ? `${run.executor_stats.pending} pending` : null,
          ]
            .filter(Boolean)
            .join(" · ") || "all succeeded"}
          progress={percent(run.executor_stats.success, execDone || run.task_count)}
        />
        <SummaryCard
          label="Executor"
          value={run.executor_agent ?? "–"}
          hint={run.executor_model ?? "model not recorded"}
          mono
        />
        <SummaryCard
          label="Evaluator"
          value={run.evaluator_agent ?? "–"}
          hint={`${run.evaluator_model ?? "model not recorded"} · ${run.judge_mode ?? "?"} judge`}
          mono
        />
      </div>

      <Card className="overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead>Task run</TableHead>
              <TableHead>Variant</TableHead>
              <TableHead>Executor</TableHead>
              <TableHead>Time</TableHead>
              <TableHead>Single judge</TableHead>
              {hasParallel && <TableHead>Parallel judge</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {run.tasks.length ? (
              run.tasks.map((task) => (
                <TableRow
                  key={task.run_task_id}
                  tabIndex={0}
                  className="cursor-pointer"
                  onClick={() =>
                    navigate(
                      `/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(
                        task.run_task_id,
                      )}`,
                    )
                  }
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      navigate(
                        `/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(
                          task.run_task_id,
                        )}`,
                      )
                    }
                  }}
                >
                  <TableCell>
                    <div className="font-mono text-sm font-medium">{task.run_task_id}</div>
                    {task.task_id && (
                      <div className="text-xs text-muted-foreground">{task.task_id}</div>
                    )}
                  </TableCell>
                  <TableCell>
                    <VariantBadge variant={task.instruction_variant} />
                  </TableCell>
                  <TableCell>
                    <ExecBadge status={task.executor_status} timedOut={task.executor_timed_out} />
                  </TableCell>
                  <TableCell className="font-mono text-sm tabular-nums text-muted-foreground">
                    {fmtDuration(task.executor_duration_seconds)}
                  </TableCell>
                  <TableCell>
                    <VerdictBadge cell={task.judges.single} />
                  </TableCell>
                  {hasParallel && (
                    <TableCell>
                      <VerdictBadge cell={task.judges.parallel} />
                    </TableCell>
                  )}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center text-muted-foreground">
                  No task runs on disk yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      {run.ablation?.groups?.length ? <AblationCard groups={run.ablation.groups} /> : null}

      {run.config && <ConfigCard config={run.config} />}
    </div>
  )
}

function describeConfig(run: RunDetailData): string {
  const bits = [
    run.executor_backend && `${run.executor_backend} backend`,
    run.seed !== null && run.seed !== undefined && `seed ${run.seed}`,
    run.instruction_mode && run.instruction_mode !== "none" && `${run.instruction_mode} instructions`,
  ].filter(Boolean)
  return bits.join(" · ")
}

function SummaryCard({
  label,
  value,
  hint,
  progress,
  mono,
}: {
  label: string
  value: string
  hint: string
  progress?: number | null
  mono?: boolean
}) {
  return (
    <Card>
      <CardContent className="grid gap-1.5">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div
          className={
            mono
              ? "truncate font-mono text-xl font-semibold tracking-tight"
              : "text-2xl font-semibold tabular-nums tracking-tight"
          }
        >
          {value}
        </div>
        {progress !== undefined && progress !== null && (
          <Progress value={progress * 100} className="h-1.5" />
        )}
        <div className="truncate text-xs text-muted-foreground">{hint}</div>
      </CardContent>
    </Card>
  )
}

function ProgressCard({
  progress,
}: {
  progress: NonNullable<RunDetailData["progress"]>
}) {
  return (
    <Card className="border-live-ink/25 bg-live-soft/40">
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <ProgressLane
          label="Executors"
          done={progress.executor_done}
          total={progress.totals.executors}
          stats={progress.executor_stats}
        />
        <ProgressLane
          label="Evaluators"
          done={progress.evaluator_done}
          total={progress.totals.evaluators}
          stats={progress.evaluator_stats}
        />
        {progress.active_executors.length > 0 && (
          <div className="sm:col-span-2">
            <div className="text-xs uppercase tracking-wide text-muted-foreground">Active now</div>
            <div className="mt-1 font-mono text-sm">{progress.active_executors.join("  ·  ")}</div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function ProgressLane({
  label,
  done,
  total,
  stats,
}: {
  label: string
  done: number
  total: number
  stats: { success: number; failed: number; timeout: number }
}) {
  const statBits = [
    stats.success ? `${stats.success} success` : null,
    stats.failed ? `${stats.failed} failed` : null,
    stats.timeout ? `${stats.timeout} timeout` : null,
  ]
    .filter(Boolean)
    .join(" · ")
  return (
    <div className="grid gap-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono tabular-nums">
          {done}/{total || "?"}
          {statBits && <span className="ml-2 text-xs text-muted-foreground">{statBits}</span>}
        </span>
      </div>
      <Progress value={total ? (done / total) * 100 : undefined} className="h-2" />
    </div>
  )
}

function AblationCard({
  groups,
}: {
  groups: NonNullable<RunDetailData["ablation"]>["groups"]
}) {
  return (
    <Card className="gap-0 overflow-hidden pb-0">
      <CardHeader className="pb-4">
        <CardTitle>Instruction ablation</CardTitle>
        <CardDescription>
          Uplift of each instruction variant against the baseline variant
        </CardDescription>
      </CardHeader>
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50 hover:bg-muted/50">
            <TableHead>Task</TableHead>
            <TableHead>Variant</TableHead>
            <TableHead>Judge</TableHead>
            <TableHead className="text-right">Runs</TableHead>
            <TableHead className="text-right">Overall pass</TableHead>
            <TableHead className="text-right">Rubric pass</TableHead>
            <TableHead className="text-right">Δ overall</TableHead>
            <TableHead className="text-right">Δ rubric</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {groups.map((group) => {
            const delta = group.delta_vs_baseline
            return (
              <TableRow key={`${group.task_id}-${group.judge_mode}-${group.instruction_variant}`}>
                <TableCell className="text-sm">{group.task_id}</TableCell>
                <TableCell className="font-mono text-sm">{group.instruction_variant}</TableCell>
                <TableCell className="text-sm text-muted-foreground">{group.judge_mode}</TableCell>
                <TableCell className="text-right font-mono text-sm tabular-nums">
                  {group.runs}
                </TableCell>
                <TableCell className="text-right font-mono text-sm tabular-nums">
                  {fmtRate(group.overall_pass_rate)}
                </TableCell>
                <TableCell className="text-right font-mono text-sm tabular-nums">
                  {fmtRate(group.mean_rubric_pass_rate)}
                </TableCell>
                <DeltaCell value={delta?.overall_pass_rate_delta} />
                <DeltaCell value={delta?.mean_rubric_pass_rate_delta} />
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </Card>
  )
}

function DeltaCell({ value }: { value: number | null | undefined }) {
  const color =
    value === null || value === undefined
      ? "text-muted-foreground"
      : value > 0
        ? "text-pass-ink"
        : value < 0
          ? "text-fail-ink"
          : "text-muted-foreground"
  return (
    <TableCell className={`text-right font-mono text-sm tabular-nums ${color}`}>
      {fmtDelta(value)}
    </TableCell>
  )
}

function ConfigCard({ config }: { config: Record<string, unknown> }) {
  const skip = new Set(["instruction_variants", "task_order"])
  const entries = Object.entries(config).filter(([key]) => !skip.has(key))
  return (
    <Collapsible>
      <Card className="gap-3">
        <CollapsibleTrigger className="group flex w-full items-center gap-2 px-6 text-left">
          <CardTitle className="text-base">Run configuration</CardTitle>
          <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent>
            <dl className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-6 gap-y-3">
              {entries.map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="text-xs uppercase tracking-wide text-muted-foreground">{key}</dt>
                  <dd className="break-all font-mono text-sm">
                    {Array.isArray(value)
                      ? value.length
                        ? value.join(", ")
                        : "[]"
                      : value === null || value === ""
                        ? "–"
                        : String(value)}
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
