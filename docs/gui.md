# StarBench Console (GUI)

`starbench-gui` serves a local web console over a runs directory. It renders what
exists on disk (`<runs-dir>/<run_id>/…`) and can launch new `starbench-run` processes on
the same machine. It never keeps its own database: delete a run directory and it
disappears from the console; copy one in and it shows up.

The console consumes the same public task-package and run-artifact contracts as
the CLI; see [Artifact Contracts](artifact_contracts.md).

## The experiment model

The console's unit of work is the **experiment**: a fixed task set and one shared
judge (the controls) compared across multiple **agents under test** (the
variable). The agents are coding-agent CLIs — the six built-in runtimes
(Claude Code, Codex, Gemini CLI, Grok Build, OpenCode, Pi) plus any **custom
runtime** registered as a `runtimes/<id>.json` spec — each configured with a
model drawn from an AI provider; the model is configuration, the runtime is the
subject being measured. Launching a batch orchestrates one plain
`starbench-run` per contender with identical tasks, judge, and seed; the batch
name rides each launch as `--batch`, so the runner records it in the run's
`run_config.json` (a measurement fact; runs from before this promotion carry it
only in the supervisor's `run_state.json`, which the read model still falls back
to), and cross-run comparison is computed statelessly from artifacts
(`/api/compare?runs=…`). **Profiles**
(`<runs-dir>/profiles.json`) store the shared configuration plus a declaration
of which fields each contender fills in individually (model id, credentials,
gateway); the default profile pre-fills the wizard so repeated evaluations keep
the same measurement methodology. A profile can additionally declare a
**roster** (the contender columns it intends to measure) and a **task_set**,
making it a complete, launchable measurement contract; launching from such a
profile hands each contender's run a self-contained `profile_snapshot.json`
(validated and written by the runner) that pins the contract as of launch —
profile id + revision, this contender, the full roster, instrument, execution
parameters, and resolved task list — with provider endpoints inlined and only
env-var *names* for credentials, never key values. Editing the profile later
never rewrites past runs' snapshots, and runs launched without a
roster-carrying profile stay fully supported. Both files are plain JSON you can
edit or delete; the runs themselves stay fully CLI-owned.

## Start

```bash
starbench-gui                       # serves $STARBENCH_HOME/runs (default ~/.starbench/runs) on http://127.0.0.1:8321/
starbench-gui --runs-dir path/to/runs --port 9000
starbench-gui --tasks-dir path/to/tasks     # single task library; pass at most one --tasks-dir
starbench-gui --runtimes-dir runtimes       # custom runtime specs (default: $STARBENCH_HOME/runtimes, ~/.starbench/runtimes)
starbench-gui --skills-dir skills           # executor skill library (default: $STARBENCH_HOME/skills, ~/.starbench/skills)
starbench-gui --no-browser          # do not open a browser tab
```

Every directory flag defaults to the StarBench home layout — explicit flag >
`$STARBENCH_HOME` > `~/.starbench` — never to the working directory. A fresh
home has an empty task library until it is seeded; see the README Quick
Start for `mkdir -p ~/.starbench/tasks` followed by
`cp -r examples/tasks/* ~/.starbench/tasks/`.

The server is standard-library only and binds to `127.0.0.1` by default. It is a
single-operator tool; do not expose it to a network.

## Views

- **Overview** — KPI cards (task pass rate, completed runs, running now, needs
  attention) plus coverage/volume/runtime tiles, progress over time, runs by
  status, a per-task performance heatmap, and side panels for what is running
  now and recent failures.
- **Run matrix** — task resilience across every agent × model combination on
  disk, one metric lens at a time; scoped by the active profile's roster when
  one is set.
- **Agents** — the runtime resource side. Built-in runtime cards show wire
  protocol, compatible-provider count, Docker capability, and whether the CLI
  is on PATH. Install/Update goes through each runtime's *official* channel:
  the vendor's standalone installer script for Codex, Claude Code, opencode,
  Pi, and Kimi Code (the card badge names the script's source domain, because
  running a remote script is a bigger trust grant than npm; updates prefer the
  CLI's own self-updater — `codex update`, `claude update`, `opencode
  upgrade` — which detects its install channel and swaps atomically), and the
  official npm package for Gemini CLI, Grok, DeepSeek Harness, and Qwen Code.
  Pi's script is a
  hardened npm install, so its on-disk artifact classifies as npm-layout
  (`artifact_channel`) and never trips the mismatch warning. Latest
  versions come from the channel's own source of truth (npm registry or
  GitHub releases), cached server-side. The status probe classifies every
  discovered copy of a CLI by realpath — the PATH hit plus each runtime's
  known install drop points and the npm global bin — and the card shows a
  warning with per-copy channel/version/path evidence whenever copies from
  different channels coexist or PATH runs a different channel than the
  official one (the way a stale standalone binary silently shadows an
  npm-installed update). Custom runtimes are created and edited here as
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
  OpenAI-protocol or xAI provider (gateway flags), Pi takes any Anthropic, OpenAI,
  Google, or xAI provider (its four native provider kinds, key injected as
  that vendor's own env var), and Grok Build is official-only (its CLI has no
  endpoint override). The wizard contains no endpoint or credential inputs at
  all.
- **Skills** — the executor skill library (`$STARBENCH_HOME/skills` by default,
  or `--skills-dir`) as read-only cards plus the groups declared over it; a
  library that cannot be read is reported as an error, not hidden.
- **Profiles** — the measurement contracts in `<runs-dir>/profiles.json`, edited
  as a form: executors/roster, instrument (judge), execution parameters, task
  set, and the per-agent field declaration. Built-in templates show until the
  first save creates the file.
- **Task library** — the console's single task library (the home
  `$STARBENCH_HOME/tasks` directory by default, or whatever directory
  `--tasks-dir` names) as browsable cards; a fresh, unseeded home shows an
  empty library rather than falling back to the repo's `examples/tasks/`.
  Click a card to preview its prompt and rubrics and launch it directly.
  Import new packages by dragging a task folder or `.zip` onto the page
  (validated server-side before anything is written; the library directory is
  created on the first import if it does not exist yet). There is exactly one
  library per running console — directory registration and server-side
  browsing of other folders are gone; start the console with a different
  `--tasks-dir` to serve a different library.
- **Runs** — every run in the runs directory with status, executor outcomes, and
  judge pass counts; sortable and filterable. Runs in flight refresh automatically.
- **Run detail** — summary cards, a live progress strip while executing, one row
  per task run, the instruction-ablation uplift table when present, and the full
  configuration.
- **Task run detail** — four panes: *Trace* (usage, commands, reasoning, file
  changes, raw events), *Deliverables* (the executor's output files, with the
  final message pinned at the top of the list), *Verdicts* (per-rubric verdicts
  with the judge's evidence), *Logs*.
- **Compare** — a stateless comparison named entirely by the URL
  (`/compare?runs=a,b,c`; nothing is created or persisted): one summary card per
  run and a rubric × run matrix per task built from single-judge results,
  refreshed live while runs are in flight.
- **New experiment** — a five-step wizard: choose the launch mode (from a
  rostered profile, or a custom launch); pick tasks; add agents from runtime
  cards (the six built-ins plus every registered custom runtime) and configure
  each with a provider + model; review the shared configuration from the active
  profile (judge, environment, seed/batch/repeat, per-agent field declaration)
  and optionally save it back; review the full launch plan (one command per
  agent) and launch. The judge is configured runtime-first — any built-in or
  custom runtime can judge — and the console warns when it shares a model with
  an agent under test, since self-grading biases scores. Docker isolation covers
  every built-in runtime — each in its own image,
  resolved per runtime (`make docker-images`) — and custom runtimes with a
  Docker image in their spec; the rest run locally and are labeled honestly.
  The executor and the judge run under isolated environment scopes (the console
  ships each side's injected variables under a `STARBENCH_EXECUTOR_ENV_*` /
  `STARBENCH_JUDGE_ENV_*` prefix that the runner unpacks separately), so an
  agent's injected endpoint no longer reroutes the judge; a variable read by
  both is surfaced as an amber advisory in the plan, not a rejection. Shared
  config also carries research experiments — executor skills, with a per-skill
  **Off / Available / Required by prompt** control, and a **Prompt assistance**
  region whose Expert instructions sub-section runs the
  human-reference sweep (none / selected steps / traverse / ablation) and whose
  **Rigor requirements** sub-section (off by default) restates selected rubric
  requirements as hard requirements in every agent's prompt — a controlled
  experiment that injects into the existing runs without expanding variants. The
  review step separates available from required skills and states that required
  usage is instructed rather than trace-verified. A skill supplied by a group
  remains available by default and can be upgraded individually to required.
  The review step's billing uses the backend execution estimate so any variant
  fan-out is visible before launch.

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
