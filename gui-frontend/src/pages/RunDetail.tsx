import { Fragment, useEffect, useMemo, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip as ChartTooltip,
} from "recharts"
import {
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  Copy,
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
  type TaskRow,
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

      <ConvergenceCharts run={run} />

      {run.ablation?.groups?.length ? <AblationCard groups={run.ablation.groups} /> : null}

      {run.config && <ConfigCard config={run.config} taskCount={run.task_count} />}
    </div>
  )
}

/* ---------- convergence + uplift small charts ----------
   Rendered only when their data exists on disk: repeats derive from the task
   rows (k-th occurrence of a (task, variant) pair = repeat k), uplift comes
   straight from instruction_ablation_summary.json. Colors reuse the console's
   chart/status tokens (same jobs they already do in Dashboard and the
   ablation table: one hue for magnitude, pass/fail only for polarity). */

interface RepeatPoint {
  repeat: number
  rate: number | null
  passed: number
  judged: number
}

function buildRepeatSeries(tasks: TaskRow[]): RepeatPoint[] | null {
  const occurrence = new Map<string, number>()
  const buckets = new Map<number, { judged: number; passed: number }>()
  let maxRepeat = 1
  for (const task of tasks) {
    const key = `${task.task_id ?? task.run_task_id}::${task.instruction_variant ?? ""}`
    const repeat = (occurrence.get(key) ?? 0) + 1
    occurrence.set(key, repeat)
    maxRepeat = Math.max(maxRepeat, repeat)
    const cell = task.judges.single
    if (!cell || cell.overall_pass === null || cell.overall_pass === undefined) continue
    const bucket = buckets.get(repeat) ?? { judged: 0, passed: 0 }
    bucket.judged += 1
    if (cell.overall_pass) bucket.passed += 1
    buckets.set(repeat, bucket)
  }
  if (maxRepeat < 2) return null
  return Array.from({ length: maxRepeat }, (_, index) => {
    const bucket = buckets.get(index + 1)
    return {
      repeat: index + 1,
      rate: bucket && bucket.judged ? (bucket.passed / bucket.judged) * 100 : null,
      passed: bucket?.passed ?? 0,
      judged: bucket?.judged ?? 0,
    }
  })
}

interface UpliftRow {
  label: string
  delta: number
  rate: number | null
  baseline: number | null
}

function buildUpliftRows(run: RunDetailData): UpliftRow[] {
  const groups = run.ablation?.groups ?? []
  const judgeModes = new Set(groups.map((group) => group.judge_mode))
  const baselines = new Map(
    groups
      .filter((group) => group.instruction_variant === "baseline")
      .map((group) => [`${group.task_id}::${group.judge_mode}`, group.overall_pass_rate]),
  )
  return groups
    .filter(
      (group) =>
        group.instruction_variant !== "baseline" &&
        group.delta_vs_baseline?.overall_pass_rate_delta !== null &&
        group.delta_vs_baseline?.overall_pass_rate_delta !== undefined,
    )
    .map((group) => ({
      label:
        `${group.task_id} · ${group.instruction_variant}` +
        (judgeModes.size > 1 ? ` · ${group.judge_mode}` : ""),
      delta: (group.delta_vs_baseline!.overall_pass_rate_delta as number) * 100,
      rate: group.overall_pass_rate,
      baseline: baselines.get(`${group.task_id}::${group.judge_mode}`) ?? null,
    }))
}

const CHART_TOOLTIP_STYLE = {
  borderRadius: 8,
  border: "1px solid var(--border)",
  fontSize: 12,
} as const

function ConvergenceCharts({ run }: { run: RunDetailData }) {
  const repeatSeries = useMemo(() => buildRepeatSeries(run.tasks), [run.tasks])
  const upliftRows = useMemo(() => buildUpliftRows(run), [run])
  if (!repeatSeries && !upliftRows.length) return null
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {repeatSeries && (
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Repeat pass rate</CardTitle>
            <CardDescription>
              Single-judge pass rate at each repeat of the same (task, variant)
            </CardDescription>
          </CardHeader>
          <CardContent className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={repeatSeries} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="repeat"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={(value: number) => `#${value}`}
                />
                <YAxis
                  domain={[0, 100]}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={(value: number) => `${value}%`}
                />
                <ChartTooltip
                  contentStyle={CHART_TOOLTIP_STYLE}
                  formatter={(value, _name, item) => {
                    const point = item?.payload as RepeatPoint | undefined
                    const detail = point ? ` (${point.passed}/${point.judged} tasks)` : ""
                    return [
                      typeof value === "number" ? `${value.toFixed(0)}%${detail}` : "not judged",
                      "pass rate",
                    ]
                  }}
                  labelFormatter={(value) => `Repeat #${value}`}
                />
                <Line
                  dataKey="rate"
                  stroke="var(--chart-1)"
                  strokeWidth={2}
                  dot={{ r: 4, fill: "var(--chart-1)", strokeWidth: 0 }}
                  connectNulls={false}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
      {upliftRows.length > 0 && (
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Instruction uplift</CardTitle>
            <CardDescription>
              Overall pass-rate delta vs baseline, in percentage points ·{" "}
              <span className="text-pass-ink">green</span> = uplift,{" "}
              <span className="text-fail-ink">red</span> = regression
            </CardDescription>
          </CardHeader>
          <CardContent style={{ height: Math.max(120, 40 + upliftRows.length * 36) }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                layout="vertical"
                data={upliftRows}
                margin={{ top: 4, right: 16, bottom: 0, left: 8 }}
              >
                <CartesianGrid horizontal={false} stroke="var(--border)" />
                <XAxis
                  type="number"
                  domain={[-100, 100]}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={(value: number) => `${value > 0 ? "+" : ""}${value}pp`}
                />
                <YAxis
                  type="category"
                  dataKey="label"
                  width={170}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                  tickFormatter={(value: string) =>
                    value.length > 24 ? `…${value.slice(-23)}` : value
                  }
                />
                <ReferenceLine x={0} stroke="var(--muted-foreground)" />
                <ChartTooltip
                  cursor={{ fill: "var(--muted)" }}
                  contentStyle={CHART_TOOLTIP_STYLE}
                  formatter={(value, _name, item) => {
                    const row = item?.payload as UpliftRow | undefined
                    const context =
                      row && row.rate !== null && row.baseline !== null
                        ? ` (${fmtRate(row.baseline)} → ${fmtRate(row.rate)})`
                        : ""
                    const delta = typeof value === "number" ? value : Number(value ?? 0)
                    return [`${delta > 0 ? "+" : ""}${delta.toFixed(1)}pp${context}`, "Δ overall pass"]
                  }}
                />
                <Bar dataKey="delta" maxBarSize={20} radius={4} isAnimationActive={false}>
                  {upliftRows.map((row) => (
                    <Cell
                      key={row.label}
                      fill={row.delta > 0 ? "var(--pass)" : row.delta < 0 ? "var(--fail)" : "var(--muted-foreground)"}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}
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

/* ---------- Run configuration → measurement recipe ----------
   The launcher writes ~34 flat keys per run. As an alphabetical env dump they
   make every run look identical; the operator's real question is "what did this
   run measure, and how". So the card leads with a one-line recipe, then groups
   the keys by the role each plays — who executed, what judged, what varied, what
   pins a rerun. Keys stay literal (mono, lower-case, grep-able) and the complete
   raw config is one click away: the file system is still the truth. */

type ConfigGroupId = "executor" | "judge" | "variables" | "repro"

const CONFIG_GROUPS: { id: ConfigGroupId; label: string; gloss: string }[] = [
  { id: "executor", label: "Executor", gloss: "how tasks were run" },
  { id: "judge", label: "Judge", gloss: "how outputs were scored" },
  { id: "variables", label: "Variables", gloss: "what changed across tasks" },
  { id: "repro", label: "Reproducibility", gloss: "what pins an exact rerun" },
]

// task_order duplicates the task table above and can run long; keep it to Raw.
const CONFIG_SKIP = new Set(["task_order"])

/* First match wins; every non-skipped key lands in exactly one group. Anything
   unrecognized (a future launcher flag) falls through to Reproducibility and is
   always visible under Raw, so no key is silently dropped. */
function classifyConfigKey(key: string): ConfigGroupId {
  if (
    key === "run_id" ||
    key === "seed" ||
    key === "docker_image" ||
    key === "claude_thinking_effort"
  )
    return "repro"
  if (key.endsWith("_bin")) return "repro"
  if (key.startsWith("requested_")) return "variables"
  if (key.startsWith("evaluator_") || key === "judge_mode" || key === "max_evaluator_parallel")
    return "judge"
  if (key.startsWith("instruction_") || key.startsWith("rigor_") || key === "batch_size")
    return "variables"
  if (key.startsWith("executor_") || key === "auth_mode") return "executor"
  if (
    key.endsWith("_base_url") ||
    key.endsWith("_provider") ||
    key.endsWith("_api_key_env") ||
    key.endsWith("_api_key") ||
    key.endsWith("_endpoint")
  )
    return "executor"
  return "repro"
}

// A value is "empty" when it carries no measurement decision: null, [], "", or
// the literal sentinels the launcher writes for an unset flag ("-", "none").
function isEmptyConfigValue(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (Array.isArray(value)) return value.length === 0
  if (typeof value === "string") {
    const v = value.trim().toLowerCase()
    return v === "" || v === "-" || v === "–" || v === "none" || v === "null"
  }
  return false
}

function formatConfigValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "–"
  if (Array.isArray(value)) return value.length ? value.join(", ") : "[]"
  return String(value)
}

/* One-line recipe. Each piece is emitted only when its source field is present,
   so a sparse config degrades to a shorter (still honest) line rather than
   inventing "none"/"-" placeholders. */
type CrossUnit =
  | { type: "agent"; prefix?: string; agent: string; model: string | null }
  | { type: "count"; value: number }
interface RecipeMeta {
  label: string
  value: string
}

function readConfigStr(config: Record<string, unknown>, key: string): string | null {
  const v = config[key]
  if (typeof v === "number") return String(v)
  if (typeof v === "string") {
    const t = v.trim()
    return t && t.toLowerCase() !== "none" ? t : null
  }
  return null
}

function buildRecipe(
  config: Record<string, unknown>,
  taskCount: number | null,
): { cross: CrossUnit[]; meta: RecipeMeta[]; text: string } | null {
  const cross: CrossUnit[] = []
  const executorAgent = readConfigStr(config, "executor_agent")
  if (executorAgent)
    cross.push({ type: "agent", agent: executorAgent, model: readConfigStr(config, "executor_model") })
  const orderLen = Array.isArray(config.task_order) ? config.task_order.length : null
  const count = taskCount ?? orderLen
  if (count !== null && count !== undefined) cross.push({ type: "count", value: count })
  const evaluatorAgent = readConfigStr(config, "evaluator_agent")
  if (evaluatorAgent)
    cross.push({
      type: "agent",
      prefix: "judge",
      agent: evaluatorAgent,
      model: readConfigStr(config, "evaluator_model"),
    })

  const meta: RecipeMeta[] = []
  const seed = readConfigStr(config, "seed")
  if (seed !== null) meta.push({ label: "seed", value: seed })
  const backend = readConfigStr(config, "executor_backend")
  if (backend) meta.push({ label: "", value: backend })

  if (!cross.length && !meta.length) return null

  const unitText = (u: CrossUnit) =>
    u.type === "count"
      ? `${u.value} task${u.value === 1 ? "" : "s"}`
      : `${u.prefix ? `${u.prefix} ` : ""}${u.agent}${u.model ? `(${u.model})` : ""}`
  const text =
    cross.map(unitText).join(" × ") +
    meta.map((m) => ` · ${m.label ? `${m.label} ` : ""}${m.value}`).join("")
  return { cross, meta, text }
}

function CopyRecipeButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => void (timer.current && clearTimeout(timer.current)), [])
  const onCopy = () => {
    const done = () => {
      setCopied(true)
      toast.success("Recipe copied")
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => setCopied(false), 1400)
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => toast.error("Copy failed"))
    } else {
      toast.error("Clipboard unavailable")
    }
  }
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      onClick={onCopy}
      aria-label={copied ? "Recipe copied" : "Copy recipe"}
      title="Copy recipe"
      className="shrink-0 text-muted-foreground hover:text-foreground"
    >
      {copied ? <Check className="text-pass-ink" /> : <Copy />}
    </Button>
  )
}

function ConfigGroup({
  label,
  gloss,
  rows,
  showEmpty,
}: {
  label: string
  gloss: string
  rows: [string, unknown][]
  showEmpty: boolean
}) {
  const visible = showEmpty ? rows : rows.filter(([, v]) => !isEmptyConfigValue(v))
  const hiddenEmpty = rows.length - visible.length
  return (
    <section className="min-w-0">
      <div className="mb-2.5 flex items-baseline gap-2 border-b border-border/70 pb-1.5">
        <h3 className="text-sm font-medium text-foreground">{label}</h3>
        <span className="text-xs text-muted-foreground">{gloss}</span>
      </div>
      {visible.length ? (
        <dl className="grid grid-cols-[minmax(0,max-content)_minmax(0,1fr)] gap-x-4 gap-y-1.5">
          {visible.map(([key, value]) => {
            const empty = isEmptyConfigValue(value)
            return (
              <Fragment key={key}>
                <dt className="font-mono text-[13px] leading-5 text-muted-foreground">{key}</dt>
                <dd
                  className={cn(
                    "min-w-0 break-all font-mono text-[13px] leading-5",
                    empty ? "text-muted-foreground" : "text-foreground",
                  )}
                >
                  {formatConfigValue(value)}
                </dd>
              </Fragment>
            )
          })}
        </dl>
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {hiddenEmpty ? `${hiddenEmpty} empty field${hiddenEmpty === 1 ? "" : "s"}` : "none set"}
        </p>
      )}
    </section>
  )
}

function RawConfig({ config }: { config: Record<string, unknown> }) {
  const entries = Object.entries(config).sort(([a], [b]) => a.localeCompare(b))
  return (
    <div className="mt-3 rounded-lg border border-border bg-muted/40 p-4">
      <dl className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-x-6 gap-y-2">
        {entries.map(([key, value]) => (
          <div key={key} className="min-w-0">
            <dt className="font-mono text-[11px] text-muted-foreground">{key}</dt>
            <dd className="break-all font-mono text-[13px] text-foreground">
              {formatConfigValue(value)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function ConfigCard({
  config,
  taskCount,
}: {
  config: Record<string, unknown>
  taskCount: number | null
}) {
  const [showEmpty, setShowEmpty] = useState(false)
  const [showRaw, setShowRaw] = useState(false)

  const { grouped, emptyTotal } = useMemo(() => {
    const grouped = new Map<ConfigGroupId, [string, unknown][]>(
      CONFIG_GROUPS.map((g) => [g.id, [] as [string, unknown][]]),
    )
    let emptyTotal = 0
    for (const [key, value] of Object.entries(config)) {
      if (CONFIG_SKIP.has(key)) continue
      grouped.get(classifyConfigKey(key))!.push([key, value])
      if (isEmptyConfigValue(value)) emptyTotal += 1
    }
    for (const rows of grouped.values()) rows.sort(([a], [b]) => a.localeCompare(b))
    return { grouped, emptyTotal }
  }, [config])

  const recipe = useMemo(() => buildRecipe(config, taskCount), [config, taskCount])
  const rawKeyCount = Object.keys(config).length

  return (
    <Collapsible defaultOpen>
      <Card className="gap-0 py-5">
        <div className="flex flex-col gap-3 px-6">
          <CollapsibleTrigger className="group flex items-center gap-2 self-start rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
            <CardTitle className="text-base">Run configuration</CardTitle>
            <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
          </CollapsibleTrigger>
          {recipe && (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 py-2.5 pl-3.5 pr-2">
              <code className="min-w-0 flex-1 break-words font-mono text-sm leading-6">
                {recipe.cross.map((u, i) => (
                  <Fragment key={i}>
                    {i > 0 && <span className="mx-1.5 text-muted-foreground/60">×</span>}
                    {u.type === "count" ? (
                      <span>
                        <span className="tabular-nums text-foreground">{u.value}</span>
                        <span className="text-muted-foreground"> task{u.value === 1 ? "" : "s"}</span>
                      </span>
                    ) : (
                      <span>
                        {u.prefix && <span className="text-muted-foreground">{u.prefix} </span>}
                        <span className="font-medium text-foreground">{u.agent}</span>
                        {u.model && <span className="text-muted-foreground">({u.model})</span>}
                      </span>
                    )}
                  </Fragment>
                ))}
                {recipe.meta.map((m, i) => (
                  <Fragment key={`m${i}`}>
                    <span className="mx-1.5 text-muted-foreground/60">·</span>
                    {m.label && <span className="text-muted-foreground">{m.label} </span>}
                    <span className="text-foreground">{m.value}</span>
                  </Fragment>
                ))}
              </code>
              <CopyRecipeButton text={recipe.text} />
            </div>
          )}
        </div>

        <CollapsibleContent>
          <CardContent className="pt-5">
            <div className="grid gap-x-10 gap-y-6 md:grid-cols-2">
              {CONFIG_GROUPS.map((group) => (
                <ConfigGroup
                  key={group.id}
                  label={group.label}
                  gloss={group.gloss}
                  rows={grouped.get(group.id)!}
                  showEmpty={showEmpty}
                />
              ))}
            </div>

            <div className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border/70 pt-3">
              {emptyTotal > 0 && (
                <button
                  type="button"
                  onClick={() => setShowEmpty((v) => !v)}
                  aria-expanded={showEmpty}
                  className="inline-flex items-center gap-1.5 rounded text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                >
                  <ChevronDown className={cn("size-3.5 transition-transform", showEmpty && "rotate-180")} />
                  {emptyTotal} empty field{emptyTotal === 1 ? "" : "s"}
                </button>
              )}
              <button
                type="button"
                onClick={() => setShowRaw((v) => !v)}
                aria-expanded={showRaw}
                className="inline-flex items-center gap-1.5 rounded text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              >
                <ChevronDown className={cn("size-3.5 transition-transform", showRaw && "rotate-180")} />
                Raw config · {rawKeyCount} keys
              </button>
            </div>

            {showRaw && <RawConfig config={config} />}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
