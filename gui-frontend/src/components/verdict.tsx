import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { ExecutorStats, JudgeCell } from "@/lib/api"

/* Verdicts are always glyph + word + color, never color alone. */

export function StatusBadge({ status }: { status: string }) {
  if (status === "running") {
    return (
      <Badge className="gap-1.5 border-transparent bg-live-soft text-live-ink">
        <span className="size-1.5 animate-pulse rounded-full bg-live-ink" aria-hidden />
        Running
      </Badge>
    )
  }
  if (status === "complete") {
    return <Badge className="border-transparent bg-pass-soft text-pass-ink">✓ Complete</Badge>
  }
  return <Badge className="border-transparent bg-warn-soft text-warn-ink">⊘ Interrupted</Badge>
}

export function ExecBadge({
  status,
  timedOut,
}: {
  status: string | null | undefined
  timedOut?: boolean | null
}) {
  if (status === "success") {
    return <Badge className="border-transparent bg-pass-soft text-pass-ink">✓ Success</Badge>
  }
  if (status === "timeout" || timedOut) {
    return <Badge className="border-transparent bg-warn-soft text-warn-ink">◷ Timeout</Badge>
  }
  if (status === "failed") {
    return <Badge className="border-transparent bg-fail-soft text-fail-ink">✕ Failed</Badge>
  }
  if (!status) {
    return <Badge variant="secondary">Pending</Badge>
  }
  return <Badge variant="secondary">{status}</Badge>
}

export function VerdictBadge({ cell }: { cell: JudgeCell | null | undefined }) {
  if (!cell || cell.total_count === null || cell.total_count === undefined) {
    return <span className="text-muted-foreground">–</span>
  }
  if (
    cell.overall_pass === null ||
    cell.outcome === "inconclusive_judge" ||
    cell.outcome === "inconclusive_executor" ||
    cell.outcome === "invalid_task"
  ) {
    return (
      <Badge className="border-transparent bg-warn-soft text-warn-ink">
        ◌ Inconclusive
      </Badge>
    )
  }
  const count = `${cell.passed_count}/${cell.total_count}`
  return cell.overall_pass ? (
    <Badge className="border-transparent bg-pass-soft font-mono text-pass-ink tabular-nums">
      ✓ {count}
    </Badge>
  ) : (
    <Badge className="border-transparent bg-fail-soft font-mono text-fail-ink tabular-nums">
      ✕ {count}
    </Badge>
  )
}

export function RubricBadge({ passed }: { passed: boolean | null }) {
  if (passed === null) {
    return <Badge variant="secondary">Not judged</Badge>
  }
  return passed ? (
    <Badge className="border-transparent bg-pass-soft text-pass-ink">✓ Pass</Badge>
  ) : (
    <Badge className="border-transparent bg-fail-soft text-fail-ink">✕ Fail</Badge>
  )
}

export function ExecutorStatsInline({ stats }: { stats: ExecutorStats }) {
  const parts: { key: string; label: string; className: string }[] = []
  if (stats.success) parts.push({ key: "s", label: `${stats.success} ✓`, className: "text-pass-ink" })
  if (stats.failed) parts.push({ key: "f", label: `${stats.failed} ✕`, className: "text-fail-ink" })
  if (stats.timeout) parts.push({ key: "t", label: `${stats.timeout} ◷`, className: "text-warn-ink" })
  if (stats.pending) parts.push({ key: "p", label: `${stats.pending} pending`, className: "text-muted-foreground" })
  if (!parts.length) return <span className="text-muted-foreground">–</span>
  return (
    <span className="font-mono text-sm tabular-nums">
      {parts.map((part, index) => (
        <span key={part.key} className={cn(part.className, index > 0 && "ml-2")}>
          {part.label}
        </span>
      ))}
    </span>
  )
}

/* Run-level rollup: all pass / partial / none. Partial is a state of its own,
   not a failure; keep red for the zero case. */
export function PassSummaryBadge({ passed, total }: { passed: number; total: number }) {
  if (!total) return <span className="text-muted-foreground">–</span>
  const count = `${passed}/${total}`
  if (passed === total) {
    return (
      <Badge className="border-transparent bg-pass-soft font-mono text-pass-ink tabular-nums">
        ✓ {count}
      </Badge>
    )
  }
  if (passed === 0) {
    return (
      <Badge className="border-transparent bg-fail-soft font-mono text-fail-ink tabular-nums">
        ✕ {count}
      </Badge>
    )
  }
  return (
    <Badge className="border-transparent bg-warn-soft font-mono text-warn-ink tabular-nums">
      ◑ {count}
    </Badge>
  )
}

export function VariantBadge({ variant }: { variant: string | null }) {
  if (!variant || variant === "baseline") {
    return <Badge variant="outline" className="text-muted-foreground">baseline</Badge>
  }
  return (
    <Badge className="border-transparent bg-accent font-mono text-accent-foreground">
      {variant}
    </Badge>
  )
}
