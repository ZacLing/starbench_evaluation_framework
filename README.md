# Starbench Evaluation Framework

Starbench is a small benchmark runner for evaluating Codex-style agents with GPT-based rubric judges.

It runs executor agents on task packages, captures the event trace exposed by the CLI, then grades the delivered outputs with yes/no rubrics. Executors can run in a Docker workspace by default, while evaluators inspect only the delivered package, trace summaries, and rubrics.

## What Is Included

- Batch execution with `--seed`, `--batch-size`, and deterministic task ordering.
- Docker-backed executor isolation by default.
- Independent executor and evaluator model selection.
- Runtime selection for Codex, Claude Code, or OpenCode executors/evaluators.
  - Use Claude Code for Claude-family models.
  - Use Codex for GPT/OpenAI-family models.
  - Use OpenCode for other OpenAI-compatible models, such as Doubao or Qwen.
- Single-judge and per-rubric parallel-judge modes.
- `human_reference.json` instruction sweep support.
- Rule-based instruction ablation: baseline, one variant per expert instruction, and an all-instructions variant, with repeat runs and uplift summaries.
- Trace capture: raw JSONL events, final message, status/timing, artifact manifest, and derived summary.
- A default `tasks/` directory for user task packages.
- Two sample task packages under `examples/tasks/`.
- Unit and closed-loop fake-runner smoke tests that do not call a live model.

## Quick Start

```bash
cd starbench_evaluation_framework
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

Install the Codex CLI on the host, then authenticate it in the way your environment expects.

Build the Docker executor image:

```bash
docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .
```

Optional Claude Code helper image, useful when the host does not have the `claude` CLI:

```bash
docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .
```

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

Runtime convention:

```text
Claude-family models          -> --executor-agent/--evaluator-agent claude
GPT/OpenAI-family models      -> --executor-agent/--evaluator-agent codex
Other OpenAI-compatible models -> --executor-agent/--evaluator-agent opencode
```

To switch the evaluator, set both the evaluator model and evaluator runtime:

```bash
--evaluator-agent codex    --evaluator-model gpt-5.5
--evaluator-agent claude   --evaluator-model claude-opus-4-8
--evaluator-agent opencode --evaluator-model yunwu/doubao-seed-2-0-pro-260215
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
  --claude-bin "$(pwd)/tmp/claude-code-docker.sh" \
  --auth-mode env \
  --executor-backend local \
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

For a no-cost local framework smoke test:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Documentation

- [Quickstart](docs/quickstart.md)
- [Task Package Structure](docs/task_package.md)
- [Runner Reference](docs/runner_reference.md)
- [Docker Isolation](docs/docker.md)
- [Executor Codex Skills](docs/executor_skills.md)
- [Trace-to-Skill Distillation](docs/skill_distillation.md)
- [Distill Tasks Into Executor Skills](docs/distill_task_to_skill.md)
- [Use Executor Skills In Evaluation Runs](docs/use_skills_in_eval.md)
- [Authoring Rubrics](docs/rubrics.md)
- [Human Reference Instructions](docs/human_reference.md)

## Where To Put Tasks

Put your own task packages under `tasks/`:

```text
tasks/
  my_task/
    task.json
    prompt.md
    rubrics.json
    materials/
```

`starbench-run` uses `tasks/` by default. The bundled `examples/tasks/` directory is only for sample tasks and smoke tests. To run a sample, pass `--tasks-dir examples/tasks`.

## Output Layout

Each run writes to `runs/<run_id>/`.

```text
runs/<run_id>/
  run_config.json
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
