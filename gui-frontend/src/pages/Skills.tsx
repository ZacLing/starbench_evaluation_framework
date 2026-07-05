import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, FileText, Layers, Puzzle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type Skill } from "@/lib/api"

const DOCS_PATH = "docs/executor_skills.md"

function fmtBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const kb = bytes / 1024
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`
  const mb = kb / 1024
  return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`
}

export default function Skills() {
  const skillsQuery = useQuery({ queryKey: ["skills"], queryFn: api.skills })

  if (skillsQuery.isPending) return <Skeleton className="h-96" />
  if (skillsQuery.isError) return <ErrorNote message={(skillsQuery.error as Error).message} />
  const payload = skillsQuery.data
  const groupNames = Object.keys(payload.groups)

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Skills</h1>
        <p className="text-sm text-muted-foreground">
          Reusable packets of expert guidance an agent can read while it works. Pick skills when
          you set up an experiment to install them into every agent's workspace for that run.
        </p>
      </div>

      {payload.error ? (
        <Card className="border-warn-ink/40 py-4">
          <CardContent className="grid gap-2 px-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="size-4 text-warn-ink" />
              <span className="text-sm font-semibold">This skill library could not be read</span>
            </div>
            <p className="text-xs text-warn-ink">{payload.error}</p>
            <p className="text-xs text-muted-foreground">
              Fix the library on disk, then reload. See{" "}
              <code className="font-mono">{DOCS_PATH}</code>.
            </p>
          </CardContent>
        </Card>
      ) : payload.skills.length === 0 ? (
        <Card className="py-10">
          <CardContent className="grid justify-items-center gap-2 px-4 text-center">
            <span className="grid size-11 place-content-center rounded-full bg-muted text-muted-foreground">
              <Puzzle className="size-5" />
            </span>
            <span className="text-sm font-semibold">Your skill library is empty</span>
            <p className="max-w-md text-xs text-muted-foreground">
              A skill is a folder with a <code className="font-mono">SKILL.md</code> of private
              execution guidance. Add one under the library folder shown below, then follow{" "}
              <code className="font-mono">{DOCS_PATH}</code> to list it so runs can pick it up.
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {payload.skills.map((skill) => (
              <SkillCard key={skill.id} skill={skill} />
            ))}
          </div>

          {groupNames.length > 0 && (
            <div className="grid gap-3">
              <div className="flex items-center gap-2">
                <Layers className="size-4 text-muted-foreground" />
                <span className="text-sm font-semibold">Groups</span>
                <span className="text-xs text-muted-foreground">
                  A shortcut that injects several skills at once.
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {groupNames.map((name) => (
                  <Card key={name} className="py-4">
                    <CardContent className="grid gap-2 px-4">
                      <span className="text-sm font-semibold">{name}</span>
                      <div className="flex flex-wrap gap-1.5">
                        {payload.groups[name].length ? (
                          payload.groups[name].map((id) => (
                            <Badge
                              key={id}
                              variant="outline"
                              className="font-mono text-[11px] text-muted-foreground"
                            >
                              {id}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-xs text-muted-foreground">no skills</span>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <p
        className="truncate font-mono text-[11px] text-muted-foreground"
        title={payload.root}
      >
        Skill library · {payload.root}
      </p>
    </div>
  )
}

function SkillCard({ skill }: { skill: Skill }) {
  return (
    <Card className="py-4">
      <CardContent className="grid gap-2 px-4">
        <div className="flex items-center gap-2">
          <FileText className="size-4 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate font-mono text-sm font-semibold">
            {skill.id}
          </span>
        </div>
        {skill.description && (
          <p className="line-clamp-3 text-xs text-muted-foreground" title={skill.description}>
            {skill.description}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
          <span>
            {skill.file_count} file{skill.file_count === 1 ? "" : "s"} · {fmtBytes(skill.size_bytes)}
          </span>
        </div>
        {skill.groups.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {skill.groups.map((group) => (
              <Badge
                key={group}
                variant="outline"
                className="gap-1 text-[11px] text-muted-foreground"
              >
                <Layers className="size-3" /> {group}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
