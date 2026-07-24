import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table"
import {
  ArrowUpDown,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  FlaskConical,
  ListChecks,
  Loader2,
  MoreHorizontal,
  MousePointerClick,
  PencilLine,
  Plus,
  RefreshCw,
  Search,
  Timer,
  TrendingUp,
  XCircle,
} from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { RunStatusChip } from "@/components/verdict"
import { AgentIcon } from "@/components/brand"
import { ErrorNote } from "@/components/error-note"
import { RunRail } from "@/features/run-inspector/RunRail"
import { useAgentCatalog } from "@/hooks/useAgentCatalog"
import { useMinWidth } from "@/hooks/use-min-width"
import { api, type RunOverview, type RunProfileRef } from "@/lib/api"
import { fmtDuration, fmtRelative, shortDir } from "@/lib/format"
import { cn } from "@/lib/utils"

/* The inspector rail needs real horizontal room; below this the ledger keeps
   the whole width and rows navigate directly. */
const RAIL_BREAKPOINT = 1280

/* Runs: KPI strip, filter row, ledger table, and a selected-run inspector rail
   (HSW Eval reference layout). Every figure on this page is computed from the
   runs on disk — nothing invented. */
export default function Runs() {
  const navigate = useNavigate()
  const [sorting, setSorting] = useState<SortingState>([])
  const [filter, setFilter] = useState("")
  const [status, setStatus] = useState("all")
  const [runtime, setRuntime] = useState("all")
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  /* Once the operator dismisses the rail, don't re-open it on the next poll. */
  const dismissed = useRef(false)
  const railVisible = useMinWidth(RAIL_BREAKPOINT)
  const { agentLabel } = useAgentCatalog()
  /* Re-render every 30s so "Last updated" relative text stays honest. */
  const [, tick] = useReducer((x: number) => x + 1, 0)
  useEffect(() => {
    const timer = setInterval(tick, 30_000)
    return () => clearInterval(timer)
  }, [])

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: (query) => {
      if (!autoRefresh) return false
      return query.state.data?.runs.some((run) => run.status === "running") ? 4000 : 30_000
    },
  })
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity })

  /* batch -> member run_ids, computed from the rows themselves (each run's
     run_state records its launch batch), so a member row can link to a
     stateless comparison of its batch. */
  const batchMembers = useMemo(() => {
    const map = new Map<string, string[]>()
    for (const run of runsQuery.data?.runs ?? []) {
      if (!run.batch) continue
      map.set(run.batch, [...(map.get(run.batch) ?? []), run.run_id])
    }
    return map
  }, [runsQuery.data])

  /* Status/runtime filters, then time-descending: the ledger reads
     newest-first by default; column sorts override this ordering. */
  const data = useMemo(() => {
    const all = runsQuery.data?.runs ?? []
    const filtered = all.filter(
      (run) =>
        (status === "all" || run.status === status) &&
        (runtime === "all" || run.executor_agent === runtime),
    )
    return [...filtered].sort((a, b) => startedMs(b) - startedMs(a))
  }, [runsQuery.data, status, runtime])

  /* Runtime filter options come from the data on disk, not a hardcoded list. */
  const runtimeOptions = useMemo(() => {
    const agents = new Set<string>()
    for (const run of runsQuery.data?.runs ?? []) {
      if (run.executor_agent) agents.add(run.executor_agent)
    }
    return [...agents].sort()
  }, [runsQuery.data])

  /* The inspector starts on the newest run — the operator's most common
     question is "how did my latest run go" — and follows clicks from there. */
  useEffect(() => {
    if (!railVisible || selectedId || dismissed.current) return
    if (data.length) setSelectedId(data[0].run_id)
  }, [railVisible, data, selectedId])

  const openRun = useCallback(
    (runId: string) => navigate(`/runs/${encodeURIComponent(runId)}`),
    [navigate],
  )
  const activateRow = (run: RunOverview) => {
    if (!railVisible) {
      openRun(run.run_id)
      return
    }
    setSelectedId(run.run_id)
  }
  const closeRail = () => {
    dismissed.current = true
    setSelectedId(null)
  }

  /* With the inspector open, the ledger keeps identity/verdict columns and the
     rail carries the rest; closing it restores the full ledger. */
  const railOpen = railVisible && selectedId !== null

  const columns = useMemo<ColumnDef<RunOverview>[]>(
    () => [
      {
        id: "run",
        header: "Run",
        cell: ({ row }) => (
          <RunIdCell
            run={row.original}
            compact={railOpen}
            batchRunIds={
              row.original.batch ? batchMembers.get(row.original.batch) : undefined
            }
          />
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <RunStatusChip status={row.original.status} />,
      },
      {
        id: "progress",
        header: "Progress",
        cell: ({ row }) => <ProgressCell run={row.original} />,
      },
      {
        id: "pass_rate",
        accessorFn: (run) =>
          run.judge_totals.single ? (run.judge_passes.single ?? 0) / run.judge_totals.single : -1,
        header: ({ column }) => <SortButton column={column} label="Pass rate" />,
        cell: ({ row }) => <PassRateCell run={row.original} />,
      },
      {
        accessorKey: "task_count",
        header: ({ column }) => <SortButton column={column} label="Tasks" />,
        cell: ({ row }) => (
          <span className="text-sm tabular-nums">{row.original.task_count}</span>
        ),
      },
      {
        id: "runtime",
        header: "Runtime",
        cell: ({ row }) => (
          <ModelCell agent={row.original.executor_agent} model={row.original.executor_model} />
        ),
      },
      {
        id: "evaluator",
        header: "Evaluator",
        cell: ({ row }) => (
          <ModelCell agent={row.original.evaluator_agent} model={row.original.evaluator_model} />
        ),
      },
      {
        id: "updated",
        accessorFn: (run) => startedMs(run),
        header: ({ column }) => <SortButton column={column} label="Updated" />,
        cell: ({ row }) => (
          <span
            className="text-sm text-muted-foreground"
            title={row.original.ended_at ?? row.original.started_at ?? undefined}
          >
            {fmtRelative(row.original.ended_at ?? row.original.started_at) || "–"}
          </span>
        ),
      },
      {
        id: "actions",
        header: () => <span className="sr-only">Actions</span>,
        cell: ({ row }) => (
          <RowActions
            run={row.original}
            batchRunIds={
              row.original.batch ? batchMembers.get(row.original.batch) : undefined
            }
            onOpen={() => openRun(row.original.run_id)}
          />
        ),
      },
    ],
    [batchMembers, railOpen, openRun],
  )

  const table = useReactTable({
    data,
    columns,
    initialState: { pagination: { pageSize: 20 } },
    state: {
      sorting,
      globalFilter: filter,
      columnVisibility: railOpen
        ? { task_count: false, evaluator: false, updated: false }
        : {},
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    globalFilterFn: (row, _columnId, value) =>
      row.original.run_id.toLowerCase().includes(String(value).toLowerCase()) ||
      String(row.original.executor_model ?? "").toLowerCase().includes(String(value).toLowerCase()),
  })

  if (runsQuery.isPending) return <RunsSkeleton />
  if (runsQuery.isError) return <ErrorNote message={(runsQuery.error as Error).message} />

  const runs = runsQuery.data.runs
  const total = runs.length
  const shown = table.getFilteredRowModel().rows.length
  const stats = computeStats(runs)
  const selectedRun = selectedId ? runs.find((run) => run.run_id === selectedId) : undefined
  const pageRows = table.getRowModel().rows
  const pageCount = table.getPageCount()
  const pageIndex = table.getState().pagination.pageIndex

  return (
    <div className="flex flex-col gap-5">
      {/* Page header: title left; primary action + freshness controls right. */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Manage evaluation runs, review status, and compare results in{" "}
            <span className="font-mono" title={meta.data?.runs_dir}>
              {shortDir(meta.data?.runs_dir)}
            </span>
          </p>
        </div>
        <div className="flex flex-col items-end justify-end gap-2 self-stretch">
          {/* The primary "New experiment" action lives in the app top bar. */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>
              Last updated:{" "}
              {runsQuery.dataUpdatedAt
                ? fmtRelative(new Date(runsQuery.dataUpdatedAt).toISOString())
                : "–"}
            </span>
            <RefreshCw className="size-3" aria-hidden />
            <label htmlFor="auto-refresh" className="cursor-pointer select-none">
              Auto refresh
            </label>
            <Switch id="auto-refresh" checked={autoRefresh} onCheckedChange={setAutoRefresh} />
          </div>
        </div>
      </div>

      {/* KPI strip — every figure computed from the runs on disk. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 min-[1700px]:grid-cols-6">
        <StatCard
          icon={ListChecks}
          tint="bg-accent text-accent-foreground"
          label="Total runs"
          value={String(stats.total)}
          sub={stats.last7d > 0 ? `+${stats.last7d} last 7d` : "none in last 7d"}
        />
        <StatCard
          icon={Loader2}
          tint="bg-live-soft text-live-ink"
          label="Active"
          value={String(stats.running)}
          sub={stats.total ? `${Math.round((stats.running / stats.total) * 100)}%` : "–"}
        />
        <StatCard
          icon={CheckCircle2}
          tint="bg-pass-soft text-pass-ink"
          label="Completed"
          value={String(stats.complete)}
          sub={stats.total ? `${Math.round((stats.complete / stats.total) * 100)}%` : "–"}
        />
        <StatCard
          icon={XCircle}
          tint="bg-warn-soft text-warn-ink"
          label="Interrupted"
          value={String(stats.interrupted)}
          sub={stats.total ? `${Math.round((stats.interrupted / stats.total) * 100)}%` : "–"}
        />
        <StatCard
          icon={TrendingUp}
          tint="bg-pass-soft text-pass-ink"
          label="Avg pass rate"
          value={stats.judgedTotal ? `${((stats.judgedPassed / stats.judgedTotal) * 100).toFixed(1)}%` : "–"}
          sub={
            stats.judgedTotal
              ? `${stats.judgedPassed}/${stats.judgedTotal} judged tasks passed`
              : "no judged tasks yet"
          }
        />
        <StatCard
          icon={Timer}
          tint="bg-accent text-accent-foreground"
          label="Total runtime"
          value={stats.runtimeSeconds > 0 ? fmtDuration(stats.runtimeSeconds) : "–"}
          sub={`across ${stats.tasks} task runs`}
        />
      </div>

      <div className="flex min-w-0 items-start gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {/* Filter row, reference-style: search + dimension selects. */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Search runs…"
                aria-label="Search runs by id or model"
                className="h-9 w-56 bg-card pl-8 sm:w-72"
              />
            </div>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="h-9 w-40 bg-card" aria-label="Filter by status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Status · All</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="complete">Completed</SelectItem>
                <SelectItem value="interrupted">Interrupted</SelectItem>
              </SelectContent>
            </Select>
            {runtimeOptions.length > 1 && (
              <Select value={runtime} onValueChange={setRuntime}>
                <SelectTrigger className="h-9 w-44 bg-card" aria-label="Filter by runtime">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Runtime · All</SelectItem>
                  {runtimeOptions.map((agent) => (
                    <SelectItem key={agent} value={agent}>
                      {agentLabel(agent)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <Card className="gap-0 overflow-hidden py-0">
            <div className="flex items-center gap-2 border-b px-4 py-3">
              <h2 className="text-sm font-semibold">
                Runs <span className="font-normal text-muted-foreground">({shown})</span>
              </h2>
              {stats.running > 0 && (
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-live-ink">
                  <span className="size-1.5 animate-pulse rounded-full bg-live" aria-hidden />
                  {stats.running} running
                </span>
              )}
            </div>

            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow
                    key={headerGroup.id}
                    className="hover:bg-transparent [&>th]:h-10 [&>th]:whitespace-nowrap [&>th]:text-xs [&>th]:font-medium [&>th]:text-muted-foreground"
                  >
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id}>
                        {flexRender(header.column.columnDef.header, header.getContext())}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {pageRows.length ? (
                  pageRows.map((row) => {
                    const isSelected = railVisible && row.original.run_id === selectedId
                    return (
                      <TableRow
                        key={row.id}
                        tabIndex={0}
                        aria-selected={isSelected}
                        data-selected={isSelected}
                        className="group/row cursor-pointer data-[selected=true]:bg-accent/50 focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring [&>td]:py-3"
                        onClick={() => activateRow(row.original)}
                        onDoubleClick={() => openRun(row.original.run_id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            if (isSelected) openRun(row.original.run_id)
                            else activateRow(row.original)
                          }
                          if (event.key === "Escape" && isSelected) closeRail()
                        }}
                      >
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id} className="whitespace-nowrap">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </TableCell>
                        ))}
                      </TableRow>
                    )
                  })
                ) : (
                  <TableRow>
                    <TableCell
                      colSpan={table.getVisibleLeafColumns().length}
                      className="h-32 text-center"
                    >
                      {total === 0 ? (
                        <div className="grid justify-items-center gap-2 py-4">
                          <p className="text-sm text-muted-foreground">
                            No runs yet in{" "}
                            <span className="font-mono">{shortDir(meta.data?.runs_dir)}</span>.
                          </p>
                          <Button size="sm" asChild>
                            <Link to="/new">
                              <Plus className="size-4" /> Launch an experiment
                            </Link>
                          </Button>
                        </div>
                      ) : (
                        <span className="text-muted-foreground">No runs match this filter.</span>
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>

            {/* Pagination footer, reference-style. */}
            <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-2.5">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Rows per page</span>
                <Select
                  value={String(table.getState().pagination.pageSize)}
                  onValueChange={(value) => table.setPageSize(Number(value))}
                >
                  <SelectTrigger
                    className="h-8 w-[4.5rem] bg-card"
                    aria-label="Rows per page"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[10, 20, 50].map((size) => (
                      <SelectItem key={size} value={String(size)}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  disabled={!table.getCanPreviousPage()}
                  onClick={() => table.previousPage()}
                  aria-label="Previous page"
                >
                  <ChevronLeft className="size-4" />
                </Button>
                {Array.from({ length: pageCount }, (_, index) => (
                  <Button
                    key={index}
                    variant={index === pageIndex ? "secondary" : "ghost"}
                    size="icon"
                    className="size-8 text-sm tabular-nums"
                    onClick={() => table.setPageIndex(index)}
                    aria-label={`Page ${index + 1}`}
                    aria-current={index === pageIndex ? "page" : undefined}
                  >
                    {index + 1}
                  </Button>
                ))}
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  disabled={!table.getCanNextPage()}
                  onClick={() => table.nextPage()}
                  aria-label="Next page"
                >
                  <ChevronRight className="size-4" />
                </Button>
              </div>
            </div>
          </Card>
        </div>

        {railVisible && total > 0 && (
          <aside className="sticky top-[4.5rem] w-[21rem] shrink-0" aria-label="Run inspector">
            {selectedId ? (
              <RunRail
                runId={selectedId}
                batchRunIds={
                  selectedRun?.batch ? batchMembers.get(selectedRun.batch) : undefined
                }
                onClose={closeRail}
                className="max-h-[calc(100vh-5.5rem)] overflow-y-auto"
              />
            ) : (
              <div className="grid justify-items-center gap-2 rounded-xl border border-dashed bg-card px-6 py-10 text-center">
                <MousePointerClick className="size-5 text-muted-foreground/70" aria-hidden />
                <p className="text-sm text-muted-foreground">Select a run to inspect it here.</p>
              </div>
            )}
          </aside>
        )}
      </div>
    </div>
  )
}

function startedMs(run: RunOverview): number {
  if (!run.started_at) return -Infinity
  const ms = Date.parse(run.started_at)
  return Number.isNaN(ms) ? -Infinity : ms
}

function computeStats(runs: RunOverview[]) {
  const now = Date.now()
  let running = 0
  let complete = 0
  let interrupted = 0
  let last7d = 0
  let judgedPassed = 0
  let judgedTotal = 0
  let tasks = 0
  let runtimeSeconds = 0
  for (const run of runs) {
    if (run.status === "running") running += 1
    else if (run.status === "complete") complete += 1
    else interrupted += 1
    const started = startedMs(run)
    if (Number.isFinite(started) && now - started <= 7 * 86_400_000) last7d += 1
    judgedPassed += run.judge_passes.single ?? 0
    judgedTotal += run.judge_totals.single ?? 0
    tasks += run.task_count
    if (run.started_at && run.ended_at) {
      const span = (Date.parse(run.ended_at) - Date.parse(run.started_at)) / 1000
      if (Number.isFinite(span) && span > 0) runtimeSeconds += span
    }
  }
  return { total: runs.length, running, complete, interrupted, last7d, judgedPassed, judgedTotal, tasks, runtimeSeconds }
}

/* KPI tile: tinted icon chip + muted label, ink number, muted sub-line.
   Numbers wear text tokens, not status colors (dataviz rule). */
function StatCard({
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
    <Card className="gap-2 rounded-xl px-4 py-4">
      <div className="flex items-center gap-2.5">
        <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-full", tint)}>
          <Icon className="size-4" />
        </span>
        <span className="truncate text-sm text-muted-foreground">{label}</span>
      </div>
      <div className="text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      <div className="truncate text-xs text-muted-foreground">{sub}</div>
    </Card>
  )
}

/* Identity cell: run id (mono) with quiet attribution tags underneath. */
function RunIdCell({
  run,
  batchRunIds,
  compact,
}: {
  run: RunOverview
  batchRunIds?: string[]
  compact?: boolean
}) {
  const tags = (run.profile?.modified ? 1 : 0) + (run.batch ? 1 : 0)
  return (
    <div className={cn("min-w-0", compact ? "max-w-[13rem]" : "max-w-[22rem]")}>
      <div className="truncate font-mono text-sm font-medium text-foreground" title={run.run_id}>
        {run.run_id}
      </div>
      {tags > 0 && (
        <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {run.profile?.modified && <AdHocTag profile={run.profile} />}
          {run.batch && <BatchTag batch={run.batch} runIds={batchRunIds ?? [run.run_id]} />}
        </div>
      )}
    </div>
  )
}

/* Percent label above a slim status-colored track (reference progress cell).
   Progress is executor completion, not verdict. */
function ProgressCell({ run }: { run: RunOverview }) {
  const stats = run.executor_stats
  const done = stats.success + stats.failed + stats.timeout + (stats.skipped ?? 0)
  const total = run.task_count
  const pct = total ? Math.round((done / total) * 100) : 0
  const barColor =
    run.status === "running" ? "bg-live" : run.status === "complete" ? "bg-pass" : "bg-warn"
  return (
    <div className="grid w-28 gap-1">
      <span className="text-xs tabular-nums text-muted-foreground">{pct}%</span>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label={`${done} of ${total} executors finished`}
        title={`${done} of ${total} executors finished`}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-300", barColor)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

function PassRateCell({ run }: { run: RunOverview }) {
  const total = run.judge_totals.single ?? 0
  if (!total) return <span className="text-sm text-muted-foreground">–</span>
  const rate = ((run.judge_passes.single ?? 0) / total) * 100
  return (
    <span className="text-sm font-medium tabular-nums" title={`${run.judge_passes.single}/${total} tasks passed`}>
      {rate.toFixed(1)}%
    </span>
  )
}

/* Row overflow menu (reference ⋯ column). */
function RowActions({
  run,
  batchRunIds,
  onOpen,
}: {
  run: RunOverview
  batchRunIds?: string[]
  onOpen: () => void
}) {
  const navigate = useNavigate()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="size-7 text-muted-foreground"
          aria-label={`Actions for run ${run.run_id}`}
          onClick={(event) => event.stopPropagation()}
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" onClick={(event) => event.stopPropagation()}>
        <DropdownMenuItem onSelect={onOpen}>
          <ChevronRight /> Open run details
        </DropdownMenuItem>
        {batchRunIds && batchRunIds.length > 1 && (
          <DropdownMenuItem
            onSelect={() =>
              navigate(`/compare?runs=${encodeURIComponent(batchRunIds.join(","))}`)
            }
          >
            <FlaskConical /> Compare batch ({batchRunIds.length})
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => navigator.clipboard.writeText(run.run_id)}>
          <Copy /> Copy run id
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/* A run launched from a profile but deviating from it: an ad-hoc test. */
function AdHocTag({ profile }: { profile: RunProfileRef }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full bg-warn-soft px-1.5 py-px font-medium text-warn-ink"
      title={`Ad-hoc test — deviated from profile ${profile.id} (rev ${profile.rev}) at launch`}
    >
      <PencilLine className="size-3 shrink-0" aria-hidden />
      ad-hoc
    </span>
  )
}

/* Quiet attribution: a run launched as part of a batch links to a stateless
   comparison of its batch mates. stopPropagation keeps the row click out. */
function BatchTag({ batch, runIds }: { batch: string; runIds: string[] }) {
  return (
    <Link
      to={`/compare?runs=${encodeURIComponent(runIds.join(","))}`}
      aria-label={`Compare batch ${batch}`}
      title={`Launched together as ${batch} — compare ${runIds.length} runs`}
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") event.stopPropagation()
      }}
      className="inline-flex min-w-0 items-center gap-1 rounded-full border border-border bg-background px-1.5 py-px font-mono text-[0.6875rem] leading-4 text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <FlaskConical className="size-3 shrink-0" aria-hidden />
      <span className="truncate">{batch}</span>
    </Link>
  )
}

function SortButton({
  column,
  label,
}: {
  column: { toggleSorting: (desc?: boolean) => void; getIsSorted: () => false | "asc" | "desc" }
  label: string
}) {
  const sorted = column.getIsSorted()
  return (
    <Button
      variant="ghost"
      size="sm"
      className="-ml-2 h-8 gap-1 text-xs font-medium text-muted-foreground data-[active=true]:text-foreground"
      data-active={sorted !== false}
      onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
    >
      {label}
      <ArrowUpDown className="size-3" />
    </Button>
  )
}

function ModelCell({ agent, model }: { agent: string | null; model: string | null }) {
  const { agentLabel } = useAgentCatalog()
  if (!agent) return <span className="text-muted-foreground">–</span>
  return (
    <div className="flex min-w-0 max-w-[12rem] items-center gap-2">
      <AgentIcon agent={agent} size={18} />
      <div className="min-w-0">
        <div className="truncate text-sm">{agentLabel(agent)}</div>
        {model && (
          <div className="truncate font-mono text-xs text-muted-foreground" title={model}>
            {model}
          </div>
        )}
      </div>
    </div>
  )
}

/* Loading mirrors the destination: KPI strip + table well, not a spinner. */
function RunsSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-start justify-between">
        <div>
          <Skeleton className="h-8 w-28" />
          <Skeleton className="mt-2 h-4 w-72" />
        </div>
        <Skeleton className="h-9 w-40" />
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 min-[1700px]:grid-cols-6">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-28 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-9 w-full max-w-md" />
      <Skeleton className="h-72 w-full rounded-xl" />
    </div>
  )
}
