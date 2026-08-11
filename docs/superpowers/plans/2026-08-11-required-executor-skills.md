# Required Executor Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-skill prompt-required mode that installs selected executor skills, directs the agent to read and follow them, and preserves that intent through CLI, GUI, run plans, profiles, and run artifacts.

**Architecture:** Extend the additive run contract with `required_executor_skills`, normalize ordinary/group/required inputs into one installed list plus an ordered required-id overlay, and let `TaskRunSpec` expose all/advisory/required views. The GUI stores ordinary and required ids in disjoint arrays and uses a pure state helper for the three-state control; the backend remains the authority for validation and artifact metadata.

**Tech Stack:** Python 3.9+ stdlib, `unittest`, JSON Schema, React 19, TypeScript 6, Vite 8, Vitest 5, Tailwind/Radix UI.

## Global Constraints

- Requirement is prompt-enforced only; never inspect trace evidence or alter benchmark scoring.
- Task prompt and materials remain authoritative over skill instructions.
- Preserve existing behavior and prompt text when `required_executor_skills` is absent.
- `required_executor_skills` implies selection and installation; an ordinary/group selection of the same id is upgraded, not installed twice.
- Groups remain Available-level; individual members may be upgraded to Required.
- Keep `executor_skill_ids` and `executor_skills` as all-installed compatibility fields.
- Author schemas under `schemas/starbench/`, then run `make sync-schemas` for packaged mirrors.
- After editing `src/starbench/gui/contracts.py`, run `make gen-types`; do not hand-edit generated `gui-frontend/src/lib/api-types.ts`.
- Rebuild committed GUI assets with `make gui-build` after frontend source changes.
- Never persist credentials or hidden rubric content.

---

### Task 1: Core contract, normalization, prompt, and artifacts

**Files:**
- Modify: `schemas/starbench/v1/run_plan.schema.json`
- Modify: `schemas/starbench/v1/task_manifest.schema.json`
- Modify: `schemas/starbench/v1/task_summary.schema.json`
- Modify: `schemas/starbench/v1/run_summary.schema.json`
- Modify (generated): `src/starbench/contracts/schemas/v1/run_plan.schema.json`
- Modify (generated): matching schemas under `src/starbench/contracts/schemas/v1/`
- Modify: `src/starbench/runner/cli.py`
- Modify: `src/starbench/runner/models.py`
- Modify: `src/starbench/runner/task_loader.py`
- Modify: `src/starbench/runner/orchestrator.py`
- Modify: `src/starbench/runner/prompts.py`
- Modify: `src/starbench/runner/summary.py`
- Test: `tests/runner/test_run_plan.py`
- Test: `tests/runner/test_executor_skills.py`
- Test: `tests/contracts/test_artifact_schemas.py`

**Interfaces:**
- Consumes: existing ordinary `executor_skills`, `executor_skill_groups`, `ExecutorSkill`, and adapter-provided `executor_skill_location`.
- Produces: CLI `--required-executor-skill`; plan key `required_executor_skills`; `TaskRunSpec.required_executor_skill_ids`, `.advisory_executor_skill_ids`, `.required_executor_skills`, and `.advisory_executor_skills`; mode-aware prompt and metadata.

- [ ] **Step 1: Write failing CLI and plan-contract tests**

Add tests that parse repeated required flags and a v2 plan:

```python
def test_required_executor_skill_cli_argument_is_repeatable(self) -> None:
    args = parse_args([
        "--tasks-dir", self.tmp,
        "--required-executor-skill", "skill-a",
        "--required-executor-skill", "skill-b",
    ])
    self.assertEqual(args.required_executor_skill, ["skill-a", "skill-b"])

def test_required_executor_skills_expand_from_plan(self) -> None:
    path = self.write_plan(required_executor_skills=["skill-a", "skill-b"])
    args = parse_args(["--plan", str(path)])
    self.assertEqual(args.required_executor_skill, ["skill-a", "skill-b"])
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.runner.test_run_plan.RunPlanTests.test_required_executor_skills_expand_from_plan \
  tests.runner.test_executor_skills.ExecutorSkillTests.test_required_executor_skill_cli_argument_is_repeatable
```

Expected: failures because the schema/flag does not exist.

- [ ] **Step 3: Add the additive plan and CLI surface**

Add `required_executor_skills` beside `executor_skills` in the authoring schema, add it to `PLAN_LIST_FLAGS`, and add the repeatable parser flag:

```python
"required_executor_skills": "--required-executor-skill",

parser.add_argument(
    "--required-executor-skill",
    action="append",
    help="Executor skill id that must be used as prompt-required private guidance. Repeatable.",
)
```

Run `make sync-schemas`, then rerun Step 2 and require PASS.

- [ ] **Step 4: Write failing normalization, prompt, install, and metadata tests**

Cover required-only, mixed ordinary/required, group upgrade, duplicate required ids, runtime path, and manifest fields. The central assertion shape is:

```python
task_run = build_task_runs(
    [task],
    instruction_mode="none",
    executor_skill_ids=["available-skill"],
    required_executor_skill_ids=["required-skill"],
    external_executor_skills=skills,
)[0]
self.assertEqual(task_run.executor_skill_ids, ["available-skill", "required-skill"])
self.assertEqual(task_run.advisory_executor_skill_ids, ["available-skill"])
self.assertEqual(task_run.required_executor_skill_ids, ["required-skill"])
self.assertIn("Required executor skills:", build_executor_prompt(task_run))
self.assertIn("read the complete SKILL.md", build_executor_prompt(task_run))
```

Also assert a required id already present in ordinary/group selection appears once and becomes Required, while a repeated id inside the required list raises `Duplicate --required-executor-skill`.

- [ ] **Step 5: Run the new core tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.runner.test_executor_skills -v
```

Expected: new assertions fail because `TaskRunSpec` and prompt metadata have no required mode.

- [ ] **Step 6: Implement ordered mode normalization and metadata**

Extend `build_task_runs` with `required_executor_skill_ids`. Validate duplicates within that list, resolve the ordered installed ids as ordinary ids followed by unseen required ids, and mark the required overlay on every generated `TaskRunSpec` variant. In `TaskRunSpec`, derive mode views without copying skill objects:

```python
@property
def advisory_executor_skill_ids(self) -> List[str]:
    required = set(self.required_executor_skill_ids or [])
    return [skill.id for skill in self.selected_executor_skills or [] if skill.id not in required]

@property
def required_executor_skills(self) -> List[ExecutorSkill]:
    required = set(self.required_executor_skill_ids or [])
    return [skill for skill in self.selected_executor_skills or [] if skill.id in required]
```

Add `advisory_executor_skill_ids`, `advisory_executor_skills`, `required_executor_skill_ids`, and `required_executor_skills` to `instruction_metadata()` while preserving all-installed compatibility fields.

- [ ] **Step 7: Implement mode-aware prompt text**

Partition selected skills by mode. Preserve the exact current output for available-only runs. For required or mixed runs, render a Required section whose rules say to read the complete `SKILL.md` before task work, follow applicable workflow during planning/execution/final self-checking, and not skip it because the task seems simple. Reuse the adapter-supplied location string.

- [ ] **Step 8: Wire orchestrator selection and provenance**

In `run_benchmark`, validate duplicate required ids, build the installed union, pass both the union and required ids to `build_task_runs`, and record:

```python
"requested_executor_skill_ids": requested_executor_skill_ids,
"requested_required_executor_skill_ids": requested_required_executor_skill_ids,
```

Carry advisory/required fields through `summary.py` grouping so `task_summary.json` and run summaries retain the mode.

- [ ] **Step 9: Run core and contract tests and require GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.runner.test_executor_skills \
  tests.runner.test_run_plan \
  tests.contracts.test_artifact_schemas -v
```

Expected: all tests pass and schema mirror equality remains green.

- [ ] **Step 10: Commit the core slice**

```bash
git add schemas/starbench/v1/run_plan.schema.json \
  src/starbench/contracts/schemas/v1/run_plan.schema.json \
  src/starbench/runner tests/runner tests/contracts
git commit -m "Add prompt-required executor skills to runner"
```

### Task 2: GUI backend and profile pass-through

**Files:**
- Modify: `src/starbench/gui/skills.py`
- Modify: `src/starbench/gui/launcher.py`
- Modify: `src/starbench/gui/services/planning.py`
- Modify: `src/starbench/gui/contracts.py`
- Modify (generated): `gui-frontend/src/lib/api-types.ts`
- Test: `tests/gui/test_skills.py`
- Test: `tests/gui/test_equivalence.py`
- Test: profile tests discovered under `tests/gui/`

**Interfaces:**
- Consumes: `required_executor_skills` from `SharedConfig` and runner plan contract from Task 1.
- Produces: validated required ids, launch-plan/argv pass-through, group-expanded all/advisory/required preview lists, and profile persistence through generated API types.

- [ ] **Step 1: Write failing GUI validation and launch tests**

Add tests asserting:

```python
selection = skills.validate_selection(
    self.root,
    [],
    ["core"],
    ["alpha-expert"],
)
self.assertEqual(selection.installed_ids, ["alpha-expert", "beta-expert"])
self.assertEqual(selection.required_ids, ["alpha-expert"])
```

and that `build_run_plan`/`build_run_argv` emit `required_executor_skills` / `--required-executor-skill`, while plan previews separate advisory and required ids.

- [ ] **Step 2: Run GUI skill tests and verify RED**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.gui.test_skills -v
```

Expected: failures because GUI contracts and validation accept only two selection inputs.

- [ ] **Step 3: Implement a normalized GUI skill selection result**

Add a focused immutable result type in `src/starbench/gui/skills.py`:

```python
@dataclass(frozen=True)
class SkillSelection:
    installed_ids: List[str]
    advisory_ids: List[str]
    required_ids: List[str]
```

Extend `validate_selection` to accept required ids, preserve current duplicate errors among ordinary/group inputs, validate required-list duplicates, and upgrade overlap to Required. Update planning callers to use its three lists.

- [ ] **Step 4: Pass the field through launcher, preview, profiles, and contracts**

Add `required_executor_skills` to `SharedConfig`, run-plan construction, argv rendering, and preview item contracts. The preview item exposes all-installed `executor_skills` plus `advisory_executor_skills` and `required_executor_skills`. Run `make gen-types` after Python contract changes.

- [ ] **Step 5: Run GUI backend tests and require GREEN**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests/gui -v
```

Expected: all GUI backend tests pass, including plan-equivalence and profile serialization.

- [ ] **Step 6: Commit the GUI backend slice**

```bash
git add src/starbench/gui gui-frontend/src/lib/api-types.ts tests/gui
git commit -m "Carry required skill modes through GUI plans"
```

### Task 3: Three-state frontend control and review provenance

**Files:**
- Create: `gui-frontend/src/features/new-run/skill-modes.ts`
- Create: `gui-frontend/src/features/new-run/skill-modes.test.ts`
- Modify: `gui-frontend/src/features/new-run/steps/ExecutorSkillsBlock.tsx`
- Modify: `gui-frontend/src/features/new-run/steps/ReviewStep.tsx`
- Modify: `gui-frontend/src/pages/RunDetail.tsx`
- Modify: `gui-frontend/package.json`
- Modify: `gui-frontend/package-lock.json`
- Modify (generated build): `src/starbench/gui/static/`

**Interfaces:**
- Consumes: generated `SharedConfig.required_executor_skills` and preview `advisory_executor_skills` / `required_executor_skills`.
- Produces: pure `skillMode` and `setSkillMode` helpers and an accessible Off/Available/Required control.

- [ ] **Step 1: Add Vitest and write failing pure-state tests**

Add `vitest` as a dev dependency and a `test` script using `vitest run`. Write tests for Off→Available, Available→Required migration, Required→Off removal, and group member Required→Available fallback:

```typescript
test("upgrades an available skill to required without duplication", () => {
  const next = setSkillMode(
    { executor_skills: ["alpha"], required_executor_skills: [] },
    "alpha",
    "required",
    false,
  )
  expect(next.executor_skills).toEqual([])
  expect(next.required_executor_skills).toEqual(["alpha"])
})
```

- [ ] **Step 2: Run the frontend unit test and verify RED**

Run:

```bash
cd gui-frontend && npm test -- skill-modes.test.ts
```

Expected: failure because `skill-modes.ts` does not exist.

- [ ] **Step 3: Implement the pure state helper and require GREEN**

Implement `SkillMode = "off" | "available" | "required"`. `skillMode` returns Required first, Available for explicit or group membership, otherwise Off. `setSkillMode` returns disjoint arrays and refuses Off for group-covered members by falling back to Available. Rerun Step 2 and require PASS.

- [ ] **Step 4: Replace individual checkboxes with an accessible three-state selector**

Keep the existing card layout and tokens. Each skill row retains its id and description, then adds a compact three-button `role="radiogroup"` labeled by skill id. Use exact visible labels `Off`, `Available`, and `Required by prompt`; group-covered members disable only Off, not Required. Required state uses the existing warning/live semantic treatment rather than a new palette. Keep keyboard focus visible and the summary badges mode-specific.

- [ ] **Step 5: Separate modes in Review and run provenance**

Review renders two labeled badge groups. RunDetail shows required skill ids as `Required by prompt` and advisory ids as `Available`; it does not claim verification.

- [ ] **Step 6: Run frontend tests, lint, and build**

Run:

```bash
cd gui-frontend && npm test && npm run lint && npm run build
```

Expected: Vitest passes, oxlint reports no errors, and TypeScript/Vite build exits 0.

- [ ] **Step 7: Rebuild committed assets and commit**

Run `make gui-build`, then:

```bash
git add gui-frontend src/starbench/gui/static
git commit -m "Add per-skill required mode to run wizard"
```

### Task 4: Documentation and end-to-end regression

**Files:**
- Modify: `README.md`
- Modify: `docs/executor_skills.md`
- Modify: `docs/use_skills_in_eval.md`
- Modify: `docs/runner_reference.md`
- Modify: `docs/artifact_contracts.md`

**Interfaces:**
- Consumes: finalized CLI names, plan field, prompt semantics, GUI labels, and artifact fields from Tasks 1–3.
- Produces: current operational documentation with no claim of verified execution.

- [ ] **Step 1: Update current-operation docs**

Document `--required-executor-skill`, `required_executor_skills`, per-skill GUI modes, group-member upgrades, artifact fields, and the explicit prompt-only limitation. Include one example using:

```bash
starbench-run \
  --executor-skill-root executor_skills \
  --required-executor-skill preipo-investment-decision
```

- [ ] **Step 2: Run full verification**

Run:

```bash
make sync-schemas
make gen-types
PYTHONPATH=src python3 -m unittest discover -s tests
cd gui-frontend && npm test && npm run lint && npm run build
git diff --check
git status --short
```

Expected: every command exits 0; Python reports zero failures/errors; Vitest reports zero failed tests; lint/build succeed; schema and generated API types are current; diff check is empty.

- [ ] **Step 3: Review the specification line by line**

Confirm all of these in the final diff: per-skill state, GUI/CLI/run-plan coverage, required prompt wording, task-authority rule, group upgrade, all/advisory/required artifact metadata, profile persistence, no trace validation, backward compatibility, and current docs.

- [ ] **Step 4: Commit documentation and final fixes**

```bash
git add README.md docs gui-frontend src schemas tests
git commit -m "Document prompt-required executor skills"
```
