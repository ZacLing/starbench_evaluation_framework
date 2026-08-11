import { useEffect, useState, type Dispatch, type SetStateAction } from "react"
import { ChevronDown } from "lucide-react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import type { SharedConfig, SkillsPayload } from "@/lib/api"
import { cn } from "@/lib/utils"
import { getSkillMode, setSkillMode, type SkillMode } from "../skill-modes"

export function ExecutorSkillsBlock({
  skills,
  shared,
  setShared,
}: {
  skills?: SkillsPayload
  shared: Partial<SharedConfig>
  setShared: Dispatch<SetStateAction<Partial<SharedConfig>>>
}) {
  const selectedGroups = shared.executor_skill_groups ?? []
  const selectedSkills = shared.executor_skills ?? []
  const requiredSkills = shared.required_executor_skills ?? []
  const skillsActive = selectedGroups.length + selectedSkills.length + requiredSkills.length > 0
  /* Hooks stay above the empty-library early return (rules of hooks). */
  const [open, setOpen] = useState(skillsActive)
  useEffect(() => {
    if (skillsActive) setOpen(true)
  }, [skillsActive])

  // Hidden entirely when the library is empty or unreadable — nothing to inject.
  if (!skills || skills.error || skills.skills.length === 0) return null
  const coveredByGroup = new Set<string>()
  for (const group of selectedGroups) {
    for (const id of skills.groups[group] ?? []) coveredByGroup.add(id)
  }
  const selectedTotal = new Set<string>([
    ...coveredByGroup,
    ...selectedSkills,
    ...requiredSkills,
  ])
  const groupNames = Object.keys(skills.groups)

  const toggleGroup = (group: string, on: boolean) =>
    setShared((current) => {
      const groups = new Set(current.executor_skill_groups ?? [])
      const individual = new Set(current.executor_skills ?? [])
      if (on) {
        groups.add(group)
        for (const id of skills.groups[group] ?? []) individual.delete(id)
      } else {
        groups.delete(group)
      }
      return {
        ...current,
        executor_skill_groups: [...groups],
        executor_skills: [...individual],
      }
    })

  const chooseSkillMode = (id: string, mode: SkillMode, inGroup: boolean) =>
    setShared((current) => setSkillMode(current, id, mode, inGroup))

  const skillsSummary = skillsActive
    ? [
        selectedSkills.length
          ? `${selectedSkills.length} skill${selectedSkills.length === 1 ? "" : "s"}`
          : "",
        requiredSkills.length
          ? `${requiredSkills.length} required`
          : "",
        selectedGroups.length
          ? `${selectedGroups.length} group${selectedGroups.length === 1 ? "" : "s"}`
          : "",
      ]
        .filter(Boolean)
        .join(" · ")
    : "none selected"

  return (
    <Card className={open ? undefined : "py-3"}>
      <CardContent className="grid gap-4">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full flex-wrap items-center gap-2 text-left"
        >
          <span className="text-sm font-semibold">Executor skills</span>
          {open ? (
            <span className="text-xs text-muted-foreground">
              Expert guidance installed into every agent's workspace for this run. Shared
              across all agents, like the judge, so the comparison stays fair.
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">{skillsSummary}</span>
          )}
          <span
            className={cn(
              "ml-auto size-1.5 rounded-full",
              skillsActive ? "bg-live-ink" : "bg-muted-foreground/40",
            )}
            aria-hidden
          />
          <ChevronDown
            className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </button>
        {open && (
          <>
        <div className="-mt-2 flex justify-end">
          <Link to="/skills" className="text-xs text-primary hover:underline">
            Browse the skill library
          </Link>
        </div>

        {groupNames.length > 0 && (
          <div className="grid gap-2">
            <Label className="text-xs text-muted-foreground">Groups</Label>
            <div className="grid gap-2 sm:grid-cols-2">
              {groupNames.map((group) => {
                const members = skills.groups[group] ?? []
                const checked = selectedGroups.includes(group)
                return (
                  <label
                    key={group}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                      checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                    )}
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={checked}
                      onCheckedChange={(value) => toggleGroup(group, value === true)}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{group}</span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {members.length} skill{members.length === 1 ? "" : "s"}: {members.join(", ")}
                      </span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        )}

        <div className="grid gap-2">
          <Label className="text-xs text-muted-foreground">Individual skills</Label>
          <div className="grid gap-2 sm:grid-cols-2">
            {skills.skills.map((skill) => {
              const inGroup = coveredByGroup.has(skill.id)
              const mode = getSkillMode(shared, skill.id, inGroup)
              return (
                <div
                  key={skill.id}
                  className={cn(
                    "grid gap-3 rounded-md border p-3 transition-colors",
                    mode === "available" && "border-primary bg-accent/60",
                    mode === "required" && "border-warn-ink/40 bg-warn-soft/50",
                  )}
                >
                  <div className="min-w-0">
                    <span className="block truncate font-mono text-sm font-medium">{skill.id}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {inGroup && mode !== "required"
                        ? "Available through a selected group"
                        : skill.description || "—"}
                    </span>
                  </div>
                  <div
                    role="radiogroup"
                    aria-label={`Usage mode for ${skill.id}`}
                    className="grid grid-cols-3 rounded-md border bg-background/70 p-0.5"
                  >
                    {([
                      ["off", "Off"],
                      ["available", "Available"],
                      ["required", "Required by prompt"],
                    ] as const).map(([value, label]) => {
                      const disabled = value === "off" && inGroup
                      return (
                        <button
                          key={value}
                          type="button"
                          role="radio"
                          aria-checked={mode === value}
                          disabled={disabled}
                          title={
                            disabled
                              ? "Remove the selected group before turning this skill off."
                              : undefined
                          }
                          onClick={() => chooseSkillMode(skill.id, value, inGroup)}
                          className={cn(
                            "rounded-sm px-2 py-1.5 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                            mode === value && value === "required"
                              ? "bg-warn-soft text-warn-ink shadow-sm"
                              : mode === value
                                ? "bg-primary text-primary-foreground shadow-sm"
                                : "text-muted-foreground hover:text-foreground",
                            disabled && "cursor-not-allowed opacity-40",
                          )}
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {selectedTotal.size
              ? `${selectedTotal.size} skill${selectedTotal.size === 1 ? "" : "s"} selected`
              : "No skills selected — agents run without extra guidance."}
          </span>
          {[...selectedTotal].map((id) => (
            <Badge
              key={id}
              variant="outline"
              className={cn(
                "font-mono text-[11px]",
                requiredSkills.includes(id) ? "border-warn-ink/40 text-warn-ink" : "text-muted-foreground",
              )}
            >
              {id}{requiredSkills.includes(id) ? " · required" : ""}
            </Badge>
          ))}
        </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- step 4: review ---------- */
