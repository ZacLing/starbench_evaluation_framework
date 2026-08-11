import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react"
import { useEffect } from "react"
import { Card, CardContent } from "@/components/ui/card"
import type { ExperimentPlanItem, PreflightCheck } from "@/lib/api"
import { cn } from "@/lib/utils"
import { usePreflight } from "./use-preflight"

export function PreflightPanel({
  plans,
  runtimeLabel,
  onBlockedChange,
}: {
  plans: ExperimentPlanItem[] | null
  runtimeLabel: (runtime: string) => string
  onBlockedChange: (blocked: boolean) => void
}) {
  const { groups, blocked, loading, error } = usePreflight(plans)
  const judgeChecks = groups[0]?.checks.filter((check) => check.id.startsWith("evaluator")) ?? []

  useEffect(() => {
    onBlockedChange(blocked)
  }, [blocked, onBlockedChange])

  if (!plans) return null

  return (
    <Card className="py-4">
      <CardContent className="grid gap-3 px-4">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold">Ready to run?</span>
          <span className="text-xs text-muted-foreground">
            CLI, credentials, and Docker checks on this machine
          </span>
          {loading && <Loader2 className="ml-auto size-4 animate-spin text-muted-foreground" />}
        </div>
        {error && (
          <p className="text-xs text-fail-ink">Readiness checks failed to load: {error}</p>
        )}
        {groups.map((group) => (
          <div key={group.key} className="grid gap-1">
            <span className="text-xs font-medium">{runtimeLabel(group.agent)}</span>
            {group.checks
              .filter((check) => !check.id.startsWith("evaluator"))
              .map((check) => (
                <PreflightRow key={`${group.key}-${check.id}-${check.label}`} check={check} />
              ))}
          </div>
        ))}
        {judgeChecks.length > 0 && (
          <div className="grid gap-1">
            <span className="text-xs font-medium">
              Judge · {runtimeLabel(plans[0]?.evaluator_agent ?? "codex")}
            </span>
            {judgeChecks.map((check) => (
              <PreflightRow key={`judge-${check.id}-${check.label}`} check={check} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function PreflightRow({ check }: { check: PreflightCheck }) {
  const icon =
    check.status === "ok" ? (
      <CheckCircle2 className="size-3.5 text-pass-ink" />
    ) : check.status === "warn" ? (
      <AlertTriangle className="size-3.5 text-warn-ink" />
    ) : (
      <XCircle className="size-3.5 text-fail-ink" />
    )
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span
        className={cn(
          "shrink-0 font-medium",
          check.status === "fail" && "text-fail-ink",
          check.status === "warn" && "text-warn-ink",
        )}
      >
        {check.label}
      </span>
      {check.hint && <span className="min-w-0 break-all text-muted-foreground">{check.hint}</span>}
    </div>
  )
}
