import { ArrowUpRight, Layers, SlidersHorizontal } from "lucide-react"
import { Link } from "react-router-dom"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { Profile } from "@/lib/api"
import { cn } from "@/lib/utils"
import { resolveLibraryDir, shortenPath } from "../helpers"
import type { LibraryRef, WizardMode } from "../types"

export function StepMode({
  mode,
  profiles,
  rosteredProfiles,
  defaultProfileId,
  profileId,
  selectedProfile,
  libraries,
  runtimeLabel,
  onChooseProfile,
  onChooseCustom,
}: {
  mode: WizardMode
  profiles: Profile[]
  rosteredProfiles: Profile[]
  defaultProfileId: string | null
  profileId: string | null
  selectedProfile: Profile | null
  libraries: LibraryRef[]
  runtimeLabel: (runtime: string) => string
  onChooseProfile: (id: string) => void
  onChooseCustom: () => void
}) {
  const hasRostered = rosteredProfiles.length > 0
  const profileActive = mode === "profile"
  const customActive = mode === "custom"
  const enterProfile = () => {
    if (!hasRostered || profileActive) return
    const target = profileId ?? rosteredProfiles[0]?.id
    if (target) onChooseProfile(target)
  }
  return (
    <div role="radiogroup" aria-label="Launch mode" className="grid gap-3 sm:grid-cols-2">
      {/* From a profile */}
      {hasRostered ? (
        <div
          role="radio"
          aria-checked={profileActive}
          tabIndex={0}
          onClick={enterProfile}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault()
              enterProfile()
            }
          }}
          className={cn(
            "flex cursor-pointer flex-col gap-3 rounded-xl border bg-card p-5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
            profileActive
              ? "border-primary ring-1 ring-primary"
              : "hover:border-primary/40",
          )}
        >
          <div className="flex items-center gap-2.5">
            <span
              className={cn(
                "grid size-8 shrink-0 place-content-center rounded-lg",
                profileActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
              )}
            >
              <Layers className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold">From a profile</div>
              <div className="text-xs text-muted-foreground">
                Reuse a saved measurement contract
              </div>
            </div>
          </div>
          <p className="text-[13px] leading-5 text-muted-foreground">
            Its roster, task set, and judge prefill the wizard, so these runs land as
            comparable columns in the coverage matrix.
          </p>
          <div onClick={(event) => event.stopPropagation()}>
            <Select value={profileId ?? undefined} onValueChange={onChooseProfile}>
              <SelectTrigger className="w-full" aria-label="Profile">
                <SelectValue placeholder="Choose a profile" />
              </SelectTrigger>
              <SelectContent>
                {rosteredProfiles.map((profile) => (
                  <SelectItem key={profile.id} value={profile.id}>
                    {profile.name}
                    {profile.id === defaultProfileId ? " (default)" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {selectedProfile && (
            <ContractSummary
              profile={selectedProfile}
              libraries={libraries}
              runtimeLabel={runtimeLabel}
            />
          )}
        </div>
      ) : (
        <div className="flex flex-col gap-3 rounded-xl border border-dashed bg-muted/30 p-5">
          <div className="flex items-center gap-2.5">
            <span className="grid size-8 shrink-0 place-content-center rounded-lg bg-muted text-muted-foreground">
              <Layers className="size-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-muted-foreground">From a profile</div>
              <div className="text-xs text-muted-foreground">No contract to reuse yet</div>
            </div>
          </div>
          <p className="text-[13px] leading-5 text-muted-foreground">
            {profiles.length
              ? "No saved profile declares a roster, so none can prefill a comparable run."
              : "No profiles are saved yet."}{" "}
            Define one and its roster in Setup.
          </p>
          <Link
            to="/profiles"
            className="inline-flex w-fit items-center gap-1 text-sm font-medium text-primary hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          >
            Create a profile <ArrowUpRight className="size-3.5" aria-hidden />
          </Link>
        </div>
      )}

      {/* Custom */}
      <div
        role="radio"
        aria-checked={customActive}
        tabIndex={0}
        onClick={onChooseCustom}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            onChooseCustom()
          }
        }}
        className={cn(
          "flex cursor-pointer flex-col gap-3 rounded-xl border bg-card p-5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
          customActive ? "border-primary ring-1 ring-primary" : "hover:border-primary/40",
        )}
      >
        <div className="flex items-center gap-2.5">
          <span
            className={cn(
              "grid size-8 shrink-0 place-content-center rounded-lg",
              customActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
            )}
          >
            <SlidersHorizontal className="size-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-semibold">Custom</div>
            <div className="text-xs text-muted-foreground">Configure everything by hand</div>
          </div>
        </div>
        <p className="text-[13px] leading-5 text-muted-foreground">
          Pick the tasks, agents, and judge yourself. This launches a bare run: no contract
          snapshot, and it will not fill a coverage-matrix column.
        </p>
      </div>
    </div>
  )
}

/* One-line summary of a profile's measurement contract, for the mode card. */
function ContractSummary({
  profile,
  libraries,
  runtimeLabel,
}: {
  profile: Profile
  libraries: LibraryRef[]
  runtimeLabel: (runtime: string) => string
}) {
  const rosterCount = profile.roster?.length ?? 0
  const judgeAgent = String(profile.shared.evaluator_agent ?? "codex")
  const judgeModel = String(profile.shared.evaluator_model ?? "") || "runtime default"
  const repeat = Number(profile.shared.repeat) || 1
  const ts = profile.task_set
  const taskCount = ts?.task_ids?.length ?? 0
  const lib = ts ? resolveLibraryDir(ts.tasks_dir, libraries) : undefined
  const dirLabel = ts ? (lib ? shortenPath(lib.dir) : ts.tasks_dir) : null
  const facts: string[] = [
    `${rosterCount} agent${rosterCount === 1 ? "" : "s"}`,
    `${runtimeLabel(judgeAgent)} · ${judgeModel} judge`,
    `×${repeat} repeat`,
  ]
  if (ts) {
    facts.push(taskCount ? `${taskCount} task${taskCount === 1 ? "" : "s"}` : "no explicit tasks")
  }
  return (
    <div className="mt-1 flex flex-col gap-1 rounded-lg bg-muted/50 px-3 py-2.5 text-[13px] leading-5">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
        {facts.map((fact, index) => (
          <span key={index} className="flex items-center gap-2">
            {index > 0 && <span className="text-border" aria-hidden>·</span>}
            <span>{fact}</span>
          </span>
        ))}
      </div>
      {dirLabel && (
        <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
          <span className="truncate" title={ts?.tasks_dir}>{dirLabel}</span>
          {profile.rev !== undefined && (
            <>
              <span className="text-border" aria-hidden>·</span>
              <span>rev {profile.rev}</span>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/* ---------- step 1: tasks ---------- */
