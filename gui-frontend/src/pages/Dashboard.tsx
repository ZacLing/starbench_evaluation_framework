import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  XAxis,
  YAxis,
  Tooltip as ChartTooltip,
} from "recharts"
import {
  CheckCircle2,
  Clock,
  Grid3X3,
  ListChecks,
  Loader2,
  Plus,
  Timer,
  TrendingUp,
  XCircle,
} from "lucide-react"
import { ErrorNote } from "@/components/error-note"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { RunStatusChip } from "@/components/verdict"
import { AgentIcon } from "@/components/brand"
import { useAgentCatalog } from "@/hooks/useAgentCatalog"
import { api, type CoveragePayload, type RunOverview } from "@/lib/api"
import { fmtDuration, fmtRelative, shortDir, spanBetween } from "@/lib/format"
import { cn } from "@/lib/utils"

/* Overview: progress first, anomalies second, early conclusions third.
   Every figure is computed from runs/ and the task library on disk. */
export default function Dashboard() {
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => run.status === "running") ? 4000 : 30_000,
  })
  const coverageQuery = useQuery({ queryKey: ["coverage"], queryFn: () => api.coverage() })
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity })

  if (runsQuery.isPending) return <OverviewSkeleton />
  if (runsQuery.isError) return <ErrorNote message={(runsQuery.error as Error).message} />

  const runs = runsQuery.data.runs
  if (!runs.length) return <EmptyOnboarding />

  return (
    <div className="flex flex-col gap-5">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Evaluation progress and results in{" "}
          <span className="font-mono" title={meta.data?.runs_dir}>
            {shortDir(meta.data?.runs_dir) || "this directory"}
          </span>
        </p>
      </div>

      <KpiStrip runs={runs} coverage={coverageQuery.data} />

      <div className="flex min-w-0 items-start gap-4">
        <div className="grid min-w-0 flex-1 gap-4">
          <div className="grid gap-4 xl:grid-cols-5">
            <ProgressOverTime runs={runs} className="min-w-0 xl:col-span-3" />
            <RunsByStatus runs={runs} className="min-w-0 xl:col-span-2" />
          </div>
          {coverageQuery.data && <PerformanceHeatmap coverage={coverageQuery.data} />}
          {coverageQuery.data && <TopBottomTasks coverage={coverageQuery.data} />}
        </div>

        <aside className="sticky top-[4.5rem] hidden w-[21rem] shrink-0 flex-col gap-3 2xl:flex">
          <RunningNow runs={runs} />
          <RecentFailures runs={runs} />
        </aside>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ KPI -- */

function KpiStrip({ runs, coverage }: { runs: RunOverview[]; coverage?: CoveragePayload }) {
  const now = Date.now()
  const total = runs.length
  const running = runs.filter((run) => run.status === "running").length
  const complete = runs.filter((run) => run.status === "complete").length
  const interrupted = total - running - complete
  const last7d = runs.filter((run) => {
    const started = run.started_at ? Date.parse(run.started_at) : NaN
    return Number.isFinite(started) && now - started <= 7 * 86_400_000
  }).length
  const judgedTotal = runs.reduce((sum, run) => sum + (run.judge_totals.single ?? 0), 0)
  const judgedPassed = runs.reduce((sum, run) => sum + (run.judge_passes.single ?? 0), 0)
  const spans = runs
    .filter((run) => run.started_at && run.ended_at)
    .map((run) => (Date.parse(run.ended_at as string) - Date.parse(run.started_at as string)) / 1000)
    .filter((span) => Number.isFinite(span) && span > 0)
    .sort((a, b) => a - b)
  const totalRuntime = spans.reduce((sum, span) => sum + span, 0)
  const p95 = spans.length ? spans[Math.max(0, Math.ceil(spans.length * 0.95) - 1)] : null

  /* Planned = rostered contenders × library tasks: the coverage denominator.
     Tested counts cells with at least one judged sample. */
  let planned: { total: number; tested: number } | null = null
  if (coverage?.profile) {
    const rosteredKeys = new Set(
      coverage.columns.filter((column) => column.rostered).map((column) => column.key),
    )
    const libraryRows = coverage.rows.filter((row) => row.in_library)
    let tested = 0
    for (const row of libraryRows) {
      for (const cell of row.cells) {
        if (rosteredKeys.has(cell.column_key) && cell.judged > 0) tested += 1
      }
    }
    planned = { total: rosteredKeys.size * libraryRows.length, tested }
  }

  const pct = (value: number) => (total ? `${Math.round((value / total) * 100)}%` : "–")

  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi
          icon={TrendingUp}
          tint="bg-pass-soft text-pass-ink"
          label="Task pass rate"
          value={judgedTotal ? `${((judgedPassed / judgedTotal) * 100).toFixed(1)}%` : "–"}
          sub={judgedTotal ? `${judgedPassed} of ${judgedTotal} judged tasks` : "No judged tasks"}
        />
        <Kpi
          icon={CheckCircle2}
          tint="bg-pass-soft text-pass-ink"
          label="Completed runs"
          value={String(complete)}
          sub={`${pct(complete)} of ${total} total`}
        />
        <Kpi
          icon={Loader2}
          tint="bg-live-soft text-live-ink"
          label="Running now"
          value={String(running)}
          sub={running ? `${pct(running)} of all runs` : "Nothing in flight"}
        />
        <Kpi
          icon={XCircle}
          tint="bg-warn-soft text-warn-ink"
          label="Needs attention"
          value={String(interrupted)}
          sub={interrupted ? `${pct(interrupted)} interrupted` : "No interruptions"}
        />
      </div>

      <Card className="grid gap-0 overflow-hidden rounded-xl py-0 sm:grid-cols-2 xl:grid-cols-4">
        {planned && (
          <CompactKpi
            icon={Grid3X3}
            label="Coverage"
            value={`${planned.tested}/${planned.total}`}
            sub="cells tested"
          />
        )}
        <CompactKpi
          icon={ListChecks}
          label="Run volume"
          value={String(total)}
          sub={last7d > 0 ? `${last7d} in last 7 days` : "none in last 7 days"}
        />
        <CompactKpi
          icon={Timer}
          label="Total runtime"
          value={totalRuntime > 0 ? fmtDuration(totalRuntime) : "–"}
          sub={`${spans.length} finished runs`}
        />
        <CompactKpi
          icon={Clock}
          label="P95 duration"
          value={p95 !== null ? fmtDuration(p95) : "–"}
          sub="finished runs"
        />
      </Card>
    </div>
  )
}

function Kpi({
  icon: Icon,
  tint,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>
  tint: string
  label: string
  value: string
  sub: string
}) {
  return (
    <Card className="gap-3 rounded-xl px-4 py-4 shadow-none">
      <div className="flex items-center gap-2.5">
        <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-full", tint)}>
          <Icon className="size-4" />
        </span>
        <span className="truncate text-sm text-muted-foreground">{label}</span>
      </div>
      <div className="text-[1.75rem] font-semibold leading-none tabular-nums tracking-tight">
        {value}
      </div>
      <div className="truncate text-xs text-muted-foreground" title={sub}>
        {sub}
      </div>
    </Card>
  )
}

function CompactKpi({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: string
  sub: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-3 border-b px-4 py-3 last:border-b-0 sm:[&:nth-child(odd)]:border-r sm:[&:nth-last-child(-n+2)]:border-b-0 xl:border-b-0 xl:border-r xl:last:border-r-0">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-xs font-medium text-muted-foreground">{label}</span>
          <span className="font-mono text-sm font-semibold tabular-nums">{value}</span>
        </div>
        <p className="truncate text-xs text-muted-foreground" title={sub}>
          {sub}
        </p>
      </div>
    </div>
  )
}

/* --------------------------------------------------------------- charts -- */

/* Cumulative finished runs per day. Two series only: completed and
   interrupted — the honest terminal states we have. */
function ProgressOverTime({ runs, className }: { runs: RunOverview[]; className?: string }) {
  const data = useMemo(() => {
    const finished = runs
      .filter((run) => run.status !== "running")
      .map((run) => ({
        status: run.status,
        at: Date.parse(run.ended_at ?? run.started_at ?? ""),
      }))
      .filter((entry) => Number.isFinite(entry.at))
      .sort((a, b) => a.at - b.at)
    if (!finished.length) return []
    const dayMs = 86_400_000
    const firstDay = Math.floor(finished[0].at / dayMs) * dayMs
    const lastDay = Math.floor(Date.now() / dayMs) * dayMs
    const points: { day: string; completed: number; interrupted: number }[] = []
    let completed = 0
    let interrupted = 0
    let index = 0
    for (let day = firstDay; day <= lastDay; day += dayMs) {
      while (index < finished.length && finished[index].at < day + dayMs) {
        if (finished[index].status === "complete") completed += 1
        else interrupted += 1
        index += 1
      }
      points.push({
        day: new Date(day).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        completed,
        interrupted,
      })
    }
    return points
  }, [runs])

  return (
    <Card className={cn("gap-3 rounded-xl py-4", className)}>
      <div className="px-4">
        <h2 className="text-sm font-semibold">Progress over time</h2>
        <p className="text-xs text-muted-foreground">Cumulative finished runs, by day</p>
      </div>
      <CardContent className="h-52 px-2">
        {data.length ? (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 4, right: 12, bottom: 0, left: -22 }}>
              <CartesianGrid vertical={false} stroke="var(--border)" />
              <XAxis
                dataKey="day"
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              />
              <YAxis
                allowDecimals={false}
                tickLine={false}
                axisLine={false}
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              />
              <ChartTooltip
                cursor={{ stroke: "var(--border)" }}
                contentStyle={{ borderRadius: 8, border: "1px solid var(--border)", fontSize: 12 }}
              />
              <Area
                dataKey="completed"
                name="Completed"
                stackId="finished"
                stroke="var(--pass)"
                fill="var(--pass)"
                fillOpacity={0.18}
                strokeWidth={2}
                isAnimationActive={false}
              />
              <Area
                dataKey="interrupted"
                name="Interrupted"
                stackId="finished"
                stroke="var(--warn)"
                fill="var(--warn)"
                fillOpacity={0.18}
                strokeWidth={2}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <p className="grid h-full place-content-center text-sm text-muted-foreground">
            No finished runs yet.
          </p>
        )}
      </CardContent>
      <div className="flex items-center gap-4 px-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-pass" aria-hidden /> Completed
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm bg-warn" aria-hidden /> Interrupted
        </span>
      </div>
    </Card>
  )
}

const STATUS_SLICES = [
  { key: "complete", label: "Completed", color: "var(--pass)" },
  { key: "running", label: "Running", color: "var(--live)" },
  { key: "interrupted", label: "Interrupted", color: "var(--warn)" },
] as const

function RunsByStatus({ runs, className }: { runs: RunOverview[]; className?: string }) {
  const counts = STATUS_SLICES.map((slice) => ({
    ...slice,
    value: runs.filter((run) => run.status === slice.key).length,
  })).filter((slice) => slice.value > 0)

  return (
    <Card className={cn("gap-3 rounded-xl py-4 shadow-none", className)}>
      <div className="px-4">
        <h2 className="text-sm font-semibold">Runs by status</h2>
      </div>
      <CardContent className="grid grid-cols-[repeat(auto-fit,minmax(8.5rem,1fr))] items-center justify-items-center gap-3 px-4">
        <div className="relative size-36 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={counts}
                dataKey="value"
                nameKey="label"
                innerRadius={45}
                outerRadius={64}
                paddingAngle={2}
                isAnimationActive={false}
              >
                {counts.map((slice) => (
                  <Cell key={slice.key} fill={slice.color} stroke="var(--card)" />
                ))}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 grid place-content-center text-center">
            <span className="text-xl font-semibold tabular-nums">{runs.length}</span>
            <span className="text-xs text-muted-foreground">runs</span>
          </div>
        </div>
        <ul className="grid w-full min-w-0 gap-2 self-center text-sm">
          {counts.map((slice) => (
            <li key={slice.key} className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2">
              <span
                className="size-2.5 shrink-0 rounded-sm"
                style={{ background: slice.color }}
                aria-hidden
              />
              <span className="min-w-0 truncate text-muted-foreground">{slice.label}</span>
              <span className="whitespace-nowrap font-medium tabular-nums">
                {slice.value}{" "}
                <span className="font-normal text-muted-foreground">
                  ({Math.round((slice.value / runs.length) * 100)}%)
                </span>
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------------- heatmap -- */

/* Agent rows × model columns; cell = rubric mean + pass rate from the
   combination rollup. A dash is a combination never run — a visible gap. */
function PerformanceHeatmap({ coverage }: { coverage: CoveragePayload }) {
  const { agentLabel } = useAgentCatalog()
  const agents = [...new Set(coverage.columns.map((column) => column.agent))]
  const models = [...new Set(coverage.columns.map((column) => column.model ?? "unknown"))]
  const byKey = new Map(coverage.columns.map((column) => [column.key, column]))

  if (!coverage.columns.length) return null

  return (
    <Card className="gap-3 rounded-xl py-4">
      <div className="flex items-baseline justify-between px-4">
        <div>
          <h2 className="text-sm font-semibold">Performance heatmap</h2>
          <p className="text-xs text-muted-foreground">
            Rubric mean and task pass rate per Agent × Model
          </p>
        </div>
        <Link to="/coverage" className="text-xs font-medium text-primary hover:underline">
          Open run matrix
        </Link>
      </div>
      <CardContent className="overflow-x-auto px-4">
        <table className="w-full min-w-[36rem] border-separate border-spacing-1">
          <thead>
            <tr>
              <th className="w-36 text-left text-xs font-medium text-muted-foreground">
                Agent \ Model
              </th>
              {models.map((model) => (
                <th
                  key={model}
                  className="truncate px-2 pb-1 text-left font-mono text-xs font-medium text-muted-foreground"
                  title={model}
                >
                  {model}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {agents.map((agent) => (
              <tr key={agent}>
                <td className="pr-2">
                  <span className="inline-flex items-center gap-1.5 text-sm">
                    <AgentIcon agent={agent} size={16} />
                    {agentLabel(agent)}
                  </span>
                </td>
                {models.map((model) => {
                  const column = byKey.get(`${agent}::${model === "unknown" ? "" : model}`)
                  const mean = column?.stats.rubric_ratio_mean ?? null
                  const passRate =
                    column && column.stats.judged
                      ? column.stats.passed / column.stats.judged
                      : null
                  return (
                    <td key={model}>
                      {column && mean !== null ? (
                        <Link
                          to="/coverage"
                          className={cn(
                            "block rounded-md px-2.5 py-2 transition-colors hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            heatTint(mean),
                          )}
                        >
                          <span className="block text-sm font-semibold tabular-nums">
                            {Math.round(mean * 100)}%
                          </span>
                          <span className="block text-xs tabular-nums opacity-80">
                            {passRate !== null ? `${Math.round(passRate * 100)}% pass` : "–"}
                          </span>
                        </Link>
                      ) : (
                        <span className="block rounded-md bg-muted/40 px-2.5 py-3 text-center text-muted-foreground/60">
                          –
                        </span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function heatTint(ratio: number) {
  if (ratio >= 0.9) return "bg-pass/20 text-pass-ink"
  if (ratio >= 0.75) return "bg-pass-soft text-pass-ink"
  if (ratio >= 0.5) return "bg-warn-soft text-warn-ink"
  if (ratio >= 0.25) return "bg-fail-soft/70 text-fail-ink"
  return "bg-fail/20 text-fail-ink"
}

/* -------------------------------------------------------- top / bottom -- */

function TopBottomTasks({ coverage }: { coverage: CoveragePayload }) {
  const [tab, setTab] = useState<"top" | "bottom">("top")
  const ranked = useMemo(() => {
    const entries = coverage.rows
      .map((row) => {
        const ratios: number[] = []
        for (const cell of row.cells) {
          if (cell.rubric_ratio_mean !== null && cell.rubric_samples > 0) {
            ratios.push(cell.rubric_ratio_mean)
          }
        }
        if (!ratios.length) return null
        return {
          task_id: row.task_id,
          mean: ratios.reduce((sum, value) => sum + value, 0) / ratios.length,
          combos: ratios.length,
        }
      })
      .filter((entry): entry is NonNullable<typeof entry> => entry !== null)
      .sort((a, b) => b.mean - a.mean)
    return entries
  }, [coverage])

  if (!ranked.length) return null
  const shown = tab === "top" ? ranked.slice(0, 5) : [...ranked].reverse().slice(0, 5)

  return (
    <Card className="gap-3 rounded-xl py-4">
      <div className="flex items-center justify-between px-4">
        <h2 className="text-sm font-semibold">Tasks by rubric mean</h2>
        <div className="flex items-center gap-1 rounded-lg border bg-background p-0.5">
          {(["top", "bottom"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setTab(key)}
              data-active={tab === key}
              className="rounded-md px-2.5 py-1 text-xs text-muted-foreground transition-colors data-[active=true]:bg-accent data-[active=true]:font-medium data-[active=true]:text-accent-foreground"
            >
              {key === "top" ? "Top 5" : "Bottom 5"}
            </button>
          ))}
        </div>
      </div>
      <CardContent className="grid gap-1 px-2">
        {shown.map((entry, index) => (
          <div key={entry.task_id} className="flex items-center gap-3 rounded-md px-2 py-1.5">
            <span className="w-4 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
              {index + 1}
            </span>
            <span
              className="min-w-0 flex-1 truncate font-mono text-sm"
              title={`${entry.task_id} — mean over ${entry.combos} combination${entry.combos === 1 ? "" : "s"}`}
            >
              {entry.task_id}
            </span>
            <div className="h-1.5 w-28 shrink-0 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full",
                  entry.mean >= 0.5 ? "bg-pass" : "bg-warn",
                )}
                style={{ width: `${Math.round(entry.mean * 100)}%` }}
              />
            </div>
            <span className="w-12 shrink-0 text-right text-sm font-medium tabular-nums">
              {Math.round(entry.mean * 100)}%
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

/* ------------------------------------------------------------ side rail -- */

function RunningNow({ runs }: { runs: RunOverview[] }) {
  const running = runs.filter((run) => run.status === "running")
  return (
    <Card className="gap-0 rounded-xl py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold">Running now</h2>
        <Link to="/runs" className="text-xs font-medium text-primary hover:underline">
          View all
        </Link>
      </div>
      {running.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted-foreground">Nothing in flight.</p>
      ) : (
        <ul className="px-2 py-1.5">
          {running.map((run) => {
            const stats = run.executor_stats
            const done = stats.success + stats.failed + stats.timeout + (stats.skipped ?? 0)
            const pct = run.task_count ? Math.round((done / run.task_count) * 100) : 0
            return (
              <li key={run.run_id}>
                <Link
                  to={`/runs/${encodeURIComponent(run.run_id)}`}
                  className="grid gap-1.5 rounded-lg px-2 py-2 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-[0.8125rem]">{run.run_id}</span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {spanBetween(run.started_at, run.ended_at, true)}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <span className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
                      <span
                        className="block h-full rounded-full bg-live transition-[width] duration-300"
                        style={{ width: `${pct}%` }}
                      />
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {pct}%
                    </span>
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

/* Needs attention: runs whose executors failed or timed out, whose judges came
   back inconclusive, or that were interrupted — the honest attention taxonomy
   on disk. (Named to match the KPI card: a "Completed" run with a timeout
   belongs here, and under a "failures" title that chip read as a
   contradiction.) */
function RecentFailures({ runs }: { runs: RunOverview[] }) {
  const failures = runs
    .map((run) => {
      const parts: string[] = []
      if (run.executor_stats.failed) parts.push(`${run.executor_stats.failed} executor failed`)
      if (run.executor_stats.timeout) parts.push(`${run.executor_stats.timeout} timeout`)
      const inconclusive = run.judge_inconclusive.single ?? 0
      if (inconclusive) parts.push(`${inconclusive} inconclusive`)
      if (run.status === "interrupted") parts.push("interrupted")
      if (!parts.length) return null
      return { run, parts }
    })
    .filter((entry): entry is NonNullable<typeof entry> => entry !== null)
    .slice(0, 6)

  return (
    <Card className="gap-0 rounded-xl py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold">Needs attention</h2>
        <Link to="/runs" className="text-xs font-medium text-primary hover:underline">
          View all
        </Link>
      </div>
      {failures.length === 0 ? (
        <p className="px-4 py-4 text-sm text-muted-foreground">Nothing needs attention.</p>
      ) : (
        <ul className="px-2 py-1.5">
          {failures.map(({ run, parts }) => (
            <li key={run.run_id}>
              <Link
                to={`/runs/${encodeURIComponent(run.run_id)}`}
                className="grid gap-1 rounded-lg px-2 py-2 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="min-w-0 truncate font-mono text-[0.8125rem]">{run.run_id}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">
                    {fmtRelative(run.ended_at ?? run.started_at)}
                  </span>
                </span>
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs text-warn-ink">{parts.join(" · ")}</span>
                  <RunStatusChip status={run.status} />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/* ---------------------------------------------------------------- misc -- */

function EmptyOnboarding() {
  return (
    <Card>
      <CardContent className="grid place-content-center gap-3 py-16 text-center">
        <h2 className="text-lg font-semibold">No runs yet</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          Launch an evaluation from this console, or run{" "}
          <code className="font-mono">starbench-run</code> in a terminal against this runs
          directory. Results appear here as soon as they hit disk.
        </p>
        <div className="mt-2 flex justify-center">
          <Button asChild>
            <Link to="/new">
              <Plus /> New run
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <div>
        <Skeleton className="h-8 w-36" />
        <Skeleton className="mt-2 h-4 w-72" />
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 8 }, (_, index) => (
          <Skeleton key={index} className="h-28 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 w-full rounded-xl" />
    </div>
  )
}
