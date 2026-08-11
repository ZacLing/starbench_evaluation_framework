import { useEffect, useState, type Dispatch, type SetStateAction } from "react"
import { useQueries } from "@tanstack/react-query"
import { AlertTriangle, Check, ChevronDown, Loader2, Sparkles } from "lucide-react"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { api, type SharedConfig, type TaskPackage } from "@/lib/api"
import { cn } from "@/lib/utils"

const INSTRUCTION_MODE_CARDS = [
  {
    value: "none",
    label: "None",
    note: "Baseline — the task runs exactly as written.",
  },
  {
    value: "select",
    label: "Selected steps",
    note: "Bundle the expert steps you pick into the prompt; one run per task.",
  },
  {
    value: "traverse",
    label: "Traverse",
    note: "One variant per expert step, to see each step's effect on its own.",
  },
  {
    value: "ablation",
    label: "Ablation",
    note: "Baseline + each step alone + all steps together; auto-generates a baseline comparison and a step-by-step uplift report.",
  },
] as const

/* Instruction ablation: a research sweep over a task's human_reference expert
   steps. This is the "Prompt assistance (research)" region; B4 will add a Rigor
   sub-section alongside Expert instructions, so the block is structured for two
   sub-sections. Only public step text is ever shown — the private `reasoning`
   never crosses the API (enforced backend-side). */
export function PromptAssistanceBlock({
  tasksDir,
  selectedTasks,
  shared,
  setShared,
  setSharedField,
}: {
  tasksDir: string
  selectedTasks: TaskPackage[]
  shared: Partial<SharedConfig>
  setShared: Dispatch<SetStateAction<Partial<SharedConfig>>>
  setSharedField: (key: keyof SharedConfig, value: unknown) => void
}) {
  const mode = String(shared.instruction_mode ?? "none")
  const selectedSteps = shared.instruction_steps ?? []
  const repeat = Number(shared.repeat) || 1

  const tasksWithSteps = selectedTasks.filter((task) => task.has_human_reference)
  const tasksWithoutSteps = selectedTasks.filter((task) => !task.has_human_reference)
  // Only the baseline applies when no selected task ships any expert steps.
  const noExpertSteps = selectedTasks.length > 0 && tasksWithSteps.length === 0

  // Public step detail per step-bearing task; keys are stable per (dir, task) so
  // react-query caches across renders and steps rerender.
  const detailQueries = useQueries({
    queries: tasksWithSteps.map((task) => ({
      queryKey: ["tasklib-task", tasksDir, task.dir_name],
      queryFn: () => api.taskDetail(tasksDir, task.dir_name),
      enabled: Boolean(tasksDir),
      staleTime: 60_000,
    })),
  })
  const stepsLoading = detailQueries.some((query) => query.isPending)

  // Pool steps across the selected tasks, keyed by step id, tracking how many of
  // the step-bearing tasks contain each id. The runner requires a chosen step to
  // exist in EVERY selected task, so a step present in only some tasks (marked
  // in k/N) will make the run reject the tasks that lack it.
  const pooled = new Map<
    string,
    { step_id: string; step_type: string; instruction: string; inTasks: number }
  >()
  for (const query of detailQueries) {
    if (!query.data) continue
    for (const step of query.data.human_reference_steps) {
      const existing = pooled.get(step.step_id)
      if (existing) existing.inTasks += 1
      else pooled.set(step.step_id, { ...step, inTasks: 1 })
    }
  }
  const unionSteps = [...pooled.values()]
  const stepTaskCount = tasksWithSteps.length

  // If the task selection changed to one with no expert steps, don't leave a
  // stale step-requiring mode (or step choice) selected.
  useEffect(() => {
    if (noExpertSteps && mode !== "none") {
      setShared((current) => ({
        ...current,
        instruction_mode: "none",
        instruction_steps: [],
      }))
    }
  }, [noExpertSteps, mode, setShared])

  const setMode = (next: string) =>
    setShared((current) => ({
      ...current,
      instruction_mode: next,
      // Chosen steps only apply to select mode; drop them otherwise so ablation
      // and traverse always sweep the full step set.
      instruction_steps: next === "select" ? current.instruction_steps ?? [] : [],
    }))

  const toggleStep = (id: string, on: boolean) =>
    setShared((current) => {
      const chosen = new Set(current.instruction_steps ?? [])
      if (on) chosen.add(id)
      else chosen.delete(id)
      return { ...current, instruction_steps: [...chosen] }
    })

  const partialModeLabel =
    mode === "select" ? "Selected steps" : mode === "traverse" ? "Traverse" : "Ablation"

  // --- Rigor requirements (research). A parallel sub-section to Expert
  //     instructions: it restates selected rubric-level requirements as hard
  //     requirements in every agent's prompt. It's off by default (a controlled
  //     experiment, not part of the baseline benchmark score) and, unlike the
  //     instruction sweep, does not expand executor variants. All rigor text is
  //     public. ---
  const rigorEnabled = String(shared.rigor_mode ?? "none") === "select"
  const selectedRigors = shared.rigors ?? []

  const tasksWithRigors = selectedTasks.filter((task) => task.rigor_count > 0)
  const tasksWithoutRigors = selectedTasks.filter((task) => !task.rigor_count)
  const noRigors = selectedTasks.length > 0 && tasksWithRigors.length === 0

  // Public rigor detail per rigor-bearing task. Same query key as the step
  // queries above, so react-query serves both from one cache entry per task.
  const rigorDetailQueries = useQueries({
    queries: tasksWithRigors.map((task) => ({
      queryKey: ["tasklib-task", tasksDir, task.dir_name],
      queryFn: () => api.taskDetail(tasksDir, task.dir_name),
      enabled: Boolean(tasksDir),
      staleTime: 60_000,
    })),
  })
  const rigorsLoading = rigorDetailQueries.some((query) => query.isPending)

  // Pool rigors across the selected tasks, keyed by id, tracking how many of the
  // rigor-bearing tasks contain each id. The runner requires a chosen rigor to
  // exist in EVERY selected task, so one present in only some tasks (marked in
  // k/N) makes the run reject the tasks that lack it.
  const pooledRigors = new Map<
    string,
    { id: string; rubric_id: string; requirement: string; inTasks: number }
  >()
  for (const query of rigorDetailQueries) {
    if (!query.data) continue
    for (const rigor of query.data.rigors) {
      const existing = pooledRigors.get(rigor.id)
      if (existing) existing.inTasks += 1
      else pooledRigors.set(rigor.id, { ...rigor, inTasks: 1 })
    }
  }
  const unionRigors = [...pooledRigors.values()]
  const rigorTaskCount = tasksWithRigors.length

  // If the task selection changed to one with no rigors, don't leave rigor mode
  // (or a stale id choice) selected.
  useEffect(() => {
    if (noRigors && rigorEnabled) {
      setShared((current) => ({ ...current, rigor_mode: "none", rigors: [] }))
    }
  }, [noRigors, rigorEnabled, setShared])

  const setRigorEnabled = (on: boolean) =>
    setShared((current) => ({
      ...current,
      rigor_mode: on ? "select" : "none",
      rigors: on ? current.rigors ?? [] : [],
    }))

  const toggleRigor = (id: string, on: boolean) =>
    setShared((current) => {
      const chosen = new Set(current.rigors ?? [])
      if (on) chosen.add(id)
      else chosen.delete(id)
      return { ...current, rigors: [...chosen] }
    })

  /* Collapsed by default while inactive: research layers are additions, not
     required configuration, and the closed row states exactly what is on. */
  const assistActive = mode !== "none" || rigorEnabled
  const assistSummary = [
    mode === "none"
      ? "instructions off"
      : mode === "select"
        ? `instructions: selected steps (${selectedSteps.length})`
        : `instructions: ${mode}`,
    rigorEnabled ? `rigor: ${selectedRigors.length} requirement${selectedRigors.length === 1 ? "" : "s"}` : "rigor off",
  ].join(" · ")
  const [open, setOpen] = useState(assistActive)
  useEffect(() => {
    if (assistActive) setOpen(true)
  }, [assistActive])

  return (
    <Card className={open ? undefined : "py-3"}>
      <CardContent className="grid gap-4">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
          className="flex w-full flex-wrap items-center gap-2 text-left"
        >
          <Sparkles className="size-4 text-live-ink" />
          <span className="text-sm font-semibold">Prompt assistance (research)</span>
          {open ? (
            <span className="text-xs text-muted-foreground">
              Optional experiments that add expert guidance to the prompt. Shared across all
              agents, like the judge, so the comparison stays fair.
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">{assistSummary}</span>
          )}
          <span
            className={cn(
              "ml-auto size-1.5 rounded-full",
              assistActive ? "bg-live-ink" : "bg-muted-foreground/40",
            )}
            aria-hidden
          />
          <ChevronDown
            className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </button>
        {open && (
          <>

        {/* --- Expert instructions --- */}
        <div className="grid gap-3">
          <span className="text-xs font-semibold text-muted-foreground">
            Expert instructions
          </span>

          {noExpertSteps ? (
            <p className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">
              None of the selected tasks ship expert steps (a{" "}
              <code className="font-mono">human_reference.json</code>), so only the baseline
              (None) applies. Add expert steps to a task to enable this experiment.
            </p>
          ) : (
            <>
              <div className="grid gap-2 sm:grid-cols-2">
                {INSTRUCTION_MODE_CARDS.map((card) => {
                  const active = mode === card.value
                  return (
                    <button
                      key={card.value}
                      type="button"
                      onClick={() => setMode(card.value)}
                      className={cn(
                        "grid gap-0.5 rounded-md border p-3 text-left transition-colors",
                        active ? "border-primary bg-accent/60" : "hover:border-primary/40",
                      )}
                    >
                      <span className="flex items-center gap-2 text-sm font-medium">
                        {active && <Check className="size-3.5 text-primary" />}
                        {card.label}
                        {card.value === "none" && (
                          <Badge variant="outline" className="text-[10px] text-muted-foreground">
                            default
                          </Badge>
                        )}
                      </span>
                      <span className="text-xs text-muted-foreground">{card.note}</span>
                    </button>
                  )
                })}
              </div>

              {/* Partial coverage: some selected tasks ship no expert steps. In any
                  step mode the runner rejects the whole run for those tasks. */}
              {tasksWithoutSteps.length > 0 && mode !== "none" && (
                <Alert className="border-warn-ink/40 bg-warn-soft/60">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>Some selected tasks have no expert steps</AlertTitle>
                  <AlertDescription>
                    {partialModeLabel} mode requires every selected task to ship expert steps.
                    The runner rejects the whole run for tasks that don't:{" "}
                    {tasksWithoutSteps.map((task) => task.id).join(", ")}. Remove them or switch
                    to None.
                  </AlertDescription>
                </Alert>
              )}

              {/* Selected mode: the step multi-selector, pooled across tasks. */}
              {mode === "select" && (
                <div className="grid gap-2">
                  <p className="text-xs text-muted-foreground">
                    Every chosen step must exist in each selected task. Steps below are pooled
                    across your selected tasks; one marked{" "}
                    <span className="text-warn-ink">in k/N</span> is missing from some, and the
                    run is rejected for any task that lacks a chosen step.
                  </p>
                  {stepsLoading ? (
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="size-3.5 animate-spin" /> Loading expert steps…
                    </p>
                  ) : unionSteps.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      No expert steps found in the selected tasks.
                    </p>
                  ) : (
                    <div className="grid gap-2">
                      {unionSteps.map((step) => {
                        const checked = selectedSteps.includes(step.step_id)
                        const partial = stepTaskCount > 1 && step.inTasks < stepTaskCount
                        return (
                          <label
                            key={step.step_id}
                            className={cn(
                              "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                              checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                            )}
                          >
                            <Checkbox
                              className="mt-0.5"
                              checked={checked}
                              onCheckedChange={(value) => toggleStep(step.step_id, value === true)}
                            />
                            <span className="grid min-w-0 gap-1">
                              <span className="flex flex-wrap items-center gap-2">
                                <code className="font-mono text-sm font-medium">
                                  {step.step_id}
                                </code>
                                {step.step_type && (
                                  <Badge
                                    variant="outline"
                                    className="text-[10px] uppercase tracking-wide text-muted-foreground"
                                  >
                                    {step.step_type}
                                  </Badge>
                                )}
                                {stepTaskCount > 1 && (
                                  <Badge
                                    variant="outline"
                                    className={cn(
                                      "text-[10px]",
                                      partial
                                        ? "border-warn-ink/50 text-warn-ink"
                                        : "text-muted-foreground",
                                    )}
                                  >
                                    in {step.inTasks}/{stepTaskCount}
                                  </Badge>
                                )}
                              </span>
                              <span
                                className="truncate text-xs text-muted-foreground"
                                title={step.instruction}
                              >
                                {step.instruction || "—"}
                              </span>
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* Ablation: nudge repeat >= 3 for a stable uplift signal. */}
              {mode === "ablation" && (
                <Alert>
                  <Sparkles className="size-4" />
                  <AlertTitle>Repeat 3+ recommended</AlertTitle>
                  <AlertDescription className="flex flex-wrap items-center gap-2">
                    <span>
                      Ablation compares pass rates across variants; a few repeats smooth out
                      per-run noise so the uplift report is trustworthy.
                    </span>
                    {repeat < 3 && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setSharedField("repeat", 3)}
                      >
                        Set repeat to 3
                      </Button>
                    )}
                  </AlertDescription>
                </Alert>
              )}
            </>
          )}
        </div>

        {/* --- Rigor requirements --- */}
        <div className="grid gap-3 border-t pt-4">
          <div className="grid gap-1">
            <span className="text-xs font-semibold text-muted-foreground">
              Rigor requirements
            </span>
            <p className="text-xs text-muted-foreground">
              Restates a few rubric requirements as hard requirements inside every agent's
              prompt. Use this for a controlled experiment — it is not part of the default
              benchmark score, so leave it off for a plain comparison.
            </p>
          </div>

          {noRigors ? (
            <p className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">
              None of the selected tasks ship rigor requirements (a{" "}
              <code className="font-mono">rigors.json</code>), so this experiment is
              unavailable. Add rigor requirements to a task to enable it.
            </p>
          ) : (
            <>
              <label
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                  rigorEnabled ? "border-primary bg-accent/60" : "hover:border-primary/40",
                )}
              >
                <Checkbox
                  className="mt-0.5"
                  checked={rigorEnabled}
                  onCheckedChange={(value) => setRigorEnabled(value === true)}
                />
                <span className="grid gap-0.5">
                  <span className="text-sm font-medium">Inject rigor requirements</span>
                  <span className="text-xs text-muted-foreground">
                    Off by default. When on, pick the requirements to restate below.
                  </span>
                </span>
              </label>

              {/* Partial coverage: some selected tasks ship no rigors. In select
                  mode the runner rejects the whole run for those tasks. */}
              {rigorEnabled && tasksWithoutRigors.length > 0 && (
                <Alert className="border-warn-ink/40 bg-warn-soft/60">
                  <AlertTriangle className="size-4" />
                  <AlertTitle>Some selected tasks have no rigor requirements</AlertTitle>
                  <AlertDescription>
                    Rigor injection requires every selected task to ship rigor requirements.
                    The runner rejects the whole run for tasks that don't:{" "}
                    {tasksWithoutRigors.map((task) => task.id).join(", ")}. Remove them or turn
                    rigor injection off.
                  </AlertDescription>
                </Alert>
              )}

              {/* The requirement multi-selector, pooled across tasks. */}
              {rigorEnabled && (
                <div className="grid gap-2">
                  <p className="text-xs text-muted-foreground">
                    Every chosen requirement must exist in each selected task. Requirements
                    below are pooled across your selected tasks; one marked{" "}
                    <span className="text-warn-ink">in k/N</span> is missing from some, and the
                    run is rejected for any task that lacks a chosen requirement.
                  </p>
                  {rigorsLoading ? (
                    <p className="flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="size-3.5 animate-spin" /> Loading rigor requirements…
                    </p>
                  ) : unionRigors.length === 0 ? (
                    <p className="text-xs text-muted-foreground">
                      No rigor requirements found in the selected tasks.
                    </p>
                  ) : (
                    <div className="grid gap-2">
                      {unionRigors.map((rigor) => {
                        const checked = selectedRigors.includes(rigor.id)
                        const partial = rigorTaskCount > 1 && rigor.inTasks < rigorTaskCount
                        return (
                          <label
                            key={rigor.id}
                            className={cn(
                              "flex cursor-pointer items-start gap-3 rounded-md border p-3 transition-colors",
                              checked ? "border-primary bg-accent/60" : "hover:border-primary/40",
                            )}
                          >
                            <Checkbox
                              className="mt-0.5"
                              checked={checked}
                              onCheckedChange={(value) => toggleRigor(rigor.id, value === true)}
                            />
                            <span className="grid min-w-0 gap-1">
                              <span className="flex flex-wrap items-center gap-2">
                                <code className="font-mono text-sm font-medium">{rigor.id}</code>
                                {rigor.rubric_id && (
                                  <Badge
                                    variant="outline"
                                    className="text-[10px] uppercase tracking-wide text-muted-foreground"
                                  >
                                    rubric {rigor.rubric_id}
                                  </Badge>
                                )}
                                {rigorTaskCount > 1 && (
                                  <Badge
                                    variant="outline"
                                    className={cn(
                                      "text-[10px]",
                                      partial
                                        ? "border-warn-ink/50 text-warn-ink"
                                        : "text-muted-foreground",
                                    )}
                                  >
                                    in {rigor.inTasks}/{rigorTaskCount}
                                  </Badge>
                                )}
                              </span>
                              <span
                                className="truncate text-xs text-muted-foreground"
                                title={rigor.requirement}
                              >
                                {rigor.requirement || "—"}
                              </span>
                            </span>
                          </label>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/* ---------- shared: executor skills ---------- */

/* Skills and groups are kept separate in `shared`: checking a group injects the
   whole group, and its members drop out of the individual list so a skill is
   never installed twice (which the runner rejects). */
