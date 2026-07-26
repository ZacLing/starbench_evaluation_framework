# Contributing Notes

This project treats the CLI surface and public artifacts as product contracts.
Small changes are welcome, but contract changes need explicit review.

## Artifact Contract Checklist

Use this checklist when changing task packages, run outputs, GUI import logic,
or readers under `src/starbench/gui/data.py`.

- Update `docs/artifact_contracts.md` when public artifact meaning changes.
- Update `schemas/starbench/` (v1, and v2 for `judge_aggregate`) when public
  artifact shape changes, then run `make sync-schemas` to refresh the packaged
  mirror under `src/starbench/contracts/schemas/`.
- Add or update `tests/contracts/` for task packages, run artifacts, privacy, or
  version behavior.
- Preserve legacy readers where practical; missing `schema_version` means
  legacy v0.
- Keep `human_reference.reasoning` private. It must not enter executor prompts,
  GUI API responses, public run artifacts, or reports.
- Never write credential values to prompts, task packages, run artifacts, logs,
  docs, or tests.
- Keep evaluator response schemas under `src/starbench/runner/schemas/`
  separate from public artifact schemas.

## CLI Compatibility Checklist

`starbench-run` arguments are consumed by local users, the GUI, and external
platforms.

- Prefer additive flags over changing existing flag semantics.
- Keep aliases during a deprecation period when renaming flags.
- Update `docs/runner_reference.md` for new or changed flags.
- Add focused parser or launch-plan tests for every new CLI surface.

## Test Commands

Before committing behavior changes, run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests   # same as `make test`
```

For artifact contract changes, also run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/contracts
```
