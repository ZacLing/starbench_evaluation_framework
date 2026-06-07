# Rigor Prompt Injection

This document describes a second prompt-injection path for StarBench-HSW experiments. It is similar in form to human-reference instruction injection, but the injected content is derived from rubric-level requirements and is written as hard requirements rather than as optional expert advice.

## Purpose

Rigor injection tests whether an executor improves when a small number of reader-fair rubric requirements are restated directly in the executor prompt.

The injected prefix is:

```text
Ensure your answer reaches an equivalent level of rigor and depth to the following requirements:
```

The selected requirements then appear as a numbered list.

Use this mode for controlled experiments, not as a default benchmark setting. The baseline score should remain the no-instruction/no-rigor score unless the experiment is explicitly about prompt assistance.

## File Format

Add a `rigors.json` file to the task package:

```json
{
  "rigors": [
    {
      "id": "G",
      "rubric_id": "G",
      "requirement": "The deliverable must specify RSJ boundary-condition handling for near-zero or zero RV, insufficient valid bars, trading halts, missing adjustment factors, non-positive prices, and extreme returns."
    }
  ]
}
```

Then register it in `task.json`:

```json
{
  "rigors": "rigors.json"
}
```

When registered, `rigors.json` is treated as evaluator/control metadata. It is not copied as an ordinary task material unless selected through the runner.

## Converting Rubrics To Rigors

For each rubric, rewrite the evaluator question as an executor-facing hard requirement.

Good conversion rules:

- Keep the same requirement scope as the original rubric.
- Convert yes/no phrasing into “must” language.
- Preserve concrete thresholds, edge cases, named artifacts, or exclusion rules.
- Remove evaluator-only phrasing such as “Does the deliverable...”
- Do not add hidden expert knowledge that is absent from the rubric.
- Prefer one concise sentence unless the rubric itself is compound.
- Keep `id` equal to the rubric id whenever possible, so experiment commands stay readable.

Example:

```text
Rubric:
Does the deliverable define continuous intraday trading windows and state that returns must not be connected across price discontinuities?

Rigor:
The deliverable must define continuous intraday trading windows and state that returns must not be connected across price discontinuities caused by lunch breaks, temporary halts, circuit breakers, early closes, pre/post-market sessions, or cross-day boundaries.
```

## Selecting Rigors For An Experiment

A common first experiment is to choose rubrics that were failed in every baseline run.

Procedure:

1. Run the task without instructions or rigors for 5 repeats.
2. Inspect the five `judges/single_aggregate.json` files.
3. Count failed rubric frequency.
4. Select a small number of stable failures, usually 1-3 rubrics, and inject only their corresponding rigors.
5. Compare the new mean pass count and pass percentage against the baseline.

Stable failures are useful because they reduce noise: if a rubric already passes sometimes, an improvement may be caused by executor variance rather than by the injected rigor.

## Runner Usage

Select rigors with `--rigor`. Passing any `--rigor` value implies `--rigor-mode select`.

```bash
.venv/bin/starbench-run \
  --tasks-dir /tmp/rsj_v3_rigor \
  --runs-dir runs \
  --task task_package \
  --run-id rsj_v3_rigor_G_H_gpt55_high_test \
  --repeat 1 \
  --batch-size 1 \
  --executor-backend docker \
  --docker-image starbench-codex:latest \
  --auth-mode copy-auth \
  --codex-bin "codex -c 'model_reasoning_effort=\"high\"'" \
  --executor-model gpt-5.5 \
  --evaluator-model gpt-5.5 \
  --judge-mode single \
  --instruction-mode none \
  --rigor G \
  --rigor H \
  --seed 123
```

The materialized prompt is written to:

```text
runs/<run_id>/<task_run_id>/workspace/inputs/prompt.md
```

The run metadata records selected rigors in:

```text
runs/<run_id>/run_config.json
runs/<run_id>/<task_run_id>/manifest.json
runs/<run_id>/<task_run_id>/task_summary.json
```

## Interpretation

Rigor injection answers a narrow experimental question: “If the executor is given a direct form of selected rubric requirements, does it satisfy them more reliably?”

Interpretation guidelines:

- Large gains suggest the original failure may be partly due to prompt salience or task planning, not only inability.
- Small gains suggest the requirement may require deeper execution, domain judgment, or artifact production beyond explicit prompting.
- Regressions can happen when added requirements consume attention or cause the executor to overfit a narrow part of the task.
- Rigor-injected scores should not replace baseline benchmark scores unless the benchmark setting explicitly includes such assistance.

