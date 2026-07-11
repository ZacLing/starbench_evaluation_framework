# Custom Agent Runtime + Generalized Docker Backend — Design

Status: awaiting maintainer review
Date: 2026-07-04
Depends on: bug-fix commits `f057ae0` / `a4325df` / `16f726e`

## Problem

Every new agent CLI currently requires a hand-written adapter in
`codex_process.py` + `run_benchmark.py` (five adapters exist: codex, claude,
opencode, grok, gemini). Maintenance cost grows linearly with each vendor.
Separately, Docker isolation is Codex-only; all other runtimes run on the
host with permissions bypassed.

## Goals

1. `--executor-agent custom:<id>` / `--evaluator-agent custom:<id>`: plug in
   any headless agent CLI through a declarative config file, no Python
   changes.
2. Generalize the Docker execution path so non-Codex runtimes can opt in.

Non-goals (YAGNI, explicitly out of scope for v1):

- Python plugin parsers (arbitrary code execution surface, maintenance burden).
- Refactoring the five built-in adapters onto the new abstraction (regression
  risk; revisit only if the custom path proves itself).
- Per-runtime auth-mode variants for custom runtimes (v1 inherits host env +
  static `env` from config).

## Decisions taken by default (flagged for maintainer review)

| Decision | Choice | Rationale |
|---|---|---|
| Config shape | Declarative `runtimes/<id>.json` files | Committable, single source of truth, new agent = new file; matches project preference for explicit state files |
| Parsers | Three built-ins: `headless-json`, `jsonl-events`, `text` | Covers the dominant CLI output shapes; no plugin hook |
| Sequencing | Custom runtime first, Docker generalization in the same iteration, two milestone commits | Docker builds on the same process contract |

## Config schema — `runtimes/<id>.json`

```json
{
  "id": "qwen-code",
  "command": "qwen",
  "args": ["--output-format", "json", "--yolo"],
  "judge_args": ["--output-format", "json", "--approval-mode", "plan"],
  "model_flag": "-m",
  "prompt_via": "stdin",
  "prompt_flag": "-p",
  "parser": "headless-json",
  "env": {"SOME_STATIC_VAR": "1"},
  "docker": {
    "image": "starbench-qwen:latest",
    "env_passthrough": ["OPENAI_API_KEY", "OPENAI_BASE_URL"]
  }
}
```

Field semantics:

- `id` (required): must match filename; referenced as `custom:<id>`.
- `command` (required): executable or shell-like prefix, `shlex.split` like
  the existing `--*-bin` flags.
- `args`: extra argv for executor runs. `judge_args`: extra argv for judge
  runs; defaults to `args` when omitted (e.g. a read-only/plan variant).
- `model_flag`: how `--executor-model` / `--evaluator-model` is passed
  (`null`/omitted = model not passed on argv).
- `prompt_via`: `"stdin"` (default; prompt written to stdin) or `"arg"`
  (appended as `prompt_flag <prompt>`; docs warn about ARG_MAX for large
  prompts).
- `parser`: one of
  - `headless-json` — stdout is one JSON object (gemini/grok shape). Final
    text via the existing `_extract_headless_response_text`; events via
    `normalize_headless_events(provider=<id>)`.
  - `jsonl-events` — stdout is Codex-compatible JSONL `item.completed`
    events; passed through untouched, final = last `agent_message` text.
  - `text` — raw stdout is the final message; a single synthetic
    `agent_message` compat event is appended so trace_summary stays coherent.
- `env`: static environment additions for both executor and judge runs.
- `docker` (optional): presence enables `--executor-backend docker` for this
  runtime. `image` required; `env_passthrough` lists host env vars forwarded
  into the container (only when set, mirroring the codex whitelist behavior).

Judge structured output: always prompt-injected JSON schema
(`append_json_schema_instruction`) + `_extract_json_object` on the parsed
final text — identical to today's opencode/grok/gemini judge contract.

Executor skills install to `workspace/.starbench/executor_skills/<skill-id>/`
(same location and prompt wording as the opencode runtime).

## CLI surface

- `--runtimes-dir PATH` (default `<cwd>/runtimes`).
- `--executor-agent` / `--evaluator-agent` accept `custom:<id>` in addition
  to the five built-ins (argparse `choices` replaced by a validator).
- Missing/invalid runtime config fails at argument parsing, not mid-run.
- `run_config.json` records the resolved runtime spec (id + parsed fields)
  for reproducibility.

## Docker generalization

- Extract `run_agent_process_in_docker(...)` from the current codex-specific
  function: parameters `docker_image`, `workspace`, `inner_command`,
  `env_whitelist`, `container_name`, plus the existing hardening flags and
  the timeout `docker kill` from commit `a4325df`. The codex path delegates
  to it unchanged (zero behavior change).
- Custom runtimes with a `docker` section run their command inside the
  container with `/workspace` mounted, cwd `/workspace`.
- Built-in claude gains docker support: container env sets
  `CLAUDE_CONFIG_DIR=/workspace/.runner/claude_home`, whitelist
  `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_BASE_URL`;
  `docker/claude-code.Dockerfile` drops its `ENTRYPOINT` so the runner can
  invoke `claude` explicitly.
- `parse_args` backend validation updated: docker allowed for codex, claude,
  and any `custom:<id>` whose config has a `docker` section.
- Constraint: Colima/docker daemon is currently down on the dev machine, so
  v1 ships with unit tests for command construction + fake-CLI closed loops;
  a real-container smoke run is a follow-up when the daemon is available.

## Components

- `src/starbench/runner/custom_runtime.py` (new): `CustomRuntimeSpec`
  dataclass, `load_custom_runtime(dir, id)`, validation errors with file
  paths.
- `codex_process.py`: `build_custom_command(spec, ...)`,
  `write_custom_final_output(spec, ...)` (parser dispatch),
  `normalize_custom_events(spec, ...)`; `run_agent_process_in_docker`.
- `run_benchmark.py`: custom branches in `run_executor` /
  `run_single_judge` / `run_parallel_judges`; CLI flag + validation;
  skills install root for custom runtimes.

## Error handling

- Config errors (missing file, unknown parser, bad `prompt_via`) → SystemExit
  at parse time with the offending path.
- Runtime process failures reuse the per-task isolation from `a4325df`
  (failed task recorded, run continues).
- Parser failures (e.g. `text` judge output with no JSON) mark the task
  failed via the existing post-processing try/except pattern.

## Testing

- Unit: spec loading/validation, command construction (stdin vs arg,
  model_flag, judge_args fallback), each parser's final+events output,
  docker command construction for custom & claude.
- Closed loop (no live models): fake custom CLI in headless-json shape
  (reusing the fake_gemini pattern) through executor + judge to
  `single_aggregate.json`.
- All following the repo's existing fake-runner test conventions.

## Milestones

1. Custom runtime end-to-end (config → executor → judge → aggregate), fake
   CLI closed loop green. First commit.
2. Docker generalization (shared docker runner, claude + custom docker
   support, Dockerfile fix). Second commit. Real-container smoke deferred
   until docker daemon available.
