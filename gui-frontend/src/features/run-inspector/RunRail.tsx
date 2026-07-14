import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock,
  Copy,
  FlaskConical,
  HelpCircle,
  X,
  XCircle,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { RunStatusChip } from "@/components/verdict"
import { AGENT_LABELS, AgentIcon } from "@/components/brand"
import { ErrorNote } from "@/components/error-note"
import { api, type RunDetail, type TaskRow } from "@/lib/api"
import { fmtDuration, fmtRelative, fmtTime, spanBetween } from "@/lib/format"
import { cn } from "@/lib/utils"

const TASK_PREVIEW_LIMIT = 6

/* Selected-run inspector (reference "Selected Evaluation" panel): summary card
   with a metrics grid, configuration facts, per-task activity, quick actions.
   Same query key as the detail page, so opening the run lands on warm cache.
   Everything shown is read from the run's artifacts on disk. */
export function RunRail({
  runId,
  batchRunIds,
  onClose,
  className,
}: {
  runId: string
  batchRunIds?: string[]
  onClose: () => void
  className?: string
}) {
  const query = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.run(runId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 4000 : false),
  })

  return (
    <div className={cn("flex flex-col gap-3", className)} aria-label={`Run ${runId} summary`}>
      <Card className="gap-0 rounded-xl py-0">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">Selected run</h2>
          <Button
            variant="ghost"
            size="icon"
            className="-mr-1.5 size-7 text-muted-foreground"
            onClick={onClose}
            aria-label="Close run inspector"
          >
            <X className="size-4" />
          </Button>
        </div>

        {query.isPending && <RailSkeleton />}
        {query.isError && (
          <div className="p-4">
            <ErrorNote message={(query.error as Error).message} />
          </div>
        )}
        {query.data && <SummaryBlock run={query.data} />}
      </Card>

      {query.data && (
        <>
          <ConfigCard run={query.data} />
          <TasksCard run={query.data} />
          <QuickActionsCard run={query.data} batchRunIds={batchRunIds} />
        </>
      )}
    </div>
  )
}

/* Title + status chip, context line, then a 2×2 metrics grid. Numbers wear
   ink, not status colors. */
function SummaryBlock({ run }: { run: RunDetail }) {
  const judged = run.judge_totals.single ?? 0
  const passed = run.judge_passes.single ?? 0
  const stats = run.executor_stats
  const done = stats.success + stats.failed + stats.timeout + (stats.skipped ?? 0)
  return (
    <div className="grid gap-3 px-4 py-4">
      <div className="grid gap-1.5">
        <div className="flex items-start justify-between gap-2">
          <span className="break-all font-mono text-sm font-semibold leading-5" title={run.run_id}>
            {run.run_id}
          </span>
          <span className="shrink-0 pt-px">
            <RunStatusChip status={run.status} />
          </span>
        </div>
        <span className="text-xs text-muted-foreground">
          {run.executor_agent ? (AGENT_LABELS[run.executor_agent] ?? run.executor_agent) : "–"}
          {run.executor_model ? ` · ${run.executor_model}` : ""} · {run.task_count} tasks
        </span>
      </div>

      {run.status === "running" && run.task_count > 0 && (
        <div className="grid gap-1">
          <div
            className="h-1.5 overflow-hidden rounded-full bg-muted"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={run.task_count}
            aria-valuenow={done}
            aria-label={`${done} of ${run.task_count} executors finished`}
          >
            <div
              className="h-full rounded-full bg-live transition-[width] duration-300"
              style={{ width: `${Math.round((done / run.task_count) * 100)}%` }}
            />
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {done} of {run.task_count} executors finished
          </span>
        </div>
      )}

      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        <Metric label="Pass rate" value={judged ? `${((passed / judged) * 100).toFixed(1)}%` : "–"} />
        <Metric label="Tasks passed" value={judged ? `${passed}/${judged}` : "–"} />
        <Metric
          label="Duration"
          value={spanBetween(run.started_at, run.ended_at, run.status === "running")}
        />
        <Metric label="Started" value={fmtRelative(run.started_at) || "–"} title={fmtTime(run.started_at)} />
      </div>
    </div>
  )
}

function Metric({ label, value, title }: { label: string; value: string; title?: string }) {
  return (
    <div className="grid gap-0.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tabular-nums tracking-tight" title={title}>
        {value}
      </span>
    </div>
  )
}

/* Configuration facts straight from run_state; null facts are omitted. */
function ConfigCard({ run }: { run: RunDetail }) {
  return (
    <Card className="gap-0 rounded-xl py-0">
      <h3 className="border-b px-4 py-3 text-sm font-semibold">Configuration</h3>
      <dl className="grid gap-2.5 px-4 py-3.5">
        {run.evaluator_agent && (
          <ConfigRow label="Evaluator">
            <span className="flex min-w-0 items-center justify-end gap-1.5">
              <AgentIcon agent={run.evaluator_agent} size={14} />
              <span className="truncate" title={run.evaluator_model ?? undefined}>
                {run.evaluator_model ?? AGENT_LABELS[run.evaluator_agent] ?? run.evaluator_agent}
              </span>
            </span>
          </ConfigRow>
        )}
        {run.judge_mode && <ConfigRow label="Judge mode">{run.judge_mode}</ConfigRow>}
        {run.executor_backend && <ConfigRow label="Backend">{run.executor_backend}</ConfigRow>}
        {run.seed !== null && <ConfigRow label="Seed">{run.seed}</ConfigRow>}
        {run.instruction_mode && <ConfigRow label="Instructions">{run.instruction_mode}</ConfigRow>}
        {run.profile && (
          <ConfigRow label="Profile">
            {run.profile.id} · rev {run.profile.rev}
            {run.profile.modified ? " · modified" : ""}
          </ConfigRow>
        )}
      </dl>
    </Card>
  )
}

function ConfigRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="shrink-0 text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right font-mono text-xs text-foreground">{children}</dd>
    </div>
  )
}

/* Per-task outcomes as an activity list (reference "Recent Activity"):
   colored icon, id, duration; the outcome word lives in the title tooltip
   and the icon shape (never color alone). */
function TasksCard({ run }: { run: RunDetail }) {
  const mode = run.judge_mode ?? "single"
  const preview = run.tasks.slice(0, TASK_PREVIEW_LIMIT)
  return (
    <Card className="gap-0 rounded-xl py-0">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <h3 className="text-sm font-semibold">
          Tasks <span className="font-normal text-muted-foreground">({run.tasks.length})</span>
        </h3>
        <Link
          to={`/runs/${encodeURIComponent(run.run_id)}`}
          className="text-xs font-medium text-primary hover:underline"
        >
          View all
        </Link>
      </div>
      {run.tasks.length === 0 ? (
        <p className="px-4 py-3.5 text-sm text-muted-foreground">No task runs on disk yet.</p>
      ) : (
        <ul className="px-2 py-1.5">
          {preview.map((task) => {
            const outcome = taskOutcome(task, mode)
            return (
              <li key={task.run_task_id}>
                <Link
                  to={`/runs/${encodeURIComponent(run.run_id)}/tasks/${encodeURIComponent(task.run_task_id)}`}
                  className="flex items-center gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  title={`${task.task_id ?? task.run_task_id} — ${outcome.label}`}
                >
                  <outcome.icon className={cn("size-4 shrink-0", outcome.className)} aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-mono text-[0.8125rem]">
                    {task.task_id ?? task.run_task_id}
                  </span>
                  <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                    {task.executor_duration_seconds !== null
                      ? fmtDuration(task.executor_duration_seconds)
                      : outcome.label}
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

/* Judged verdict first; executor state as the fallback for unjudged tasks. */
function taskOutcome(task: TaskRow, mode: string) {
  const cell = task.judges?.[mode]
  if (cell && cell.overall_pass !== null && cell.overall_pass !== undefined) {
    return cell.overall_pass
      ? { icon: CheckCircle2, className: "text-pass", label: `passed ${cell.passed_count}/${cell.total_count}` }
      : { icon: XCircle, className: "text-fail", label: `failed ${cell.passed_count}/${cell.total_count}` }
  }
  if (cell && cell.outcome) {
    return { icon: HelpCircle, className: "text-warn", label: "inconclusive" }
  }
  if (task.executor_status === "timeout" || task.executor_timed_out) {
    return { icon: Clock, className: "text-warn", label: "timeout" }
  }
  if (task.executor_status === "failed") {
    return { icon: XCircle, className: "text-fail", label: "executor failed" }
  }
  if (task.executor_status === "success") {
    return { icon: CheckCircle2, className: "text-muted-foreground", label: "not judged" }
  }
  return { icon: CircleDashed, className: "text-muted-foreground", label: "pending" }
}

/* Reference "Quick Actions": rows with leading icon and trailing chevron. */
function QuickActionsCard({
  run,
  batchRunIds,
}: {
  run: RunDetail
  batchRunIds?: string[]
}) {
  const navigate = useNavigate()
  const [copied, setCopied] = useState(false)
  return (
    <Card className="gap-0 rounded-xl py-0">
      <h3 className="border-b px-4 py-3 text-sm font-semibold">Quick actions</h3>
      <div className="grid px-2 py-1.5">
        <ActionRow
          icon={ArrowRight}
          label="Open run details"
          onClick={() => navigate(`/runs/${encodeURIComponent(run.run_id)}`)}
        />
        {batchRunIds && batchRunIds.length > 1 && (
          <ActionRow
            icon={FlaskConical}
            label={`Compare batch (${batchRunIds.length} runs)`}
            onClick={() =>
              navigate(`/compare?runs=${encodeURIComponent(batchRunIds.join(","))}`)
            }
          />
        )}
        <ActionRow
          icon={copied ? Check : Copy}
          label={copied ? "Copied" : "Copy run id"}
          onClick={() => {
            navigator.clipboard.writeText(run.run_id)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        />
      </div>
    </Card>
  )
}

function ActionRow({
  icon: Icon,
  label,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-left text-sm transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" aria-hidden />
    </button>
  )
}

function RailSkeleton() {
  return (
    <div className="grid gap-3 p-4">
      <Skeleton className="h-6 w-2/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-16 w-full" />
    </div>
  )
}
