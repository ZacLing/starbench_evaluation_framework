import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, CheckCircle2, FolderSearch, Loader2, XCircle } from "lucide-react"
import { ImportDropzone } from "@/components/task-import"
import { TaskBadges } from "@/components/task-badges"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { api, type TaskHistory, type TaskHistoryConfig, type TaskPackage } from "@/lib/api"
import { fmtDuration, fmtRelative } from "@/lib/format"
import { cn } from "@/lib/utils"

export function StepTasks({
  libraries,
  tasksDir,
  tasks,
  setTasksDir,
  setTasks,
  onOpenPicker,
  onImported,
  runtimeLabel,
}: {
  libraries: { dir: string; tasks: TaskPackage[] }[]
  tasksDir: string
  tasks: string[]
  setTasksDir: (dir: string) => void
  setTasks: (tasks: string[]) => void
  onOpenPicker: () => void
  onImported: () => void
  runtimeLabel: (runtime: string) => string
}) {
  const library = libraries.find((item) => item.dir === tasksDir)
  const historyQuery = useQuery({
    queryKey: ["task-history", tasksDir],
    queryFn: () => api.taskHistory(tasksDir),
    enabled: Boolean(tasksDir),
  })
  const historyByTask = historyQuery.data?.tasks ?? {}
  const runnableTasks = library?.tasks.filter((task) => !task.error) ?? []
  const selectedRunnableCount = tasks.filter((id) =>
    runnableTasks.some((task) => task.id === id),
  ).length
  const allRunnableSelected =
    runnableTasks.length > 0 && selectedRunnableCount === runnableTasks.length
  const someRunnableSelected = selectedRunnableCount > 0 && !allRunnableSelected
  const requiresTaskSelection = runnableTasks.length > 0 && selectedRunnableCount === 0
  const toggleTask = (task: TaskPackage, checked: boolean) => {
    if (task.error) return
    setTasks(checked ? [...tasks, task.id] : tasks.filter((id) => id !== task.id))
  }
  const toggleAllRunnableTasks = (checked: boolean) => {
    const runnableIds = new Set(runnableTasks.map((task) => task.id))
    setTasks(
      checked
        ? Array.from(new Set([...tasks, ...runnableIds]))
        : tasks.filter((id) => !runnableIds.has(id)),
    )
  }
  return (
    <Card>
      <CardContent className="grid gap-5">
        <div className="grid gap-2">
          <Label>Task folder</Label>
          <div className="flex flex-wrap items-center gap-2">
            {libraries.map((item) => (
              <button
                key={item.dir}
                type="button"
                onClick={() => setTasksDir(item.dir)}
                className={cn(
                  "max-w-full truncate rounded-md border px-3 py-1.5 font-mono text-xs transition-colors",
                  item.dir === tasksDir
                    ? "border-primary bg-accent text-accent-foreground"
                    : "hover:border-primary/40",
                )}
                title={item.dir}
              >
                …/{item.dir.split("/").slice(-2).join("/")}
                <span className="ml-2 text-muted-foreground">{item.tasks.length}</span>
              </button>
            ))}
            <Button variant="outline" size="sm" onClick={onOpenPicker}>
              <FolderSearch /> Browse…
            </Button>
          </div>
        </div>

        {library && library.tasks.length > 0 ? (
          <div className="grid gap-2">
            <div className="flex items-baseline justify-between">
              <Label>Tasks to run</Label>
              <span
                className={cn(
                  "text-xs",
                  requiresTaskSelection ? "font-medium text-warn-ink" : "text-muted-foreground",
                )}
              >
                {selectedRunnableCount} of {runnableTasks.length} runnable selected
              </span>
            </div>
            {runnableTasks.length === 0 ? (
              <Alert className="border-warn-ink/40 bg-warn-soft/60">
                <AlertTriangle className="size-4" />
                <AlertTitle>No runnable tasks in this folder</AlertTitle>
                <AlertDescription>
                  Fix the broken task packages, import valid ones, or choose another task
                  folder before continuing.
                </AlertDescription>
              </Alert>
            ) : requiresTaskSelection ? (
              <Alert className="border-warn-ink/40 bg-warn-soft/60">
                <AlertTriangle className="size-4" />
                <AlertTitle>Select at least one task</AlertTitle>
                <AlertDescription>
                  The experiment needs an explicit task set so the run snapshot is
                  reproducible and comparable.
                </AlertDescription>
              </Alert>
            ) : null}
            {historyQuery.isError && (
              <p className="text-xs text-warn-ink">
                Run history could not be loaded: {(historyQuery.error as Error).message}
              </p>
            )}
            <div className="overflow-hidden rounded-md border">
              <Table className="min-w-[82rem]">
                <TableHeader>
                  <TableRow className="bg-muted/50 hover:bg-muted/50">
                    <TableHead className="w-11 pl-4">
                      <Checkbox
                        checked={
                          allRunnableSelected
                            ? true
                            : someRunnableSelected
                              ? "indeterminate"
                              : false
                        }
                        aria-label={
                          allRunnableSelected
                            ? "Deselect all runnable tasks"
                            : "Select all runnable tasks"
                        }
                        onCheckedChange={(value) => toggleAllRunnableTasks(Boolean(value))}
                      />
                    </TableHead>
                    <TableHead className="min-w-[19rem]">Task</TableHead>
                    <TableHead className="w-24 text-right">Rubrics</TableHead>
                    <TableHead className="w-28">Time limit</TableHead>
                    <TableHead className="min-w-[13rem]">Capabilities</TableHead>
                    <TableHead className="min-w-[12rem]">Test history</TableHead>
                    <TableHead className="min-w-[24rem]">Configurations</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {library.tasks.map((task) => {
                    const checked = tasks.includes(task.id)
                    const broken = Boolean(task.error)
                    const history = historyByTask[task.id]
                    return (
                      <TableRow
                        key={task.dir_name}
                        data-state={checked ? "selected" : undefined}
                        tabIndex={broken ? undefined : 0}
                        aria-selected={checked}
                        aria-label={`${checked ? "Deselect" : "Select"} task ${task.id}`}
                        onClick={(event) => {
                          if (broken) return
                          const target = event.target as HTMLElement
                          if (
                            target.closest(
                              "button, a, input, select, textarea, [role=checkbox]",
                            )
                          ) {
                            return
                          }
                          toggleTask(task, !checked)
                        }}
                        onKeyDown={(event) => {
                          if (broken || event.target !== event.currentTarget) return
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault()
                            toggleTask(task, !checked)
                          }
                        }}
                        className={cn(
                          broken && "bg-fail-soft/30 hover:bg-fail-soft/40",
                          !broken && "cursor-pointer hover:bg-accent/35 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                          checked && "bg-accent/60 hover:bg-accent/75",
                        )}
                      >
                        <TableCell className="pl-4">
                          <Checkbox
                            checked={checked}
                            disabled={broken}
                            aria-label={`Select ${task.id}`}
                            onCheckedChange={(value) => toggleTask(task, Boolean(value))}
                          />
                        </TableCell>
                        <TableCell className="whitespace-normal">
                          <div className="grid min-w-0 gap-1">
                            <div className="truncate font-mono text-sm font-medium" title={task.id}>
                              {task.id}
                            </div>
                            {broken ? (
                              <div className="text-xs text-fail-ink">
                                Not runnable: {task.error}
                              </div>
                            ) : (
                              <>
                                <div className="truncate text-xs text-muted-foreground" title={task.name}>
                                  {task.name}
                                </div>
                                {task.warning && (
                                  <div className="text-xs text-warn-ink">{task.warning}</div>
                                )}
                              </>
                            )}
                          </div>
                        </TableCell>
                        <TableCell className="text-right align-top font-mono text-xs tabular-nums">
                          {broken ? "—" : task.rubric_count}
                        </TableCell>
                        <TableCell className="align-top font-mono text-xs tabular-nums text-muted-foreground">
                          {broken || !task.timeout_seconds ? "—" : fmtDuration(task.timeout_seconds)}
                        </TableCell>
                        <TableCell className="whitespace-normal align-top">
                          {broken ? (
                            <span className="text-xs text-muted-foreground">Unavailable</span>
                          ) : (
                            <TaskCapabilitySummary task={task} />
                          )}
                        </TableCell>
                        <TableCell className="whitespace-normal">
                          <TaskHistoryStatus
                            history={history}
                            loading={historyQuery.isPending || historyQuery.isFetching}
                          />
                        </TableCell>
                        <TableCell className="whitespace-normal">
                          <TaskHistoryConfigs history={history} runtimeLabel={runtimeLabel} />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
            <p className="text-xs text-muted-foreground">
              Only selected runnable task packages will run.
            </p>
            {library.tasks.some((task) => task.error) && (
              <p className="text-xs text-warn-ink">
                This folder contains broken packages. They are disabled here until fixed.
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            No task packages in this folder. Import one below or browse to another folder.
          </p>
        )}

        {tasksDir && <ImportDropzone compact targetDir={tasksDir} onImported={onImported} />}
      </CardContent>
    </Card>
  )
}

function TaskCapabilitySummary({ task }: { task: TaskPackage }) {
  const hasDeclaredCapability =
    task.allow_web_search !== null || task.has_human_reference || task.rigor_count > 0
  if (!hasDeclaredCapability) {
    return <span className="text-xs text-muted-foreground">None declared</span>
  }
  return <TaskBadges task={task} showTimeout={false} />
}

function TaskHistoryStatus({
  history,
  loading,
}: {
  history?: TaskHistory
  loading: boolean
}) {
  if (loading && !history) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3 animate-spin" />
        checking history
      </span>
    )
  }
  if (!history || history.task_run_count === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <XCircle className="size-3.5" />
        Not tested yet
      </span>
    )
  }
  const runLabel = `${history.run_count} run${history.run_count === 1 ? "" : "s"}`
  const executionLabel = `${history.task_run_count} execution${
    history.task_run_count === 1 ? "" : "s"
  }`
  return (
    <span className="grid gap-0.5 text-xs">
      <span className="inline-flex items-center gap-1.5 font-medium text-pass-ink">
        <CheckCircle2 className="size-3.5" />
        Tested
      </span>
      <span className="text-muted-foreground">
        {runLabel} · {executionLabel}
        {history.last_tested ? ` · ${fmtRelative(history.last_tested)}` : ""}
      </span>
    </span>
  )
}

function TaskHistoryConfigs({
  history,
  runtimeLabel,
}: {
  history?: TaskHistory
  runtimeLabel: (runtime: string) => string
}) {
  if (!history || history.configs.length === 0) {
    return <span className="text-xs text-muted-foreground">No previous config.</span>
  }
  return (
    <div className="grid gap-1">
      {history.configs.map((config, index) => (
        <TaskHistoryConfigLine
          key={`${config.executor_agent ?? "agent"}-${config.executor_model ?? "model"}-${index}`}
          config={config}
          runtimeLabel={runtimeLabel}
        />
      ))}
    </div>
  )
}

function TaskHistoryConfigLine({
  config,
  runtimeLabel,
}: {
  config: TaskHistoryConfig
  runtimeLabel: (runtime: string) => string
}) {
  const executor = config.executor_agent
    ? `${runtimeLabel(config.executor_agent)}${config.executor_model ? ` · ${config.executor_model}` : ""}`
    : config.executor_model || "unknown executor"
  const judge =
    config.evaluator_agent || config.evaluator_model
      ? `judge ${config.evaluator_agent ? runtimeLabel(config.evaluator_agent) : "unknown"}${
          config.evaluator_model ? ` · ${config.evaluator_model}` : ""
        }`
      : ""
  const knobs = [
    config.judge_mode,
    config.executor_backend,
    config.instruction_mode && config.instruction_mode !== "none" ? config.instruction_mode : "",
    config.thinking_effort && !["none", "default"].includes(config.thinking_effort)
      ? `think ${config.thinking_effort}`
      : "",
    config.repeat && config.repeat > 1 ? `x${config.repeat}` : "",
    config.seed !== null && config.seed !== undefined ? `seed ${config.seed}` : "",
  ].filter((value): value is string => Boolean(value))

  return (
    <div className="rounded-md border bg-muted/30 px-2 py-1.5">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span
          className="min-w-0 truncate font-mono text-xs font-medium"
          title={executor}
        >
          {executor}
        </span>
        <Badge variant="outline" className="px-1.5 py-0 text-[10px] text-muted-foreground">
          {config.task_run_count}x
        </Badge>
      </div>
      <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
        {judge && <span>{judge}</span>}
        {knobs.map((item) => (
          <span key={item}>{item}</span>
        ))}
        {config.last_tested && <span>{fmtRelative(config.last_tested)}</span>}
      </div>
    </div>
  )
}

/* ---------- step 2: contenders (pure references to providers) ---------- */
