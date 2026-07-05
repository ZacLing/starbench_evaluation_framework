# Docker Isolation

Starbench uses Docker as the default executor backend for the Codex runtime. Docker executor support now covers:

- **Codex** (default backend `docker`): isolated `CODEX_HOME` mounted at `/codex-home`; env whitelist `CODEX_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`.
- **Claude Code** (`--executor-agent claude --executor-backend docker --docker-image starbench-claude-code:latest`): config dir isolated at `/workspace/.runner/claude_home` inside the workspace mount; env whitelist `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` (use `--auth-mode env`).
- **Custom runtimes** with a `docker` section in their `runtimes/<id>.json` (image + `env_passthrough`).

OpenCode, Grok Build, and Gemini CLI executors remain host-local (`--executor-backend local`, which is their automatic default).

On executor timeout, Starbench kills the container itself (killing only the `docker run` client would leave the container running and still writing into the mounted workspace).

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

## Real-container smoke checklist

These were deferred because the docker daemon was down at build time. Run once the daemon is available:

- [ ] `colima start` (or Docker Desktop) and `docker info` succeeds.
- [ ] `make docker-build`; `docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .`
- [ ] Codex regression: demo task with `--executor-backend docker` still passes.
- [ ] Claude: demo task with `--executor-agent claude --executor-backend docker --docker-image starbench-claude-code:latest --auth-mode env` (requires `ANTHROPIC_API_KEY`).
- [ ] Timeout kill: run a long task with a small `timeout_seconds`; verify `docker ps` shows no leftover container.

## Evaluators

Evaluators currently run host-local with read-only Codex sandboxing. They inspect a slim judge workspace containing:

- executor outputs,
- prompt,
- manifest,
- trace summaries,
- final message,
- status/timing.

Raw input materials are omitted from evaluator workspaces by default for speed and to reduce accidental task re-solving. Rubric questions should be written so the judge can evaluate the executor deliverable and trace.
