import { Badge } from "@/components/ui/badge"
import { Timer } from "lucide-react"
import { fmtDuration } from "@/lib/format"

/* Task-package facts, badge-ified. These are properties of the task package
   (task.json / human_reference.json / rigors.json), not run settings; the
   same component renders them in the task library and inside the wizard so
   the two surfaces can never disagree. */

export function WebSearchBadge({ allow }: { allow: boolean | null | undefined }) {
  if (allow === true) {
    return (
      <Badge variant="outline" className="text-[11px]" title="This task lets agents search the web (task.json: allow_web_search)">
        web
      </Badge>
    )
  }
  if (allow === false) {
    return (
      <Badge
        variant="outline"
        className="text-[11px] text-muted-foreground"
        title="This task forbids web search (task.json: allow_web_search)"
      >
        no web
      </Badge>
    )
  }
  return null
}

export interface TaskFacts {
  allow_web_search?: boolean | null
  timeout_seconds?: number | null
  has_human_reference?: boolean
  rigor_count?: number
}

export function TaskBadges({ task, showTimeout = true }: { task: TaskFacts; showTimeout?: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <WebSearchBadge allow={task.allow_web_search} />
      {showTimeout && task.timeout_seconds ? (
        <Badge
          variant="outline"
          className="gap-1 text-[11px] text-muted-foreground"
          title="Executor time limit set by the task package"
        >
          <Timer className="size-3" /> {fmtDuration(task.timeout_seconds)}
        </Badge>
      ) : null}
      {task.has_human_reference && (
        <Badge variant="outline" className="text-[11px] text-muted-foreground" title="Ships expert steps for instruction experiments">
          expert steps
        </Badge>
      )}
      {(task.rigor_count ?? 0) > 0 && (
        <Badge variant="outline" className="text-[11px] text-muted-foreground" title="Ships rigor requirements for prompt-assistance experiments">
          {task.rigor_count} {task.rigor_count === 1 ? "rigor" : "rigors"}
        </Badge>
      )}
    </span>
  )
}
