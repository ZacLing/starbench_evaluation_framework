import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import { ClipboardList, FolderSearch, Play, Timer } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { DirectoryPickerDialog, ImportDropzone } from "@/components/task-import"
import { WebSearchBadge } from "@/components/task-badges"
import { ErrorNote } from "@/pages/Dashboard"
import { api, type TaskPackage } from "@/lib/api"
import { renderMarkdown } from "@/lib/markdown"
import { fmtDuration } from "@/lib/format"

export default function Tasks() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const tasklib = useQuery({ queryKey: ["tasklib"], queryFn: api.tasklib })
  const [pickerOpen, setPickerOpen] = useState(false)
  const [preview, setPreview] = useState<{ dir: string; task: TaskPackage } | null>(null)

  if (tasklib.isPending) return <Skeleton className="h-96" />
  if (tasklib.isError) return <ErrorNote message={(tasklib.error as Error).message} />

  const libraries = tasklib.data.libraries.filter((library) => library.exists)
  const importTarget = libraries[0]?.dir

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Task library</h1>
          <p className="text-sm text-muted-foreground">
            {libraries.reduce((sum, library) => sum + library.tasks.length, 0)} task packages in{" "}
            {libraries.length} folders
          </p>
        </div>
        <div className="ml-auto">
          <Button variant="outline" onClick={() => setPickerOpen(true)}>
            <FolderSearch /> Add a task folder
          </Button>
        </div>
      </div>

      {importTarget && (
        <ImportDropzone
          compact
          targetDir={importTarget}
          onImported={() => queryClient.invalidateQueries({ queryKey: ["tasklib"] })}
        />
      )}

      {libraries.map((library) => (
        <section key={library.dir} className="grid gap-3">
          <h2 className="truncate font-mono text-xs text-muted-foreground" title={library.dir}>
            {library.dir}
          </h2>
          {library.tasks.length ? (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {library.tasks.map((task) => (
                <Card
                  key={`${library.dir}/${task.dir_name}`}
                  className="cursor-pointer py-4 transition-colors hover:border-primary/40"
                  onClick={() => setPreview({ dir: library.dir, task })}
                >
                  <CardContent className="grid gap-2 px-4">
                    {task.error ? (
                      <p className="text-xs text-fail-ink" title={task.error}>
                        broken: {task.error}
                      </p>
                    ) : task.warning ? (
                      <p className="text-xs text-warn-ink" title={task.warning}>
                        {task.warning}
                      </p>
                    ) : null}
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-mono text-sm font-semibold">{task.id}</span>
                      <div className="flex flex-wrap items-center justify-end gap-1">
                        <WebSearchBadge allow={task.allow_web_search} />
                        {task.has_human_reference && (
                          <Badge variant="outline" className="text-xs text-muted-foreground">
                            expert steps
                          </Badge>
                        )}
                        {task.rigor_count > 0 && (
                          <Badge variant="outline" className="text-xs text-muted-foreground">
                            {task.rigor_count} {task.rigor_count === 1 ? "rigor" : "rigors"}
                          </Badge>
                        )}
                      </div>
                    </div>
                    <p className="line-clamp-2 text-sm text-muted-foreground">{task.name}</p>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <ClipboardList className="size-3.5" /> {task.rubric_count} rubrics
                      </span>
                      {task.timeout_seconds ? (
                        <span className="flex items-center gap-1">
                          <Timer className="size-3.5" /> {fmtDuration(task.timeout_seconds)} limit
                        </span>
                      ) : null}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No task packages in this folder yet.</p>
          )}
        </section>
      ))}

      {!libraries.length && (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            No task folders registered. Add one with the button above.
          </CardContent>
        </Card>
      )}

      <DirectoryPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        title="Add a task folder"
        description="Pick a folder that contains task packages (each with its own task.json)."
        onSelect={async (path) => {
          try {
            await api.registerTasksDir(path)
            queryClient.invalidateQueries({ queryKey: ["tasklib"] })
            toast.success("Task folder added.")
          } catch (error) {
            toast.error((error as Error).message)
          }
        }}
      />

      <TaskPreviewSheet
        selection={preview}
        onClose={() => setPreview(null)}
        onRun={(dir, taskId) =>
          navigate("/new", { state: { tasksDir: dir, taskIds: [taskId] } })
        }
      />
    </div>
  )
}

export function TaskPreviewSheet({
  selection,
  onClose,
  onRun,
}: {
  selection: { dir: string; task: TaskPackage } | null
  onClose: () => void
  onRun: (dir: string, taskId: string) => void
}) {
  const detail = useQuery({
    queryKey: ["taskDetail", selection?.dir, selection?.task.dir_name],
    queryFn: () => api.taskDetail(selection!.dir, selection!.task.dir_name),
    enabled: Boolean(selection),
  })

  return (
    <Sheet open={Boolean(selection)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-2xl">
        <SheetHeader className="border-b">
          <SheetTitle className="font-mono">{selection?.task.id}</SheetTitle>
          <SheetDescription>{selection?.task.name}</SheetDescription>
          {detail.data && (
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              <WebSearchBadge allow={detail.data.allow_web_search} />
              {detail.data.timeout_seconds ? (
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  {fmtDuration(detail.data.timeout_seconds)} limit
                </Badge>
              ) : null}
              {detail.data.human_reference_step_count > 0 && (
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  {detail.data.human_reference_step_count} expert step
                  {detail.data.human_reference_step_count === 1 ? "" : "s"}
                </Badge>
              )}
              {detail.data.rigor_count > 0 && (
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  {detail.data.rigor_count} {detail.data.rigor_count === 1 ? "rigor" : "rigors"}
                </Badge>
              )}
            </div>
          )}
          <div className="flex gap-2 pt-1">
            <Button
              size="sm"
              onClick={() => selection && onRun(selection.dir, selection.task.id)}
            >
              <Play /> Run this task
            </Button>
          </div>
        </SheetHeader>
        {detail.isPending ? (
          <div className="grid gap-3 p-4">
            <Skeleton className="h-24" />
            <Skeleton className="h-48" />
          </div>
        ) : detail.isError ? (
          <div className="p-4">
            <ErrorNote message={(detail.error as Error).message} />
          </div>
        ) : (
          <div className="grid gap-6 p-4">
            <section className="grid gap-2">
              <h3 className="text-sm font-semibold">
                Rubrics{" "}
                <span className="font-normal text-muted-foreground">
                  {detail.data.rubrics.length}
                </span>
              </h3>
              <div className="overflow-hidden rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50 hover:bg-muted/50">
                      <TableHead>Id</TableHead>
                      <TableHead className="w-full">Question</TableHead>
                      <TableHead>Expected</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {detail.data.rubrics.map((rubric) => (
                      <TableRow key={rubric.id}>
                        <TableCell className="whitespace-nowrap font-mono text-xs font-medium">
                          {rubric.id}
                          {rubric.fail_fast && (
                            <Badge
                              variant="outline"
                              className="ml-1 px-1 text-[10px] text-muted-foreground"
                              title="fail-fast rubric"
                            >
                              ff
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-xs">{rubric.question}</TableCell>
                        <TableCell className="text-xs tabular-nums">
                          {rubric.expected ? "Yes" : "No"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </section>
            <section className="grid gap-2">
              <h3 className="text-sm font-semibold">Prompt</h3>
              {detail.data.prompt ? (
                <div
                  className="prose-starbench rounded-md border bg-muted/30 p-4"
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(detail.data.prompt) }}
                />
              ) : (
                <p className="text-sm text-muted-foreground">Prompt file could not be read.</p>
              )}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
