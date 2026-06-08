# Model Runtime Matrix

This document records the required CLI/runtime mapping for Starbench model-family evaluations.

## Required Runtime Mapping

| Model family | Required CLI/runtime | Notes |
|---|---|---|
| GPT models | Codex CLI | Use Starbench's `codex` agent path. |
| Claude models | Claude Code | Use Starbench's `claude` agent path. |
| Gemini models | Gemini CLI | Use Starbench's `gemini` agent path. |
| Grok models | Grok Build CLI | Use Starbench's `grok` agent path. |

## Starbench Agent Selection

The framework exposes dedicated agent paths for Codex, Claude Code, Gemini CLI, and Grok Build CLI:

```bash
--executor-agent codex
--evaluator-agent codex
```

```bash
--executor-agent claude
--evaluator-agent claude
```

```bash
--executor-agent gemini
--evaluator-agent gemini
```

```bash
--executor-agent grok
--evaluator-agent grok
```

Gemini CLI and Grok Build CLI should not be routed through OpenCode when the benchmark is comparing native CLI behavior. Their native adapters should preserve the same process contract:

- receive the task prompt,
- run in the prepared task workspace,
- write the final assistant message,
- emit or normalize trace events,
- support evaluator structured output when used as a judge.

## Five-Run Evaluation Convention

For model comparisons on the same task package, run five repeats with executor parallelism:

```bash
starbench-run \
  --task <task-id-or-dir> \
  --repeat 5 \
  --batch-size 5 \
  --judge-mode single \
  --run-id <model-task-run-id>
```

Final rubric scores are read from each task run's:

```text
runs/<run_id>/<task_run_id>/judges/single_aggregate.json
```

Use `passed_count / total_count` as the per-run final rubric score, and report the five-run mean and standard deviation when comparing models.
