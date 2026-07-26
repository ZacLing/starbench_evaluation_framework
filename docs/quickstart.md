# Quickstart

This page gets a new user from a clean checkout to a working Starbench run.

## Prerequisites

- Python 3.9 or newer.
- Docker Desktop or Docker Engine.
- Codex CLI available on the host.
- A working API credential for Codex and GPT judging.

## Install

```bash
cd starbench_evaluation_framework
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e .
```

Check the CLI:

```bash
starbench-run --help
```

## Pick the Runtime

Use Claude Code for Claude-family models, Codex for GPT/OpenAI-family models, and OpenCode for other OpenAI-compatible models such as Doubao or Qwen. See [Runner Reference](runner_reference.md#agent-runtimes) for provider-specific flags and mixed-auth examples.

Executor and evaluator runtimes are selected independently. To change the evaluator, set `--evaluator-agent` to `codex`, `claude`, or `opencode`, and set `--evaluator-model` to the exact model id that runtime should call.

## Build the Docker Image

```bash
docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .
```

The image contains Node, Python, Git, ripgrep, jq, and the Codex CLI. The runner mounts only the per-task workspace and a per-task Codex home into the container.

## Configure Credentials

Recommended local mode:

```bash
codex login
```

Then run Starbench with:

```bash
--auth-mode copy-auth
```

Environment-variable mode is also supported:

```bash
export CODEX_API_KEY="your-key-here"
starbench-run ... --auth-mode env
```

Do not commit real keys.

## Run a Real Sample

```bash
starbench-run \
  --tasks-dir examples/tasks \
  --task demo_python_cli \
  --runs-dir runs \
  --run-id demo_python_cli_real \
  --executor-backend docker \
  --docker-image starbench-codex:latest \
  --auth-mode copy-auth \
  --executor-model gpt-5.5 \
  --evaluator-model gpt-5.5 \
  --judge-mode single \
  --seed 123
```

Useful output files:

- `runs/demo_python_cli_real/summary.json`: whole-run summary.
- `runs/demo_python_cli_real/demo_python_cli/logs/status.json`: executor duration and exit status.
- `runs/demo_python_cli_real/demo_python_cli/logs/events.jsonl`: raw exposed event trace.
- `runs/demo_python_cli_real/demo_python_cli/workspace/outputs/`: executor deliverables.
- `runs/demo_python_cli_real/demo_python_cli/judges/single_aggregate.json`: final rubric score.

## Run Without Live Model Calls

The included unit tests use a fake Codex CLI process to validate trace parsing, aggregation, task materialization, and the closed loop:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Your Own Tasks

Put real benchmark task packages in the StarBench home task library —
`$STARBENCH_HOME/tasks` (`~/.starbench/tasks` by default):

```text
~/.starbench/tasks/
  my_task/
    task.json
    prompt.md
    rubrics.json
```

Then run without `--tasks-dir`, since it now resolves to that directory:

```bash
starbench-run \
  --task my_task \
  --runs-dir runs \
  --run-id my_task_run \
  --executor-backend docker \
  --docker-image starbench-codex:latest \
  --auth-mode copy-auth \
  --executor-model gpt-5.5 \
  --evaluator-model gpt-5.5 \
  --judge-mode single
```

The bundled sample tasks stay in `examples/tasks/`, so sample commands explicitly pass `--tasks-dir examples/tasks`.
