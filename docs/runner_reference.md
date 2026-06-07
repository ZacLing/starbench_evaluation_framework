# Runner Reference

The main command is:

```bash
starbench-run [options]
```

## Core Options

- `--tasks-dir PATH`: directory containing task packages. Default: `tasks`.
- `--runs-dir PATH`: directory for run outputs. Default: `runs`.
- `--task ID_OR_DIR`: include one task. Repeat for multiple tasks.
- `--repeat N`: repeat the selected task list.
- `--seed INT`: controls task shuffle, batch grouping, and evaluator launch order.
- `--batch-size N`: number of executor tasks to run concurrently.
- `--run-id NAME`: stable output directory name.

The seed controls Starbench scheduling randomness. It does not claim to make model internals deterministic.

## Models

- `--executor-model MODEL_ID`: exact model id passed to executor `codex exec -m`.
- `--evaluator-model MODEL_ID`: exact model id passed to evaluator `codex exec -m`.

These are independent. Starbench does not normalize model names.

Example:

```bash
starbench-run \
  --executor-model gpt-5.4-mini \
  --evaluator-model gpt-5.5
```

## Agent Runtimes

Codex is the default executor and evaluator runtime:

```bash
--executor-agent codex
--evaluator-agent codex
```

Claude Code can also be selected for either side:

```bash
--executor-agent claude
--evaluator-agent claude
--claude-bin /path/to/claude-or-wrapper
--executor-model claude-opus-4-8
--evaluator-model claude-opus-4-8
```

Claude Code runs through `claude -p --output-format json`. Evaluators use Claude Code structured output with `--json-schema`, and Starbench writes the resulting `structured_output` into the same judge result files used by Codex evaluators.

Claude Code does not currently expose a native CLI equivalent of Codex `model_reasoning_effort`. Starbench provides a prompt-level control:

```bash
--claude-thinking-effort high
```

The allowed values are `none`, `low`, `medium`, and `high`. They append increasingly explicit think/deep-think instructions to Claude Code prompts and are recorded in `run_config.json`. This is not the same as directly sending Anthropic API `thinking.effort`.

For proxy/API-gateway use, set Claude Code environment variables before launching the runner:

```bash
export ANTHROPIC_BASE_URL=https://your-anthropic-compatible-gateway
export ANTHROPIC_AUTH_TOKEN=...
```

Claude executor support currently uses `--executor-backend local`. If the host does not have `claude`, build the helper image and use the Docker wrapper:

```bash
docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .

starbench-run \
  --executor-agent claude \
  --evaluator-agent claude \
  --claude-bin /absolute/path/to/tmp/claude-code-docker.sh \
  --executor-backend local
```

## Judge Modes

- `--judge-mode single`: one evaluator sees all rubrics for a task.
- `--judge-mode parallel`: one evaluator per rubric.
- `--judge-mode both`: run both modes.

For large rubric sets, `single` is usually faster and cheaper. `parallel` is useful when you want independent rubric judgments.

Control evaluator concurrency:

```bash
--max-evaluator-parallel 4
```

## Executor Backend

Default:

```bash
--executor-backend docker
```

Alternative for local debugging:

```bash
--executor-backend local
```

Docker executor options:

- `--docker-bin docker`
- `--docker-image starbench-codex:latest`

## Authentication

- `--auth-mode env`: pass `CODEX_API_KEY` or compatible environment variables.
- `--auth-mode copy-auth`: copy local CLI auth into per-task isolated Codex homes.
- `--auth-mode global`: use the host credential environment directly for local runs.

For Docker runs, `copy-auth` or `env` is recommended.

## Human Reference Instructions

Run a baseline with no extra instructions:

```bash
starbench-run --instruction-mode none
```

Run one executor per human-reference step:

```bash
starbench-run --instruction-mode traverse
```

Run one executor with selected step ids appended together:

```bash
starbench-run --instruction-mode select --instruction-step H001 --instruction-step H004
```

Run a baseline, one executor per human-reference step, and one all-instructions executor:

```bash
starbench-run --instruction-mode ablation --repeat 5 --judge-mode single
```

Only `instruction` text is appended to the executor prompt. `reasoning` stays hidden in the task package and is not copied into executor or evaluator workspaces. For instruction variants, the augmented prompt is also written to `workspace/inputs/prompt.md` so the exact task seen by the executor is replayable.

When `--instruction-mode ablation` is used, the runner also writes:

- `instruction_ablation_summary.json`: grouped pass-rate and rubric-level deltas versus baseline.
- `instruction_ablation_summary.md`: compact human-readable uplift report.
