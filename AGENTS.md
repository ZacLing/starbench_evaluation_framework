# Agent Guide

## Project Shape

StarBench is a benchmark runner for isolated coding-agent task execution and rubric judging. Structure, layer boundaries, ownership, and the console/core contract surface are governed by `docs/ARCHITECTURE.md` — read it before making cross-layer changes. Keep runtime integrations first-class and explicit in the adapter registry (`src/starbench/adapters/`); do not hide runtime-specific behavior in ad hoc shell wrappers unless the wrapper is part of a documented test fixture.

## Working Rules

- Preserve task isolation: executor work belongs under each run's `workspace/`, with deliverables under `workspace/outputs/`.
- Run-directory file ownership is disjoint: the runner writes all run artifacts; the console supervisor owns exactly two files — `run_state.json` (process supervision) and the `.runner_claim` reservation handshake. Neither side writes the other's files.
- Keep evaluator workspaces slim and evidence-oriented; evaluators should inspect executor outputs, logs, trace summaries, manifests, and prompts rather than re-solving tasks.
- Prefer deterministic fake CLI tests for runtime compatibility, then use real CLIs only for manual smoke runs.
- Do not put live API tokens in prompts, committed docs, task packages, rubrics, or test fixtures.
- Use `rg`/`rg --files` for repository exploration when available.

## Runtime Notes

- Codex remains the Docker-backed default runtime and uses `$CODEX_HOME/skills/` for selected executor skills.
- Every built-in runtime ships its own Docker image (`make docker-images`); Codex defaults to the docker backend, the others default to local with docker selectable per run.
- Pi (pi.dev) auth mode is env only — the operator's `~/.pi` OAuth login must never carry benchmark traffic.
- DeepSeek Harness (`dsh`) auth mode is env only too — every run gets its own `DSH_HOME`, so the operator's `~/.dsh` profile, settings, and `.credentials.yaml` never carry benchmark traffic. **dsh ships a session-telemetry plugin that mirrors every session-log event — assistant text included, with no redaction rule mounted — to a DeepSeek OTLP endpoint whenever its row runs.** StarBench turns it off three ways (`DSH_TELEMETRY_DISABLED=1`, `DSH_TELEMETRY_MODE=DISABLED`, and a `--patch` row that disables the plugin under both ids dsh has shipped for it); the patch is the version-independent one. Never weaken that, and never run dsh against benchmark data with a hand-rolled invocation that skips it.
- When running tests locally, never use the Claude Code CLI login as the executor model credential. If Claude Code is the executor, it must run in API mode: `--executor-auth-mode env` with `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`, never `global` or `copy-auth`. The CLI login is the operator's personal subscription identity; benchmark executor traffic must not ride on it.
- Grok Build reads this `AGENTS.md` natively.
- Gemini CLI reads `GEMINI.md`; this repo keeps `GEMINI.md` as a thin import of this file so runtime guidance has one maintained source. `CLAUDE.md` is the same thin import for Claude Code.

<!-- memory-connector:start -->
## Friday Memory

- When using the `memory_connector` MCP server, the installed `MEMORY_CONNECTOR_PAT` is the authenticated PAT identity; do not provide or invent a separate memory `user_id`.
- Tool selection guide:
  - `user_get`: session bootstrap. Use it to confirm the active authenticated PAT identity, readable graph scope, or durable user profile; do not treat bootstrap as evidence for a fact answer.
  - `memory_recall`: semantic retrieval and context assembly. Use it first for prior decisions, preferences, project history, repository history, or cross-session state.
  - `memory_get`: exact UUID drilldown. Use it after `memory_recall` or another trusted source gives a stable uuid. Do not use `memory_get` for fuzzy search.
  - `timeline_get`: exact `thread_id` timeline drilldown. Use it for thread summaries and ordered episodes from a known `thread_id`. Do not use `timeline_get` without an exact `thread_id`.
  - `memory_write`: durable memory write for confirmed preferences, decisions, reusable conventions, and stable summaries.
  - `document_upload`: durable document ingest for long files, PDFs, reports, meeting notes, and other searchable artifacts. Ask before uploading local documents, screenshots, logs, or private files.
<!-- memory-connector:end -->
