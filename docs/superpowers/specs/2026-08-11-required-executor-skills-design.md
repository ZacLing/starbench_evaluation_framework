# Required Executor Skills Design

## Goal

Let a StarBench run distinguish executor skills that are merely available from
skills the executor is explicitly required to use. The choice is per skill and
must work through the GUI, CLI, typed run plan, prompt builder, and persisted
run artifacts.

This feature strengthens the executor instruction only. It does not inspect the
event trace, infer whether a skill was followed, or fail a run because usage
evidence is absent.

## User-facing model

Each skill has one normalized state in a run:

- **Off**: not installed and not mentioned to the executor.
- **Available**: installed and presented as optional private guidance. This is
  the existing `executor_skills` behavior.
- **Required**: installed and accompanied by an explicit instruction to read
  its complete `SKILL.md` before task work and follow its applicable workflow
  during planning, execution, and final self-checking.

Task instructions and materials remain authoritative when they conflict with a
skill. Required skills remain private execution guidance and must not be named
in task deliverables.

## Launch contract

Add an optional `required_executor_skills` string array to the v2 run-plan
schema and a repeatable CLI flag:

```text
--required-executor-skill <skill-id>
```

The existing inputs remain unchanged:

```text
--executor-skill <skill-id>
--executor-skill-group <group-id>
```

`required_executor_skills` implies selection and installation; callers do not
need to repeat the same id in `executor_skills`. During normalization, a
required id upgrades an ordinary selection of the same skill, including a
skill brought in by a selected group. This upgrade is not treated as a
duplicate. Existing duplicate errors within ordinary selections or overlapping
ordinary groups remain unchanged, and duplicate entries within the required
list fail validation.

The final installed order stays deterministic: ordinary individual and
group-expanded skills keep their existing order, then previously unseen
required ids are appended in required-list order. Requirement status does not
change a skill's install location or directory hash.

## Backend representation and flow

`TaskRunSpec` continues to own the ordered list of selected `ExecutorSkill`
objects and gains an ordered `required_executor_skill_ids` list derived from
launch normalization. It exposes three named views:

- `executor_skill_ids`: all installed ids, for backward compatibility;
- `advisory_executor_skill_ids`: installed Available ids;
- `required_executor_skill_ids`: installed Required ids.

The flow is:

1. CLI or GUI plan input validates ordinary ids, groups, and required ids
   against the combined task-local and shared registries.
2. Group ids expand using the existing registry rules.
3. The resolver builds one installed skill list and overlays required status by
   id.
4. Materialization copies every resolved skill through the existing runtime
   adapter install path.
5. Prompt assembly renders available and required skills separately.
6. Run metadata persists both normalized states.

Task-local and shared-registry skills use the same behavior. Unknown required
ids fail before execution just like unknown ordinary ids.

## Executor prompt

The current skill section becomes mode-aware. Available skills retain the
existing guidance. Required skills receive unambiguous rules equivalent to:

```text
Required executor skills:
- `<skill-id>`: <activation>

Required skill usage rules:
- Before beginning task work, read the complete SKILL.md for every required
  executor skill from <runtime-specific-location>.
- You must follow each required skill's applicable workflow during planning,
  execution, and final self-checking.
- Do not skip a required skill because it appears optional or because the task
  seems simple.
```

The shared rules about task authority and not leaking skill details remain in
the prompt. Runtime-specific skill locations continue to come from adapters;
no runtime gets special prompt semantics.

When no required skills are selected, prompt output remains byte-for-byte
compatible with the current available-skill behavior. When no skills are
selected, no skill section is emitted.

## GUI behavior

The New Run executor-skills block gives each individual skill a three-state
choice: Off, Available, or Required. Moving between Available and Required
updates disjoint `executor_skills` and `required_executor_skills` arrays.

Groups remain an Available-level convenience. A group member cannot be turned
Off while its group is selected, but it can be upgraded individually to
Required. Removing the requirement returns that member to Available through
the group.

The Review step shows Available and Required skills separately, with Required
visually prominent and described as prompt-enforced rather than
trace-verified. Measurement profiles preserve the new field, so saved and
reloaded runs retain per-skill modes.

## Artifacts and compatibility

Persist required-skill intent anywhere selected skills are currently recorded:

- `run_config.json`
- `run_plan.json`
- per-task `manifest.json`
- per-task `task_summary.json`
- GUI run-detail provenance

Keep the existing all-installed `executor_skill_ids` / `executor_skills`
metadata for readers that do not know about the new feature. Add
`advisory_executor_skill_ids`, `advisory_executor_skills`,
`required_executor_skill_ids`, and `required_executor_skills` to per-task
metadata. `run_config.json` additionally records
`requested_required_executor_skill_ids`, while `run_plan.json` preserves the
input `required_executor_skills` array verbatim. Consumers therefore never
need to infer intent from prompt text. Old plans, profiles, and task packages
without `required_executor_skills` behave exactly as before.

No artifact claims verified use. GUI labels use "Required by prompt" and
documentation uses "prompt-required"; neither calls a skill "verified" or
"executed".

## Error handling

- Unknown required skill ids fail at plan/argument validation before run state
  is created.
- A skill unavailable to the selected task/shared registry fails with the same
  class of error as an ordinary selected skill.
- Duplicate ids inside `required_executor_skills` fail closed.
- A required id also selected ordinarily is normalized to Required rather than
  installed twice.
- Installation, hash, and unsafe-path failures continue to use existing
  executor-skill errors.
- Missing trace evidence never changes executor status or benchmark score.

## Testing

Backend tests cover:

- CLI parsing and typed-plan expansion for the repeatable required flag;
- schema acceptance, unknown-field rejection, and old-plan compatibility;
- resolution across ordinary ids, groups, task-local skills, shared skills,
  upgrades, ordering, and duplicate errors;
- prompt text for no skills, available-only, required-only, and mixed modes;
- runtime-specific paths in required instructions;
- single installation and stable hashes when a group member is upgraded;
- required/advisory metadata in run config, manifest, and task summary;
- profile and GUI planning/launcher pass-through.

Frontend tests cover per-skill state changes, group-member upgrades, Review
labels, and profile reload behavior. Existing executor-skill tests remain the
regression suite for runs that do not use the new field.

Documentation updates cover the CLI, run-plan field, GUI semantics, examples,
and the explicit limitation that requirement is prompt-enforced rather than
trace-verified.

## Out of scope

- Trace-based proof that `SKILL.md` was read.
- Judge-based assessment of skill compliance.
- Automatic failure or retry when a required skill appears unused.
- Required skill groups as a separate launch primitive; individual group
  members can already be upgraded to Required.
- Changing skill precedence over the task prompt or materials.
