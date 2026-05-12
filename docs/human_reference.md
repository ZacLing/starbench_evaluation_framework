# Human Reference Instructions

`human_reference.json` captures expert process steps for instruction-sweep experiments.

```json
{
  "steps": [
    {
      "step_id": "H001",
      "step_type": "structure",
      "instruction": "Before drafting, organize the answer around the required deliverable headings.",
      "reasoning": "The expert first maps the answer to the specified sections before drafting."
    }
  ]
}
```

## Field Semantics

- `step_id`: stable id used by `--instruction-step`.
- `step_type`: short category such as `structure`, `coverage`, `evidence`, `risk`, or `calculation`.
- `instruction`: public abstract guidance. This may be appended to the executor prompt.
- `reasoning`: private expert trace. Starbench loads it for metadata validation but does not copy it into executor inputs or evaluator workspaces.

## Important Design Rule

The steps may represent a real step-by-step expert workflow, but each public `instruction` should also be usable alone. In traverse mode Starbench runs one task per step, so each instruction must make sense without requiring previous instructions.

## Modes

Baseline:

```bash
starbench-run --instruction-mode none
```

Traverse:

```bash
starbench-run --task demo_instruction_reference --instruction-mode traverse
```

Selected bundle:

```bash
starbench-run \
  --task demo_instruction_reference \
  --instruction-mode select \
  --instruction-step H001 \
  --instruction-step H004
```

The appended prompt section looks like:

```text
Additional human reference instructions:
1. <instruction text>
2. <instruction text>
```
