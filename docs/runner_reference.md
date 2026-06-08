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

- `--executor-model MODEL_ID`: exact model id passed to the selected executor runtime.
- `--evaluator-model MODEL_ID`: exact model id passed to the selected evaluator runtime.

These are independent. Starbench does not normalize model names. When the executor and evaluator use different runtimes, pair each model flag with the matching agent runtime flag from [Agent Runtimes](#agent-runtimes).

Example:

```bash
starbench-run \
  --executor-model gpt-5.4-mini \
  --evaluator-model gpt-5.5
```

Evaluator-only switch examples:

```bash
# GPT/OpenAI-family evaluator through Codex.
--evaluator-agent codex \
--evaluator-model gpt-5.5

# Claude-family evaluator through Claude Code.
--evaluator-agent claude \
--claude-bin /path/to/claude-or-wrapper \
--evaluator-model claude-opus-4-8

# Other OpenAI-compatible evaluator through OpenCode.
--evaluator-agent opencode \
--opencode-provider yunwu \
--opencode-base-url https://yunwu.ai/v1 \
--opencode-api-key-env ANTHROPIC_AUTH_TOKEN \
--evaluator-model yunwu/doubao-seed-2-0-pro-260215

# Grok Build evaluator.
--evaluator-agent grok \
--grok-bin grok \
--evaluator-model your-grok-model

# Gemini CLI evaluator.
--evaluator-agent gemini \
--gemini-bin gemini \
--evaluator-model gemini-2.5-pro
```

## Agent Runtimes

Use this runtime convention:

| Model family | Runtime |
|---|---|
| Claude-family models | Claude Code, `--executor-agent claude` / `--evaluator-agent claude` |
| GPT/OpenAI-family models | Codex, `--executor-agent codex` / `--evaluator-agent codex` |
| Other OpenAI-compatible models, such as Doubao or Qwen | OpenCode, `--executor-agent opencode` / `--evaluator-agent opencode` |
| xAI Grok Build models | Grok Build, `--executor-agent grok` / `--evaluator-agent grok` |
| Gemini CLI models | Gemini CLI, `--executor-agent gemini` / `--evaluator-agent gemini` |

Codex is the default executor and evaluator runtime, and is the expected runtime for GPT/OpenAI-family models:

```bash
--executor-agent codex
--evaluator-agent codex
```

Claude Code is the expected runtime for Claude-family models:

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

OpenCode is the expected runtime for other OpenAI-compatible models, including models that do not expose an Anthropic Messages API, such as Doubao:

```bash
--executor-agent opencode
--evaluator-agent opencode
--opencode-bin /path/to/opencode
--executor-backend local
--executor-model provider/model-id
--evaluator-model provider/model-id
```

For OpenAI-compatible gateways, Starbench can generate isolated OpenCode provider config through `OPENCODE_CONFIG_CONTENT`:

```bash
export ANTHROPIC_AUTH_TOKEN=...

starbench-run \
  --executor-agent opencode \
  --opencode-bin "$HOME/.opencode/bin/opencode" \
  --opencode-provider yunwu \
  --opencode-base-url https://yunwu.ai/v1 \
  --opencode-api-key-env ANTHROPIC_AUTH_TOKEN \
  --executor-model doubao-seed-2-0-pro-260215 \
  --executor-backend local
```

If `--executor-model` or `--evaluator-model` does not include a slash and `--opencode-provider` is set, Starbench passes it to OpenCode as `provider/model`. OpenCode evaluator runs do not currently have a CLI schema-enforcement flag equivalent to Codex `--output-schema`; Starbench appends the JSON schema to the evaluator prompt, parses the final assistant text from the OpenCode JSON event stream, and falls back to `opencode export` when needed.

When a run mixes runtimes, split auth modes if needed. For example, an OpenCode executor can read a gateway token from the environment while a Codex evaluator reads the local Codex login:

```bash
--executor-agent opencode \
--evaluator-agent codex \
--auth-mode env \
--executor-auth-mode env \
--evaluator-auth-mode global
```

Grok Build support uses the host `grok` CLI in headless mode:

```bash
starbench-run \
  --executor-agent grok \
  --evaluator-agent grok \
  --grok-bin grok \
  --executor-backend local \
  --auth-mode global \
  --executor-model your-grok-model \
  --evaluator-model your-grok-model
```

StarBench invokes Grok with `-p`, `--output-format json`, `--no-auto-update`, `--no-alt-screen`, and `--always-approve` for executor runs. Evaluators use read-only sandbox settings and prompt-level JSON schema instructions. Selected executor skills are installed under `./.grok/skills/<skill-id>/` inside the isolated task workspace.

Gemini CLI support uses the host `gemini` CLI in non-interactive JSON output mode:

```bash
starbench-run \
  --executor-agent gemini \
  --evaluator-agent gemini \
  --gemini-bin gemini \
  --executor-backend local \
  --auth-mode global \
  --executor-model gemini-2.5-pro \
  --evaluator-model gemini-2.5-pro
```

StarBench invokes Gemini with `--output-format json`, `--skip-trust`, and `-p ""` so the long StarBench prompt can still be sent on stdin. Executor runs use `--yolo`; evaluator runs use `--approval-mode plan`. Evaluators receive the JSON schema in the prompt, and StarBench extracts the final assistant response into `result.json`. Selected executor skills are installed under `./.gemini/skills/<skill-id>/` inside the isolated task workspace.

Grok Build and Gemini CLI executor support currently requires `--executor-backend local`. Docker support is still Codex-only because the bundled Docker image installs Codex and mounts a `CODEX_HOME`.

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
