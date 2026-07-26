# Starbench Evaluation Framework

Starbench is a small benchmark runner for evaluating coding-agent CLIs with rubric judges.

It runs executor agents on task packages, captures the event trace exposed by the CLI, then grades the delivered outputs with yes/no rubrics. Every built-in runtime has its own Docker executor image for isolated runs (Codex defaults to Docker; the others opt in with `--executor-backend docker`), and docker-enabled custom runtimes get the same isolation. Evaluators inspect only the delivered package, trace summaries, and rubrics.

## What Is Included

- Batch execution with `--seed`, `--batch-size`, `--repeat`, and deterministic task ordering.
- A typed launch contract: `starbench-run --plan plan.json` takes one validated JSON file ([schemas/starbench/v1/run_plan.schema.json](schemas/starbench/v1/run_plan.schema.json)) instead of thirty flags, fails closed before any run state exists, and materializes the plan into the run directory for provenance. Flag-by-flag argv still works and shares the same validation.
- Per-runtime Docker executor images for isolated execution (see [docs/docker.md](docs/docker.md)).
- Independent executor and evaluator model selection, with separate auth modes and isolated executor/judge environment scopes.
- Runtime selection for Codex, Claude Code, OpenCode, Grok Build, or Gemini CLI executors/evaluators.
  - Use Claude Code for Claude-family models.
  - Use Codex for GPT/OpenAI-family models.
  - Use OpenCode for other OpenAI-compatible models, such as Doubao or Qwen.
  - Use Grok Build for xAI Grok Build runs.
  - Use Gemini CLI for existing Gemini CLI environments.
- Declarative custom runtimes (`custom:<id>`), with Qwen Code, Kimi Code CLI, and Trae Agent specs bundled in `runtimes/`.
- `--thinking-effort {default,minimal,low,medium,high,xhigh,max,ultra}` applied through each runtime's native reasoning switch where one exists (Claude Code `--effort`, Codex `model_reasoning_effort`, OpenCode `--variant`) and as a prompt-level instruction elsewhere. `default` leaves the runtime/model default alone (`none` is its deprecated spelling); each runtime declares which tiers it supports, and the console narrows the choice further to the selected model's own published level table where the runtime ships one (Codex model catalog).
- `--web-search {task,allow,deny}`: follow each task package's `allow_web_search` or override it for the run (enforced for Claude Code and Codex; other runtimes' own tooling decides).
- Single-judge and per-rubric parallel-judge modes.
- `human_reference.json` instruction sweep support.
- Rule-based instruction ablation: baseline, one variant per expert instruction, and an all-instructions variant, with repeat runs and uplift summaries.
- Rigor prompt injection: restate selected rubric requirements as hard requirements in the executor prompt.
- Executor skills: install reusable skill folders into the executor workspace, individually or as named groups.
- Trace capture: raw JSONL events, final message, status/timing, artifact manifest, and derived summary.
- A default task library at `$STARBENCH_HOME/tasks` (`~/.starbench/tasks`) for user task packages.
- Two sample task packages under `examples/tasks/`.
- Unit and closed-loop fake-runner smoke tests that do not call a live model.
- A local GUI console (`starbench-gui`): a five-step launch wizard with readiness checks (broken task packages surfaced, CLI/credential/Docker preflight gating Launch), reusable measurement profiles (shared judge/seed/roster/task set, frozen into each run as `profile_snapshot.json`), a task-by-agent coverage matrix, run browsing with rubric verdicts and traces, and stateless side-by-side comparison of any runs (`/api/compare?runs=a,b,c`).

## Quick Start

StarBench keeps everything — task packages, run results, custom runtimes,
executor skills — under one home: `~/.starbench`, relocatable with
`STARBENCH_HOME`. Explicit `--tasks-dir` / `--runs-dir` flags always win.

    pip install starbench
    mkdir -p ~/.starbench/tasks
    cp -r examples/tasks/* ~/.starbench/tasks/   # seed the library (from a repo checkout)
    starbench-gui                                 # zero-argument console

Migrating an existing checkout:

    mkdir -p ~/.starbench
    mv runs ~/.starbench/runs

For a full Docker-isolated run from a repository checkout:

```bash
cd starbench_evaluation_framework
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

Install the Codex CLI on the host, then authenticate it in the way your environment expects.

Build the Docker executor image for Codex (the default Docker runtime):

```bash
docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .
```

Each runtime has its own image (`starbench-claude-code`, `starbench-gemini-cli`, `starbench-grok`, `starbench-opencode`, plus images for the bundled custom runtimes); build the ones you plan to isolate — see [docs/docker.md](docs/docker.md) for the full list and build commands.

Run the sample task with real Codex execution and one GPT judge:

```bash
starbench-run \
  --tasks-dir examples/tasks \
  --task demo_python_cli \
  --runs-dir runs \
  --run-id smoke_real \
  --executor-backend docker \
  --docker-image starbench-codex:latest \
  --auth-mode copy-auth \
  --executor-model gpt-5.5 \
  --evaluator-model gpt-5.5 \
  --judge-mode single \
  --seed 123
```

The same run as a typed plan file — one validated document instead of flags
(`--plan` is exclusive; only `--runs-dir` and `--no-progress` may accompany it):

```bash
cat > plan.json <<'JSON'
{
  "schema_version": 1,
  "run_id": "smoke_plan",
  "tasks_dir": "examples/tasks",
  "tasks": ["demo_python_cli"],
  "executor_backend": "docker",
  "docker_image": "starbench-codex:latest",
  "auth_mode": "copy-auth",
  "executor_model": "gpt-5.5",
  "evaluator_model": "gpt-5.5",
  "judge_mode": "single",
  "seed": 123
}
JSON
starbench-run --plan plan.json --runs-dir runs
```

An invalid plan (unknown key, wrong type, credential-shaped field) aborts at
argument time with the exact contract violation; nothing is written to disk.

Runtime convention:

```text
Claude-family models          -> --executor-agent/--evaluator-agent claude
GPT/OpenAI-family models      -> --executor-agent/--evaluator-agent codex
Other OpenAI-compatible models -> --executor-agent/--evaluator-agent opencode
xAI Grok Build models         -> --executor-agent/--evaluator-agent grok
Gemini CLI models             -> --executor-agent/--evaluator-agent gemini
Any other headless agent CLI  -> --executor-agent/--evaluator-agent custom:<id>
```

Custom runtimes are declarative: drop a `<id>.json` file in `runtimes/`
(command, prompt delivery, output parser, env, optional docker image) and no
Python changes are needed. See [runtimes/README.md](runtimes/README.md).

To switch the evaluator, set both the evaluator model and evaluator runtime:

```bash
--evaluator-agent codex    --evaluator-model gpt-5.5
--evaluator-agent claude   --evaluator-model claude-opus-4-8
--evaluator-agent opencode --evaluator-model yunwu/doubao-seed-2-0-pro-260215
--evaluator-agent grok     --evaluator-model your-grok-model
--evaluator-agent gemini   --evaluator-model gemini-2.5-pro
```

When mixing runtimes, split auth modes. For example, use `--executor-auth-mode env` for an OpenCode executor that reads an API key from the environment, and `--evaluator-auth-mode global` for a Codex evaluator that should read local Codex login credentials.

Run the sample task with Claude Code through an Anthropic-compatible gateway:

```bash
export ANTHROPIC_BASE_URL=https://your-gateway.example
export ANTHROPIC_AUTH_TOKEN=...

PYTHONPATH=src python3 -m starbench.runner.run_benchmark \
  --tasks-dir examples/tasks \
  --task demo_python_cli \
  --runs-dir runs \
  --run-id smoke_claude \
  --executor-agent claude \
  --evaluator-agent claude \
  --auth-mode env \
  --executor-model claude-opus-4-8 \
  --evaluator-model claude-opus-4-8 \
  --judge-mode single
```

Run the sample task with OpenCode through an OpenAI-compatible gateway:

```bash
export ANTHROPIC_AUTH_TOKEN=...

PYTHONPATH=src python3 -m starbench.runner.run_benchmark \
  --tasks-dir examples/tasks \
  --task demo_python_cli \
  --runs-dir runs \
  --run-id smoke_opencode \
  --executor-agent opencode \
  --evaluator-agent codex \
  --opencode-bin "$HOME/.opencode/bin/opencode" \
  --opencode-provider yunwu \
  --opencode-base-url https://yunwu.ai/v1 \
  --opencode-api-key-env ANTHROPIC_AUTH_TOKEN \
  --auth-mode env \
  --executor-auth-mode env \
  --evaluator-auth-mode global \
  --executor-backend local \
  --executor-model doubao-seed-2-0-pro-260215 \
  --evaluator-model gpt-5.5 \
  --judge-mode single
```

Run the sample task with Grok Build:

```bash
starbench-run \
  --tasks-dir examples/tasks \
  --task demo_python_cli \
  --runs-dir runs \
  --run-id smoke_grok \
  --executor-agent grok \
  --evaluator-agent grok \
  --executor-backend local \
  --auth-mode global \
  --executor-model your-grok-model \
  --evaluator-model your-grok-model \
  --judge-mode single
```

Run the sample task with Gemini CLI:

```bash
starbench-run \
  --tasks-dir examples/tasks \
  --task demo_python_cli \
  --runs-dir runs \
  --run-id smoke_gemini \
  --executor-agent gemini \
  --evaluator-agent gemini \
  --executor-backend local \
  --auth-mode global \
  --executor-model gemini-2.5-pro \
  --evaluator-model gemini-2.5-pro \
  --judge-mode single
```

Grok Build and Gemini CLI run host-local by default; both also ship Docker images (`starbench-grok`, `starbench-gemini-cli`) for isolated runs with `--executor-backend docker`. Authenticate those CLIs before invoking StarBench, or use `--auth-mode env` when the CLI reads its API key from the environment.

Run-level knobs that apply to any of the above:

```text
--thinking-effort {default,minimal,low,    reasoning effort, via each runtime's native
                   medium,high,xhigh,       switch (Claude --effort, Codex
                   max,ultra}               model_reasoning_effort, OpenCode --variant);
                                           prompt-level request for the rest;
                                           "default" = leave the model default alone
--web-search {task,allow,deny}             follow the task package's allow_web_search,
                                           or force it on/off for the whole run
                                           (enforced for Claude Code and Codex)
--instruction-mode / --rigor-mode          expert-step sweeps and rigor prompt injection
                                           (see the docs below)
```

Every knob above is also a field of the run plan (same names, underscores
instead of dashes).

For a no-cost local framework smoke test:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Documentation

- [Quickstart](docs/quickstart.md)
- [Business Requirements Document](docs/BRD.md)
- [Recipes: common changes, one file each](docs/recipes.md)
- [Architecture: structure, boundaries, ownership](docs/ARCHITECTURE.md)
- [GUI Console](docs/gui.md)
- [Task Package Structure](docs/task_package.md)
- [Artifact Contracts](docs/artifact_contracts.md)
- [Runner Reference](docs/runner_reference.md)
- [Model Runtime Matrix](docs/model_runtime_matrix.md)
- [Docker Isolation](docs/docker.md)
- [Executor Skills](docs/executor_skills.md)
- [Trace-to-Skill Distillation](docs/skill_distillation.md)
- [Distill Tasks Into Executor Skills](docs/distill_task_to_skill.md)
- [Use Executor Skills In Evaluation Runs](docs/use_skills_in_eval.md)
- [Authoring Rubrics](docs/rubrics.md)
- [Human Reference Instructions](docs/human_reference.md)
- [Rigor Prompt Injection](docs/rigor_prompt_injection.md)
- [Contributing Notes](docs/contributing.md)

## Where To Put Tasks

Put your own task packages under the StarBench home task library —
`$STARBENCH_HOME/tasks` (`~/.starbench/tasks` by default; `--tasks-dir`
overrides it):

```text
~/.starbench/tasks/
  my_task/
    task.json
    prompt.md
    rubrics.json
    materials/
```

`starbench-run` and `starbench-gui` use `$STARBENCH_HOME/tasks` by default.
The bundled `examples/tasks/` directory in a repository checkout is only for
sample tasks and smoke tests, and it is never auto-loaded: seed it into the
library with `cp -r examples/tasks/* ~/.starbench/tasks/`, or pass
`--tasks-dir examples/tasks` to run it directly without seeding.

## Output Layout

Each run writes to `<runs-dir>/<run_id>/`, where `<runs-dir>` defaults to
`$STARBENCH_HOME/runs` (`~/.starbench/runs`) and `--runs-dir` overrides it.

```text
<runs-dir>/<run_id>/
  run_config.json
  run_plan.json                     # plan-launched runs: the exact launch contract
  profile_snapshot.json             # profile-launched runs: the frozen measurement contract
  run_state.json                    # console-launched runs: supervision state (batch, heartbeat)
  progress_events.jsonl
  summary.json
  instruction_ablation_summary.json
  instruction_ablation_summary.md
  <task_run_id>/
    manifest.json
    workspace/
      inputs/
      outputs/
    logs/
      events.jsonl
      final.md
      status.json
      trace_summary.json
      artifact_manifest.json
      stderr.log
    judges/
      single_result.json
      single_aggregate.json
      single_status.json
```

`logs/status.json` records executor start/end timestamps and duration. `judges/*_aggregate.json` includes the executor timing alongside rubric scores.

## Security Note

Do not put live API tokens in prompts, task files, rubrics, or committed docs. Prefer environment variables, your CLI credential store, or a local `.env` ignored by git.
