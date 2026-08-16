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
- **DeepSeek Harness** (image `starbench-dsh:latest`): `HOME` pointed at `/workspace/.runner/dsh`, with `DSH_HOME` at `.../dsh/home` and the session log at `.../dsh/sessions`, so the generated settings/patch documents and the transcript all stay inside the workspace mount and readable from the host. `DSH_TELEMETRY_DISABLED=1` and `DSH_TELEMETRY_MODE=DISABLED` are forced, and `DSH_PERMISSION_MODE=danger-full-access` because the container itself is the sandbox. Env whitelist `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`, `DEEPSEEK_API_KEY` (use `--auth-mode env`; dsh refuses the other modes).
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
docker build -t starbench-dsh:latest -f docker/dsh.Dockerfile .
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

## Why The Executor Runs Unprompted

Every executor is given full access to `/workspace` so it can create files, run
commands, install local dependencies if the task permits, and verify outputs.
Each runtime spells that its own way: Codex `--sandbox danger-full-access`,
Claude Code `--permission-mode acceptEdits`, Gemini CLI `--yolo`, Grok Build
`bypassPermissions`, OpenCode `--dangerously-skip-permissions`. Pi passes no
permission flag at all — its headless `--mode json` run is already unprompted.

Docker provides the outer boundary, so the executor cannot see sibling tasks or
the host project unless you mount them. Note that this is why the two layers are
not interchangeable: with `--executor-backend local` (the default for every
runtime except Codex) the same unprompted permission mode applies with **no**
container around it, and the executor runs against your real filesystem with only
the workspace path convention keeping it in place.

## Real-container smoke checklist

**Verification status: none of the boxes below have been ticked in this repository.**
What *is* verified is the deterministic layer: the container argv, mounts, and env
whitelist for every built-in runtime are asserted in `tests/adapters/test_docker_commands.py`
and run on every `make test`. The timeout kill
(`execution/docker.py:kill_container_on_timeout`) has no test — it is only
covered by the manual box below. Nothing here has been confirmed against a live
daemon with a real model, so treat the whole section as unrun. Tick a box only
after you have actually run it, and say which host and image tag you ran it on.

Preconditions:

- [ ] `colima start` (or Docker Desktop) and `docker info` succeeds.
- [ ] `make docker-images` builds all six built-in images without error
      (`make docker-build` alone builds only the Codex image).
- [ ] `make docker-images-custom` builds the three bundled custom-runtime images.

Per-runtime demo-task run with `--executor-backend docker`. Each needs that
runtime's own credential in the environment; `--docker-image` may be omitted
because it defaults to the runtime's own tag, and `--auth-mode` already defaults
to `env`:

- [ ] Codex — `--executor-agent codex` (docker is already its default backend; this is the regression case). Needs `OPENAI_API_KEY`.
- [ ] Claude Code — `--executor-agent claude --executor-backend docker`. Needs `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`; must stay on `--auth-mode env`.
- [ ] Gemini CLI — `--executor-agent gemini --executor-backend docker`. Needs `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
- [ ] Grok Build — `--executor-agent grok --executor-backend docker`. Needs `XAI_API_KEY`.
- [ ] OpenCode — `--executor-agent opencode --executor-backend docker --executor-option provider=…`. Needs the gateway key named by its `api_key_env` option (default `OPENAI_API_KEY`).
- [ ] Pi — `--executor-agent pi --executor-backend docker` (Pi rejects `global` and `copy-auth` outright). Needs the key for the provider you select.
- [ ] DeepSeek Harness — `--executor-agent dsh --executor-backend docker --executor-option provider=…` (dsh rejects `global` and `copy-auth` outright). Needs the key for the route you select; confirm the generated `settings.yaml`/`starbench.patch.yml` and the session log all landed under `workspace/.runner/dsh/`.
- [ ] A docker-enabled custom runtime — `--executor-agent custom:<id> --executor-backend docker`.

Cross-cutting:

- [ ] Timeout kill: run a long task with a small `timeout_seconds`; verify `docker ps` shows no leftover container.
- [ ] Isolation: after a run, confirm the agent home lives where this document says it does for that runtime, and that nothing was written outside the run directory.

## Evaluators

Evaluators always run host-local — `--executor-backend` covers the executor only.
How much each runtime is restrained on the judge side differs, and one runtime is
not restrained at all:

| Judge runtime | Restraint |
|---|---|
| Codex | `--sandbox read-only` |
| Gemini CLI | `--approval-mode plan` |
| Grok Build | `--permission-mode dontAsk` |
| Claude Code | tool allowlist `Read,Glob,Grep,Bash,LS` (no sandbox; `Bash` is allowed) |
| OpenCode | a dedicated judge agent profile |
| Pi | **none** — the judge runs the same command shape as the executor |

Since judges run on the host, a judge that is not sandboxed can in principle
touch anything the invoking user can. They inspect a slim judge workspace
containing:

- executor outputs,
- prompt,
- manifest,
- trace summaries,
- final message,
- status/timing.

Raw input materials are omitted from evaluator workspaces by default for speed and to reduce accidental task re-solving. Rubric questions should be written so the judge can evaluate the executor deliverable and trace.
