# Runner Reference

The main command is:

```bash
starbench-run [options]
```

For stable run-output files written by this command, see
[Artifact Contracts](artifact_contracts.md).

## Core Options

- `--tasks-dir PATH`: directory containing task packages. Default: `$STARBENCH_HOME/tasks` (`~/.starbench/tasks`).
- `--runs-dir PATH`: directory for run outputs. Default: `$STARBENCH_HOME/runs` (`~/.starbench/runs`).
- `--task ID_OR_DIR`: include one task. Repeat for multiple tasks.
- `--repeat N`: repeat the selected task list.
- `--seed INT`: controls task shuffle, batch grouping, and evaluator launch order.
- `--batch-size N`: number of executor tasks to run concurrently.
- `--run-id NAME`: stable output directory name.
- `--batch NAME`: experiment batch label recorded in `run_config.json`. Runs launched together share it, and the console groups and compares them by it. Optional; a run without one is simply unlabelled. Note: `--batch` no longer abbreviates `--batch-size`. Argparse's unambiguous-prefix matching used to accept the shorter `--batch` as shorthand for `--batch-size`; now that `--batch` is its own flag, that shortcut is gone — always spell `--batch-size` in full.

The seed controls Starbench scheduling randomness. It does not claim to make model internals deterministic.

## Profile Snapshot

- `--profile-snapshot PATH`: a JSON file carrying the launch-time measurement contract (profile identity + revision, this run's contender, the full roster, judge instrument, execution parameters, resolved task set — see `schemas/starbench/v1/profile_snapshot.schema.json`). The runner validates it against the public contract **before anything is written**: an unreadable file, invalid JSON, or a contract violation aborts the start and no run directory is created (fail closed, never a silent drop). A valid snapshot is written atomically to `<run-root>/profile_snapshot.json`, so the run carries the exact contract it was launched under even after the profile is edited later. Credentials never travel through a snapshot — the contract only has fields for environment-variable *names* (`api_key_env`) and rejects unknown keys. The console passes this flag automatically when launching from a profile that declares a roster; runs without it stay fully supported.

## Models

- `--executor-model MODEL_ID`: exact model id passed to the selected executor runtime.
- `--evaluator-model MODEL_ID`: exact model id passed to the selected evaluator runtime.

These are independent. Starbench does not normalize model names. When the executor and evaluator use different runtimes, pair each model flag with the matching agent runtime flag from [Agent Runtimes](#agent-runtimes).

The executable is role-scoped as well:

- `--executor-bin COMMAND`: override only the executor runtime command.
- `--evaluator-bin COMMAND`: override only the evaluator runtime command.

The historical runtime flags (`--codex-bin`, `--claude-bin`, `--opencode-bin`,
and peers) remain shared defaults for backward compatibility. Prefer the
role-specific flags when executor and evaluator use the same runtime through
different wrappers or endpoints. A command may include fixed arguments, for
example `--executor-bin "codex -c model_provider=openrouter"`.

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
--evaluator-option provider=yunwu \
--evaluator-option base_url=https://yunwu.ai/v1 \
--evaluator-option api_key_env=ANTHROPIC_AUTH_TOKEN \
--evaluator-model yunwu/doubao-seed-2-0-pro-260215

# Grok Build evaluator.
--evaluator-agent grok \
--grok-bin grok \
--evaluator-model your-grok-model

# Gemini CLI evaluator.
--evaluator-agent gemini \
--gemini-bin gemini \
--evaluator-model gemini-2.5-pro

# Pi evaluator (auth mode env only).
--evaluator-agent pi \
--pi-bin pi \
--evaluator-auth-mode env \
--evaluator-option provider=anthropic \
--evaluator-model claude-opus-4-8
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
| Anthropic, OpenAI, Google, or xAI models through one multi-provider CLI | Pi, `--executor-agent pi` / `--evaluator-agent pi` |
| Any other headless agent CLI | Custom runtime, `--executor-agent custom:<id>` / `--evaluator-agent custom:<id>` |

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

Claude Code executors run through `claude -p --output-format stream-json`, so the full event trace (reasoning, commands, file changes, usage) is captured and normalized into the same Codex-style `trace_summary.json` items used by other runtimes. Evaluators run through `claude -p --output-format json` with `--json-schema` structured output, and Starbench writes the resulting `structured_output` into the same judge result files used by Codex evaluators. Runs that exit 0 but report `is_error` (for example "Not logged in") are treated as failed instead of being graded.

Claude Code executors have no agentic turn cap by default, matching other runtimes. Set one explicitly if needed:

```bash
--executor-option max_turns=30
```

When a task package sets `allow_web_search: true` (or the run forces it with `--web-search allow`), the Claude executor tool allowlist additionally includes `WebSearch` and `WebFetch`; otherwise both stay disabled. `--web-search` defaults to `task`, which follows each package's own flag.

Reasoning effort is a run-level knob shared by all runtimes:

```bash
--thinking-effort high
```

The tiers are `default`, `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, and `ultra` (`none` is the deprecated spelling of `default`, which leaves the runtime/model default alone). `off` is distinct from `default`: it passes the runtime's switch to explicitly disable reasoning, where `default` passes no switch at all. Runtimes with a native switch apply it there (Claude Code `--effort`, Codex `model_reasoning_effort`, OpenCode `--variant`, Pi `--thinking`); the rest get a prompt-level instruction (`low`/`medium`/`high` only). Each runtime declares the tiers its CLI accepts and the runner rejects unsupported levels at start; the value is recorded in `run_config.json`. `--claude-thinking-effort` remains as a deprecated alias.

`--thinking-effort` is a single run-level value that applies to the executor and the evaluator alike, but the start-up check validates it against the **executor** runtime only. A tier that only one side's runtime declares therefore reaches the judge unclamped: `off` is declared by Pi alone, so `--executor-agent pi --thinking-effort off` paired with a Claude Code evaluator hands `off` to the judge side, which has no instruction for that tier and fails the judge call. The asymmetry bites same-runtime pairs too: a Claude executor takes `xhigh` on its native `--effort` switch, but a Claude evaluator renders the tier through the prompt-instruction table, which stops at `high` — so `--executor-agent claude --evaluator-agent claude --thinking-effort xhigh` passes the start-up check and then fails the judge call. Pick a tier both sides accept.

For proxy/API-gateway use, set Claude Code environment variables before launching the runner:

```bash
export ANTHROPIC_BASE_URL=https://your-anthropic-compatible-gateway
export ANTHROPIC_AUTH_TOKEN=...
```

The Claude executor defaults to `--executor-backend local` (the automatic default for every non-Codex runtime). With `--auth-mode global`, Starbench keeps the host `CLAUDE_CONFIG_DIR` so the host `claude` login is used directly; with `--auth-mode env`, each task gets an isolated config dir and credentials must come from `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`.

If the host does not have `claude`, build the runtime's own image and select it with `--executor-backend docker`; the adapter mounts the task workspace and passes the `ANTHROPIC_*` variables through itself, so no `--claude-bin` wrapper script is needed:

```bash
docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .
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
  --executor-option provider=yunwu \
  --executor-option base_url=https://yunwu.ai/v1 \
  --executor-option api_key_env=ANTHROPIC_AUTH_TOKEN \
  --executor-model doubao-seed-2-0-pro-260215 \
  --executor-backend local
```

OpenCode gateway settings are role-scoped through the repeatable
`--executor-option` / `--evaluator-option` flags (option names `provider`,
`base_url`, `api_key_env`). Each role carries its own option box, so one side
cannot reroute the other; `api_key_env` defaults to `OPENAI_API_KEY` per role,
while `provider` and `base_url` stay unset unless given. A mixed-provider run
sets each side explicitly:

```bash
starbench-run \
  --executor-agent opencode \
  --executor-option provider=openrouter \
  --executor-option base_url=https://openrouter.ai/api/v1 \
  --executor-option api_key_env=OPENROUTER_API_KEY \
  --executor-model openai/gpt-5.3-codex \
  --evaluator-agent opencode \
  --evaluator-option provider=internal-judge \
  --evaluator-option base_url=https://judge.example/v1 \
  --evaluator-option api_key_env=JUDGE_API_KEY \
  --evaluator-model judge/gpt-5.5
```

If `--executor-model` or `--evaluator-model` does not include a slash and the
corresponding role's OpenCode provider is set, Starbench passes it to OpenCode
as `provider/model`. OpenCode evaluator runs do not currently have a CLI
schema-enforcement flag equivalent to Codex `--output-schema`; Starbench
appends the JSON schema to the evaluator prompt, parses the final assistant
text from the OpenCode JSON event stream, and falls back to `opencode export`
when needed.

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

StarBench invokes Gemini with `--output-format json`, `--skip-trust`, and `-p ""` so the long StarBench prompt can still be sent on stdin. Executor runs use `--yolo`; evaluator runs use `--approval-mode plan`. Evaluators receive the JSON schema in the prompt, and StarBench extracts the final assistant response into the judge result file. Selected executor skills are installed under `./.gemini/skills/<skill-id>/` inside the isolated task workspace.

Pi is one CLI over four native provider kinds (Anthropic, OpenAI, Google, xAI) and runs headless through `pi --mode json`:

```bash
starbench-run \
  --executor-agent pi \
  --evaluator-agent pi \
  --pi-bin pi \
  --executor-backend local \
  --auth-mode env \
  --executor-option provider=anthropic \
  --evaluator-option provider=anthropic \
  --executor-model claude-opus-4-8 \
  --evaluator-model claude-opus-4-8
```

StarBench invokes Pi with `--mode json` and `--no-skills`, and sends the prompt on stdin. `--no-skills` turns off Pi's own skill discovery, and each selected executor skill is then passed back explicitly as `--skill <path>`, so a run only ever loads the skills it chose; evaluator runs get no `--skill` at all. Reasoning rides Pi's native `--thinking` flag, which is the one runtime accepting the `off` tier (`off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; `default` passes no flag). Evaluators receive the JSON schema in the prompt, and StarBench extracts the final assistant message from the event stream into the judge result file. `--executor-option provider=<kind>` / `--evaluator-option provider=<kind>` select which provider Pi talks to.

Pi accepts `--auth-mode env` only; `global` and `copy-auth` are refused by the adapter and fail the task with that reason recorded in `status.json`. Every run gets its own `PI_CODING_AGENT_DIR` under the task's `agent_home/` (the executor and the judge get separate ones), with `PI_CODING_AGENT_SESSION_DIR` pinned beneath it, and `PI_OFFLINE` / `PI_SKIP_VERSION_CHECK` are forced on, so the operator's `~/.pi` OAuth login never carries benchmark traffic. Credentials come from the provider's own API-key variable: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, or `XAI_API_KEY`.

In Pi's container the isolation home moves into the workspace mount (`/workspace/.runner/pi_home`), so session artifacts stay readable from the host after the run. Per-runtime image and backend rules: [Executor Backend](#executor-backend).

Custom runtimes plug in any other headless agent CLI through a declarative
config file — no Python adapter:

```bash
starbench-run \
  --executor-agent custom:qwen-code \
  --evaluator-agent custom:qwen-code \
  --runtimes-dir runtimes \
  --executor-model qwen3-coder \
  --evaluator-model qwen3-coder
```

`--runtimes-dir` (default `$STARBENCH_HOME/runtimes`, i.e. `~/.starbench/runtimes`) holds one `<id>.json` per runtime
declaring the command, prompt delivery (`stdin` or argv), one of three output
parsers (`headless-json`, `jsonl-events`, `text`), static env, and an
optional docker image. Configs are validated at argument parsing. Field
reference and parser contracts: [runtimes/README.md](../runtimes/README.md).

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

The default follows the executor runtime: `docker` for Codex, `local` for all other runtimes. Docker can be selected explicitly for every built-in — each has its own image, all built by `make docker-images` — and for custom runtimes that declare a `docker` section; other combinations are rejected at argument parsing.

```bash
# Claude Code in Docker (auth via environment):
docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .
starbench-run \
  --executor-agent claude \
  --executor-backend docker \
  --docker-image starbench-claude-code:latest \
  --executor-auth-mode env
```

```bash
--executor-backend docker   # codex default
--executor-backend local    # other runtimes, or codex local debugging
```

On executor timeout, Starbench kills the Docker container itself (not just the `docker run` client), so timed-out tasks cannot keep writing into the workspace.

Docker executor options:

- `--docker-bin docker`
- `--docker-image starbench-codex:latest`

## Authentication

- `--auth-mode env`: pass `CODEX_API_KEY` or compatible environment variables.
- `--auth-mode copy-auth`: copy local CLI auth into per-task isolated Codex homes.
- `--auth-mode global`: use the host credential environment directly for local runs.

For Docker runs, `copy-auth` or `env` is recommended.

## Environment Scopes (executor vs judge)

A single `starbench-run` process runs both the executor and the judge, so their
environments must be kept apart: a contender's `OPENAI_BASE_URL` must not reroute
an OpenAI-family judge in the same run. The runner therefore builds two base
environments from its own process environment:

- Plain (unprefixed) variables are visible to **both** sides. Running the CLI
  directly from a terminal — where nothing is prefixed — leaves executor and
  judge with the ambient environment, exactly as before.
- Variables named `STARBENCH_EXECUTOR_ENV_<VAR>` are stripped of the prefix and
  placed in the **executor** scope only; `STARBENCH_JUDGE_ENV_<VAR>` variables go
  to the **judge** scope only. The prefix names themselves are removed from the
  ambient environment, so nothing leaks between scopes or into child processes.

Adapters build their run environment on top of the side's base env (never a bare
`os.environ.copy()`), so the isolation holds for local and Docker runs alike.
Only *values* travel in environment variables — never on the command line (`ps`
visible) or in a temp file. The console uses these prefixes to route each
contender's and the judge's injected endpoint/credentials to the correct side;
running the CLI by hand you would set them the same way if you needed one
variable seen by only one side, e.g.:

```bash
STARBENCH_EXECUTOR_ENV_OPENAI_BASE_URL=https://openrouter.ai/api/v1 \
  starbench-run --executor-agent opencode --evaluator-agent codex ...
# executor talks to OpenRouter; the Codex judge keeps the official endpoint.
```

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

Only `instruction` text is appended to the executor prompt. `reasoning` stays hidden in the task package and is not copied into executor or evaluator workspaces. Every run writes the augmented prompt to `workspace/inputs/prompt.md` so the exact task seen by the executor is replayable.

When `--instruction-mode ablation` is used, the runner also writes:

- `instruction_ablation_summary.json`: grouped pass-rate and rubric-level deltas versus baseline.
- `instruction_ablation_summary.md`: compact human-readable uplift report.
