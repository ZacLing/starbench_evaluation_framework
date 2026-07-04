import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
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
import { ArrowUpDown, Search } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import { ErrorNote } from "@/pages/Dashboard"
import { api, type RunOverview } from "@/lib/api"
import { fmtTime, spanBetween } from "@/lib/format"

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

  const data = useMemo(() => {
    const runs = runsQuery.data?.runs ?? []
    return status === "all" ? runs : runs.filter((run) => run.status === status)
  }, [runsQuery.data, status])

  const columns = useMemo<ColumnDef<RunOverview>[]>(
    () => [
      {
        accessorKey: "run_id",
        header: ({ column }) => <SortButton column={column} label="Run" />,
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-mono text-sm font-medium">{row.original.run_id}</div>
            <div className="text-xs text-muted-foreground">{fmtTime(row.original.started_at)}</div>
          </div>
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
        id: "executors",
        header: "Executors",
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
        id: "executor",
        header: "Executor",
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
        header: "Duration",
        cell: ({ row }) => (
          <span className="font-mono text-sm tabular-nums text-muted-foreground">
            {spanBetween(
              row.original.started_at,
              row.original.ended_at,
              row.original.status === "running",
            )}
          </span>
        ),
      },
    ],
    [],
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

  return (
    <div className="grid gap-4">
      <ExperimentsSection />
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">All runs</h1>
          <p className="text-sm text-muted-foreground">
            {runsQuery.data.runs.length} in this directory, including experiment members
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Filter by run id or model…"
              className="w-64 pl-8"
            />
          </div>
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-36">
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

      <Card className="overflow-hidden py-0">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="bg-muted/50 hover:bg-muted/50">
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
                  className="cursor-pointer"
                  onClick={() => navigate(`/runs/${encodeURIComponent(row.original.run_id)}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      navigate(`/runs/${encodeURIComponent(row.original.run_id)}`)
                    }
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
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

function ExperimentsSection() {
  const navigate = useNavigate()
  const experimentsQuery = useQuery({
    queryKey: ["experiments"],
    queryFn: api.experiments,
    refetchInterval: (query) =>
      query.state.data?.experiments.some((experiment) =>
        experiment.runs.some((run) => "status" in run && run.status === "running"),
      )
        ? 4000
        : false,
  })
  const experiments = experimentsQuery.data?.experiments ?? []
  if (!experiments.length) return null

  return (
    <section className="grid gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Experiments</h1>
        <p className="text-sm text-muted-foreground">
          One configuration compared across contender runtimes
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {experiments.map((experiment) => {
          const running = experiment.runs.some(
            (run) => "status" in run && run.status === "running",
          )
          return (
            <Card
              key={experiment.id}
              className="cursor-pointer py-4 transition-colors hover:border-primary/40"
              onClick={() => navigate(`/experiments/${encodeURIComponent(experiment.id)}`)}
            >
              <CardContent className="grid gap-2.5 px-4">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-mono text-sm font-semibold">
                    {experiment.id}
                  </span>
                  <StatusBadge status={running ? "running" : "complete"} />
                </div>
                <div className="grid gap-1.5">
                  {experiment.contenders.map((contender) => {
                    const run = experiment.runs.find(
                      (item) => item.run_id === contender.run_id,
                    ) as RunOverview | undefined
                    return (
                      <div key={contender.run_id} className="flex items-center gap-2 text-xs">
                        <AgentIcon agent={contender.agent} size={14} />
                        <span className="min-w-0 flex-1 truncate">
                          <span className="font-medium">
                            {AGENT_LABELS[contender.agent] ?? contender.agent}
                          </span>
                          {contender.model && (
                            <span className="ml-1 font-mono text-muted-foreground">
                              {contender.model}
                            </span>
                          )}
                        </span>
                        {run && run.judge_totals ? (
                          <PassSummaryBadge
                            passed={run.judge_passes.single}
                            total={run.judge_totals.single}
                          />
                        ) : (
                          <span className="text-muted-foreground">–</span>
                        )}
                      </div>
                    )
                  })}
                </div>
                <span className="text-xs text-muted-foreground">
                  {fmtTime(experiment.created_at)} ·{" "}
                  {experiment.tasks.length ? `${experiment.tasks.length} tasks` : "all tasks"}
                </span>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </section>
  )
}

function SortButton({
  column,
  label,
}: {
  column: { toggleSorting: (desc?: boolean) => void; getIsSorted: () => false | "asc" | "desc" }
  label: string
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      className="-ml-2 h-8 text-sm font-medium text-muted-foreground"
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
    <div className="flex min-w-0 items-center gap-2">
      <AgentIcon agent={agent} size={18} />
      <div className="min-w-0">
        <div className="text-sm">{AGENT_LABELS[agent] ?? agent}</div>
        {model && <div className="truncate font-mono text-xs text-muted-foreground">{model}</div>}
      </div>
    </div>
  )
}
