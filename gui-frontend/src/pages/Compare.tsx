import { useState } from "react"
import { Link, useNavigate, useSearchParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { AgentIcon } from "@/components/brand"
import { useAgentCatalog } from "@/hooks/useAgentCatalog"
import { RunStatusChip, StatusBadge, PassSummaryBadge } from "@/components/verdict"
import { ErrorNote } from "@/components/error-note"
import { api, type CompareRunRow, type MatrixCell } from "@/lib/api"
import { fmtRelative, spanBetween } from "@/lib/format"
import { cn } from "@/lib/utils"

/* Stateless comparison over any set of runs, named entirely by the URL
   (?runs=a,b,c). Nothing is created or persisted: the matrix is computed
   from run artifacts at request time. */
export default function Compare() {
  const [searchParams] = useSearchParams()
  const runIds = (searchParams.get("runs") ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)

  const compareQuery = useQuery({
    queryKey: ["compare", runIds.join(",")],
    queryFn: () => api.compare(runIds),
    enabled: runIds.length > 0,
    refetchInterval: (query) =>
      query.state.data?.runs.some((row) => row.run?.status === "running") ? 3000 : false,
  })
  const agentsQuery = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  const customs = agentsQuery.data?.custom ?? []
  const { agentLabel } = useAgentCatalog()
  const agentIconHint = (agent: string) => customs.find((item) => item.id === agent)?.icon

  if (runIds.length === 0) {
    return <RunPicker />
  }
  if (compareQuery.isPending) return <Skeleton className="h-96" />
  if (compareQuery.isError) return <ErrorNote message={(compareQuery.error as Error).message} />
  const payload = compareQuery.data
  const anyRunning = payload.runs.some((row) => row.run?.status === "running")
  const batches = Array.from(
    new Set(payload.runs.map((row) => row.run?.batch).filter(Boolean)),
  ) as string[]

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">
            Compare {payload.runs.length} runs
          </h1>
          <p className="text-sm text-muted-foreground">
            {batches.length === 1 ? (
              <>
                launched together as <span className="font-mono">{batches[0]}</span> ·{" "}
              </>
            ) : null}
            same rubric, side by side; computed from run artifacts.
          </p>
        </div>
        {anyRunning && (
          <span className="ml-auto">
            <StatusBadge status="running" />
          </span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {payload.runs.map((row) => (
          <RunCard
            key={row.run_id}
            row={row}
            label={row.run ? agentLabel(row.run.executor_agent ?? "") : row.run_id}
            iconHint={row.run ? agentIconHint(row.run.executor_agent ?? "") : undefined}
          />
        ))}
      </div>

      <section className="grid gap-3">
        <div>
          <h2 className="text-base font-semibold">Rubric comparison</h2>
          <p className="text-sm text-muted-foreground">
            Each column is one run; single-judge results.
          </p>
        </div>
        {payload.matrix.length ? (
          payload.matrix.map((taskGroup) => (
            <Card key={taskGroup.task_id} className="gap-0 overflow-hidden py-0">
              <div className="border-b bg-muted/30 px-4 py-2.5 font-mono text-sm font-semibold">
                {taskGroup.task_id}
              </div>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="min-w-56">Rubric</TableHead>
                      {payload.runs.map((row) => (
                        <TableHead key={row.run_id} className="text-center">
                          <span
                            className="inline-flex items-center gap-1.5"
                            title={row.run_id}
                          >
                            {row.run && (
                              <AgentIcon
                                agent={row.run.executor_agent ?? ""}
                                icon={agentIconHint(row.run.executor_agent ?? "")}
                                size={15}
                              />
                            )}
                            <span className="grid justify-items-start normal-case">
                              <span className="text-xs font-semibold">
                                {row.run ? agentLabel(row.run.executor_agent ?? "") : row.run_id}
                              </span>
                              <span className="max-w-32 truncate font-mono text-[10px] font-normal text-muted-foreground">
                                {row.run?.executor_model || "runtime default"}
                              </span>
                            </span>
                          </span>
                        </TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {taskGroup.rubrics.map((rubric) => (
                      <TableRow key={rubric.id}>
                        <TableCell className="max-w-md">
                          <span className="font-mono text-xs font-medium">{rubric.id}</span>
                          <span className="block truncate text-xs text-muted-foreground" title={rubric.question}>
                            {rubric.question}
                          </span>
                        </TableCell>
                        {payload.runs.map((row) => (
                          <MatrixCellView key={row.run_id} cell={rubric.cells[row.run_id]} />
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Card>
          ))
        ) : (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              No judge results on disk yet.{" "}
              {anyRunning ? "The matrix fills in as runs finish." : ""}
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  )
}

/* Entry when the URL names no runs: pick any set of runs to compare. The
   comparison itself stays stateless and URL-named — the picker only builds
   the ?runs= list, so batch siblings and hand-picked sets go through the
   same door. */
function RunPicker() {
  const navigate = useNavigate()
  const runsQuery = useQuery({ queryKey: ["runs"], queryFn: api.runs })
  const { agentLabel, custom } = useAgentCatalog()
  const [selected, setSelected] = useState<string[]>([])
  if (runsQuery.isPending) return <Skeleton className="h-96" />
  if (runsQuery.isError) return <ErrorNote message={(runsQuery.error as Error).message} />
  const runs = [...runsQuery.data.runs].sort((a, b) =>
    (b.started_at ?? "").localeCompare(a.started_at ?? ""),
  )
  const toggle = (runId: string, checked: boolean) =>
    setSelected((current) =>
      checked ? [...current, runId] : current.filter((id) => id !== runId),
    )
  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Compare runs</h1>
        <p className="text-sm text-muted-foreground">
          Pick two or more runs to lay their rubric results side by side — computed from run
          artifacts on disk, nothing is created or persisted.
        </p>
      </div>
      <Card className="gap-0 overflow-hidden py-0">
        {runs.length ? (
          <ul className="divide-y">
            {runs.map((run) => (
              <li key={run.run_id}>
                <label className="flex cursor-pointer items-center gap-3 px-4 py-2.5 hover:bg-muted/40">
                  <Checkbox
                    checked={selected.includes(run.run_id)}
                    onCheckedChange={(checked) => toggle(run.run_id, checked === true)}
                    aria-label={`Select ${run.run_id}`}
                  />
                  <AgentIcon
                    agent={run.executor_agent ?? ""}
                    icon={custom.find((item) => item.id === run.executor_agent)?.icon}
                    size={16}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-mono text-sm">{run.run_id}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {agentLabel(run.executor_agent ?? "")}
                      {run.executor_model ? ` · ${run.executor_model}` : ""}
                    </span>
                  </span>
                  <span className="hidden text-xs text-muted-foreground sm:block">
                    {fmtRelative(run.started_at)}
                  </span>
                  <RunStatusChip status={run.status} />
                </label>
              </li>
            ))}
          </ul>
        ) : (
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No runs on disk yet — launch one first, then compare it against later runs.
          </CardContent>
        )}
      </Card>
      <div className="flex items-center gap-3">
        <Button
          disabled={selected.length < 2}
          onClick={() => navigate(`/compare?runs=${selected.join(",")}`)}
        >
          Compare {selected.length >= 2 ? `${selected.length} runs` : "runs"}
        </Button>
        <span className="text-sm text-muted-foreground" aria-live="polite">
          {selected.length < 2 ? "Select at least two runs." : `${selected.length} selected.`}
        </span>
      </div>
    </div>
  )
}

function RunCard({
  row,
  label,
  iconHint,
}: {
  row: CompareRunRow
  label: string
  iconHint?: string
}) {
  const run = row.run
  return (
    <Card className="py-4">
      <CardContent className="grid gap-2 px-4">
        <div className="flex items-center gap-2">
          {run && <AgentIcon agent={run.executor_agent ?? ""} icon={iconHint} size={20} />}
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">{label}</span>
            <span className="block truncate font-mono text-xs text-muted-foreground">
              {run ? run.executor_model || "runtime default" : row.run_id}
            </span>
          </span>
          {run ? <StatusBadge status={run.status} /> : <Badge variant="secondary">missing</Badge>}
        </div>
        {run && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {run.executor_backend && (
              <Badge variant="outline" className="text-[10px] text-muted-foreground">
                {run.executor_backend}
              </Badge>
            )}
            <span>{spanBetween(run.started_at, run.ended_at, run.status === "running")}</span>
          </div>
        )}
        <div className="flex items-center justify-between">
          {run ? (
            <PassSummaryBadge passed={run.judge_passes.single} total={run.judge_totals.single} />
          ) : (
            <span className="text-xs text-muted-foreground">run directory not found</span>
          )}
          {run && (
            <Link
              to={`/runs/${encodeURIComponent(row.run_id)}`}
              className="text-xs text-primary hover:underline"
            >
              View run →
            </Link>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function MatrixCellView({ cell }: { cell: MatrixCell | undefined }) {
  if (!cell || !cell.total) {
    return <TableCell className="text-center text-muted-foreground">–</TableCell>
  }
  const allPassed = cell.passed === cell.total
  const nonePassed = cell.passed === 0
  return (
    <TableCell className="text-center">
      <span
        className={cn(
          "inline-flex min-w-8 items-center justify-center rounded px-1.5 py-0.5 font-mono text-xs font-semibold tabular-nums",
          allPassed && "bg-pass-soft text-pass-ink",
          nonePassed && "bg-fail-soft text-fail-ink",
          !allPassed && !nonePassed && "bg-warn-soft text-warn-ink",
        )}
        aria-label={allPassed ? "pass" : nonePassed ? "fail" : "partial"}
      >
        {cell.total === 1 ? (allPassed ? "✓" : "✕") : `${cell.passed}/${cell.total}`}
      </span>
    </TableCell>
  )
}
