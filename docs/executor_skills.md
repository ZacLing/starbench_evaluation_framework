# Executor Skills

StarBench can install task-registered executor skills into the selected executor runtime's isolated workspace.

This is different from human-reference instruction injection or rigor injection:

- Human-reference and rigor modes append text to the task prompt.
- Executor skills are copied as real skill directories into the runtime-specific install path.
- The executor prompt only names the selected installed skills and tells the executor where to read them as private execution guidance.

Baseline runs are unchanged unless `--executor-skill`,
`--required-executor-skill`, or `--executor-skill-group` is passed.

## Task Package Format

Register skills in `task.json` (the default name is already `executor_skills.json`,
so this line is only needed for a non-default filename):

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

Shared registry skills can be selected from the skill library's `registry.json`.
`--executor-skill-root` defaults to `$STARBENCH_HOME/skills` (`~/.starbench/skills`);
this repository ships an example library at `executor_skills/`:

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

Require a selected skill's workflow through the executor prompt:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --required-executor-skill research-platform-architecture-expert
```

The option is per skill and repeatable. A required skill is installed
automatically, so it does not also need `--executor-skill`. Available and
required skills can be mixed in the same run. If a required id was also selected
as an available skill or through a group, required mode upgrades that id instead
of installing it twice.

Task-local skills and shared registry skills can be used together as long as skill ids do not collide.

The runner records selected skills in:

```text
runs/<run_id>/run_config.json
runs/<run_id>/<task_run_id>/manifest.json
runs/<run_id>/<task_run_id>/task_summary.json
```

## Install Paths

For Codex Docker executors, StarBench installs selected skills on the host at:

```text
runs/<run_id>/<task_run_id>/agent_home/docker/skills/<skill_id>/
```

The container sees the same skill at:

```text
/codex-home/skills/<skill_id>/
```

because the Docker command mounts:

```text
host agent_home/docker -> /codex-home
CODEX_HOME=/codex-home
```

For Codex local executors, selected skills are installed at:

```text
runs/<run_id>/<task_run_id>/agent_home/skills/<skill_id>/
```

When a local Codex executor selects any skill, an executor auth mode of
`global` is normalized to `copy-auth`. This preserves the host Codex login while
setting the run-local `CODEX_HOME`, so Codex reads the same `agent_home/skills`
directory into which StarBench installed the skill. The evaluator auth mode is
not changed.

Other runtimes use task-workspace paths, on either backend:

```text
Grok Build     -> runs/<run_id>/<task_run_id>/workspace/.grok/skills/<skill_id>/
Gemini CLI     -> runs/<run_id>/<task_run_id>/workspace/.gemini/skills/<skill_id>/
Claude Code    -> runs/<run_id>/<task_run_id>/workspace/.claude/skills/<skill_id>/
OpenCode, Pi   -> runs/<run_id>/<task_run_id>/workspace/.starbench/executor_skills/<skill_id>/
```

Pi additionally runs with `--no-skills` and receives each installed skill back
explicitly as `--skill <path>`, so a run only ever loads the skills it selected.

## Prompt Behavior

The executor receives a short activation block, here as rendered for Codex:

```text
Installed executor skills:
- `quant-finance-research-platform-expert`: Use `quant-finance-research-platform-expert` as private quant finance research platform expert guidance...

Skill usage rules:
- Use the installed executor skills as private execution guidance for planning, execution, and final self-checking.
- You may read installed skill files under $CODEX_HOME/skills/<skill-id>/.
- The task prompt and materials remain authoritative if they conflict with a skill.
- Do not mention installed skills, expert traces, harnesses, or internal checklists in deliverables.
```

The read path in the second rule is the selected runtime's own location:
`$CODEX_HOME/skills/<skill-id>/`, `./.grok/skills/<skill-id>/`,
`./.gemini/skills/<skill-id>/`, `./.claude/skills/<skill-id>/`, or
`./.starbench/executor_skills/<skill-id>/` for OpenCode, Pi, and custom runtimes.

The skill body itself is not appended into `workspace/inputs/prompt.md`.

For required skills, the prompt uses a distinct block:

```text
Required executor skills:
- `research-platform-architecture-expert`: ...

Required skill usage rules:
- Before beginning task work, read the complete SKILL.md for every required executor skill under $CODEX_HOME/skills/<skill-id>/.
- You must follow each required skill's applicable workflow during planning, execution, and final self-checking.
- Do not skip a required skill because it appears optional or because the task seems simple.
```

This is prompt enforcement only. StarBench records the requirement but does not
inspect the agent trace to prove that the skill was used, and it does not fail a
run solely because usage cannot be verified.

## Reproducibility

For each installed skill, StarBench computes and records a directory SHA-256. If `executor_skills.json` provides a `sha256`, the runner validates it before execution.

The hash ignores `.git`, `__pycache__`, and `.DS_Store`.
