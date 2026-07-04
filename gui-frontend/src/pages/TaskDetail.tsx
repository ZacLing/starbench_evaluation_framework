import { useState } from "react"
import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { toast } from "sonner"
import { ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ExecBadge, RubricBadge, VariantBadge } from "@/components/verdict"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type JudgeAggregate, type TaskRunDetail } from "@/lib/api"
import { fmtDuration, fmtTime } from "@/lib/format"
import { renderMarkdown } from "@/lib/markdown"
import { cn } from "@/lib/utils"

export default function TaskDetail() {
  const { runId = "", taskRunId = "" } = useParams()
  const taskQuery = useQuery({
    queryKey: ["task", runId, taskRunId],
    queryFn: () => api.task(runId, taskRunId),
  })

  if (taskQuery.isPending) return <Skeleton className="h-96" />
  if (taskQuery.isError) return <ErrorNote message={(taskQuery.error as Error).message} />

  const detail = taskQuery.data
  const executor = detail.executor ?? {}
  const rubricCount =
    detail.judges.single?.aggregate.total_count ??
    detail.judges.parallel?.aggregate.total_count ??
    null

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0">
          <h1 className="break-all font-mono text-xl font-semibold tracking-tight">
            {detail.run_task_id}
          </h1>
          <p className="text-sm text-muted-foreground">
            {detail.task_id ?? "unknown task"}
            {executor.started_at && ` · started ${fmtTime(executor.started_at)}`}
            {` · ${fmtDuration(executor.duration_seconds)}`}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <VariantBadge variant={detail.instruction_variant} />
          <ExecBadge status={executor.status} timedOut={executor.timed_out} />
        </div>
      </div>

      <Tabs defaultValue="verdicts">
        <TabsList>
          <TabsTrigger value="verdicts">
            Verdicts{rubricCount !== null && <TabCount value={rubricCount} />}
          </TabsTrigger>
          <TabsTrigger value="trace">
            Trace{detail.raw_event_count > 0 && <TabCount value={detail.raw_event_count} />}
          </TabsTrigger>
          <TabsTrigger value="final">Final message</TabsTrigger>
          <TabsTrigger value="artifacts">
            Artifacts
            {detail.artifact_manifest && <TabCount value={detail.artifact_manifest.file_count} />}
          </TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
        </TabsList>

        <TabsContent value="verdicts" className="mt-4 grid gap-4">
          <VerdictsPane detail={detail} />
        </TabsContent>
        <TabsContent value="trace" className="mt-4 grid gap-4">
          <TracePane detail={detail} runId={runId} taskRunId={taskRunId} />
        </TabsContent>
        <TabsContent value="final" className="mt-4">
          <FinalPane detail={detail} />
        </TabsContent>
        <TabsContent value="artifacts" className="mt-4">
          <ArtifactsPane detail={detail} />
        </TabsContent>
        <TabsContent value="logs" className="mt-4 grid gap-4">
          <LogsPane detail={detail} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function TabCount({ value }: { value: number }) {
  return <span className="ml-1 text-xs text-muted-foreground tabular-nums">{value}</span>
}

/* ---------- verdicts ---------- */

function VerdictsPane({ detail }: { detail: TaskRunDetail }) {
  const modes = (["single", "parallel"] as const).filter((mode) => detail.judges[mode])
  if (!modes.length) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No judge results yet.{" "}
          {detail.evaluated ? "" : "This task run has not been evaluated."}
        </CardContent>
      </Card>
    )
  }
  return (
    <>
      {modes.map((mode) => (
        <JudgePanel
          key={mode}
          mode={mode}
          aggregate={detail.judges[mode]!.aggregate}
          status={detail.judges[mode]!.status}
          questions={detail.rubric_questions}
        />
      ))}
    </>
  )
}

function JudgePanel({
  mode,
  aggregate,
  status,
  questions,
}: {
  mode: string
  aggregate: JudgeAggregate
  status: { status?: string; duration_seconds?: number } | null
  questions: Record<string, string>
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex flex-wrap items-center gap-2 border-b bg-muted/30 px-4 py-3">
        <span className="text-sm font-semibold capitalize">{mode} judge</span>
        {aggregate.overall_pass ? (
          <Badge className="border-transparent bg-pass-soft text-pass-ink">
            ✓ Pass · {aggregate.passed_count}/{aggregate.total_count}
          </Badge>
        ) : (
          <Badge className="border-transparent bg-fail-soft text-fail-ink">
            ✕ Fail · {aggregate.passed_count}/{aggregate.total_count}
          </Badge>
        )}
        {aggregate.fail_fast_failures.length > 0 && (
          <Badge className="border-transparent bg-fail-soft text-fail-ink">
            fail-fast: {aggregate.fail_fast_failures.join(", ")}
          </Badge>
        )}
        {aggregate.missing.length > 0 && (
          <Badge className="border-transparent bg-warn-soft text-warn-ink">
            missing: {aggregate.missing.join(", ")}
          </Badge>
        )}
        {status?.status && (
          <span className="ml-auto text-xs text-muted-foreground">
            judge {status.status} · {fmtDuration(status.duration_seconds)}
          </span>
        )}
      </div>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-8" />
            <TableHead>Rubric</TableHead>
            <TableHead className="w-full">Question</TableHead>
            <TableHead>Expected</TableHead>
            <TableHead>Answer</TableHead>
            <TableHead>Verdict</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {aggregate.results.map((row) => {
            const isOpen = expanded.has(row.rubric_id)
            return [
              <TableRow
                key={row.rubric_id}
                className="cursor-pointer"
                onClick={() => toggle(row.rubric_id)}
              >
                <TableCell>
                  <button
                    type="button"
                    aria-expanded={isOpen}
                    aria-label={`Toggle evidence for ${row.rubric_id}`}
                    className="grid size-6 place-content-center rounded text-muted-foreground hover:bg-muted"
                    onClick={(event) => {
                      event.stopPropagation()
                      toggle(row.rubric_id)
                    }}
                  >
                    <ChevronRight
                      className={cn("size-4 transition-transform", isOpen && "rotate-90")}
                    />
                  </button>
                </TableCell>
                <TableCell className="whitespace-nowrap font-mono text-sm font-medium">
                  {row.rubric_id}
                  {row.fail_fast && (
                    <Badge
                      variant="outline"
                      className="ml-1.5 px-1 text-[10px] text-muted-foreground"
                      title="fail-fast rubric"
                    >
                      ff
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="max-w-[52ch] text-sm">
                  {questions[row.rubric_id] ?? (
                    <span className="text-muted-foreground">question not in manifest</span>
                  )}
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {row.expected ? "Yes" : "No"}
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {row.answer === null || row.answer === undefined
                    ? "–"
                    : row.answer
                      ? "Yes"
                      : "No"}
                </TableCell>
                <TableCell>
                  <RubricBadge passed={row.passed} />
                </TableCell>
              </TableRow>,
              isOpen ? (
                <TableRow key={`${row.rubric_id}-evidence`} className="hover:bg-transparent">
                  <TableCell colSpan={6} className="bg-muted/40 px-6 py-4">
                    <div className="max-w-[72ch]">
                      <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                        Judge evidence
                      </div>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed">
                        {row.evidence || "No evidence text."}
                      </p>
                    </div>
                  </TableCell>
                </TableRow>
              ) : null,
            ]
          })}
        </TableBody>
      </Table>
    </Card>
  )
}

/* ---------- trace ---------- */

function TracePane({
  detail,
  runId,
  taskRunId,
}: {
  detail: TaskRunDetail
  runId: string
  taskRunId: string
}) {
  const trace = detail.trace_summary
  if (!trace) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No trace summary on disk for this task run.
        </CardContent>
      </Card>
    )
  }
  const usageEntries = Object.entries(trace.usage ?? {}).filter(
    ([, value]) => typeof value === "number",
  ) as [string, number][]

  return (
    <>
      {(usageEntries.length > 0 || Object.keys(trace.item_type_counts).length > 0) && (
        <div className="flex flex-wrap gap-2">
          {usageEntries.map(([key, value]) => (
            <StatChip key={key} label={key.replace(/_/g, " ")} value={value.toLocaleString()} />
          ))}
          {Object.entries(trace.item_type_counts).map(([key, value]) => (
            <StatChip key={key} label={key.replace(/_/g, " ")} value={String(value)} />
          ))}
        </div>
      )}

      <TraceSection title="Commands" count={trace.command_executions.length}>
        {trace.command_executions.map((command, index) => (
          <div key={command.id ?? index} className="grid gap-2 px-4 py-3">
            <div className="flex flex-wrap items-baseline gap-2">
              <code className="break-all font-mono text-sm">{command.command}</code>
              <span
                className={cn(
                  "text-xs font-medium tabular-nums",
                  command.exit_code === 0 ? "text-pass-ink" : "text-fail-ink",
                )}
              >
                exit {command.exit_code ?? "?"}
              </span>
            </div>
            {command.aggregated_output && (
              <pre className="max-h-64 overflow-auto rounded-md border bg-muted/50 px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap">
                {command.aggregated_output}
              </pre>
            )}
          </div>
        ))}
      </TraceSection>

      <TraceSection title="Agent messages" count={trace.agent_messages.length}>
        {trace.agent_messages.map((message, index) => (
          <p
            key={message.id ?? index}
            className="max-w-[80ch] whitespace-pre-wrap px-4 py-3 text-sm leading-relaxed"
          >
            {message.text}
          </p>
        ))}
      </TraceSection>

      <TraceSection title="Reasoning" count={trace.reasoning_items.length}>
        {trace.reasoning_items.map((item, index) => (
          <ReasoningRow key={item.id ?? index} text={item.text ?? ""} />
        ))}
      </TraceSection>

      <TraceSection title="File changes" count={trace.file_changes.length}>
        {trace.file_changes.map((change, index) => (
          <pre
            key={change.id ?? index}
            className="mx-4 my-3 overflow-auto rounded-md border bg-muted/50 px-3 py-2 text-xs leading-relaxed"
          >
            {JSON.stringify(change.changes ?? change, null, 2)}
          </pre>
        ))}
      </TraceSection>

      <RawEvents runId={runId} taskRunId={taskRunId} total={detail.raw_event_count} />
    </>
  )
}

function StatChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-baseline gap-1.5 rounded-md border bg-card px-2.5 py-1 text-xs">
      <span className="uppercase tracking-wide text-muted-foreground">{label}</span>
      <span className="font-mono font-medium tabular-nums">{value}</span>
    </span>
  )
}

function TraceSection({
  title,
  count,
  children,
}: {
  title: string
  count: number
  children: React.ReactNode
}) {
  if (!count) return null
  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2.5">
        <span className="text-sm font-semibold">{title}</span>
        <span className="text-xs text-muted-foreground tabular-nums">{count}</span>
      </div>
      <div className="divide-y">{children}</div>
    </Card>
  )
}

function ReasoningRow({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const long = text.length > 220
  return (
    <div className="px-4 py-3">
      <p
        className={cn(
          "max-w-[80ch] whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground",
          long && !open && "line-clamp-3",
        )}
      >
        {text}
      </p>
      {long && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 h-7 px-2 text-xs text-muted-foreground"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Collapse" : "Expand"}
        </Button>
      )}
    </div>
  )
}

function RawEvents({
  runId,
  taskRunId,
  total,
}: {
  runId: string
  taskRunId: string
  total: number
}) {
  const [events, setEvents] = useState<Record<string, unknown>[]>([])
  const [nextOffset, setNextOffset] = useState<number | null>(0)
  const [loading, setLoading] = useState(false)

  const loadMore = async () => {
    if (nextOffset === null) return
    setLoading(true)
    try {
      const page = await api.events(runId, taskRunId, nextOffset)
      setEvents((current) => [...current, ...page.events])
      setNextOffset(page.next_offset)
    } catch (error) {
      toast.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card className="gap-0 overflow-hidden py-0">
      <div className="flex items-center gap-2 border-b bg-muted/30 px-4 py-2.5">
        <span className="text-sm font-semibold">Raw events</span>
        <span className="text-xs text-muted-foreground tabular-nums">{total}</span>
        {(events.length === 0 || nextOffset !== null) && total > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto h-7"
            disabled={loading}
            onClick={loadMore}
          >
            {loading ? "Loading…" : events.length ? `Load more (${total - events.length} left)` : "Load raw events"}
          </Button>
        )}
      </div>
      {events.length > 0 && (
        <div className="divide-y">
          {events.map((event, index) => (
            <details key={index} className="group px-4 py-2">
              <summary className="cursor-pointer list-none font-mono text-xs text-muted-foreground">
                <ChevronRight className="mr-1 inline size-3 transition-transform group-open:rotate-90" />
                #{index} {String((event as { type?: string }).type ?? "event")}
              </summary>
              <pre className="mt-2 overflow-auto rounded-md border bg-muted/50 px-3 py-2 text-xs leading-relaxed">
                {JSON.stringify(event, null, 2)}
              </pre>
            </details>
          ))}
        </div>
      )}
    </Card>
  )
}

/* ---------- final message / artifacts / logs ---------- */

function FinalPane({ detail }: { detail: TaskRunDetail }) {
  if (!detail.final_message) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          No final message captured.
        </CardContent>
      </Card>
    )
  }
  return (
    <Card>
      <CardContent
        className="prose-starbench max-w-[72ch]"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(detail.final_message) }}
      />
    </Card>
  )
}

function ArtifactsPane({ detail }: { detail: TaskRunDetail }) {
  const manifest = detail.artifact_manifest
  const files = manifest?.entries.filter((entry) => entry.kind === "file") ?? []
  if (!manifest || !files.length) {
    return (
      <Card>
        <CardContent className="py-10 text-center text-sm text-muted-foreground">
          {manifest ? "The delivered outputs directory is empty." : "No artifact manifest on disk."}
        </CardContent>
      </Card>
    )
  }
  return (
    <div className="grid gap-2">
      <Card className="overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead>Path</TableHead>
              <TableHead className="text-right">Size</TableHead>
              <TableHead>SHA-256</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {files.map((entry) => (
              <TableRow key={entry.path}>
                <TableCell className="break-all font-mono text-sm">{entry.path}</TableCell>
                <TableCell className="whitespace-nowrap text-right font-mono text-sm tabular-nums">
                  {(entry.size_bytes ?? 0).toLocaleString()} B
                </TableCell>
                <TableCell className="font-mono text-xs text-muted-foreground">
                  {(entry.sha256 ?? "").slice(0, 12)}…
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <p className="font-mono text-xs text-muted-foreground">{manifest.outputs_dir}</p>
    </div>
  )
}

function LogsPane({ detail }: { detail: TaskRunDetail }) {
  const executor = detail.executor
  return (
    <>
      <Card>
        <CardContent className="grid gap-4">
          {executor ? (
            <dl className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-x-6 gap-y-3">
              {(
                [
                  ["status", executor.status],
                  ["exit code", executor.exit_code],
                  ["timed out", executor.timed_out],
                  ["started", executor.started_at],
                  ["ended", executor.ended_at],
                  ["duration", fmtDuration(executor.duration_seconds)],
                ] as [string, unknown][]
              )
                .filter(([, value]) => value !== undefined && value !== null)
                .map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-xs uppercase tracking-wide text-muted-foreground">{key}</dt>
                    <dd className="break-all font-mono text-sm">{String(value)}</dd>
                  </div>
                ))}
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">No executor status recorded.</p>
          )}
          {Array.isArray(executor?.command) && (
            <pre className="overflow-auto rounded-md border bg-muted/50 px-3 py-2 font-mono text-xs leading-relaxed">
              {executor.command.join(" ")}
            </pre>
          )}
        </CardContent>
      </Card>
      <Card className="gap-0 overflow-hidden py-0">
        <div className="border-b bg-muted/30 px-4 py-2.5 text-sm font-semibold">stderr tail</div>
        {detail.stderr_tail ? (
          <pre className="max-h-[480px] overflow-auto bg-muted/40 px-4 py-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
            {detail.stderr_tail}
          </pre>
        ) : (
          <p className="px-4 py-6 text-sm text-muted-foreground">stderr.log is empty or absent.</p>
        )}
      </Card>
    </>
  )
}
