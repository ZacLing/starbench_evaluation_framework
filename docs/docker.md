# Docker Isolation

Starbench can execute every built-in runtime inside Docker. Each has its own
image (one CLI per image), and `--docker-image` defaults to the runtime's own
tag, so `--executor-backend docker` is all you need:

- **Codex** (default backend `docker`, image `starbench-codex:latest`): isolated `CODEX_HOME` mounted at `/codex-home`; env whitelist `CODEX_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`.
- **Claude Code** (image `starbench-claude-code:latest`): config dir isolated at `/workspace/.runner/claude_home` inside the workspace mount; env whitelist `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` (use `--auth-mode env`).
- **Gemini CLI** (image `starbench-gemini-cli:latest`): `HOME` pointed at `/workspace/.runner/gemini_home`; env whitelist `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `GOOGLE_GEMINI_BASE_URL`.
- **Grok Build** (image `starbench-grok:latest`): `HOME` pointed at `/workspace/.runner/grok_home`; env whitelist `XAI_API_KEY`. The prompt travels on the container argv (grok takes `-p <prompt>`).
- **OpenCode** (image `starbench-opencode:latest`): `HOME` pointed at `/workspace/.runner/opencode_home` so config *and* session storage stay inside the workspace mount — the host reads the session afterwards for the final-message export fallback. Gateway configuration is injected via `OPENCODE_CONFIG_CONTENT`; env whitelist `OPENAI_API_KEY`, `XAI_API_KEY`, plus the gateway's `api_key_env` option when set.
- **Pi** (image `starbench-pi:latest`): `HOME` and `PI_CODING_AGENT_DIR` pointed at `/workspace/.runner/pi_home` (session dir beneath it) so session artifacts stay readable from the host; `PI_OFFLINE` and `PI_SKIP_VERSION_CHECK` are forced on. Env whitelist `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY` (use `--auth-mode env`; Pi refuses the other modes). Installed executor skills are passed as `--skill /workspace/.starbench/executor_skills/<skill-id>`.
- **Custom runtimes** with a `docker` section in their `runtimes/<id>.json` (image + `env_passthrough`). `HOME` defaults to `/workspace/.runner/custom_home` inside the container. Dockerfiles for the bundled runtimes ship in `docker/` (`make docker-images-custom` builds `starbench-qwen:latest`, `starbench-kimi:latest`, and `starbench-trae-agent:latest`). The Kimi image bakes a seeded `~/.kimi/config.toml` (see `docker/kimi-config.toml`) whose endpoint/key are overridden by `OPENAI_BASE_URL` / `OPENAI_API_KEY` at run time.

All executor backends default to `local` except Codex; pass
`--executor-backend docker` explicitly for the others.

On executor timeout, Starbench kills the container itself (killing only the `docker run` client would leave the container running and still writing into the mounted workspace).

## Build

```bash
make docker-images   # builds every built-in runtime image
# or individually:
docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .
docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .
docker build -t starbench-gemini-cli:latest -f docker/gemini-cli.Dockerfile .
docker build -t starbench-grok:latest -f docker/grok.Dockerfile .
docker build -t starbench-opencode:latest -f docker/opencode.Dockerfile .
docker build -t starbench-pi:latest -f docker/pi.Dockerfile .
```

Grok Build installs via xAI's shell installer rather than npm; if a build of
`docker/grok.Dockerfile` fails or `grok` is not found on PATH inside the
container, check the installer's target directory and adjust the Dockerfile's
`ENV PATH` line.

## Runtime Shape

For each executor task, Starbench creates:

```text
runs/<run_id>/<task_run_id>/
  workspace/
    inputs/
    outputs/
  agent_home/
  logs/
```

The container receives only:

- `workspace` mounted at `/workspace`.
- an isolated agent home — Codex mounts `agent_home/docker` at `/codex-home`; the
  other runtimes keep theirs inside the workspace mount under
  `/workspace/.runner/` (see the per-runtime list above), since the container
  rootfs is read-only.
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

Evaluators always run host-local — `--executor-backend` covers the executor only — each under its own runtime's read-only judge settings (Codex's `read-only` sandbox, Grok's read-only sandbox flags, Gemini's `--approval-mode plan`). They inspect a slim judge workspace containing:

- executor outputs,
- prompt,
- manifest,
- trace summaries,
- final message,
- status/timing.

Raw input materials are omitted from evaluator workspaces by default for speed and to reduce accidental task re-solving. Rubric questions should be written so the judge can evaluate the executor deliverable and trace.
