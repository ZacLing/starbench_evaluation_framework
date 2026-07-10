import type {
  ExecutionEstimate,
  ExperimentPlanItem,
  TaskLibrary,
} from "@/lib/api"

export type WizardMode = "profile" | "custom"

export interface ContenderDraft {
  key: string
  runtime: string
  provider_id: string
  model: string
  thinking_effort: string
}

export type LibraryRef = Pick<TaskLibrary, "dir" | "tasks">

export interface PlanPreview {
  plans: ExperimentPlanItem[] | null
  estimate: ExecutionEstimate | null
  profileModified: boolean
  profileModifiedFields: string[]
  error: string | null
  loading: boolean
}

export interface RuntimeOption {
  id: string
  label: string
  note: string
  icon?: string
  protocol?: string
  cliMissing?: boolean
  localOnly?: boolean
}
