import { Check, PencilLine } from "lucide-react"
import { fmtDuration } from "@/lib/format"
import type { TaskPackage } from "@/lib/api"
import { cn } from "@/lib/utils"
import { NEW_RUN_STEPS } from "./constants"
import { deviationLabel } from "./helpers"

export function Stepper({
  current,
  onSelect,
}: {
  current: number
  onSelect: (step: number) => void
}) {
  return (
    <div className="-mx-1 min-w-0 overflow-x-auto px-1 pb-1">
      <ol className="flex min-w-max items-center gap-2 sm:min-w-0">
        {NEW_RUN_STEPS.map((label, index) => {
          const done = index < current
          const active = index === current
          return (
            <li key={label} className="flex min-w-0 flex-none items-center gap-2 sm:flex-1">
              <button
                type="button"
                disabled={index > current}
                onClick={() => onSelect(index)}
                className={cn(
                  "flex min-w-0 shrink-0 items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors sm:shrink",
                  active ? "font-semibold text-foreground" : "text-muted-foreground",
                  done && "hover:text-foreground",
                )}
              >
                <span
                  className={cn(
                    "grid size-6 shrink-0 place-content-center rounded-full border text-xs font-semibold",
                    active && "border-primary bg-primary text-primary-foreground",
                    done && "border-pass-ink/40 bg-pass-soft text-pass-ink",
                    !active && !done && "border-border bg-muted text-muted-foreground",
                  )}
                >
                  {done ? <Check className="size-3.5" /> : index + 1}
                </span>
                <span className="truncate">{label}</span>
              </button>
              {index < NEW_RUN_STEPS.length - 1 && (
                <div className="h-px w-10 flex-none bg-border sm:flex-1" />
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

export function ContractStatusBar({
  profileName,
  rev,
  verified,
  checking,
  modified,
  fields,
}: {
  profileName: string
  rev?: number
  verified: boolean
  checking?: boolean
  modified: boolean
  fields: string[]
}) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
      <span className="text-muted-foreground">
        Under <span className="font-medium text-foreground">{profileName}</span>
        {rev !== undefined && (
          <>
            <span className="text-border"> · </span>
            <span className="font-mono">rev {rev}</span>
          </>
        )}
      </span>
      {!verified ? (
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          {checking ? "checking contract changes…" : "contract changes verified on Review"}
        </span>
      ) : modified ? (
        <span
          className="inline-flex items-center gap-1.5 rounded-md bg-warn-soft px-2 py-0.5 font-medium text-warn-ink"
          title={`Deviates from the profile at: ${fields.map(deviationLabel).join(", ")}`}
        >
          <PencilLine className="size-3.5 shrink-0" aria-hidden />
          modified
          <span className="font-normal text-warn-ink/80">
            · {fields.length} change{fields.length === 1 ? "" : "s"}
          </span>
        </span>
      ) : (
        <span className="inline-flex items-center gap-1.5 text-muted-foreground">
          <Check className="size-3.5 shrink-0 text-pass" aria-hidden />
          matches the contract
        </span>
      )}
    </div>
  )
}

export function TaskFactsStrip({ tasks }: { tasks: TaskPackage[] }) {
  if (!tasks.length) return null
  const webOn = tasks.filter((task) => task.allow_web_search === true).length
  const webOff = tasks.filter((task) => task.allow_web_search === false).length
  const maxTimeout = Math.max(0, ...tasks.map((task) => task.timeout_seconds ?? 0))
  const withSteps = tasks.filter((task) => task.has_human_reference).length
  const rigors = tasks.reduce((sum, task) => sum + (task.rigor_count ?? 0), 0)
  const webLabel =
    webOn === tasks.length
      ? "web search allowed"
      : webOn === 0
        ? webOff > 0
          ? "web search off"
          : "web search not declared"
        : `web search on ${webOn}/${tasks.length}`

  return (
    <div
      className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-muted/40 px-3 py-2 text-xs text-muted-foreground"
      title="Facts set by the selected task packages, not by this run's configuration"
    >
      <span className="font-medium text-foreground">
        {tasks.length} task{tasks.length === 1 ? "" : "s"}
      </span>
      <span>{webLabel}</span>
      {maxTimeout > 0 && <span>up to {fmtDuration(maxTimeout)} each</span>}
      {withSteps > 0 && (
        <span>
          expert steps in {withSteps}/{tasks.length}
        </span>
      )}
      {rigors > 0 && (
        <span>
          {rigors} rigor requirement{rigors === 1 ? "" : "s"}
        </span>
      )}
      <span className="ml-auto hidden text-[11px] sm:inline">set by the task packages</span>
    </div>
  )
}
