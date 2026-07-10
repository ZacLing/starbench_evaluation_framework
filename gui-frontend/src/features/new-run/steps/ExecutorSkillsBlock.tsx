import { useEffect, useState, type Dispatch, type SetStateAction } from "react"
import { ChevronDown } from "lucide-react"
import { Link } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import type { SharedConfig, SkillsPayload } from "@/lib/api"
import { cn } from "@/lib/utils"

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
  const skillsActive = selectedGroups.length + selectedSkills.length > 0
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
  const selectedTotal = new Set<string>([...coveredByGroup, ...selectedSkills])
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

  const toggleSkill = (id: string, on: boolean) =>
    setShared((current) => {
      const individual = new Set(current.executor_skills ?? [])
      if (on) individual.add(id)
      else individual.delete(id)
      return { ...current, executor_skills: [...individual] }
    })

  const skillsSummary = skillsActive
    ? [
        selectedSkills.length
          ? `${selectedSkills.length} skill${selectedSkills.length === 1 ? "" : "s"}`
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
              const checked = inGroup || selectedSkills.includes(skill.id)
              return (
                <label
                  key={skill.id}
                  className={cn(
                    "flex items-start gap-3 rounded-md border p-3 transition-colors",
                    inGroup
                      ? "cursor-not-allowed opacity-70"
                      : "cursor-pointer hover:border-primary/40",
                    checked && "border-primary bg-accent/60",
                  )}
                >
                  <Checkbox
                    className="mt-0.5"
                    checked={checked}
                    disabled={inGroup}
                    onCheckedChange={(value) => toggleSkill(skill.id, value === true)}
                  />
                  <span className="min-w-0">
                    <span className="block truncate font-mono text-sm font-medium">{skill.id}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {inGroup ? "included via a selected group" : skill.description || "—"}
                    </span>
                  </span>
                </label>
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
            <Badge key={id} variant="outline" className="font-mono text-[11px] text-muted-foreground">
              {id}
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
