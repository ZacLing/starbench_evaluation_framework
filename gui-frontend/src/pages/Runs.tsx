import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table"
import { ArrowUpDown, FlaskConical, PencilLine, Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
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
import { ExecutorStatsInline, PassSummaryBadge, StatusBadge } from "@/components/verdict"
import { AGENT_LABELS, AgentIcon } from "@/components/brand"
import { ErrorNote } from "@/components/error-note"
import { api, type RunOverview, type RunProfileRef } from "@/lib/api"
import { fmtTime, shortDir, spanBetween } from "@/lib/format"

/* The Runs page is an execution ledger: one row per run, newest first,
   answering "which job, what config, how did it go". Experiments are no longer
   an organizing principle here — a run that belongs to one carries a quiet
   attribution tag that links out to the comparison view. */
export default function Runs() {
  const navigate = useNavigate()
  const [sorting, setSorting] = useState<SortingState>([])
  const [filter, setFilter] = useState("")
  const [status, setStatus] = useState("all")

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: api.runs,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => run.status === "running") ? 4000 : false,
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

  /* Status filter, then time-descending: the ledger reads newest-first by
     default; column sorts (Tasks, Tasks passed) override this ordering. */
  const data = useMemo(() => {
    const all = runsQuery.data?.runs ?? []
    const filtered = status === "all" ? all : all.filter((run) => run.status === status)
    return [...filtered].sort((a, b) => startedMs(b) - startedMs(a))
  }, [runsQuery.data, status])

  const columns = useMemo<ColumnDef<RunOverview>[]>(
    () => [
      {
        id: "run",
        header: () => <span className="pl-1">Run</span>,
        cell: ({ row }) => (
          <RunIdCell
            run={row.original}
            batchRunIds={
              row.original.batch ? batchMembers.get(row.original.batch) : undefined
            }
          />
        ),
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "task_count",
        header: ({ column }) => <SortButton column={column} label="Tasks" />,
        cell: ({ row }) => (
          <span className="font-mono text-sm tabular-nums">{row.original.task_count}</span>
        ),
      },
      {
        id: "task_states",
        header: "Task states",
        cell: ({ row }) => <ExecutorStatsInline stats={row.original.executor_stats} />,
      },
      {
        id: "verdict",
        accessorFn: (run) =>
          run.judge_totals.single ? run.judge_passes.single / run.judge_totals.single : -1,
        header: ({ column }) => <SortButton column={column} label="Tasks passed" />,
        cell: ({ row }) => (
          <PassSummaryBadge
            passed={row.original.judge_passes.single}
            total={row.original.judge_totals.single}
          />
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
        id: "duration",
        header: () => <span className="block text-right">Duration</span>,
        cell: ({ row }) => (
          <span className="block text-right font-mono text-sm tabular-nums text-muted-foreground">
            {spanBetween(
              row.original.started_at,
              row.original.ended_at,
              row.original.status === "running",
            )}
          </span>
        ),
      },
    ],
    [batchMembers],
  )

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    globalFilterFn: (row, _columnId, value) =>
      row.original.run_id.toLowerCase().includes(String(value).toLowerCase()) ||
      String(row.original.executor_model ?? "").toLowerCase().includes(String(value).toLowerCase()),
  })

  if (runsQuery.isPending) return <Skeleton className="h-96" />
  if (runsQuery.isError) return <ErrorNote message={(runsQuery.error as Error).message} />

  const total = runsQuery.data.runs.length
  const shown = table.getRowModel().rows.length
  const runningCount = runsQuery.data.runs.filter((run) => run.status === "running").length

  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Runs</h1>
        <p className="text-sm text-muted-foreground">
          Execution ledger, newest first, in{" "}
          <span className="font-mono" title={meta.data?.runs_dir}>
            {shortDir(meta.data?.runs_dir)}
          </span>
        </p>
      </div>

      <Card className="gap-0 overflow-hidden py-0">
        {/* Filters live in the table's toolbar well, not floating above it. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-muted/40 px-3 py-2.5">
          <span className="text-sm tabular-nums text-muted-foreground">
            {shown === total ? `${total} runs` : `${shown} of ${total} runs`}
          </span>
          {runningCount > 0 && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-live-soft px-2 py-0.5 text-xs font-medium text-live-ink">
              <span className="size-1.5 animate-pulse rounded-full bg-live-ink" aria-hidden />
              {runningCount} running
            </span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter by run id or model…"
                aria-label="Filter runs by id or model"
                className="h-9 w-56 bg-background pl-8 sm:w-64"
              />
            </div>
            <Select value={status} onValueChange={setStatus}>
              <SelectTrigger className="h-9 w-36 bg-background" aria-label="Filter by status">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="complete">Complete</SelectItem>
                <SelectItem value="interrupted">Interrupted</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow
                key={headerGroup.id}
                className="hover:bg-transparent [&>th]:h-9 [&>th]:whitespace-nowrap [&>th]:text-xs [&>th]:font-medium [&>th]:tracking-wide [&>th]:text-muted-foreground"
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
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  tabIndex={0}
                  className="cursor-pointer focus-visible:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  onClick={() => navigate(`/runs/${encodeURIComponent(row.original.run_id)}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      navigate(`/runs/${encodeURIComponent(row.original.run_id)}`)
                    }
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="whitespace-nowrap">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="h-24 text-center text-muted-foreground"
                >
                  No runs match this filter.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  )
}

function startedMs(run: RunOverview): number {
  if (!run.started_at) return -Infinity
  const ms = Date.parse(run.started_at)
  return Number.isNaN(ms) ? -Infinity : ms
}

/* Identity cell: the run id is the ledger's key (mono, prominent); the
   timestamp and batch attribution sit under it as quiet context. */
function RunIdCell({ run, batchRunIds }: { run: RunOverview; batchRunIds?: string[] }) {
  return (
    <div className="min-w-0 max-w-[24rem] pl-1">
      <div
        className="truncate font-mono text-sm font-semibold text-foreground"
        title={run.run_id}
      >
        {run.run_id}
      </div>
      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <time dateTime={run.started_at ?? undefined} title={run.started_at ?? undefined}>
          {fmtTime(run.started_at)}
        </time>
        {run.profile?.modified && <AdHocTag profile={run.profile} />}
        {run.batch && (
          <BatchTag batch={run.batch} runIds={batchRunIds ?? [run.run_id]} />
        )}
      </div>
    </div>
  )
}

/* A run launched from a profile but deviating from it: an ad-hoc test. The
   deviation lives in the run's own snapshot, not in the profile. Glyph + word,
   never color alone; muted amber keeps it quiet against faithful runs. */
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
   comparison of its batch mates (computed from artifacts, nothing stored).
   stopPropagation keeps the row's own click/Enter from firing. */
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
      className="-ml-2 h-8 gap-1 text-xs font-medium tracking-wide text-muted-foreground data-[active=true]:text-foreground"
      data-active={sorted !== false}
      onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
    >
      {label}
      <ArrowUpDown className="size-3" />
    </Button>
  )
}

function ModelCell({ agent, model }: { agent: string | null; model: string | null }) {
  if (!agent) return <span className="text-muted-foreground">–</span>
  return (
    <div className="flex min-w-0 max-w-[12rem] items-center gap-2">
      <AgentIcon agent={agent} size={18} />
      <div className="min-w-0">
        <div className="truncate text-sm">{AGENT_LABELS[agent] ?? agent}</div>
        {model && (
          <div className="truncate font-mono text-xs text-muted-foreground" title={model}>
            {model}
          </div>
        )}
      </div>
    </div>
  )
}
