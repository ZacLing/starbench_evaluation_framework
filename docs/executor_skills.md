# Executor Codex Skills

StarBench can install task-registered Codex Skills into the executor's isolated `CODEX_HOME`.

This is different from human-reference instruction injection or rigor injection:

- Human-reference and rigor modes append text to the task prompt.
- Executor skills are copied as real Codex Skill directories into `$CODEX_HOME/skills/`.
- The executor prompt only names the selected installed skills and tells Codex to use them as private execution guidance.

Baseline runs are unchanged unless `--executor-skill` is passed.

## Task Package Format

Register skills in `task.json`:

```json
{
  "executor_skills": "executor_skills.json"
}
```

Create `executor_skills.json`:

```json
{
  "skills": [
    {
      "id": "quant-finance-research-platform-expert",
      "path": "skills/quant-finance-research-platform-expert",
      "activation": "Use `quant-finance-research-platform-expert` as private quant finance research platform expert guidance for this task.",
      "description": "Use when executing quantitative-finance research platform tasks involving factor definition, market-data quality, backtest validity, cost and capacity modeling, monitoring, and production promotion decisions.",
      "leakage_level": "S3"
    }
  ]
}
```

The skill directory must contain `SKILL.md`:

```text
task_package/
  executor_skills.json
  skills/
    quant-finance-research-platform-expert/
      SKILL.md
      references/
```

When `executor_skills.json` is present, the skill registry and skill directories are treated as runner metadata, not ordinary task materials.

## Running

Select one or more skills:

```bash
starbench-run \
  --task liquidity_shock_tech_proposal \
  --executor-skill quant-finance-research-platform-expert
```

Shared registry skills can be selected from `executor_skills/registry.json`:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --executor-skill research-platform-architecture-expert
```

Or by group:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --executor-skill-group research-platforms
```

Task-local skills and shared registry skills can be used together as long as skill ids do not collide.

The runner records selected skills in:

```text
runs/<run_id>/run_config.json
runs/<run_id>/<task_run_id>/manifest.json
runs/<run_id>/<task_run_id>/task_summary.json
```

## Docker Install Path

For Docker executors, StarBench installs selected skills on the host at:

```text
runs/<run_id>/<task_run_id>/codex_home/docker/skills/<skill_id>/
```

The container sees the same skill at:

```text
/codex-home/skills/<skill_id>/
```

because the Docker command mounts:

```text
host codex_home/docker -> /codex-home
CODEX_HOME=/codex-home
```

For local executors, selected skills are installed at:

```text
runs/<run_id>/<task_run_id>/codex_home/skills/<skill_id>/
```

## Prompt Behavior

The executor receives a short activation block:

```text
Installed executor Codex skills:
- `quant-finance-research-platform-expert`: Use `quant-finance-research-platform-expert` as private quant finance research platform expert guidance...

Skill usage rules:
- Use the installed executor skills as private execution guidance for planning, execution, and final self-checking.
- You may read installed skill files under $CODEX_HOME/skills/<skill-id>/.
- The task prompt and materials remain authoritative if they conflict with a skill.
- Do not mention installed skills, expert traces, harnesses, or internal checklists in deliverables.
```

The skill body itself is not appended into `workspace/inputs/prompt.md`.

## Reproducibility

For each installed skill, StarBench computes and records a directory SHA-256. If `executor_skills.json` provides a `sha256`, the runner validates it before execution.

The hash ignores `.git`, `__pycache__`, and `.DS_Store`.
