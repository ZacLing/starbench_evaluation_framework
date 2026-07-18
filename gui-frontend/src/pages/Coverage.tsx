import { useState } from "react"
import { Link } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { ArrowRight, Info, Plus, TriangleAlert, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { AGENT_LABELS, AgentIcon } from "@/components/brand"
import { HswVerdict } from "@/components/verdict"
import { ErrorNote } from "@/components/error-note"
import { useMinWidth } from "@/hooks/use-min-width"
import { cn } from "@/lib/utils"
import { api, type CoverageCell, type CoverageColumn, type CoverageRow } from "@/lib/api"
import { fmtDuration, fmtRelative } from "@/lib/format"

/* Run matrix — Task × Agent × Model, the platform's primary navigation.
   One matrix, six lenses: the HSW defense-line reading (inverted: an agent
   pass breaches the task), rubric ratio, task pass rate, stability across
   repeats, executor duration, and raw execution status. Cells aggregate every
   repeat and variant on disk; clicking one opens the drill-down rail. */

type Metric = "hsw" | "rubric" | "pass" | "stability" | "duration" | "status"

const METRICS: { key: Metric; label: string }[] = [
  { key: "hsw", label: "HSW coverage" },
  { key: "rubric", label: "Rubric %" },
  { key: "pass", label: "Pass rate" },
  { key: "stability", label: "Stability (σ)" },
  { key: "duration", label: "Duration" },
  { key: "status", label: "Run status" },
]

type Selection =
  | { kind: "cell"; taskId: string; columnKey: string }
  | { kind: "combo"; columnKey: string }

const RAIL_BREAKPOINT = 1280

export default function Coverage() {
  const coverageQuery = useQuery({ queryKey: ["coverage"], queryFn: () => api.coverage() })
  const [metric, setMetric] = useState<Metric>("hsw")
  const [selection, setSelection] = useState<Selection | null>(null)
  const railVisible = useMinWidth(RAIL_BREAKPOINT)

  if (coverageQuery.isPending) return <MatrixSkeleton />
  if (coverageQuery.isError) return <ErrorNote message={(coverageQuery.error as Error).message} />

  const { columns, rows, runs_scanned, profile } = coverageQuery.data
  const runLabel = `${runs_scanned} run${runs_scanned === 1 ? "" : "s"}`

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-3xl">
          <h1 className="text-2xl font-semibold tracking-tight">Run matrix</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Compare task resilience across every Agent × Model combination on disk.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {profile && (
            <span className="rounded-md border bg-card px-2.5 py-1.5">
              Profile <strong className="font-medium text-foreground">{profile.name}</strong>
              <span className="ml-1.5 font-mono tabular-nums">rev {profile.rev}</span>
            </span>
          )}
          <span className="rounded-md border bg-card px-2.5 py-1.5 font-mono tabular-nums">
            {runLabel} scanned
          </span>
        </div>
      </div>

      {/* Metric switcher: same matrix, one lens at a time — color never
          carries two meanings at once. */}
      <div
        className="flex min-w-0 items-center gap-1 overflow-x-auto rounded-lg border bg-card p-1"
        role="tablist"
        aria-label="Matrix metric"
      >
        {METRICS.map((entry) => (
          <button
            key={entry.key}
            type="button"
            onClick={() => setMetric(entry.key)}
            data-active={metric === entry.key}
            role="tab"
            aria-selected={metric === entry.key}
            className="shrink-0 rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring data-[active=true]:bg-accent data-[active=true]:font-medium data-[active=true]:text-accent-foreground"
          >
            {entry.label}
          </button>
        ))}
      </div>

      {rows.length ? (
        <div className="flex min-w-0 items-start gap-4">
          <Card className="min-w-0 flex-1 gap-0 overflow-hidden py-0 shadow-none">
            <LegendBar metric={metric} taskCount={rows.length} configCount={columns.length} />
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead
                    rowSpan={2}
                    className="sticky left-0 z-20 min-w-[14rem] border-b border-r bg-card align-bottom"
                  >
                    <span className="text-xs font-medium text-muted-foreground">Task</span>
                  </TableHead>
                  {groupColumns(columns).map((group, index) => (
                    <TableHead
                      key={`${group.agent}-${index}`}
                      colSpan={group.columns.length}
                      className={cn(
                        "h-9 border-b bg-card text-center",
                        index > 0 && "border-l border-border/60",
                      )}
                    >
                      <span className="inline-flex items-center gap-1.5 text-sm font-medium text-foreground">
                        <AgentIcon agent={group.agent} size={16} />
                        {AGENT_LABELS[group.agent] ?? group.agent}
                      </span>
                    </TableHead>
                  ))}
                </TableRow>
                <TableRow className="hover:bg-transparent">
                  {columns.map((column, index) => (
                    <TableHead
                      key={column.key}
                      className={cn(
                        "h-auto min-w-[8.5rem] border-b bg-card py-2 align-top",
                        index > 0 && "border-l border-border/60",
                      )}
                    >
                      <ColumnHeader
                        column={column}
                        hasRoster={profile !== null}
                        onSelect={() => setSelection({ kind: "combo", columnKey: column.key })}
                      />
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.task_id} className="hover:bg-transparent">
                    <TableCell className="sticky left-0 z-10 border-r bg-card align-top">
                      <TaskHeader row={row} />
                    </TableCell>
                    {columns.map((column, index) => {
                      const cell =
                        row.cells.find((entry) => entry.column_key === column.key) ?? null
                      const isSelected =
                        selection?.kind === "cell" &&
                        selection.taskId === row.task_id &&
                        selection.columnKey === column.key
                      return (
                        <TableCell
                          key={column.key}
                          className={cn(
                            "p-1 align-top",
                            index > 0 && "border-l border-border/60",
                            (!cell || cell.state === "untested") && "bg-muted/35",
                          )}
                        >
                          {cell && cell.state !== "untested" ? (
                            <MetricCell
                              metric={metric}
                              cell={cell}
                              selected={isSelected}
                              onSelect={() =>
                                setSelection({
                                  kind: "cell",
                                  taskId: row.task_id,
                                  columnKey: column.key,
                                })
                              }
                            />
                          ) : (
                            <Untested />
                          )}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>

          {railVisible && selection && (
            <aside
              className="sticky top-[4.5rem] w-[21rem] shrink-0"
              aria-label="Matrix drill-down"
            >
              <DrillDownRail
                selection={selection}
                columns={columns}
                rows={rows}
                onClose={() => setSelection(null)}
              />
            </aside>
          )}
        </div>
      ) : (
        <EmptyMatrix />
      )}
    </div>
  )
}

/* Consecutive columns of the same agent share one group header; roster order
   is authoritative, so a split group means the roster interleaved on purpose. */
function groupColumns(columns: CoverageColumn[]) {
  const groups: { agent: string; columns: CoverageColumn[] }[] = []
  for (const column of columns) {
    const last = groups[groups.length - 1]
    if (last && last.agent === column.agent) last.columns.push(column)
    else groups.push({ agent: column.agent, columns: [column] })
  }
  return groups
}

function LegendBar({
  metric,
  taskCount,
  configCount,
}: {
  metric: Metric
  taskCount: number
  configCount: number
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b bg-muted/25 px-4 py-2.5">
      <span className="text-xs text-muted-foreground">
        <span className="font-mono tabular-nums text-foreground">{taskCount}</span> task
        {taskCount === 1 ? "" : "s"} ·{" "}
        <span className="font-mono tabular-nums text-foreground">{configCount}</span> config
        {configCount === 1 ? "" : "s"}
      </span>
      {metric === "hsw" && (
        <>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Info className="size-3.5" aria-hidden />
            HSW is inverted: an agent pass means the task is breached.
          </span>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
            <HswVerdict state="untested" />
            <HswVerdict state="inconclusive" />
            <HswVerdict state="defended" />
            <HswVerdict state="breached" />
          </div>
        </>
      )}
      {(metric === "rubric" || metric === "pass") && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
          {RATIO_BANDS.map((band) => (
            <span key={band.label} className="inline-flex items-center gap-1.5">
              <span className={cn("size-2.5 rounded-sm", band.swatch)} aria-hidden />
              {band.label}
            </span>
          ))}
        </div>
      )}
      {metric === "stability" && (
        <span className="text-sm text-muted-foreground">
          Population σ of rubric ratio across repeats; needs ≥ 2 judged repeats.{" "}
          <TriangleAlert className="inline size-3.5 text-warn-ink" aria-hidden /> marks mixed
          pass/fail outcomes.
        </span>
      )}
      {metric === "duration" && (
        <span className="text-sm text-muted-foreground">
          Executor wall-clock: mean and nearest-rank P95 across attempts.
        </span>
      )}
      {metric === "status" && (
        <span className="text-sm text-muted-foreground">
          Executor terminal states; pending means no terminal status on disk yet.
        </span>
      )}
    </div>
  )
}

/* Score bands shared by the rubric and pass-rate lenses (reference legend). */
const RATIO_BANDS = [
  { min: 0.9, label: "90–100", swatch: "bg-pass/30", cell: "bg-pass/20 text-pass-ink" },
  { min: 0.75, label: "75–89", swatch: "bg-pass-soft", cell: "bg-pass-soft text-pass-ink" },
  { min: 0.5, label: "50–74", swatch: "bg-warn-soft", cell: "bg-warn-soft text-warn-ink" },
  { min: 0.25, label: "25–49", swatch: "bg-fail-soft/70", cell: "bg-fail-soft/70 text-fail-ink" },
  { min: 0, label: "0–24", swatch: "bg-fail/20", cell: "bg-fail/20 text-fail-ink" },
]

function ratioBand(ratio: number) {
  return RATIO_BANDS.find((band) => ratio >= band.min) ?? RATIO_BANDS[RATIO_BANDS.length - 1]
}

function TaskHeader({ row }: { row: CoverageRow }) {
  const measured = row.cells.filter((cell) => cell.state !== "untested")
  const breachedCount = measured.filter((cell) => cell.state === "breached").length
  const defendedCount = measured.filter((cell) => cell.state === "defended").length
  const inconclusiveCount = measured.filter((cell) => cell.state === "inconclusive").length

  return (
    <div className="grid min-w-0 gap-1.5 py-0.5">
      <span className="max-w-[16rem] truncate font-mono text-sm font-medium" title={row.task_id}>
        {row.task_id}
      </span>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {measured.length === 0 ? (
          <HswVerdict state="untested" />
        ) : breachedCount > 0 ? (
          <HswVerdict state="breached" count={`${breachedCount}/${measured.length}`} />
        ) : defendedCount > 0 ? (
          <HswVerdict state="defended" count={`${defendedCount}/${measured.length}`} />
        ) : inconclusiveCount > 0 ? (
          <HswVerdict state="inconclusive" count={`${inconclusiveCount}/${measured.length}`} />
        ) : (
          <HswVerdict state="untested" />
        )}
        {!row.in_library && (
          <Badge variant="outline" className="font-normal text-muted-foreground">
            not in library
          </Badge>
        )}
      </div>
    </div>
  )
}

/* Model-level header cell; clicking it opens the combination drill-down. */
function ColumnHeader({
  column,
  hasRoster,
  onSelect,
}: {
  column: CoverageColumn
  hasRoster: boolean
  onSelect: () => void
}) {
  const neverRun = column.run_count === 0
  const unrostered = hasRoster && !column.rostered
  return (
    <button
      type="button"
      onClick={onSelect}
      className="-mx-1 grid w-[calc(100%+0.5rem)] gap-1 rounded-md px-1 py-0.5 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={`Open combination details for ${AGENT_LABELS[column.agent] ?? column.agent} ${column.model ?? ""}`}
    >
      <span
        className="truncate font-mono text-xs font-medium text-foreground"
        title={column.model ?? "model not recorded in run config"}
      >
        {column.model ?? "model not recorded"}
      </span>
      <span className="font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
        {neverRun ? "not yet run" : `${column.run_count} run${column.run_count === 1 ? "" : "s"}`}
        {unrostered && " · unrostered"}
      </span>
    </button>
  )
}

function Untested() {
  return (
    <div className="flex min-h-[3.25rem] items-center justify-center" title="untested">
      <span aria-hidden className="select-none text-base leading-none text-muted-foreground/50">
        —
      </span>
      <span className="sr-only">untested</span>
    </div>
  )
}

/* One cell, rendered through the active lens. Every lens keeps word + number;
   tint carries exactly one meaning at a time. */
function MetricCell({
  metric,
  cell,
  selected,
  onSelect,
}: {
  metric: Metric
  cell: CoverageCell
  selected: boolean
  onSelect: () => void
}) {
  const flaky = cell.passed > 0 && cell.passed < cell.judged
  let body: React.ReactNode
  let tint = ""

  if (metric === "hsw") {
    const valueInk =
      cell.state === "breached"
        ? "text-fail-ink"
        : cell.state === "defended"
          ? "text-pass-ink"
          : "text-warn-ink"
    body = (
      <div className="grid content-start gap-1">
        <HswVerdict state={cell.state} />
        <span className={cn("font-mono text-sm font-semibold tabular-nums", valueInk)}>
          {cell.state === "inconclusive"
            ? `${cell.inconclusive || cell.total} invalid`
            : `${cell.passed}/${cell.judged}`}
        </span>
      </div>
    )
  } else if (metric === "rubric") {
    if (cell.rubric_ratio_mean === null) {
      body = <NoEvidence label="no rubric evidence" />
    } else {
      const band = ratioBand(cell.rubric_ratio_mean)
      tint = band.cell
      body = (
        <div className="grid content-start gap-0.5">
          <span className="text-sm font-semibold tabular-nums">
            {Math.round(cell.rubric_ratio_mean * 100)}%
            {cell.rubric_ratio_std !== null && (
              <span className="ml-1 text-xs font-normal opacity-80">
                ±{Math.round(cell.rubric_ratio_std * 100)}
              </span>
            )}
          </span>
          <span className="inline-flex items-center gap-1 font-mono text-xs tabular-nums opacity-90">
            {cell.passed}/{cell.judged} ✓
            {flaky && (
              <TriangleAlert
                className="size-3"
                aria-label="flaky: mixed pass/fail across repeats"
              />
            )}
          </span>
        </div>
      )
    }
  } else if (metric === "pass") {
    if (!cell.judged) {
      body = <NoEvidence label="not judged" />
    } else {
      const rate = cell.passed / cell.judged
      const band = ratioBand(rate)
      tint = band.cell
      body = (
        <div className="grid content-start gap-0.5">
          <span className="text-sm font-semibold tabular-nums">{Math.round(rate * 100)}%</span>
          <span className="font-mono text-xs tabular-nums opacity-90">
            {cell.passed}/{cell.judged} passed
          </span>
        </div>
      )
    }
  } else if (metric === "stability") {
    if (cell.rubric_ratio_std === null) {
      body = <NoEvidence label={cell.rubric_samples === 1 ? "1 sample" : "no repeats"} />
    } else {
      const pp = cell.rubric_ratio_std * 100
      tint =
        pp <= 5
          ? "bg-pass-soft text-pass-ink"
          : pp <= 15
            ? "bg-warn-soft text-warn-ink"
            : "bg-fail-soft/70 text-fail-ink"
      body = (
        <div className="grid content-start gap-0.5">
          <span className="inline-flex items-center gap-1 text-sm font-semibold tabular-nums">
            ±{pp.toFixed(1)}pp
            {flaky && (
              <TriangleAlert
                className="size-3"
                aria-label="flaky: mixed pass/fail across repeats"
              />
            )}
          </span>
          <span className="font-mono text-xs tabular-nums opacity-90">
            {cell.rubric_samples} repeats
          </span>
        </div>
      )
    }
  } else if (metric === "duration") {
    if (cell.duration_mean_seconds === null) {
      body = <NoEvidence label="no duration" />
    } else {
      body = (
        <div className="grid content-start gap-0.5">
          <span className="text-sm font-semibold tabular-nums">
            {fmtDuration(cell.duration_mean_seconds)}
          </span>
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            P95 {fmtDuration(cell.duration_p95_seconds)}
          </span>
        </div>
      )
    }
  } else {
    const parts: { label: string; className: string }[] = []
    if (cell.exec_pending)
      parts.push({ label: `${cell.exec_pending} pending`, className: "text-live-ink" })
    if (cell.exec_timeout)
      parts.push({ label: `${cell.exec_timeout} timeout`, className: "text-warn-ink" })
    if (cell.exec_failed)
      parts.push({ label: `${cell.exec_failed} failed`, className: "text-fail-ink" })
    if (cell.exec_success)
      parts.push({ label: `${cell.exec_success} ok`, className: "text-pass-ink" })
    body = (
      <div className="grid content-start gap-0.5 text-xs font-medium">
        {parts.length ? (
          parts.map((part) => (
            <span key={part.label} className={cn("tabular-nums", part.className)}>
              {part.label}
            </span>
          ))
        ) : (
          <NoEvidence label="no attempts" />
        )}
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      data-selected={selected}
      className={cn(
        "block min-h-[3.25rem] w-full rounded-md px-2 py-1.5 text-left transition-colors",
        "hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        "data-[selected=true]:ring-2 data-[selected=true]:ring-inset data-[selected=true]:ring-primary/60",
        tint,
      )}
      title={`${cell.total} attempt${cell.total === 1 ? "" : "s"}${
        cell.last_tested ? ` · last ${fmtRelative(cell.last_tested)}` : ""
      }`}
    >
      {body}
    </button>
  )
}

function NoEvidence({ label }: { label: string }) {
  return <span className="text-xs text-muted-foreground">{label}</span>
}

/* Drill-down rail: a cell opens the run-group view (this task × combination,
   every repeat); a column header opens the combination rollup. */
function DrillDownRail({
  selection,
  columns,
  rows,
  onClose,
}: {
  selection: Selection
  columns: CoverageColumn[]
  rows: CoverageRow[]
  onClose: () => void
}) {
  const column = columns.find((entry) => entry.key === selection.columnKey)
  if (!column) return null
  const cell =
    selection.kind === "cell"
      ? (rows
          .find((row) => row.task_id === selection.taskId)
          ?.cells.find((entry) => entry.column_key === selection.columnKey) ?? null)
      : null

  return (
    <Card className="max-h-[calc(100vh-5.5rem)] gap-0 overflow-y-auto rounded-xl py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h2 className="text-sm font-semibold">
          {selection.kind === "cell" ? "Run group" : "Combination details"}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          className="-mr-1.5 size-7 text-muted-foreground"
          onClick={onClose}
          aria-label="Close drill-down panel"
        >
          <X className="size-4" />
        </Button>
      </div>

      <div className="grid gap-1.5 border-b px-4 py-3.5">
        {selection.kind === "cell" && (
          <span className="break-all font-mono text-sm font-semibold leading-5">
            {selection.taskId}
          </span>
        )}
        <span className="flex items-center gap-2 text-sm">
          <AgentIcon agent={column.agent} size={16} />
          <span className="font-medium">{AGENT_LABELS[column.agent] ?? column.agent}</span>
          {column.model && (
            <span className="truncate font-mono text-xs text-muted-foreground" title={column.model}>
              {column.model}
            </span>
          )}
        </span>
        {!column.rostered && (
          <span className="text-xs text-muted-foreground">unrostered — seen in runs only</span>
        )}
      </div>

      {selection.kind === "cell" && cell ? (
        <CellDrill cell={cell} />
      ) : (
        <ComboDrill column={column} />
      )}
    </Card>
  )
}

function CellDrill({ cell }: { cell: CoverageCell }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-b px-4 py-3.5">
        <DrillMetric
          label="Rubric mean"
          value={
            cell.rubric_ratio_mean !== null ? `${Math.round(cell.rubric_ratio_mean * 100)}%` : "–"
          }
        />
        <DrillMetric
          label="Stability"
          value={cell.rubric_ratio_std !== null ? `±${(cell.rubric_ratio_std * 100).toFixed(1)}pp` : "–"}
        />
        <DrillMetric label="Passed" value={cell.judged ? `${cell.passed}/${cell.judged}` : "–"} />
        <DrillMetric
          label="P95 duration"
          value={cell.duration_p95_seconds !== null ? fmtDuration(cell.duration_p95_seconds) : "–"}
        />
        <DrillMetric label="Attempts" value={String(cell.total)} />
        <DrillMetric label="HSW state" value={cell.state} />
      </div>
      <div className="px-4 py-3.5">
        <h3 className="text-xs font-medium text-muted-foreground">
          Recent task runs ({cell.recent_refs.length} of {cell.total})
        </h3>
        <ul className="mt-1.5 grid gap-0.5">
          {cell.recent_refs.map((ref) => (
            <li key={`${ref.run_id}/${ref.run_task_id}`}>
              <Link
                to={`/runs/${encodeURIComponent(ref.run_id)}/tasks/${encodeURIComponent(ref.run_task_id)}`}
                className="group flex items-center gap-2 rounded-md px-1.5 py-1.5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <span className="min-w-0 flex-1 truncate font-mono text-xs group-hover:text-primary">
                  {ref.run_id}
                </span>
                <ArrowRight className="size-3.5 shrink-0 text-muted-foreground/60" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </>
  )
}

function ComboDrill({ column }: { column: CoverageColumn }) {
  const stats = column.stats
  const passRate = stats.judged ? stats.passed / stats.judged : null
  return (
    <>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-b px-4 py-3.5">
        <DrillMetric
          label="Rubric mean"
          value={
            stats.rubric_ratio_mean !== null ? `${Math.round(stats.rubric_ratio_mean * 100)}%` : "–"
          }
        />
        <DrillMetric
          label="Stability"
          value={
            stats.rubric_ratio_std !== null ? `±${(stats.rubric_ratio_std * 100).toFixed(1)}pp` : "–"
          }
        />
        <DrillMetric
          label="Pass rate"
          value={passRate !== null ? `${Math.round(passRate * 100)}%` : "–"}
        />
        <DrillMetric label="Tasks judged" value={String(stats.tasks_tested)} />
        <DrillMetric
          label="P95 duration"
          value={stats.duration_p95_seconds !== null ? fmtDuration(stats.duration_p95_seconds) : "–"}
        />
        <DrillMetric label="Last activity" value={fmtRelative(stats.last_tested) || "–"} />
      </div>
      <div className="grid gap-2 px-4 py-3.5">
        <Button size="sm" variant="outline" asChild>
          <Link to="/runs">
            View runs <ArrowRight className="size-4" />
          </Link>
        </Button>
      </div>
    </>
  )
}

function DrillMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-base font-semibold tabular-nums tracking-tight">{value}</span>
    </div>
  )
}

function EmptyMatrix() {
  return (
    <Card>
      <CardContent className="grid place-content-center gap-3 py-16 text-center">
        <h2 className="text-lg font-semibold">No coverage yet</h2>
        <p className="max-w-md text-sm text-muted-foreground">
          No task packages in the library and no runs on disk. Add tasks or launch an
          experiment — the matrix fills in from whatever lands in the runs directory.
        </p>
        <div className="mt-2 flex justify-center">
          <Button asChild>
            <Link to="/new">
              <Plus /> New experiment
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function MatrixSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <Skeleton className="h-8 w-40" />
        <Skeleton className="mt-2 h-4 w-96" />
      </div>
      <Skeleton className="h-10 w-full max-w-2xl" />
      <Skeleton className="h-80 w-full rounded-xl" />
    </div>
  )
}
