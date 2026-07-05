import { Link, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { Card, CardContent } from "@/components/ui/card"
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
import { AGENT_LABELS, AgentIcon } from "@/components/brand"
import { StatusBadge, PassSummaryBadge } from "@/components/verdict"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type ExperimentDetail as ExperimentDetailData, type MatrixCell } from "@/lib/api"
import { fmtTime, spanBetween } from "@/lib/format"
import { cn } from "@/lib/utils"

export default function ExperimentDetail() {
  const { experimentId = "" } = useParams()
  const detailQuery = useQuery({
    queryKey: ["experiment", experimentId],
    queryFn: () => api.experiment(experimentId),
    refetchInterval: (query) =>
      query.state.data?.contenders.some((contender) => contender.run?.status === "running")
        ? 3000
        : false,
  })

  if (detailQuery.isPending) return <Skeleton className="h-96" />
  if (detailQuery.isError) return <ErrorNote message={(detailQuery.error as Error).message} />
  const detail = detailQuery.data
  const anyRunning = detail.contenders.some((contender) => contender.run?.status === "running")

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <h1 className="break-all font-mono text-xl font-semibold tracking-tight">
            {detail.id}
          </h1>
          <p className="text-sm text-muted-foreground">
            {fmtTime(detail.created_at)} · {detail.tasks.length || "all"} tasks ×{" "}
            {detail.contenders.length} agents · judge{" "}
            <span className="font-mono">
              {String(detail.shared?.evaluator_model ?? "runtime default")}
            </span>{" "}
            ({String(detail.shared?.judge_mode ?? "single")}) · seed{" "}
            {String(detail.shared?.seed ?? "–")}
          </p>
        </div>
        {anyRunning && (
          <span className="ml-auto">
            <StatusBadge status="running" />
          </span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {detail.contenders.map((contender) => (
          <ContenderCard key={contender.run_id} contender={contender} />
        ))}
      </div>

      <section className="grid gap-3">
        <div>
          <h2 className="text-base font-semibold">Rubric comparison</h2>
          <p className="text-sm text-muted-foreground">
            Same tasks, same judge; each column is one contender.
          </p>
        </div>
        {detail.matrix.length ? (
          detail.matrix.map((taskGroup) => (
            <Card key={taskGroup.task_id} className="gap-0 overflow-hidden py-0">
              <div className="border-b bg-muted/30 px-4 py-2.5 font-mono text-sm font-semibold">
                {taskGroup.task_id}
              </div>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="min-w-56">Rubric</TableHead>
                      {detail.contenders.map((contender) => (
                        <TableHead key={contender.run_id} className="text-center">
                          <span
                            className="inline-flex items-center gap-1.5"
                            title={`${contender.label} (${contender.run_id})`}
                          >
                            <AgentIcon agent={contender.agent} size={15} />
                            <span className="grid justify-items-start normal-case">
                              <span className="text-xs font-semibold">
                                {AGENT_LABELS[contender.agent] ?? contender.agent}
                              </span>
                              <span className="max-w-32 truncate font-mono text-[10px] font-normal text-muted-foreground">
                                {contender.model || "runtime default"}
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
                        {detail.contenders.map((contender) => (
                          <MatrixCellView
                            key={contender.run_id}
                            cell={rubric.cells[contender.run_id]}
                          />
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

function ContenderCard({
  contender,
}: {
  contender: ExperimentDetailData["contenders"][number]
}) {
  const run = contender.run
  return (
    <Card className="py-4">
      <CardContent className="grid gap-2 px-4">
        <div className="flex items-center gap-2">
          <AgentIcon agent={contender.agent} size={20} />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-semibold">
              {AGENT_LABELS[contender.agent] ?? contender.agent}
            </span>
            <span className="block truncate font-mono text-xs text-muted-foreground">
              {contender.model || "runtime default"}
            </span>
          </span>
          {run ? <StatusBadge status={run.status} /> : <Badge variant="secondary">missing</Badge>}
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Badge variant="outline" className="text-[10px] text-muted-foreground">
            {contender.backend}
          </Badge>
          {run && <span>{spanBetween(run.started_at, run.ended_at, run.status === "running")}</span>}
        </div>
        <div className="flex items-center justify-between">
          {run ? (
            <PassSummaryBadge passed={run.judge_passes.single} total={run.judge_totals.single} />
          ) : (
            <span className="text-xs text-muted-foreground">run directory not found</span>
          )}
          {run && (
            <Link
              to={`/runs/${encodeURIComponent(contender.run_id)}`}
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
