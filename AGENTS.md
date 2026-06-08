# Agent Guide

## Project Shape

StarBench is a benchmark runner for isolated coding-agent task execution and rubric judging. Keep runtime integrations first-class and explicit in `src/starbench/runner/codex_process.py` and `src/starbench/runner/run_benchmark.py`; do not hide runtime-specific behavior in ad hoc shell wrappers unless the wrapper is part of a documented test fixture.

## Working Rules

- Preserve task isolation: executor work belongs under each run's `workspace/`, with deliverables under `workspace/outputs/`.
- Keep evaluator workspaces slim and evidence-oriented; evaluators should inspect executor outputs, logs, trace summaries, manifests, and prompts rather than re-solving tasks.
- Prefer deterministic fake CLI tests for runtime compatibility, then use real CLIs only for manual smoke runs.
- Do not put live API tokens in prompts, committed docs, task packages, rubrics, or test fixtures.
- Use `rg`/`rg --files` for repository exploration when available.

## Runtime Notes

- Codex remains the Docker-backed default runtime and uses `$CODEX_HOME/skills/` for selected executor skills.
- Claude Code, OpenCode, Grok Build, and Gemini CLI executor support is host-local unless explicitly documented otherwise.
- Grok Build reads this `AGENTS.md` natively.
- Gemini CLI reads `GEMINI.md`; this repo keeps `GEMINI.md` as a thin import of this file so runtime guidance has one maintained source.

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
