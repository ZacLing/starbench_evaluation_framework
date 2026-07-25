import { useEffect, useMemo, useRef, useState } from "react"
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
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Circle,
  Copy,
  LoaderCircle,
  OctagonX,
  PencilLine,
  Scale,
  TriangleAlert,
  XCircle,
} from "lucide-react"
import { AgentIcon } from "@/components/brand"
import { useAgentCatalog } from "@/hooks/useAgentCatalog"
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
import { ErrorNote } from "@/components/error-note"
import {
  api,
  type Profile,
  type ProfilesPayload,
  type RunDetail as RunDetailData,
  type RunLiveCurrent,
  type RunLiveEta,
  type RunLivePayload,
  type RunLiveState,
  type RunLiveTask,
  type TaskRow,
} from "@/lib/api"
import type { ProfileSnapshot } from "@/lib/api-types"
import { cn } from "@/lib/utils"
import { fmtDelta, fmtDuration, fmtRate, fmtRelative, fmtTime, percent, spanBetween } from "@/lib/format"

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
  // The measurement contract this run was launched under, if any. run_detail
  // carries it outside the hand-typed RunDetail interface; read it structurally.
  const snapshot =
    (runQuery.data as (RunDetailData & { profile_snapshot?: ProfileSnapshot | null }) | undefined)
      ?.profile_snapshot ?? null
  // Only fetch the live profiles when there is a snapshot to compare against —
  // the drift check ("has the contract moved on since launch?") needs both.
  const profilesQuery = useQuery({
    queryKey: ["profiles"],
    queryFn: api.profiles,
    enabled: Boolean(snapshot),
  })

  if (runQuery.isPending) return <Skeleton className="h-96" />
  if (runQuery.isError) return <ErrorNote message={(runQuery.error as Error).message} />

  const run = runQuery.data
  const stoppable = launchesQuery.data?.launches.some(
    (launch) => launch.run_id === runId && launch.running,
  )
  const singleJudged = run.tasks.filter(
    (task) => typeof task.judges.single?.overall_pass === "boolean",
  )
  const singlePassed = singleJudged.filter((task) => task.judges.single?.overall_pass)
  const singleInconclusive = run.tasks.filter(
    (task) => {
      const outcome = task.judges.single?.outcome
      return outcome === "inconclusive_judge" ||
        outcome === "inconclusive_executor" ||
        outcome === "invalid_task"
    },
  ).length
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

      {run.status === "interrupted" && (
        <InterruptionCard
          run={run}
          executed={execDone}
          judged={singleJudged.length}
          passed={singlePassed.length}
        />
      )}

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
              ? `${fmtRate(percent(singlePassed.length, singleJudged.length))} single-judge pass rate${singleInconclusive ? ` · ${singleInconclusive} inconclusive` : ""}`
              : singleInconclusive
                ? `${singleInconclusive} inconclusive · not scored`
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

      {run.config && (
        <ConfigCard
          config={run.config}
          taskCount={run.task_count}
          snapshot={snapshot}
          profiles={profilesQuery.data}
        />
      )}
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

/* The instrument narrates its own failure: when a run is interrupted, say
   what is known from disk (progress bounds, surviving run_state.json), how far
   the measurement got, and how to reproduce it. A status chip alone reads as
   the console shrugging. */
function InterruptionCard({
  run,
  executed,
  judged,
  passed,
}: {
  run: RunDetailData
  executed: number
  judged: number
  passed: number
}) {
  const info = run.interruption
  const supervision = info?.supervision ?? null
  const pending = run.executor_stats.pending
  const story = supervision?.heartbeat_at
    ? `The supervisor's last heartbeat was ${fmtTime(supervision.heartbeat_at)} (${fmtRelative(supervision.heartbeat_at)})${supervision.state ? ` in state "${supervision.state}"` : ""}; it never recorded completion.`
    : info?.last_event_at
      ? `The last progress event was written ${fmtTime(info.last_event_at)} (${fmtRelative(info.last_event_at)}); no supervision record survives on disk.`
      : "No progress events or supervision record survive on disk."
  return (
    <div className="flex items-start gap-3 rounded-lg border border-warn/40 bg-warn-soft px-4 py-3 text-sm text-warn-ink">
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="grid gap-1">
        <p className="font-medium">
          Interrupted — the run stopped before a summary was written.
          {info?.progress_finished
            ? " Its final progress event exists, but summarization never completed."
            : ""}
        </p>
        <p>{story}</p>
        <p>
          {executed} of {run.task_count} task{run.task_count === 1 ? "" : "s"} executed
          {pending ? ` (${pending} never started)` : ""} · {judged} judged · {passed} passed.
        </p>
        <p>
          A rerun reproduces this measurement exactly — the seed and roster are pinned under Run
          configuration below.
        </p>
      </div>
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
            <TableHead className="text-right">Valid / attempts</TableHead>
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
                  {group.attempts === undefined ? group.runs : `${group.runs}/${group.attempts}`}
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

/* ---------- Run configuration → measurement protocol ----------
   A run is physically a pipeline: a subject (the executor under test) works
   through a protocol (tasks, variables, seed) and an instrument (the judge)
   scores what comes out. The card renders that chain instead of enumerating
   launcher flags. Known keys are consumed explicitly by name into the three
   panels and the rerun pin strip; keys that belong to runtimes taking no part
   in this run stay in Raw only; anything unrecognized surfaces verbatim under
   "Other", so a future launcher flag can never be silently mis-filed. The
   complete raw dump stays one click away: the file system is still the truth. */

/* The launch wizard's plain-language credential vocabulary, reused verbatim. */
const AUTH_PHRASES: Record<string, string> = {
  env: "API key from env",
  global: "host CLI login",
  "copy-auth": "copied CLI login",
}

interface ProtoAttr {
  label: string
  value: string
  code?: string
}

interface ProtoParty {
  agent: string
  model: string | null
  attrs: ProtoAttr[]
}

interface ProtocolView {
  subject: ProtoParty | null
  instrument: ProtoParty | null
  taskCount: number | null
  batch: string | null
  variables: ProtoAttr[]
  pins: ProtoAttr[]
  other: [string, unknown][]
}

function buildProtocolView(
  config: Record<string, unknown>,
  taskCountProp: number | null,
  builtinIds: string[],
): ProtocolView {
  const consumed = new Set<string>()
  const raw = (key: string): unknown => {
    consumed.add(key)
    return config[key]
  }
  // Launcher sentinels for "unset" ("-", "none", "") read as absent.
  const str = (key: string): string | null => {
    const v = raw(key)
    if (typeof v === "number") return String(v)
    if (typeof v !== "string") return null
    const t = v.trim()
    if (!t || ["-", "–", "none", "null"].includes(t.toLowerCase())) return null
    return t
  }
  const ids = (key: string): string[] => {
    const v = raw(key)
    return Array.isArray(v) ? v.map(String).filter(Boolean) : []
  }

  const party = (role: "executor" | "evaluator"): ProtoParty | null => {
    const agent = str(`${role}_agent`)
    const model = str(`${role}_model`)
    const attrs: ProtoAttr[] = []
    const provider = agent ? str(`${agent}_provider`) : null
    const gatewayUrl = agent ? (str(`${agent}_base_url`) ?? str(`${agent}_endpoint`)) : null
    if (provider || gatewayUrl)
      attrs.push({
        label: "gateway",
        value: provider ?? "custom endpoint",
        code: gatewayUrl ?? undefined,
      })
    const envKey = agent ? str(`${agent}_api_key_env`) : null
    // Read both unconditionally: `??` short-circuiting would leave the legacy
    // top-level auth_mode unconsumed and it would leak into "Other".
    const roleMode = role === "executor" ? str("executor_auth_mode") : str("evaluator_auth_mode")
    const legacyMode = role === "executor" ? str("auth_mode") : null
    const mode = roleMode ?? legacyMode
    if (mode) {
      const phrase = AUTH_PHRASES[mode] ?? mode
      attrs.push(
        mode === "env" && envKey
          ? { label: "auth", value: phrase, code: envKey }
          : { label: "auth", value: phrase },
      )
    }
    if (role === "executor") {
      const backend = str("executor_backend")
      const docker = str("docker_image")
      if (backend)
        attrs.push(
          backend === "docker" && docker
            ? { label: "backend", value: backend, code: docker }
            : { label: "backend", value: backend },
        )
    } else {
      const judgeMode = str("judge_mode")
      if (judgeMode)
        attrs.push({
          label: "mode",
          value: judgeMode === "single" ? "single judge" : `${judgeMode} judges`,
        })
      const parallel = str("max_evaluator_parallel")
      if (parallel) attrs.push({ label: "parallel", value: `up to ${parallel} at once` })
    }
    if (agent === "claude") {
      const effort = str("claude_thinking_effort")
      if (effort) attrs.push({ label: "thinking", value: effort })
    }
    if (!agent && !model) return null
    return { agent: agent ?? "unknown", model, attrs }
  }

  const subject = party("executor")
  const instrument = party("evaluator")

  const order = raw("task_order")
  const taskCount = taskCountProp ?? (Array.isArray(order) ? order.length : null)
  const batch = str("batch_size")

  /* Variables render only when active; the inert launcher defaults they leave
     behind (instruction_step_order with mode none, executor_skill_order with
     no skills) are a deliberate Raw-only relegation, not an omission. */
  const variables: ProtoAttr[] = []
  const instructionMode = str("instruction_mode")
  const stepIds = ids("instruction_step_ids")
  const requestedSteps = ids("requested_instruction_step_ids")
  const stepOrder = str("instruction_step_order")
  const variantIds = ids("instruction_variants")
  if (instructionMode) {
    const detail = [
      stepIds.length
        ? `steps ${stepIds.join(", ")}`
        : requestedSteps.length
          ? `requested ${requestedSteps.join(", ")}`
          : null,
      stepOrder ? `order ${stepOrder}` : null,
      variantIds.length ? `variants ${variantIds.join(", ")}` : null,
    ]
      .filter(Boolean)
      .join(" · ")
    variables.push({ label: "instructions", value: instructionMode, code: detail || undefined })
  }
  const rigorMode = str("rigor_mode")
  const rigorIds = ids("requested_rigor_ids")
  if (rigorMode || rigorIds.length)
    variables.push({
      label: "rigor",
      value: rigorMode ?? "requested",
      code: rigorIds.length ? rigorIds.join(", ") : undefined,
    })
  const skillIds = ids("requested_executor_skill_ids")
  const skillGroups = ids("requested_executor_skill_groups")
  const skillOrder = str("executor_skill_order")
  if (skillIds.length || skillGroups.length)
    variables.push({
      label: "skills",
      value: [...skillGroups, ...skillIds].join(", "),
      code: skillOrder ? `order ${skillOrder}` : undefined,
    })

  /* Only the bins of runtimes that took part pin this run; the other three
     are launcher defaults with no bearing on a rerun (Raw keeps them all). */
  const pins: ProtoAttr[] = []
  const runId = str("run_id")
  if (runId) pins.push({ label: "run", value: runId })
  const seed = str("seed")
  if (seed !== null) pins.push({ label: "seed", value: seed })
  const participants = [subject?.agent, instrument?.agent].filter(
    (a, i, arr): a is string => Boolean(a) && arr.indexOf(a) === i,
  )
  for (const agent of participants) {
    const bin = str(`${agent}_bin`)
    if (bin) pins.push({ label: `${agent} bin`, value: bin })
  }

  const other = Object.entries(config)
    .filter(
      ([key]) =>
        !consumed.has(key) &&
        !builtinIds.some((agent) => key.startsWith(`${agent}_`)),
    )
    .sort(([a], [b]) => a.localeCompare(b))

  return { subject, instrument, taskCount, batch, variables, pins, other }
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

function PanelCaption({ caption, gloss }: { caption: string; gloss: string }) {
  return (
    <div className="mb-3 flex items-baseline gap-2 border-b border-border/70 pb-1.5">
      <h3 className="text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
        {caption}
      </h3>
      <span className="text-xs text-muted-foreground/80">{gloss}</span>
    </div>
  )
}

function AttrList({ attrs }: { attrs: ProtoAttr[] }) {
  if (!attrs.length) return null
  return (
    <dl className="mt-3 space-y-1.5">
      {attrs.map((attr) => (
        <div key={`${attr.label}:${attr.value}`} className="flex gap-3 text-[13px] leading-5">
          <dt className="w-16 shrink-0 text-muted-foreground">{attr.label}</dt>
          <dd className="min-w-0 text-foreground">
            {attr.value}
            {attr.code && (
              <>
                {" "}
                <code className="break-all font-mono text-xs text-muted-foreground">
                  {attr.code}
                </code>
              </>
            )}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function PartyPanel({
  caption,
  gloss,
  party,
}: {
  caption: string
  gloss: string
  party: ProtoParty | null
}) {
  const { agentLabel } = useAgentCatalog()
  return (
    <section className="min-w-0">
      <PanelCaption caption={caption} gloss={gloss} />
      {party ? (
        <>
          <div className="flex items-center gap-2.5">
            <AgentIcon agent={party.agent} size={22} />
            <div className="min-w-0">
              <div className="text-sm font-semibold leading-5 text-foreground">
                {agentLabel(party.agent)}
              </div>
              {party.model ? (
                <div
                  className="truncate font-mono text-[13px] leading-5 text-muted-foreground"
                  title={party.model}
                >
                  {party.model}
                </div>
              ) : (
                <div className="text-[13px] leading-5 text-muted-foreground">
                  model not recorded
                </div>
              )}
            </div>
          </div>
          <AttrList attrs={party.attrs} />
        </>
      ) : (
        <p className="text-[13px] text-muted-foreground">not recorded</p>
      )}
    </section>
  )
}

function ProtocolPanel({
  taskCount,
  batch,
  variables,
  repeat,
}: {
  taskCount: number | null
  batch: string | null
  variables: ProtoAttr[]
  repeat?: number | null
}) {
  const repeated = typeof repeat === "number" && repeat > 1
  return (
    <section className="min-w-0">
      <PanelCaption caption="Protocol" gloss="tasks and variables" />
      <div className="text-sm leading-5 text-foreground">
        {taskCount !== null ? (
          <>
            <span className="font-semibold tabular-nums">{taskCount}</span>
            <span> task{taskCount === 1 ? "" : "s"}</span>
          </>
        ) : (
          <span className="text-muted-foreground">task count not recorded</span>
        )}
        {batch && <span className="text-muted-foreground"> · batch {batch}</span>}
        {repeated && (
          <span className="font-medium text-foreground"> · ×{repeat} per task</span>
        )}
      </div>
      {repeated && (
        <p className="mt-1 text-[13px] leading-5 text-muted-foreground">
          Each task is sampled {repeat} times; under HSW a single pass is a sample, not a verdict.
        </p>
      )}
      {variables.length ? (
        <AttrList attrs={variables} />
      ) : (
        <div className="mt-3">
          <div className="text-[13px] font-medium leading-5 text-foreground">Baseline run</div>
          <p className="mt-0.5 text-[13px] leading-5 text-muted-foreground">
            No instruction variants, no rigor injection, no executor skills.
          </p>
        </div>
      )}
    </section>
  )
}

function FlowArrow() {
  return (
    <div aria-hidden="true" className="hidden self-center lg:block">
      <ArrowRight className="size-4 text-muted-foreground/60" />
    </div>
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

/* ---------- Measurement contract (profile snapshot) ----------
   When a run was launched from a profile with a roster, the runner writes a
   self-contained profile_snapshot.json: the contract as of launch. The three
   measurement panels then read the snapshot's structured fields in preference
   to the run_config keys (a bare run with no snapshot keeps the config path
   unchanged). The provenance line cites where the run came from; the drift
   check compares the snapshot's pinned rev against the profile as it stands
   now, because a profile is mutable and may have moved on since launch. */

interface SnapshotView {
  subject: ProtoParty
  instrument: ProtoParty
  taskCount: number | null
  batch: string | null
  variables: ProtoAttr[]
  repeat: number | null
}

function buildSnapshotView(snapshot: ProfileSnapshot, taskCountProp: number | null): SnapshotView {
  const contender = snapshot.contender
  const execution = snapshot.execution
  const subjectAttrs: ProtoAttr[] = []
  if (contender.provider_id || contender.base_url)
    subjectAttrs.push({
      label: "gateway",
      value: contender.provider_id ?? "custom endpoint",
      code: contender.base_url,
    })
  if (contender.auth_mode)
    subjectAttrs.push(
      contender.auth_mode === "env" && contender.api_key_env
        ? { label: "auth", value: AUTH_PHRASES[contender.auth_mode] ?? contender.auth_mode, code: contender.api_key_env }
        : { label: "auth", value: AUTH_PHRASES[contender.auth_mode] ?? contender.auth_mode },
    )
  if (execution.executor_backend)
    subjectAttrs.push({ label: "backend", value: execution.executor_backend })
  if (contender.thinking_effort)
    subjectAttrs.push({ label: "thinking", value: contender.thinking_effort })

  const inst = snapshot.instrument
  const instrumentAttrs: ProtoAttr[] = []
  if (inst.evaluator_auth_mode)
    instrumentAttrs.push({
      label: "auth",
      value: AUTH_PHRASES[inst.evaluator_auth_mode] ?? inst.evaluator_auth_mode,
    })
  if (inst.judge_mode)
    instrumentAttrs.push({
      label: "mode",
      value: inst.judge_mode === "single" ? "single judge" : `${inst.judge_mode} judges`,
    })
  if (typeof execution.max_evaluator_parallel === "number")
    instrumentAttrs.push({ label: "parallel", value: `up to ${execution.max_evaluator_parallel} at once` })
  if (typeof inst.evaluator_timeout_seconds === "number")
    instrumentAttrs.push({ label: "timeout", value: fmtDuration(inst.evaluator_timeout_seconds) })

  const taskIds = snapshot.task_set?.task_ids ?? []
  return {
    subject: { agent: contender.agent, model: contender.model || null, attrs: subjectAttrs },
    instrument: { agent: inst.evaluator_agent, model: inst.evaluator_model || null, attrs: instrumentAttrs },
    taskCount: taskIds.length || taskCountProp,
    batch: typeof execution.batch_size === "number" ? String(execution.batch_size) : null,
    variables: [],
    repeat: typeof execution.repeat === "number" ? execution.repeat : null,
  }
}

type Drift =
  | { kind: "unchanged" }
  | { kind: "moved"; fromRev: number; toRev: number; dimensions: string[] }
  | { kind: "gone" }

const DRIFT_DIMENSION_LABELS: Record<string, string> = {
  repeat: "repeat",
  roster: "roster",
  seed: "seed",
  batch_size: "batch size",
  judge_mode: "judge mode",
  evaluator_agent: "judge agent",
  evaluator_model: "judge model",
  evaluator_auth_mode: "judge auth",
  evaluator_timeout_seconds: "judge timeout",
  max_evaluator_parallel: "judge parallelism",
  executor_backend: "backend",
  executor_auth_mode: "executor auth",
}

function driftLabel(key: string): string {
  return DRIFT_DIMENSION_LABELS[key] ?? key.replace(/_/g, " ")
}

/* The snapshot pins the profile at its launch rev; the live profile may have a
   newer rev. A shallow compare of the shared fields (reconstructed from the
   snapshot's instrument + execution) plus the roster set names what moved.
   Fields the snapshot never captured are skipped, not reported as drift. */
function computeDrift(snapshot: ProfileSnapshot, profiles: ProfilesPayload | undefined): Drift | null {
  if (!profiles) return null
  const current = profiles.profiles.find((profile) => profile.id === snapshot.profile.id) as
    | (Profile & { rev?: number; roster?: { agent: string; model?: string }[] })
    | undefined
  if (!current) return { kind: "gone" }
  const toRev = typeof current.rev === "number" ? current.rev : snapshot.profile.rev
  if (toRev === snapshot.profile.rev) return { kind: "unchanged" }

  const dimensions: string[] = []
  const snapRoster = new Set(snapshot.roster.map((entry) => `${entry.agent}::${entry.model ?? ""}`))
  const curRoster = new Set((current.roster ?? []).map((entry) => `${entry.agent}::${entry.model ?? ""}`))
  const rosterSame =
    snapRoster.size === curRoster.size && [...snapRoster].every((key) => curRoster.has(key))
  if (!rosterSame) dimensions.push("roster")

  const snapShared: Record<string, unknown> = { ...snapshot.instrument, ...snapshot.execution }
  const curShared = (current.shared ?? {}) as Record<string, unknown>
  for (const key of Object.keys(curShared)) {
    const snapValue = snapShared[key]
    if (snapValue !== undefined && String(snapValue) !== String(curShared[key])) dimensions.push(key)
  }
  return { kind: "moved", fromRev: snapshot.profile.rev, toRev, dimensions }
}

function fmtCaptured(iso: string | null | undefined): string | null {
  if (!iso) return null
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function DriftChip({ drift }: { drift: Drift | null }) {
  if (!drift) return null
  if (drift.kind === "unchanged") {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Circle className="size-2 fill-current" aria-hidden />
        profile unchanged
      </span>
    )
  }
  const text =
    drift.kind === "gone"
      ? "profile no longer exists"
      : `profile has moved on: rev ${drift.fromRev} → ${drift.toRev}`
  const changed =
    drift.kind === "moved" && drift.dimensions.length
      ? drift.dimensions.map(driftLabel).join(", ")
      : null
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn-ink"
      title={changed ? `changed: ${changed}` : undefined}
    >
      <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
      {text}
      {changed && <span className="font-normal text-warn-ink/80">· {changed}</span>}
    </span>
  )
}

function ContractProvenance({
  snapshot,
  drift,
}: {
  snapshot: ProfileSnapshot
  drift: Drift | null
}) {
  const rosterIndex = snapshot.roster.findIndex(
    (entry) =>
      entry.agent === snapshot.contender.agent &&
      (entry.model ?? "") === (snapshot.contender.model ?? ""),
  )
  const contender =
    rosterIndex >= 0 && snapshot.roster.length
      ? `${rosterIndex + 1} of ${snapshot.roster.length}`
      : null
  const captured = fmtCaptured(snapshot.captured_at)
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
      <p className="text-[13px] leading-5 text-muted-foreground">
        Launched from profile{" "}
        <span className="font-medium text-foreground">{snapshot.profile.name}</span>
        <span className="text-border"> · </span>
        <span className="font-mono">rev {snapshot.profile.rev}</span>
        {contender && (
          <>
            <span className="text-border"> · </span>contender {contender}
          </>
        )}
        {captured && (
          <>
            <span className="text-border"> · </span>captured {captured}
          </>
        )}
      </p>
      {snapshot.modified && (
        <span
          className="inline-flex items-center gap-1.5 rounded-md bg-warn-soft px-2 py-0.5 text-xs font-medium text-warn-ink"
          title={
            snapshot.modified_fields?.length
              ? `Deviated from the profile at launch: ${snapshot.modified_fields.join(", ")}`
              : "Deviated from the profile at launch"
          }
        >
          <PencilLine className="size-3.5 shrink-0" aria-hidden />
          modified · ad-hoc test
        </span>
      )}
      <DriftChip drift={drift} />
    </div>
  )
}

function ConfigCard({
  config,
  taskCount,
  snapshot,
  profiles,
}: {
  config: Record<string, unknown>
  taskCount: number | null
  snapshot: ProfileSnapshot | null
  profiles: ProfilesPayload | undefined
}) {
  const [open, setOpen] = useState(true)
  const [showRaw, setShowRaw] = useState(false)
  const { builtinIds } = useAgentCatalog()

  const configView = useMemo(
    () => buildProtocolView(config, taskCount, builtinIds),
    [config, taskCount, builtinIds],
  )
  const snapView = useMemo(
    () => (snapshot ? buildSnapshotView(snapshot, taskCount) : null),
    [snapshot, taskCount],
  )
  const drift = useMemo(
    () => (snapshot ? computeDrift(snapshot, profiles) : null),
    [snapshot, profiles],
  )
  const recipe = useMemo(() => buildRecipe(config, taskCount), [config, taskCount])
  const rawKeyCount = Object.keys(config).length

  // The measurement panels read the snapshot's structured contract first; the
  // pins/other/raw sections always come from the run_config on disk (the file
  // system is still the truth for what actually ran).
  const subject = snapView?.subject ?? configView.subject
  const instrument = snapView?.instrument ?? configView.instrument
  const protocolTaskCount = snapView?.taskCount ?? configView.taskCount
  const batch = snapView?.batch ?? configView.batch
  const variables = snapView ? snapView.variables : configView.variables
  const repeat = snapView?.repeat ?? null

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className="gap-0 py-5">
        <div className="px-6">
          <div className="flex items-center gap-2">
            <CollapsibleTrigger className="group flex items-center gap-2 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
              <CardTitle className="text-base">Run configuration</CardTitle>
              <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
            </CollapsibleTrigger>
            {recipe && (
              <div className="ml-auto">
                <CopyRecipeButton text={recipe.text} />
              </div>
            )}
          </div>
          {snapshot && <ContractProvenance snapshot={snapshot} drift={drift} />}
          {!open && recipe && (
            <p
              className="mt-2 truncate font-mono text-[13px] leading-5 text-muted-foreground"
              title={recipe.text}
            >
              {recipe.text}
            </p>
          )}
        </div>

        <CollapsibleContent>
          <CardContent className="pt-5">
            <div className="grid gap-x-5 gap-y-6 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
              <PartyPanel caption="Subject" gloss="under test" party={subject} />
              <FlowArrow />
              <ProtocolPanel
                taskCount={protocolTaskCount}
                batch={batch}
                variables={variables}
                repeat={repeat}
              />
              <FlowArrow />
              <PartyPanel caption="Instrument" gloss="scores the outputs" party={instrument} />
            </div>

            {configView.other.length > 0 && (
              <div className="mt-6 border-t border-border/70 pt-4">
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                  Other
                </h3>
                <dl className="grid grid-cols-[minmax(0,max-content)_minmax(0,1fr)] gap-x-4 gap-y-1.5">
                  {configView.other.map(([key, value]) => (
                    <div key={key} className="contents">
                      <dt className="font-mono text-[13px] leading-5 text-muted-foreground">
                        {key}
                      </dt>
                      <dd className="min-w-0 break-all font-mono text-[13px] leading-5 text-foreground">
                        {formatConfigValue(value)}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}

            <div className="mt-6 flex flex-wrap items-baseline gap-x-5 gap-y-2 border-t border-border/70 pt-3">
              <span className="text-xs font-medium uppercase tracking-[0.06em] text-muted-foreground">
                Pins a rerun
              </span>
              {configView.pins.map((pin) => (
                <span key={pin.label} className="inline-flex items-baseline gap-1.5 text-xs">
                  <span className="text-muted-foreground">{pin.label}</span>
                  <code className="font-mono text-xs font-medium text-foreground">
                    {pin.value}
                  </code>
                </span>
              ))}
              <button
                type="button"
                onClick={() => setShowRaw((v) => !v)}
                aria-expanded={showRaw}
                className="ml-auto inline-flex items-center gap-1.5 rounded text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
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
