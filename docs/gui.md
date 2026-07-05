# StarBench Console (GUI)

`starbench-gui` serves a local web console over a runs directory. It renders what
exists on disk (`runs/<run_id>/…`) and can launch new `starbench-run` processes on
the same machine. It never keeps its own database: delete a run directory and it
disappears from the console; copy one in and it shows up.

## The experiment model

The console's unit of work is the **experiment**: a fixed task set and one shared
judge (the controls) compared across multiple **agents under test** (the
variable). The agents are coding-agent CLIs — the five built-in runtimes
(Claude Code, Codex, Gemini CLI, Grok Build, OpenCode) plus any **custom
runtime** registered as a `runtimes/<id>.json` spec — each configured with a
model drawn from an AI provider; the model is configuration, the runtime is the
subject being measured. Launching an experiment orchestrates one plain
`starbench-run` per contender with identical tasks, judge, and seed, and records
the grouping in `<runs-dir>/experiments/<id>.json`. **Profiles**
(`<runs-dir>/profiles.json`) store the shared configuration plus a declaration
of which fields each contender fills in individually (model id, credentials,
gateway); the default profile pre-fills the wizard so repeated evaluations keep
the same measurement methodology. Both files are plain JSON you can edit or
delete; the runs themselves stay fully CLI-owned.

## Start

```bash
starbench-gui                       # serves ./runs on http://127.0.0.1:8321/
starbench-gui --runs-dir path/to/runs --port 9000
starbench-gui --tasks-dir tasks --tasks-dir examples/tasks
starbench-gui --runtimes-dir runtimes   # custom runtime specs (defaults to repo runtimes/)
starbench-gui --no-browser          # do not open a browser tab
```

The server is standard-library only and binds to `127.0.0.1` by default. It is a
single-operator tool; do not expose it to a network.

## Views

- **Dashboard** — summary cards (runs, task pass rate, executor success, running
  now), pass rate by run, and recent runs.
- **Agents** — the runtime resource side. Built-in runtime cards show wire
  protocol, compatible-provider count, Docker capability, and whether the CLI
  is on PATH. Custom runtimes are created and edited here as
  `runtimes/<id>.json` specs — the exact files the CLI consumes via
  `--executor-agent custom:<id>` / `--runtimes-dir`, validated by the runner's
  own loader so the console and CLI can never disagree. The form covers the
  full spec (command, args, judge args, model flag, prompt delivery incl.
  positional-argument CLIs, output parser, static env, Docker image +
  env passthrough) plus console-only fields stored in the same file: `protocol`
  decides which AI providers are offered, and `base_url_env` / `api_key_env`
  name the variables through which the selected provider's endpoint and key are
  injected at launch. Verified templates ship for Qwen Code, Kimi Code CLI, and
  Trae Agent; a spec the CLI cannot parse shows up as an error card, not a
  crash.
- **AI providers** — the resource side of every experiment
  (`<runs-dir>/providers.json`; built-in presets until first save). A provider is
  a kind (Anthropic / OpenAI / Google / xAI / OpenAI-compatible, which decides
  the runtime), a credential (either the *name* of an API-key environment
  variable, or the local CLI login; keys themselves are never stored), an
  optional base URL, and a **model catalog refreshed from the provider's own
  models API** — not edited by hand. CLI-login providers and missing keys fall
  back to a public vendor catalog snapshot, labeled as such. Contenders and the
  judge are pure references to a provider + model, and runtime-provider
  compatibility is decided by wire protocol: Claude Code takes any provider
  with an Anthropic-compatible endpoint (env injection), Codex takes any
  OpenAI-protocol provider (official codex config overrides; the endpoint must
  support the Responses API), Gemini CLI takes any provider with a
  Gemini-compatible endpoint (env injection), OpenCode takes any
  OpenAI-protocol provider (gateway flags), and Grok Build is official-only
  (its CLI has no endpoint override). The wizard contains no endpoint or
  credential inputs at all.
- **Task library** — task packages as browsable cards. Click one to preview its
  prompt and rubrics and launch it directly. Import new packages by dragging a
  task folder or `.zip` onto the page (validated server-side before anything is
  written), and register additional task folders with a built-in directory picker.
- **Runs** — every run in the runs directory with status, executor outcomes, and
  judge pass counts; sortable and filterable. Runs in flight refresh automatically.
- **Run detail** — summary cards, a live progress strip while executing, one row
  per task run, the instruction-ablation uplift table when present, and the full
  configuration.
- **Task run detail** — five panes: *Verdicts* (per-rubric verdicts with the
  judge's evidence), *Trace* (usage, commands, reasoning, file changes, raw
  events), *Final message*, *Artifacts*, *Logs*.
- **Experiment detail** — per-contender summary cards and a rubric × contender
  comparison matrix built from single-judge results, refreshed live while runs
  are in flight.
- **New experiment** — a four-step wizard: pick tasks; add agents from runtime
  cards (the five built-ins plus every registered custom runtime) and configure
  each with a provider + model; review the shared configuration from the active
  profile (judge, environment, seed/batch/repeat, per-agent field declaration)
  and optionally save it back; review the full launch plan (one command per
  agent) and launch. The judge is configured runtime-first — any built-in or
  custom runtime can judge — and the console warns when it shares a model with
  an agent under test, since self-grading biases scores. Docker isolation
  covers every built-in runtime — each in its own image, resolved per runtime
  (`make docker-images`) — and custom runtimes with a Docker image in their
  spec; the rest run locally and are labeled honestly. Because the executor
  and the judge share one process environment per run, the console rejects
  plans where an agent's injected endpoint variables would silently reroute
  the judge.

## Launching runs

The review step always shows the exact `starbench-run` command it will execute;
copy it to reproduce the run in a terminal. Launching starts the runner as a
subprocess of the console with output captured to
`<runs-dir>/<run_id>.launch.log`. Runs started by the console can be stopped from
the run page (SIGTERM). Runs started elsewhere are still visible; the console
detects activity from `progress_events.jsonl`.

Validation happens server-side: unknown runtimes, missing task directories,
malformed task packages, and duplicate run ids are rejected before anything is
spawned or written.

## Development

The frontend lives in `gui-frontend/` (React + Vite + Tailwind + shadcn/ui). Its
production build is committed under `src/starbench/gui/static/`, so installing and
running the console needs Python only; Node is required only to change the UI.

```bash
make gui-build   # rebuild src/starbench/gui/static from gui-frontend/
make gui-dev     # Vite dev server with /api proxied to a running starbench-gui
```

For live development, run `starbench-gui --no-browser` in one terminal and
`make gui-dev` in another, then open the Vite URL.

## Relationship to the CLI

The console adds no capability the CLI lacks. Anything it launches is a plain
`starbench-run` invocation, and everything it displays comes from the documented
run layout (see the [Runner Reference](runner_reference.md) and the output layout
in the README).
