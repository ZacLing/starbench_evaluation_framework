import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, XAxis, YAxis, Tooltip as ChartTooltip } from "recharts"
import { Activity, CheckCircle2, ListChecks, Plus } from "lucide-react"
import { ErrorNote } from "@/components/error-note"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PassSummaryBadge, StatusBadge } from "@/components/verdict"
import { api } from "@/lib/api"
import { fmtTime, fmtRate, percent, shortDir } from "@/lib/format"

export default function Dashboard() {
  const navigate = useNavigate()
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => run.status === "running") ? 4000 : false,
  })
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity })

  if (runsQuery.isPending) {
    return (
      <div className="grid gap-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-64" />
      </div>
    )
  }
  if (runsQuery.isError) {
    return <ErrorNote message={(runsQuery.error as Error).message} />
  }

  const runs = runsQuery.data.runs
  if (!runs.length) return <EmptyOnboarding />

  const judged = runs.filter((run) => run.judge_totals.single > 0)
  const taskPassTotal = judged.reduce((sum, run) => sum + run.judge_totals.single, 0)
  const taskPassCount = judged.reduce((sum, run) => sum + run.judge_passes.single, 0)
  const execTotal = runs.reduce(
    (sum, run) =>
      sum + run.executor_stats.success + run.executor_stats.failed + run.executor_stats.timeout,
    0,
  )
  const execSuccess = runs.reduce((sum, run) => sum + run.executor_stats.success, 0)
  const running = runs.filter((run) => run.status === "running")

  const chartData = [...runs]
    .filter((run) => run.judge_totals.single > 0)
    .slice(0, 10)
    .reverse()
    .map((run) => ({
      name: run.run_id,
      rate: Math.round(((run.judge_passes.single / run.judge_totals.single) * 1000)) / 10,
    }))

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          {runs.length} runs in{" "}
          <span className="font-mono" title={meta.data?.runs_dir}>
            {shortDir(meta.data?.runs_dir) || "this directory"}
          </span>
          {running.length > 0 && `, ${running.length} running now`}
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={<ListChecks className="size-4" />}
          label="Runs"
          value={String(runs.length)}
          hint={`${runs.filter((run) => run.status === "complete").length} complete`}
        />
        <StatCard
          icon={<CheckCircle2 className="size-4" />}
          label="Task pass rate"
          value={fmtRate(percent(taskPassCount, taskPassTotal))}
          hint={`${taskPassCount}/${taskPassTotal} judged tasks passed`}
        />
        <StatCard
          icon={<CheckCircle2 className="size-4" />}
          label="Executor success"
          value={fmtRate(percent(execSuccess, execTotal))}
          hint={`${execSuccess}/${execTotal} executions succeeded`}
        />
        <StatCard
          icon={<Activity className="size-4" />}
          label="Running now"
          value={String(running.length)}
          hint={running.length ? `${running[0].run_id} →` : "nothing in flight"}
          live={running.length > 0}
          to={running.length ? `/runs/${encodeURIComponent(running[0].run_id)}` : undefined}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="min-w-0 lg:col-span-3">
          <CardHeader>
            <CardTitle>Pass rate by run</CardTitle>
            <CardDescription>
              Single-judge task pass rate, oldest to newest ·{" "}
              <span className="text-pass-ink">green</span> = all passed,{" "}
              <span className="text-fail-ink">red</span> = none
            </CardDescription>
          </CardHeader>
          <CardContent className="h-56">
            {chartData.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -22 }}>
                  <CartesianGrid vertical={false} stroke="var(--border)" />
                  <XAxis
                    dataKey="name"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                    tickFormatter={(value: string) =>
                      // Run ids share long prefixes; the tail is what tells them apart.
                      value.length > 14 ? `…${value.slice(-13)}` : value
                    }
                  />
                  <YAxis
                    domain={[0, 100]}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                    tickFormatter={(value: number) => `${value}%`}
                  />
                  <ChartTooltip
                    cursor={{ fill: "var(--muted)" }}
                    formatter={(value) => [`${value}%`, "pass rate"]}
                    contentStyle={{
                      borderRadius: 8,
                      border: "1px solid var(--border)",
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="rate" radius={[4, 4, 0, 0]} maxBarSize={48}>
                    {chartData.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={entry.rate >= 100 ? "var(--pass)" : entry.rate > 0 ? "var(--chart-1)" : "var(--fail)"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="grid h-full place-content-center text-sm text-muted-foreground">
                No judged runs yet.
              </p>
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0 lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent runs</CardTitle>
            <CardDescription>Newest first</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-1">
            {runs.slice(0, 6).map((run) => (
              <button
                key={run.run_id}
                type="button"
                onClick={() => navigate(`/runs/${encodeURIComponent(run.run_id)}`)}
                className="flex min-w-0 items-center gap-3 rounded-md px-2 py-2 text-left transition-colors hover:bg-muted"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-mono text-sm">{run.run_id}</span>
                  <span className="block text-xs text-muted-foreground">
                    {fmtTime(run.started_at)} · {run.task_count} tasks
                  </span>
                </span>
                <PassSummaryBadge
                  passed={run.judge_passes.single}
                  total={run.judge_totals.single}
                />
                <StatusBadge status={run.status} />
              </button>
            ))}
            <Button asChild variant="ghost" size="sm" className="mt-1 justify-start text-muted-foreground">
              <Link to="/runs">View all runs →</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
  hint,
  live,
  to,
}: {
  icon: React.ReactNode
  label: string
  value: string
  hint: string
  live?: boolean
  /* When set, the whole card links to this route (e.g. the running run). */
  to?: string
}) {
  const card = (
    <Card className={to ? "transition-colors hover:border-live-ink/40 hover:bg-muted/40" : undefined}>
      <CardContent className="grid gap-1">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {icon}
          {label}
          {live && <span className="size-1.5 animate-pulse rounded-full bg-live-ink" aria-hidden />}
        </div>
        <div className="text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
        <div className="truncate text-xs text-muted-foreground" title={hint}>
          {hint}
        </div>
      </CardContent>
    </Card>
  )
  if (!to) return card
  return (
    <Link
      to={to}
      aria-label={`${label}: ${hint}`}
      className="rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {card}
    </Link>
  )
}

function EmptyOnboarding() {
  return (
    <Card>
      <CardContent className="grid place-content-center gap-3 py-16 text-center">
        <h2 className="text-lg font-semibold">No runs yet</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          Launch an evaluation from this console, or run <code className="font-mono">starbench-run</code>{" "}
          in a terminal against this runs directory. Results appear here as soon as they hit disk.
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
