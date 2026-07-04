# StarBench Console (GUI)

`starbench-gui` serves a local web console over a runs directory. It renders what
exists on disk (`runs/<run_id>/…`) and can launch new `starbench-run` processes on
the same machine. It never keeps its own database: delete a run directory and it
disappears from the console; copy one in and it shows up.

## The experiment model

The console's unit of work is the **experiment**: a fixed task set and one shared
judge (the controls) compared across multiple **contender** runtimes (the
variable). Launching an experiment orchestrates one plain `starbench-run` per
contender with identical tasks, judge, and seed, and records the grouping in
`<runs-dir>/experiments/<id>.json`. **Profiles** (`<runs-dir>/profiles.json`)
store the shared configuration plus a declaration of which fields each contender
fills in individually (model id, credentials, gateway); the default profile
pre-fills the wizard so repeated evaluations keep the same measurement
methodology. Both files are plain JSON you can edit or delete; the runs
themselves stay fully CLI-owned.

## Start

```bash
starbench-gui                       # serves ./runs on http://127.0.0.1:8321/
starbench-gui --runs-dir path/to/runs --port 9000
starbench-gui --tasks-dir tasks --tasks-dir examples/tasks
starbench-gui --no-browser          # do not open a browser tab
```

The server is standard-library only and binds to `127.0.0.1` by default. It is a
single-operator tool; do not expose it to a network.

## Views

- **Dashboard** — summary cards (runs, task pass rate, executor success, running
  now), pass rate by run, and recent runs.
- **AI providers** — named endpoints with credentials and model catalogs
  (`<runs-dir>/providers.json`; built-in presets until first save). A provider is
  a kind (Anthropic / OpenAI / Google / xAI / OpenAI-compatible, which decides
  the runtime), an optional base URL, the *name* of the API-key environment
  variable (keys themselves are never stored; presence is checked live), and a
  model list that can be imported from the public Vercel AI Gateway catalog.
  The wizard's unified model picker groups models by provider; choosing one
  auto-fills gateway flags (OpenAI-compatible → OpenCode) or injects
  `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` for Anthropic-compatible gateways.
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
- **New experiment** — a four-step wizard: pick tasks; add contender runtimes
  (model-family cards with brand icons; the runtime is mapped automatically);
  review the shared configuration from the active profile (judge, environment,
  seed/batch/repeat, per-contender field declaration) and optionally save it
  back; review the full launch plan (one command per contender) and launch.
  The judge is always explicit, and the console warns when it equals a
  contender's model, since self-grading biases scores. Docker isolation applies
  to Codex contenders only (a CLI constraint) and is labeled honestly on the
  others.

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
