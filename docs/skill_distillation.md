# Trace-to-Senior-Expert Skill Distillation

StarBench can distill completed HSW traces, human references, and rubrics into reusable executor skills. The distiller now targets senior expert archetypes, not task names.

The important separation is:

- Core skill identity: broad expert capability such as quant finance research platforms or empirical measurement governance.
- Atomic cards: reusable work types such as data lineage, validation design, selection control, monitoring gates, and audit packages.
- Specializations: task-specific examples isolated under `references/specializations/`.
- Provenance: source trace and rubric evidence recorded in `provenance.json` and `references/research/`, not in the public skill description.

## Inputs

The distiller reads:

```text
<task>/
  task_package/
    task.json
    prompt.md
    rubrics.json
    human_reference.json
  trace/
    reviews/r*_review/review.json
```

## Generate A Senior Expert Skill

```bash
PYTHONPATH=src python3 -m starbench.skill_distiller.distill \
  --source-task tasks/accounting_latent_measurement_platform_v2 \
  --source-task tasks/rsj_intraday_factor_platform_hsw-v3 \
  --output-root executor_skills \
  --expert-archetype research-platform-architecture-expert \
  --group senior-expert-stack
```

Useful archetypes:

- `senior-technical-proposal-expert`
- `research-platform-architecture-expert`
- `quant-finance-research-platform-expert`
- `empirical-measurement-governance-expert`

If `--expert-archetype` is omitted, the distiller infers one from the combined source corpus. For controlled experiments, pass it explicitly.

## Output

```text
executor_skills/
  registry.json
  generated/
    research-platform-architecture-expert/
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

`SKILL.md` stays short and activation-oriented. Detailed guidance lives in `references/`.

## Load In Evaluation

Select one skill:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --executor-skill quant-finance-research-platform-expert
```

Select a group:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --executor-skill-group senior-expert-stack
```

Baseline behavior is unchanged unless `--executor-skill` or `--executor-skill-group` is passed.

## Current Example Groups

- `senior-expert-core`: proposal and research-platform architecture experts.
- `research-platforms`: shared research-platform experts.
- `quant-finance`: quant finance research-platform expert.
- `empirical-measurement`: empirical measurement governance expert.
- `senior-expert-stack`: all generated senior expert skills.

## Granularity Model

The generated harness is multi-granularity:

- `expert_profile.md`: expert role, scope, and boundaries.
- `workflow.md`: classify by work type before writing.
- `operating_principles.md`: senior framing rules.
- `decision_heuristics.md`: if/then expert moves.
- `atomic_execution_cards.md`: fine-grained executable requirements.
- `section_micro_checks.md`: section-level coverage checks.
- `specializations/`: task-specific examples kept out of core identity.
- `final_self_check.md`: final private coverage pass.

This supports fine-grained rubrics while keeping the reusable skill at senior expert level.
