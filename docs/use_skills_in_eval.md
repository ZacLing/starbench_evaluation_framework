# Use Executor Skills In Evaluation Runs

This guide shows how to load executor Codex Skills during `starbench-run`.

Baseline behavior is unchanged unless you pass `--executor-skill` or `--executor-skill-group`.

## Shared Skill Registry

Shared skills live under:

```text
executor_skills/
  registry.json
  generated/<skill-id>/SKILL.md
```

The runner reads `registry.json` from `--executor-skill-root`.

## Load One Skill

```bash
starbench-run \
  --tasks-dir tasks \
  --runs-dir runs \
  --task rsj_intraday_factor_platform_hsw-v3 \
  --executor-skill-root executor_skills \
  --executor-skill quant-finance-research-platform-expert \
  --executor-backend docker \
  --executor-model gpt-5.5 \
  --evaluator-model gpt-5.5 \
  --judge-mode single
```

## Load A Group

```bash
starbench-run \
  --tasks-dir tasks \
  --runs-dir runs \
  --task rsj_intraday_factor_platform_hsw-v3 \
  --executor-skill-root executor_skills \
  --executor-skill-group senior-expert-stack \
  --executor-backend docker \
  --executor-model gpt-5.5 \
  --evaluator-model gpt-5.5
```

Groups are defined in `executor_skills/registry.json`.

## Load Multiple Skills

Pass `--executor-skill` more than once:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --executor-skill senior-technical-proposal-expert \
  --executor-skill quant-finance-research-platform-expert
```

Or combine groups and individual skills:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --executor-skill-group senior-expert-core \
  --executor-skill quant-finance-research-platform-expert
```

The final selected skill ids must be unique. If a group and an explicit skill select the same id, the runner fails fast.

## Generated Example Groups

The repository currently includes:

```text
senior-expert-core
research-platforms
quant-finance
empirical-measurement
senior-expert-stack
```

Examples:

```bash
# Core proposal and research-platform architecture expertise
starbench-run --executor-skill-root executor_skills --executor-skill-group senior-expert-core

# Quant finance platform expertise
starbench-run --executor-skill-root executor_skills --executor-skill-group quant-finance

# All generated senior expert skills
starbench-run --executor-skill-root executor_skills --executor-skill-group senior-expert-stack
```

## What The Executor Sees

The executor prompt receives only a short activation block, for example:

```text
Installed executor Codex skills:
- `quant-finance-research-platform-expert`: Use `quant-finance-research-platform-expert` as private quant finance research platform expert guidance for this task.

Skill usage rules:
- Use the installed executor skills as private execution guidance for planning, execution, and final self-checking.
- You may read installed skill files under $CODEX_HOME/skills/<skill-id>/.
- The task prompt and materials remain authoritative if they conflict with a skill.
- Do not mention installed skills, expert traces, harnesses, or internal checklists in deliverables.
```

The full skill body is not appended to `workspace/inputs/prompt.md`.

## Install Paths

Docker executor:

```text
runs/<run_id>/<task_run_id>/codex_home/docker/skills/<skill-id>/
```

Inside the container:

```text
/codex-home/skills/<skill-id>/
```

Local executor:

```text
runs/<run_id>/<task_run_id>/codex_home/skills/<skill-id>/
```

## Run Metadata

Selected and installed skills are recorded in:

```text
runs/<run_id>/run_config.json
runs/<run_id>/<task_run_id>/manifest.json
runs/<run_id>/<task_run_id>/task_summary.json
```

`manifest.json` includes installed skill ids, source paths, and directory SHA-256 hashes.

## Task-local Skills

Task-local skills still work through `task_package/executor_skills.json`.

Shared registry skills and task-local skills can be used together, but skill ids must not collide.
