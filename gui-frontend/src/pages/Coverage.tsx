import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Plus } from "lucide-react"
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
import { ErrorNote } from "@/pages/Dashboard"
import { cn } from "@/lib/utils"
import { api, type CoverageCell, type CoverageColumn, type CoverageRow } from "@/lib/api"
import { fmtRelative } from "@/lib/format"

/* HSW coverage matrix — a defense-line board. Rows are tasks (positions held),
   columns are executor configurations (the attackers observed in runs/ on disk).
   The semantics are inverted: an agent PASS means the task was breached (bad
   news), all judged attempts failing means the position holds (good news).

   The cell is an instrument reading, not a stack of text: a state line
   (glyph + word + freshness) over an attempt meter (one segment per run:
   filled = breach, neutral = held, amber = inconclusive, hollow = pending) and the
   exact judged fraction. Every state stays glyph + word + color, never color
   alone; the meter adds a fourth, length-coded channel for magnitude. */

type CellState = "breached" | "holds" | "inconclusive" | "no-verdicts"

function cellState(cell: CoverageCell): CellState {
  if (cell.judged === 0) return cell.inconclusive > 0 ? "inconclusive" : "no-verdicts"
  return cell.passed > 0 ? "breached" : "holds"
}

export default function Coverage() {
  const coverageQuery = useQuery({ queryKey: ["coverage"], queryFn: api.coverage })

  if (coverageQuery.isPending) return <Skeleton className="h-96" />
  if (coverageQuery.isError) return <ErrorNote message={(coverageQuery.error as Error).message} />

  const { columns, rows, runs_scanned, profile } = coverageQuery.data
  const runLabel = `${runs_scanned} run${runs_scanned === 1 ? "" : "s"}`

  return (
    <div className="grid gap-5">
      <div className="max-w-3xl">
        <h1 className="text-xl font-semibold tracking-tight">Coverage</h1>
        {profile ? (
          <>
            <p className="mt-1 text-sm text-muted-foreground">
              Which rostered contenders have breached each task, and where the measurement
              set still has gaps. Rostered columns lead; a config seen in a run but outside
              the roster is marked <span className="text-foreground">unrostered</span>.
            </p>
            <p className="mt-1.5 text-sm text-muted-foreground">
              Roster from profile{" "}
              <span className="font-medium text-foreground">{profile.name}</span>
              <span className="mx-1.5 text-border">·</span>
              <span className="font-mono text-xs tabular-nums">rev {profile.rev}</span>
              <span className="mx-1.5 text-border">·</span>
              columns also include configs seen across the {runLabel} on disk
            </p>
          </>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">
            Which executor configurations each task has faced. Columns are derived from the{" "}
            {runLabel} on disk (no roster configured); rows are library tasks plus any task
            seen in a run.
          </p>
        )}
      </div>

      {rows.length ? (
        <MatrixPanel columns={columns} rows={rows} hasRoster={profile !== null} />
      ) : (
        <EmptyCoverage />
      )}
    </div>
  )
}

/* The panel frames the matrix as one instrument: a reading key across the top
   (the how-to-read legend, folded into the panel it explains) over the grid. */
function MatrixPanel({
  columns,
  rows,
  hasRoster,
}: {
  columns: CoverageColumn[]
  rows: CoverageRow[]
  hasRoster: boolean
}) {
  return (
    <Card className="overflow-hidden py-0">
      <ReadingKey taskCount={rows.length} configCount={columns.length} />
      {/* The shadcn Table wraps itself in an overflow-x-auto container, so
          horizontal scroll stays inside this panel — never on the page body.
          Row hover is disabled: the interactive unit is the cell, and a
          translucent row tint would ghost through the opaque sticky column. */}
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="sticky left-0 z-20 min-w-[15rem] border-r bg-card align-middle">
              <span className="text-[0.7rem] font-medium uppercase tracking-[0.08em] text-muted-foreground">
                Task
              </span>
            </TableHead>
            {columns.length ? (
              columns.map((column, index) => (
                <TableHead
                  key={column.key}
                  className={cn(
                    "h-auto min-w-[11rem] bg-card py-3 align-middle",
                    index > 0 && "border-l border-border/60",
                    hasRoster && !column.rostered && "bg-muted/25",
                  )}
                >
                  <ColumnHeader column={column} hasRoster={hasRoster} />
                </TableHead>
              ))
            ) : (
              <TableHead className="bg-card font-normal text-muted-foreground">
                no executor configurations yet — columns appear once runs exist on disk
              </TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {/* Backend order is authoritative: breached tasks first, then task id. */}
          {rows.map((row) => (
            <MatrixRow key={row.task_id} row={row} columns={columns} />
          ))}
        </TableBody>
      </Table>
    </Card>
  )
}

function ReadingKey({ taskCount, configCount }: { taskCount: number; configCount: number }) {
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b bg-muted/40 px-4 py-2.5">
      <span className="text-sm text-muted-foreground">
        <span className="font-mono tabular-nums text-foreground">{taskCount}</span> task
        {taskCount === 1 ? "" : "s"} ·{" "}
        <span className="font-mono tabular-nums text-foreground">{configCount}</span> config
        {configCount === 1 ? "" : "s"}
        <span className="mx-2 text-border">|</span>
        HSW reads <span className="font-medium text-foreground">inverted</span>: an agent pass
        breaches the task.
      </span>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
        <KeyItem glyph="—" word="untested" tone="text-muted-foreground/70" />
        <KeyItem glyph="◌" word="no verdicts" tone="text-muted-foreground" />
        <KeyItem glyph="!" word="inconclusive" tone="text-warn-ink" />
        <KeyItem glyph="✓" word="holds" tone="text-pass-ink" />
        <KeyItem glyph="⚠" word="breached" tone="text-fail-ink" />
      </div>
    </div>
  )
}

function KeyItem({ glyph, word, tone }: { glyph: string; word: string; tone: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span aria-hidden className={cn("w-3 text-center font-medium", tone)}>
        {glyph}
      </span>
      <span className="text-muted-foreground">{word}</span>
    </span>
  )
}

function MatrixRow({ row, columns }: { row: CoverageRow; columns: CoverageColumn[] }) {
  const byKey = new Map(row.cells.map((cell) => [cell.column_key, cell]))
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell className="sticky left-0 z-10 border-r bg-card align-top">
        <TaskHeader row={row} />
      </TableCell>
      {columns.length ? (
        columns.map((column, index) => {
          const cell = byKey.get(column.key)
          return (
            <TableCell
              key={column.key}
              className={cn(
                "align-top",
                index > 0 && "border-l border-border/60",
                !cell && "bg-muted/35",
              )}
            >
              {cell ? (
                <MatrixCell taskId={row.task_id} column={column} cell={cell} />
              ) : (
                <Untested />
              )}
            </TableCell>
          )
        })
      ) : (
        <TableCell className="bg-muted/35">
          <Untested />
        </TableCell>
      )}
    </TableRow>
  )
}

/* The sticky first column carries the task's overall posture so the row's
   verdict reads before the eye scans across the attack channels. */
function TaskHeader({ row }: { row: CoverageRow }) {
  const tested = row.cells.length
  const breachedCount = row.cells.filter((cell) => cellState(cell) === "breached").length
  const judgedCols = row.cells.filter((cell) => cell.judged > 0).length
  const inconclusiveCols = row.cells.filter(
    (cell) => cell.judged === 0 && cell.inconclusive > 0,
  ).length

  return (
    <div className="grid min-w-0 gap-1.5 py-0.5">
      <span className="max-w-[18rem] truncate font-mono text-sm font-medium" title={row.task_id}>
        {row.task_id}
      </span>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {tested === 0 ? (
          <span className="text-xs text-muted-foreground">not yet tested</span>
        ) : breachedCount > 0 ? (
          <span className="flex items-center gap-1 font-mono text-xs font-medium tabular-nums text-fail-ink">
            <span aria-hidden>⚠</span>
            breached {breachedCount}/{tested}
          </span>
        ) : judgedCols > 0 ? (
          <span className="flex items-center gap-1 font-mono text-xs font-medium tabular-nums text-pass-ink">
            <span aria-hidden>✓</span>
            holds {judgedCols}/{tested} judged
          </span>
        ) : inconclusiveCols > 0 ? (
          <span className="flex items-center gap-1 font-mono text-xs font-medium tabular-nums text-warn-ink">
            <span aria-hidden>!</span>
            inconclusive {inconclusiveCols}/{tested}
          </span>
        ) : (
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {tested} tested · no verdicts
          </span>
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

/* A column head reads three ways. A rostered config that has run looks normal.
   A rostered config never observed reports "not yet run" over an all-untested
   column — the hole in the coverage denominator. A config seen on disk but
   absent from the roster carries a muted "unrostered" mark: a candidate to
   enroll, surfaced but not yet actionable. */
function ColumnHeader({ column, hasRoster }: { column: CoverageColumn; hasRoster: boolean }) {
  const neverRun = column.run_count === 0
  const unrostered = hasRoster && !column.rostered
  return (
    <div className="grid gap-1.5">
      <div className="flex items-center gap-2.5">
        <AgentIcon agent={column.agent} size={20} />
        <div className="grid min-w-0 gap-0.5 leading-tight">
          <span className="truncate text-sm font-medium">
            {AGENT_LABELS[column.agent] ?? column.agent}
          </span>
          <span className="flex min-w-0 items-center gap-1.5 text-xs font-normal">
            <span
              className="max-w-[10rem] truncate font-mono text-muted-foreground"
              title={column.model ?? "model not recorded in run config"}
            >
              {column.model ?? "model not recorded"}
            </span>
            <span className="shrink-0 whitespace-nowrap font-mono tabular-nums text-muted-foreground/70">
              · {neverRun ? "not yet run" : `${column.run_count} run${column.run_count === 1 ? "" : "s"}`}
            </span>
          </span>
        </div>
      </div>
      {unrostered && (
        <span className="w-fit rounded border border-dashed border-border px-1.5 py-px text-[0.65rem] font-medium uppercase tracking-[0.08em] text-muted-foreground/80">
          unrostered
        </span>
      )}
    </div>
  )
}

/* Untested is a main character on this page: honest absence, rendered as a
   deliberate mark on a softly recessed field rather than a stray dash that
   reads like a rendering bug. */
function Untested() {
  return (
    <div className="flex min-h-[3.5rem] items-center justify-center" title="untested">
      <span aria-hidden className="select-none text-base leading-none text-muted-foreground/50">
        —
      </span>
      <span className="sr-only">untested</span>
    </div>
  )
}

function MatrixCell({
  taskId,
  column,
  cell,
}: {
  taskId: string
  column: CoverageColumn
  cell: CoverageCell
}) {
  const navigate = useNavigate()
  const state = cellState(cell)
  const pending = Math.max(0, cell.total - cell.judged - cell.inconclusive)
  const recency = fmtRelative(cell.last_tested)

  const head =
    state === "breached"
      ? { glyph: "⚠", word: "breached", ink: "text-fail-ink" }
      : state === "holds"
        ? { glyph: "✓", word: "holds", ink: "text-pass-ink" }
        : state === "inconclusive"
          ? { glyph: "!", word: "inconclusive", ink: "text-warn-ink" }
        : { glyph: "◌", word: "no verdicts", ink: "text-muted-foreground" }

  const value =
    state === "inconclusive"
      ? `${cell.inconclusive} invalid`
      : state === "no-verdicts"
      ? `${cell.total} run${cell.total === 1 ? "" : "s"}`
      : `${cell.passed}/${cell.judged}`
  const valueInk =
    state === "breached"
      ? "text-fail-ink"
      : state === "holds"
        ? "text-pass-ink"
        : state === "inconclusive"
          ? "text-warn-ink"
        : "text-muted-foreground"

  const body = (
    <div className="grid min-h-[3.5rem] content-start gap-2 py-0.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className={cn("flex items-center gap-1.5 text-xs font-medium", head.ink)}>
          <span aria-hidden className="text-[0.8125rem] leading-none">
            {head.glyph}
          </span>
          {head.word}
        </span>
        {recency && (
          <span className="shrink-0 font-mono text-[0.6875rem] tabular-nums text-muted-foreground">
            {recency}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2.5">
        <AttemptMeter
          passed={cell.passed}
          judged={cell.judged}
          inconclusive={cell.inconclusive}
          total={cell.total}
        />
        <span className={cn("shrink-0 font-mono text-sm font-semibold tabular-nums", valueInk)}>
          {value}
        </span>
      </div>
    </div>
  )

  const ref = cell.recent_refs[0]
  if (!ref) return <div className="px-0.5">{body}</div>

  const configLabel = `${AGENT_LABELS[column.agent] ?? column.agent}${
    column.model ? ` ${column.model}` : ""
  }`
  const stateLabel =
    state === "no-verdicts"
      ? `${cell.total} run${cell.total === 1 ? "" : "s"}, no verdicts yet`
      : state === "inconclusive"
        ? `${cell.inconclusive} inconclusive run${cell.inconclusive === 1 ? "" : "s"}, excluded from HSW scoring`
      : state === "holds"
        ? `holds, 0 of ${cell.judged} judged attempts passed`
        : `breached, ${cell.passed} of ${cell.judged} judged attempts passed`
  const pendingLabel = pending > 0 ? `, ${pending} run${pending === 1 ? "" : "s"} pending` : ""
  const inconclusiveLabel =
    cell.inconclusive > 0 && state !== "inconclusive"
      ? `, ${cell.inconclusive} inconclusive`
      : ""

  return (
    <button
      type="button"
      onClick={() =>
        navigate(
          `/runs/${encodeURIComponent(ref.run_id)}/tasks/${encodeURIComponent(ref.run_task_id)}`,
        )
      }
      aria-label={`${taskId} × ${configLabel}: ${stateLabel}${inconclusiveLabel}${pendingLabel} — open latest task run`}
      className="-mx-2 -my-1.5 block w-[calc(100%+1rem)] rounded-md px-2 py-1.5 text-left transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
    >
      {body}
    </button>
  )
}

/* Attempt meter: one segment per run, read left to right. Filled = the agent
   passed (a breach), neutral = the attempt was judged and held, amber = an
   invalid measurement, hollow-dashed = pending. Breaches group left so the bar
   doubles as a magnitude gauge — the more red from the left, the worse the
   defense held. Large attempt counts collapse to a proportional fill. */
function AttemptMeter({
  passed,
  judged,
  inconclusive,
  total,
}: {
  passed: number
  judged: number
  inconclusive: number
  total: number
}) {
  const held = Math.max(0, judged - passed)
  const pending = Math.max(0, total - judged - inconclusive)

  if (total > 16) {
    const width = (count: number) => `${Math.round((count / total) * 100)}%`
    return (
      <div
        className="flex h-2 w-full overflow-hidden rounded-full border border-dashed border-foreground/20"
        aria-hidden
        title={`${passed}/${judged} judged attempts breached${inconclusive ? `, ${inconclusive} inconclusive` : ""}${pending ? `, ${pending} pending` : ""}`}
      >
        {passed > 0 && <span className="h-full bg-fail" style={{ width: width(passed) }} />}
        {held > 0 && <span className="h-full bg-foreground/[0.14]" style={{ width: width(held) }} />}
        {inconclusive > 0 && (
          <span className="h-full bg-warn-ink/65" style={{ width: width(inconclusive) }} />
        )}
      </div>
    )
  }

  const segments: ("breach" | "held" | "inconclusive" | "pending")[] = [
    ...Array<"breach">(passed).fill("breach"),
    ...Array<"held">(held).fill("held"),
    ...Array<"inconclusive">(inconclusive).fill("inconclusive"),
    ...Array<"pending">(pending).fill("pending"),
  ]
  if (segments.length === 0) {
    return <div className="h-2 w-full rounded-full bg-foreground/10" aria-hidden />
  }

  return (
    <div
      className="flex h-2 flex-1 items-stretch gap-[2px]"
      aria-hidden
      title={`${passed}/${judged} judged attempts breached${inconclusive ? `, ${inconclusive} inconclusive` : ""}${pending ? `, ${pending} pending` : ""}`}
    >
      {segments.map((segment, index) => (
        <span
          key={index}
          className={cn(
            "min-w-[3px] flex-1 rounded-[2px]",
            segment === "breach" && "bg-fail",
            segment === "held" && "bg-foreground/[0.14]",
            segment === "inconclusive" && "bg-warn-ink/65",
            segment === "pending" && "border border-dashed border-foreground/30 bg-transparent",
          )}
        />
      ))}
    </div>
  )
}

function EmptyCoverage() {
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
