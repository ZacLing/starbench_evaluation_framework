export const JUDGE_MODES = [
  { value: "single", label: "Single judge", note: "One session grades all rubrics. Fast." },
  {
    value: "parallel",
    label: "Per-rubric judges",
    note: "Independent judge per rubric. Strict.",
  },
  { value: "both", label: "Both", note: "Run both to compare their agreement." },
]

export const PER_FIELD_OPTIONS = [{ id: "model", label: "Model", locked: true }]

export const NEW_RUN_STEPS = ["Mode", "Tasks", "Agents", "Shared config", "Review & launch"]
