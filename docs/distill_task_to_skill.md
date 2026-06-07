# Distill Tasks Into Senior Expert Skills

This guide shows how to turn completed task packages into reusable executor Codex Skills. The goal is not to produce one skill per task object. The goal is to distill the senior expert operating model behind those tasks.

## Inputs

Each `--source-task` can point to either a task root or its `task_package/` directory.

The distiller reads these files when present:

```text
<task>/
  task_package/
    task.json
    prompt.md
    rubrics.json
    human_reference.json
  trace/
    reviews/*/review.json
```

It uses:

- the prompt for task intent;
- `human_reference.json` for expert execution steps;
- `review.json` weaknesses for trace-derived failure patterns;
- `rubrics.json` for fine-grained execution requirements.

## Basic Command

From the framework root:

```bash
PYTHONPATH=src python3 -m starbench.skill_distiller.distill \
  --source-task tasks/accounting_latent_measurement_platform_v2 \
  --source-task tasks/rsj_intraday_factor_platform_hsw-v3 \
  --output-root executor_skills \
  --expert-archetype research-platform-architecture-expert \
  --group senior-expert-stack
```

The generated skill id defaults to the expert archetype id. Use `--skill-id` only when you intentionally want an alias.

## Expert Archetypes

Available archetypes:

- `senior-technical-proposal-expert`: proposal framing, stakeholder structure, roadmap, risk-to-control mapping, and success criteria.
- `research-platform-architecture-expert`: reusable research platforms, governance gates, auditability, reproducibility, and operating model.
- `quant-finance-research-platform-expert`: factor research, market data, backtests, costs, capacity, monitoring, and production promotion.
- `empirical-measurement-governance-expert`: latent constructs, proxies, method comparison, preregistration, sample comparability, and reviewer evidence.

Examples:

```bash
PYTHONPATH=src python3 -m starbench.skill_distiller.distill \
  --source-task tasks/rsj_intraday_factor_platform_hsw-v3 \
  --output-root executor_skills \
  --expert-archetype quant-finance-research-platform-expert \
  --group senior-expert-stack
```

```bash
PYTHONPATH=src python3 -m starbench.skill_distiller.distill \
  --source-task tasks/accounting_latent_measurement_platform_v2 \
  --output-root executor_skills \
  --expert-archetype empirical-measurement-governance-expert \
  --group senior-expert-stack
```

## Output

The command writes:

```text
executor_skills/
  registry.json
  generated/
    <expert-archetype-id>/
      SKILL.md
      provenance.json
      references/
        expert_profile.md
        workflow.md
        operating_principles.md
        decision_heuristics.md
        atomic_execution_cards.md
        section_micro_checks.md
        deliverable_dna.md
        anti_patterns.md
        honest_boundaries.md
        final_self_check.md
        specializations/
        research/
```

`SKILL.md` is intentionally short and positive. It describes when the executor should use the expert guidance. Source-task history stays in `provenance.json` and `references/research/`.

## Registry Groups

`registry.json` maps skill ids and groups:

```json
{
  "groups": {
    "senior-expert-core": [
      "research-platform-architecture-expert",
      "senior-technical-proposal-expert"
    ],
    "quant-finance": ["quant-finance-research-platform-expert"],
    "empirical-measurement": ["empirical-measurement-governance-expert"],
    "senior-expert-stack": [
      "empirical-measurement-governance-expert",
      "quant-finance-research-platform-expert",
      "research-platform-architecture-expert",
      "senior-technical-proposal-expert"
    ]
  }
}
```

Groups are optional but useful for loading a domain bundle during evaluation.

## Inspect The Result

Useful files to check:

```bash
sed -n '1,160p' executor_skills/generated/research-platform-architecture-expert/SKILL.md
sed -n '1,220p' executor_skills/generated/research-platform-architecture-expert/references/atomic_execution_cards.md
sed -n '1,180p' executor_skills/generated/research-platform-architecture-expert/references/specializations/*.md
jq . executor_skills/generated/research-platform-architecture-expert/provenance.json
```

The core cards should read like reusable senior expert moves. Task nouns should appear mainly in `specializations/` and `research/`.
