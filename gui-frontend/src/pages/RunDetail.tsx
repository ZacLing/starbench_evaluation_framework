import { useEffect, useRef } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  LoaderCircle,
  OctagonX,
  Scale,
  XCircle,
} from "lucide-react"
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
import {
  api,
  type RunDetail as RunDetailData,
  type RunLiveCurrent,
  type RunLiveEta,
  type RunLivePayload,
  type RunLiveState,
  type RunLiveTask,
} from "@/lib/api"
import { cn } from "@/lib/utils"
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
  const liveQuery = useQuery({
    queryKey: ["runLive", runId],
    queryFn: () => api.runLive(runId),
    enabled: runQuery.data?.status === "running",
    refetchInterval: 4000,
  })
  // When the live poll sees the run leave "running", refresh the static detail
  // (and the runs list) so the page settles into its final state.
  const liveStatus = liveQuery.data?.status
  useEffect(() => {
    if (liveStatus && liveStatus !== "running") {
      queryClient.invalidateQueries({ queryKey: ["run", runId] })
      queryClient.invalidateQueries({ queryKey: ["runs"] })
    }
  }, [liveStatus, queryClient, runId])
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

      {run.status === "running" && liveQuery.data?.status === "running" && (
        <LiveProgressCard runId={runId} live={liveQuery.data} />
      )}

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

/* Live mode — only rendered while the run is "running". Every lane speaks
   through three channels (glyph + color + word), never color alone. */

const LANE_STYLES: Record<
  RunLiveState,
  { label: string; icon: typeof Circle; card: string; ink: string }
> = {
  pending: {
    label: "Pending",
    icon: Circle,
    card: "border-dashed border-border bg-muted/30",
    ink: "text-muted-foreground",
  },
  executing: {
    label: "Executing",
    icon: LoaderCircle,
    card: "border-live-ink/40 bg-live-soft",
    ink: "text-live-ink",
  },
  judging: {
    label: "Judging",
    icon: Scale,
    card: "border-warn-ink/40 bg-warn-soft",
    ink: "text-warn-ink",
  },
  done: {
    label: "Done",
    icon: CheckCircle2,
    card: "border-pass-ink/30 bg-pass-soft",
    ink: "text-pass-ink",
  },
  failed: {
    label: "Failed",
    icon: XCircle,
    card: "border-fail-ink/40 bg-fail-soft",
    ink: "text-fail-ink",
  },
}

function LiveProgressCard({ runId, live }: { runId: string; live: RunLivePayload }) {
  const navigate = useNavigate()
  return (
    <Card className="min-w-0 border-live-ink/25">
      <CardContent className="grid gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">
            Live task progress
          </div>
          <EtaLine eta={live.eta} />
        </div>
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {live.tasks.map((lane) => (
            <LaneCell
              key={lane.run_task_id}
              lane={lane}
              onOpen={() =>
                navigate(
                  `/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(
                    lane.run_task_id,
                  )}`,
                )
              }
            />
          ))}
        </div>
        {live.current && <ExecutingNow runId={runId} current={live.current} />}
      </CardContent>
    </Card>
  )
}

function LaneCell({ lane, onOpen }: { lane: RunLiveTask; onOpen: () => void }) {
  const style = LANE_STYLES[lane.state]
  const Icon = style.icon
  const label =
    lane.state === "failed" && lane.executor_status === "timeout" ? "Timeout" : style.label
  // Pending lanes have no task directory on disk yet — nothing to open.
  const clickable = lane.state !== "pending"
  const timing =
    lane.executor_seconds === null || lane.executor_seconds === undefined
      ? null
      : lane.executor_seconds_source === "elapsed"
        ? `${fmtDuration(lane.executor_seconds)} so far`
        : fmtDuration(lane.executor_seconds)
  const body = (
    <>
      <span className={cn("flex items-center gap-1 text-xs font-medium", style.ink)}>
        <Icon
          className={cn("size-3 shrink-0", lane.state === "executing" && "animate-spin")}
          aria-hidden
        />
        {label}
      </span>
      <span className="w-full truncate font-mono text-[11px] text-muted-foreground">
        {lane.run_task_id}
      </span>
      <span className="text-[11px] tabular-nums text-muted-foreground">
        {timing ?? " "}
      </span>
    </>
  )
  const className = cn(
    "flex w-36 shrink-0 flex-col items-start gap-0.5 rounded-md border px-2.5 py-2 text-left",
    style.card,
  )
  if (!clickable) {
    return (
      <div className={className} title={`${lane.run_task_id} — ${label} (not started yet)`}>
        {body}
      </div>
    )
  }
  return (
    <button
      type="button"
      onClick={onOpen}
      title={`${lane.run_task_id} — ${label}`}
      className={cn(
        className,
        "cursor-pointer transition-shadow hover:ring-2 hover:ring-ring/40 focus-visible:ring-2 focus-visible:ring-ring",
      )}
    >
      {body}
    </button>
  )
}

function EtaLine({ eta }: { eta: RunLiveEta }) {
  if (eta.estimated_remaining_seconds === null) {
    return (
      <p className="text-xs text-muted-foreground">
        Estimating time remaining… (needs at least 2 completed tasks)
      </p>
    )
  }
  return (
    <p className="text-xs text-muted-foreground">
      ~{fmtDuration(eta.estimated_remaining_seconds)} remaining · estimate from{" "}
      {eta.completed_sample_count} completed task{eta.completed_sample_count === 1 ? "" : "s"} ×{" "}
      {eta.remaining_task_count} left
    </p>
  )
}

function ExecutingNow({ runId, current }: { runId: string; current: RunLiveCurrent }) {
  const navigate = useNavigate()
  const scrollRef = useRef<HTMLDivElement>(null)
  // Keep the newest event in view as the tail grows.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [current.events])
  return (
    <div className="grid min-w-0 gap-1.5">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="shrink-0 text-xs uppercase tracking-wide text-muted-foreground">
          Executing now
        </span>
        <button
          type="button"
          className="min-w-0 max-w-full truncate font-mono text-sm font-medium hover:underline"
          title={current.run_task_id}
          onClick={() =>
            navigate(
              `/runs/${encodeURIComponent(runId)}/tasks/${encodeURIComponent(
                current.run_task_id,
              )}`,
            )
          }
        >
          {current.run_task_id}
        </button>
        {current.elapsed_seconds !== null && current.elapsed_seconds !== undefined && (
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            running {fmtDuration(current.elapsed_seconds)}
          </span>
        )}
      </div>
      {current.events.length ? (
        <div
          ref={scrollRef}
          className="max-h-56 overflow-auto rounded-md border bg-muted/30 p-2"
        >
          {current.events.map((event, index) => (
            <div
              key={index}
              className="flex gap-2 whitespace-nowrap font-mono text-xs leading-5"
            >
              <span className="shrink-0 text-muted-foreground">{event.type}</span>
              <span>{event.summary || "–"}</span>
            </div>
          ))}
          <p className="mt-1 text-[11px] font-sans text-muted-foreground">
            Last {current.events.length} events, summarized · newest at the bottom
          </p>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No events on disk for this task yet.</p>
      )}
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
