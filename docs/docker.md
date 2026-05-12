# Docker Isolation

Starbench uses Docker as the default executor backend.

## Build

```bash
docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .
```

## Runtime Shape

For each executor task, Starbench creates:

```text
runs/<run_id>/<task_run_id>/
  workspace/
    inputs/
    outputs/
  codex_home/
  logs/
```

The container receives only:

- `workspace` mounted at `/workspace`.
- an isolated Codex home mounted at `/codex-home`.
- selected credential environment variables when present.

The Docker run command uses:

- `--read-only`
- `--cap-drop=ALL`
- `--security-opt no-new-privileges`
- `--pids-limit 512`
- `--memory 6g`
- `--cpus 4`
- `--tmpfs /tmp:rw,nosuid,nodev,size=1g`

Network access is not disabled by default. This matches research tasks that may need web access when `allow_web_search` is true.

## Why `danger-full-access` Inside Docker?

Inside the container, Codex is given full access to `/workspace` so it can create files, run commands, install local dependencies if the task permits, and verify outputs. Docker provides the outer boundary, so the executor cannot see sibling tasks or the host project unless you mount them.

## Evaluators

Evaluators currently run host-local with read-only Codex sandboxing. They inspect a slim judge workspace containing:

- executor outputs,
- prompt,
- manifest,
- trace summaries,
- final message,
- status/timing.

Raw input materials are omitted from evaluator workspaces by default for speed and to reduce accidental task re-solving. Rubric questions should be written so the judge can evaluate the executor deliverable and trace.
