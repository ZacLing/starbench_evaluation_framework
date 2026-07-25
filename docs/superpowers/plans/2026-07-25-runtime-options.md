# Runtime Options (Knob Namespacing) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every runtime-named knob field (`claude_max_turns`, `opencode_provider/base_url/api_key_env` and role variants) with role-scoped option boxes (`executor_options` / `evaluator_options`) declared per-adapter, validated at parse time, and auto-rendered in the GUI — per the approved spec `docs/superpowers/specs/2026-07-25-runtime-options-design.md` (the spec governs on any conflict).

**Architecture:** Adapters declare knobs (`RuntimeOption` on `RuntimeInfo.options`). One resolver (`resolve_runtime_options` in `adapters/base.py`) validates/coerces a raw box against a role's declarations; both entry transports (CLI flags, run_plan v2) funnel through it. Contexts carry one `options` mapping instead of named fields. The GUI backend writes wiring values into boxes; the frontend renders `surface=="user"` knobs from `/api/agents` declarations.

**Tech Stack:** Python 3 stdlib (dataclasses, argparse, unittest, json-schema via existing `contracts` validator), React + TypeScript + react-query, `make gen-types` / `make sync-schemas`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-25-runtime-options-design.md`. Decisions D1-D4 are settled; do not reopen.
- Tests green after every task: `PYTHONPATH=src python3 -m unittest discover -s tests`.
- Frontend compiles after frontend changes: `cd gui-frontend && npm run build`; after final frontend task run `make gui-build` and commit regenerated `src/starbench/gui/static/`.
- After changing `src/starbench/gui/contracts.py`: `make gen-types`, commit regenerated `gui-frontend/src/lib/api-types.ts` same commit. After changing `schemas/starbench/`: `make sync-schemas`, commit both trees same commit.
- Run semantics untouched (verdicts, aggregation, seeds, fairness). For identical configuration values, the executor/judge child-process command lines must be byte-identical to today.
- Error message texts in the spec are normative — copy exactly.
- Work on branch `codex/frontend-decomposition`. Per-task commits; imperative subject; last line trailer:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- Do not touch `README.zh-CN.md` or `.superpowers/`. Stage only files named in each task's commit step (plus regenerated outputs the constraints above name).
- Comments in English matching file style.

---

### Task 1: Declaration layer — `RuntimeOption`, adapter declarations, one resolver

**Files:**
- Modify: `src/starbench/adapters/base.py` (add `RuntimeOption`, `RuntimeInfo.options`, `resolve_runtime_options`)
- Modify: `src/starbench/adapters/claude.py`, `src/starbench/adapters/opencode.py` (declare)
- Test: `tests/adapters/test_runtime_options.py` (new)

**Interfaces:**
- Consumes: existing `RuntimeInfo`, `RuntimeAdapter`.
- Produces (later tasks rely on these exact names):
  - `RuntimeOption(name, type, role="executor", surface="user", label="", help="", default=None, choices=())` frozen dataclass
  - `RuntimeInfo.options: Tuple[RuntimeOption, ...] = ()`
  - `resolve_runtime_options(adapter: RuntimeAdapter, role: str, raw: Mapping[str, object]) -> Dict[str, object]` raising `ValueError` with the spec's normative messages
  - `OPTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")`

- [ ] **Step 1: Write the failing tests**

Create `tests/adapters/test_runtime_options.py`:

```python
"""RuntimeOption declarations and the shared box resolver."""
from __future__ import annotations

import unittest

from starbench.adapters import get_builtin, list_builtin
from starbench.adapters.base import OPTION_NAME_RE, resolve_runtime_options


class DeclarationGuardTests(unittest.TestCase):
    def test_declared_knobs_match_the_spec(self) -> None:
        by_id = {a.info.id: a.info for a in list_builtin()}
        self.assertEqual(
            [(o.name, o.type, o.role, o.surface) for o in by_id["claude"].options],
            [("max_turns", "integer", "executor", "user")],
        )
        self.assertEqual(
            [(o.name, o.type, o.role, o.surface) for o in by_id["opencode"].options],
            [
                ("provider", "string", "both", "wiring"),
                ("base_url", "string", "both", "wiring"),
                ("api_key_env", "string", "both", "wiring"),
            ],
        )
        for agent_id in ("codex", "gemini", "grok"):
            self.assertEqual(by_id[agent_id].options, ())

    def test_declarations_are_well_formed(self) -> None:
        for adapter in list_builtin():
            names = [o.name for o in adapter.info.options]
            self.assertEqual(len(names), len(set(names)), adapter.info.id)
            for option in adapter.info.options:
                self.assertRegex(option.name, OPTION_NAME_RE)
                self.assertIn(option.type, ("integer", "string", "boolean", "enum"))
                self.assertIn(option.role, ("executor", "evaluator", "both"))
                self.assertIn(option.surface, ("user", "wiring"))
                if option.type == "enum":
                    self.assertTrue(option.choices)
                if option.surface == "user":
                    self.assertTrue(option.label)


class ResolverTests(unittest.TestCase):
    def test_unknown_key_is_rejected_with_declared_list(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_options(get_builtin("gemini"), "executor", {"max_turns": 50})
        message = str(ctx.exception)
        self.assertIn('gemini has no option named "max_turns"', message)
        self.assertIn("declares no executor-side options", message)

    def test_unknown_key_lists_available_options(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_options(get_builtin("claude"), "executor", {"max_turnz": 5})
        self.assertIn("max_turns (integer)", str(ctx.exception))

    def test_integer_coercion_accepts_decimal_strings(self) -> None:
        resolved = resolve_runtime_options(get_builtin("claude"), "executor", {"max_turns": "50"})
        self.assertEqual(resolved, {"max_turns": 50})

    def test_integer_rejects_non_numeric(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_runtime_options(get_builtin("claude"), "executor", {"max_turns": "abc"})
        self.assertIn('claude option max_turns expects an integer, got "abc"', str(ctx.exception))

    def test_role_filter_excludes_wrong_side(self) -> None:
        # max_turns is executor-only: the judge side must not accept it.
        with self.assertRaises(ValueError):
            resolve_runtime_options(get_builtin("claude"), "evaluator", {"max_turns": 5})

    def test_wiring_keys_resolve_for_both_roles(self) -> None:
        raw = {"provider": "yunwu", "base_url": "https://yunwu.ai/v1", "api_key_env": "OPENAI_API_KEY"}
        for role in ("executor", "evaluator"):
            self.assertEqual(resolve_runtime_options(get_builtin("opencode"), role, raw), raw)

    def test_empty_box_resolves_empty(self) -> None:
        self.assertEqual(resolve_runtime_options(get_builtin("claude"), "executor", {}), {})
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_runtime_options -v`
Expected: FAIL with `ImportError: cannot import name 'OPTION_NAME_RE'`.

- [ ] **Step 3: Implement the declaration layer in `adapters/base.py`**

Add near the top (after existing imports; add `import re` and `Mapping` to the typing import):

```python
OPTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class RuntimeOption:
    """One runtime-specific knob, declared by the adapter that owns it.

    ``surface`` constrains the GUI only: "user" knobs are auto-rendered as
    form controls; "wiring" knobs are transport values the console computes
    from the selected AI provider and never renders. CLI/plan input treats
    both alike (a standalone CLI user has no console to fill wiring for
    them). ``default=None`` means "not set": the knob is omitted and the
    runtime CLI keeps its own default behaviour.
    """

    name: str
    type: str  # "integer" | "string" | "boolean" | "enum"
    role: str = "executor"  # "executor" | "evaluator" | "both"
    surface: str = "user"  # "user" | "wiring"
    label: str = ""
    help: str = ""
    default: object = None
    choices: Tuple[str, ...] = ()
```

Add to `RuntimeInfo` after `enforces_web_search`:

```python
    # Runtime-specific knobs (see RuntimeOption). Empty for runtimes with none.
    options: Tuple["RuntimeOption", ...] = ()
```

Add the resolver after `provider_filter_for_protocol`:

```python
def _describe_options(options) -> str:
    return ", ".join(f"{o.name} ({o.type})" for o in options)


def resolve_runtime_options(adapter, role, raw):
    """Validate and coerce one role's option box against the adapter's declarations.

    The single implementation both transports share: CLI ``--<role>-option``
    pairs and run_plan v2 boxes funnel through here, so the two entries cannot
    drift. Raises ValueError with the messages the design spec fixes verbatim.
    """
    agent_id = adapter.info.id
    declared = {o.name: o for o in adapter.info.options if o.role in (role, "both")}
    resolved: Dict[str, object] = {}
    for key, value in dict(raw).items():
        option = declared.get(key)
        if option is None:
            available = (
                f"its declared {role}-side options: {_describe_options(declared.values())}"
                if declared
                else f"it declares no {role}-side options"
            )
            raise ValueError(f'{agent_id} has no option named "{key}" ({available}).')
        resolved[key] = _coerce_option(agent_id, option, value)
    for option in declared.values():
        if option.name not in resolved and option.default is not None:
            resolved[option.name] = option.default
    return resolved


def _coerce_option(agent_id: str, option: "RuntimeOption", value: object) -> object:
    if option.type == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise ValueError(
                f'{agent_id} option {option.name} expects an integer, got "{value}".'
            )
        try:
            return int(value)
        except ValueError:
            raise ValueError(
                f'{agent_id} option {option.name} expects an integer, got "{value}".'
            )
    if option.type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.lower() in ("true", "false"):
            return value.lower() == "true"
        raise ValueError(
            f'{agent_id} option {option.name} expects true or false, got "{value}".'
        )
    if option.type == "enum":
        text = str(value)
        if text not in option.choices:
            raise ValueError(
                f'{agent_id} option {option.name} must be one of '
                f'{", ".join(option.choices)}; got "{value}".'
            )
        return text
    return str(value)
```

(`Tuple`, `Dict`, `Mapping` come from the file's existing `typing` import — extend it as needed.)

- [ ] **Step 4: Declare the knobs in the two adapters**

`adapters/claude.py`, inside its `RuntimeInfo` after `enforces_web_search=True,`:

```python
        options=(
            RuntimeOption(
                name="max_turns",
                type="integer",
                role="executor",
                surface="user",
                label="Max turns",
                help="Agentic turn cap for the executor. Blank means no cap.",
            ),
        ),
```

`adapters/opencode.py`, inside its `RuntimeInfo` (same position):

```python
        options=(
            RuntimeOption(name="provider", type="string", role="both", surface="wiring"),
            RuntimeOption(name="base_url", type="string", role="both", surface="wiring"),
            RuntimeOption(name="api_key_env", type="string", role="both", surface="wiring"),
        ),
```

Both files import `RuntimeOption` from `.base` (extend the existing `from .base import (...)` block).

- [ ] **Step 5: Run the new tests, then the full suite**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_runtime_options -v` → all PASS.
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → green (pure addition, nothing consumes it yet).

- [ ] **Step 6: Commit**

```bash
git add src/starbench/adapters/base.py src/starbench/adapters/claude.py src/starbench/adapters/opencode.py tests/adapters/test_runtime_options.py
git commit -m "Add RuntimeOption declarations and the shared box resolver"
```

---

### Task 2: Contexts carry one `options` mapping; adapters consume it

**Files:**
- Modify: `src/starbench/adapters/base.py` (`ExecutorContext`, `JudgeContext`)
- Modify: `src/starbench/adapters/claude.py:254,265` (max_turns), `src/starbench/adapters/opencode.py:276-366` (triple)
- Modify: `src/starbench/runner/orchestrator.py:329-353` (context construction — temporary bridge)
- Modify: any test constructing these contexts (find: `rg -ln "ExecutorContext(\|JudgeContext(" tests/ src/`)

**Interfaces:**
- Produces: `ExecutorContext.options: Mapping[str, object]` and `JudgeContext.options: Mapping[str, object]` (default `{}` via `field(default_factory=dict)`), replacing `claude_max_turns`, `opencode_provider`, `opencode_base_url`, `opencode_api_key_env` on `ExecutorContext` and the three `opencode_*` fields on `JudgeContext`. Adapters read `ctx.options.get("max_turns")` / `ctx.options.get("provider")` etc.

- [ ] **Step 1: Swap the context fields**

In `ExecutorContext` delete the four fields `claude_max_turns`, `opencode_provider`, `opencode_base_url`, `opencode_api_key_env`; in `JudgeContext` delete the three `opencode_*` fields. Add to both, before the fields that have defaults:

```python
    # Runtime-specific knobs for this role's resolved agent, already validated
    # by resolve_runtime_options. Adapters read their own declared names.
    options: Mapping[str, object] = field(default_factory=dict)
```

(Placement note: dataclass ordering — fields without defaults must precede fields with defaults; put `options` adjacent to `web_search_mode` in `ExecutorContext` and last in `JudgeContext`.)

- [ ] **Step 2: Update the two consuming adapters**

`claude.py`: both `max_turns=ctx.claude_max_turns` sites become `max_turns=ctx.options.get("max_turns")`.
`opencode.py`: every `ctx.opencode_provider` → `ctx.options.get("provider")`, `ctx.opencode_base_url` → `ctx.options.get("base_url")`, `ctx.opencode_api_key_env` → `ctx.options.get("api_key_env")` (executor and judge paths; `rg -n "ctx.opencode_" src/starbench/adapters/opencode.py` must end at zero hits).

`api_key_env` default caution: the legacy CLI flag `--opencode-api-key-env` defaulted to `"OPENAI_API_KEY"`, so today's contexts never see None there. Read `prepare_opencode_env`'s signature before editing: if it already falls back internally when `api_key_env` is falsy, pass the bare `ctx.options.get("api_key_env")`; if it does not, pass `ctx.options.get("api_key_env") or "OPENAI_API_KEY"` at both call sites to preserve behaviour. Record which case held in your report.

- [ ] **Step 3: Bridge in the orchestrator (explicitly temporary — Task 3 deletes it)**

In `orchestrator.py`, before the `ExecutorContext(...)` construction, replace the removed keyword arguments with:

```python
    # TEMPORARY BRIDGE (removed when the CLI grows --executor-option): funnel
    # the legacy flat flags into the role option boxes verbatim.
    executor_options = {
        key: value
        for key, value in (
            ("max_turns", args.claude_max_turns),
            ("provider", args.executor_opencode_provider),
            ("base_url", args.executor_opencode_base_url),
            ("api_key_env", args.executor_opencode_api_key_env),
        )
        if value is not None
    }
    evaluator_options = {
        key: value
        for key, value in (
            ("provider", args.evaluator_opencode_provider),
            ("base_url", args.evaluator_opencode_base_url),
            ("api_key_env", args.evaluator_opencode_api_key_env),
        )
        if value is not None
    }
```

`ExecutorContext(... options=executor_options, ...)`, `JudgeContext(... options=evaluator_options, ...)` replacing the deleted kwargs. Behaviour note: today every context carries all fields regardless of agent; the bridge reproduces exactly that (unvalidated), so nothing changes for any runtime. The shared→role fallback at `cli.py:408-412` still runs and still feeds the bridge — leave it alone in this task.

- [ ] **Step 4: Update context-constructing tests**

`rg -ln "ExecutorContext(\|JudgeContext(" tests/` — for each hit, replace removed kwargs with an `options={...}` dict carrying the same values under the new names. No assertion semantics change.

- [ ] **Step 5: Full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → green. The fake-CLI adapter tests are the byte-identical-argv proof: they assert the child command lines and must pass unchanged (except constructor-site edits from Step 4).

- [ ] **Step 6: Commit**

```bash
git add src/starbench/adapters/base.py src/starbench/adapters/claude.py src/starbench/adapters/opencode.py src/starbench/runner/orchestrator.py tests/
git commit -m "Contexts carry a validated options box instead of runtime-named fields"
```

---

### Task 3: CLI switch — generic `--executor-option/--evaluator-option`, delete the 10 legacy flags

**Files:**
- Modify: `src/starbench/runner/cli.py` (delete flags at 237-271, delete fallback loop 408-412, add generic flags + parse + validation; plan expansion rule)
- Modify: `src/starbench/runner/orchestrator.py` (delete Task-2 bridge; contexts read `args.executor_options`/`args.evaluator_options`; run_config records boxes, drops 10 flat keys)
- Modify: tests that pass legacy flags (`rg -ln -- "--claude-max-turns\|--opencode-provider\|--opencode-base-url\|--opencode-api-key-env\|opencode_provider=\|claude_max_turns=" tests/`)
- Modify: `docs/runner_reference.md` if it documents the deleted flags (`rg -n "claude-max-turns\|opencode-provider" docs/`)
- Test: extend `tests/runner/test_cli_bins.py` or new `tests/runner/test_cli_options.py`

**Interfaces:**
- Produces: `args.executor_options: Dict[str, object]`, `args.evaluator_options: Dict[str, object]` (validated, coerced); plan keys `executor_options`/`evaluator_options` expand to the repeatable flags via a shared map `PLAN_OPTION_FLAGS = {"executor_options": "--executor-option", "evaluator_options": "--evaluator-option"}` (public, used by `gui/launcher.py` in Task 4).

- [ ] **Step 1: Write the failing tests** (`tests/runner/test_cli_options.py`)

```python
"""Generic per-role option flags replace the runtime-named legacy flags."""
from __future__ import annotations

import unittest

from starbench.runner.cli import parse_args


class CliOptionFlagTests(unittest.TestCase):
    def test_executor_option_pairs_are_validated_and_coerced(self) -> None:
        args = parse_args(
            ["--executor-agent", "claude", "--executor-option", "max_turns=50"]
        )
        self.assertEqual(args.executor_options, {"max_turns": 50})

    def test_unknown_option_fails_at_parse_time(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--executor-agent", "gemini", "--executor-option", "max_turns=50"])

    def test_malformed_pair_fails(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--executor-agent", "claude", "--executor-option", "max_turns"])

    def test_evaluator_option_reaches_the_judge_box(self) -> None:
        args = parse_args(
            ["--evaluator-agent", "opencode", "--evaluator-option", "provider=yunwu"]
        )
        self.assertEqual(args.evaluator_options, {"provider": "yunwu"})

    def test_legacy_flags_are_gone(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(["--claude-max-turns", "5"])
```

Run: `PYTHONPATH=src python3 -m unittest tests.runner.test_cli_options -v` → FAIL (`unrecognized arguments: --executor-option ...`).

- [ ] **Step 2: cli.py — delete and add**

Delete: the `--claude-max-turns` block (237-245), the `--opencode-provider/base-url/api-key-env` blocks (246-258), the per-role loop (259-271), and the post-parse fallback loop (408-412). Add where the deleted flags were:

```python
    for role in ("executor", "evaluator"):
        parser.add_argument(
            f"--{role}-option",
            action="append",
            default=[],
            metavar="NAME=VALUE",
            help=(
                f"Runtime-specific option for the {role} agent, e.g. max_turns=50. "
                "Repeatable. Valid names are declared by the selected runtime's "
                "adapter; unknown names are rejected before any task runs."
            ),
        )
```

Add `PLAN_OPTION_FLAGS` next to `PLAN_LIST_FLAGS` (cli.py:50-58):

```python
# Plan keys holding role option boxes; each expands to repeated NAME=VALUE flags.
PLAN_OPTION_FLAGS = {
    "executor_options": "--executor-option",
    "evaluator_options": "--evaluator-option",
}
```

In `_expand_plan_argv`'s key loop (114-122), before the `PLAN_LIST_FLAGS` branch:

```python
        if key in PLAN_OPTION_FLAGS:
            for name, item in value.items():
                expanded += [PLAN_OPTION_FLAGS[key], f"{name}={item}"]
            continue
```

(JSON booleans render as Python `True`/`False` via f-string — normalize: `f"{name}={str(item).lower() if isinstance(item, bool) else item}"`.)

Post-parse (where the fallback loop was, after `resolve_runtime_spec`/adapter resolution around 390-405 so both adapters are resolvable), add:

```python
    def parse_option_pairs(pairs, flag):
        raw: Dict[str, str] = {}
        for pair in pairs:
            name, sep, value = pair.partition("=")
            if not sep or not name:
                parser.error(f"{flag} expects NAME=VALUE, got {pair!r}")
            raw[name] = value
        return raw

    evaluator_adapter = resolve(
        args.evaluator_agent, spec=args.evaluator_runtime_spec, runtimes_dir=args.runtimes_dir
    )
    try:
        args.executor_options = resolve_runtime_options(
            executor_adapter, "executor", parse_option_pairs(args.executor_option, "--executor-option")
        )
        args.evaluator_options = resolve_runtime_options(
            evaluator_adapter, "evaluator", parse_option_pairs(args.evaluator_option, "--evaluator-option")
        )
    except ValueError as error:
        parser.error(str(error))
```

Import `resolve_runtime_options` from `..adapters` (export it from `adapters/__init__.py` alongside the existing exports — check that file's export list and extend it).

- [ ] **Step 3: orchestrator.py — delete the bridge, record boxes**

Replace the Task-2 bridge with direct use: `options=args.executor_options` / `options=args.evaluator_options`. In `run_config` delete the 10 flat entries (259-268) and add in their place:

```python
        "executor_options": args.executor_options,
        "evaluator_options": args.evaluator_options,
```

- [ ] **Step 4: Sweep legacy-flag users in tests and docs**

For each rg hit from the Files list: rewrite to the generic form (`--executor-option max_turns=5`, plan key `executor_options: {...}`) preserving each test's intent. `docs/runner_reference.md`: update flag documentation. `rg -n -- "--claude-max-turns\|--opencode-provider" src/ docs/ tests/` → zero hits (excluding historical files under `docs/superpowers/` and `docs/archive/`, which stay).

- [ ] **Step 5: Full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → green. NOTE: `tests/gui/` equivalence/launcher tests may fail here if they emit legacy plan keys — those are updated in Task 4; if any fail for that reason, STOP and check: only proceed with a red suite if every failure is in `tests/gui/` files that Task 4's file list explicitly covers, and say so in the commit message body and your report. (Plan-mandated exception to the green-suite rule, scoped to this single boundary.)

- [ ] **Step 6: Commit**

```bash
git add src/starbench/runner/cli.py src/starbench/runner/orchestrator.py src/starbench/adapters/__init__.py tests/ docs/runner_reference.md
git commit -m "CLI: generic per-role option flags replace runtime-named knob flags"
```

---

### Task 4: Contracts v2 + GUI backend emitters (atomic: schema and its writers move together)

**Files:**
- Modify: `schemas/starbench/v1/run_plan.schema.json` (schema_version `[2]`; delete `claude_max_turns` at 147-150 and the 9 `*opencode*` keys at 95-122; add the two box definitions)
- Modify: `schemas/starbench/v1/profile_snapshot.schema.json` (delete `execution.claude_max_turns` at 243-246 + its spot in any `required`; add `options` to contender items and `evaluator_options` to `execution`)
- Run: `make sync-schemas` (mirrors under `src/starbench/contracts/schemas/`)
- Modify: `src/starbench/runner/cli.py` `_expand_plan_argv` (friendly v1 pre-check)
- Modify: `src/starbench/gui/launcher.py` (`_normalized_launch` 139-183: drop the 10 flat keys + `claude_max_turns` int row; emit boxes; `build_run_plan:232` emits `"schema_version": 2`; `build_run_argv` renders boxes via `PLAN_OPTION_FLAGS`)
- Modify: `src/starbench/gui/services/planning.py` (301-340: gateway dicts → `executor_options`/`evaluator_options` box keys; 323 `claude_max_turns` → contender-level options; 439-445/512-516 read from boxes)
- Modify: `src/starbench/gui/services/profile_snapshots.py` (DEFAULTS :26 and 200-202: flat key → boxes)
- Modify: `src/starbench/gui/contracts.py` (all 7 knob-field sites: replace with `executor_options: Dict[str, Union[int, str, bool]]`-shaped fields on the same TypedDicts; then `make gen-types`)
- Modify: `tests/gui/test_launcher.py`, `tests/gui/test_equivalence.py`, `tests/gui/test_experiments.py`, `tests/contracts/` plan-contract tests
- Test additions: v2 accepted / v1 rejected with the normative message; snapshot v2 shape

> Boundary note: between this task's api-types regeneration and Task 7's frontend rewire, `npm run build` is red on intermediate commits (frontend still references removed fields) — a known bisect hazard, resolved at Task 7.

**Interfaces:**
- Consumes: `PLAN_OPTION_FLAGS`, `resolve_runtime_options` (Task 3), declarations (Task 1).
- Produces: plan documents with `"schema_version": 2` and box keys; snapshot with per-contender `options` and `execution.evaluator_options`.

Box schema fragment (both schemas, exact):

```json
"executor_options": {
  "type": "object",
  "maxProperties": 32,
  "propertyNames": { "pattern": "^[a-z][a-z0-9_]*$" },
  "additionalProperties": {
    "type": ["string", "integer", "boolean", "null"],
    "maxLength": 512
  }
}
```

(`evaluator_options` identical. This is the spec's sanctioned additionalProperties exemption: shape-only at schema level, name-level enforcement lives in `resolve_runtime_options` at parse time. Note `maxLength` applies only to strings by JSON Schema semantics — that is intended.)

- [ ] **Step 1: Failing contract tests first** — locate the existing run_plan contract tests (`rg -ln "run_plan" tests/contracts/ tests/gui/`); add:

```python
    def test_v2_plan_with_boxes_validates(self) -> None:
        plan = {**self.minimal_plan(), "schema_version": 2,
                "executor_options": {"max_turns": 50}}
        validate_payload("run_plan.schema.json", plan)  # must not raise

    def test_v1_plan_is_rejected(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_payload("run_plan.schema.json", {**self.minimal_plan(), "schema_version": 1})
```

(Adapt `minimal_plan` to the file's existing helper; if none exists, build the smallest valid plan inline from the schema's `required` list.) Run → FAIL (v2 rejected today).

- [ ] **Step 2: Edit both schemas as specified, run `make sync-schemas`**

- [ ] **Step 3: cli.py friendly pre-check** — in `_expand_plan_argv` after JSON parse, before `validate_payload`:

```python
    if plan.get("schema_version") == 1:
        parser.error(
            f"--plan: {plan_path}: run plan schema_version 1 is no longer accepted. "
            'Move "claude_max_turns" into "executor_options": {"max_turns": ...} and '
            'the opencode_* keys into "executor_options"/"evaluator_options" '
            '({"provider": ..., "base_url": ..., "api_key_env": ...}), then re-emit '
            "with schema_version 2."
        )
```

- [ ] **Step 4: launcher.py emitters** — in `_normalized_launch`: remove the 10 keys from the string loop (147-155 entries) and `("claude_max_turns", 1)` from the int rows (178); add after the int loop:

```python
    for box_key in ("executor_options", "evaluator_options"):
        box = payload.get(box_key) or {}
        if not isinstance(box, dict):
            raise LaunchError(f"{box_key} must be an object of option values.")
        cleaned = {
            str(name): value
            for name, value in box.items()
            if value is not None and str(value).strip() != ""
        }
        if cleaned:
            plan[box_key] = cleaned
```

`build_run_plan`: `{"schema_version": 2, ...}`. `build_run_argv` (242-272): the mechanical `--key value` loop must special-case the boxes — mirror cli.py exactly by importing and using `PLAN_OPTION_FLAGS` next to the existing `PLAN_LIST_FLAGS` import (:19) and expansion (259-263), including the boolean lowercase normalization.

- [ ] **Step 5: planning.py emitters** — replace the flat writes: gateway dict (300-304) keys become `provider/base_url/api_key_env`. The box assembly is agent-agnostic — contender user options come from the frontend as `contender.get("options") or {}` (any runtime), wiring merges on top:

```python
            "executor_options": {
                **{k: v for k, v in (contender.get("options") or {}).items() if v not in (None, "")},
                **{k: v for k, v in gateway.items() if v},
            },
            "evaluator_options": {
                **{k: v for k, v in (shared.get("evaluator_options") or {}).items() if v not in (None, "")},
                **{k: v for k, v in (evaluator_gateway or {}).items() if v},
            },
```

with `gateway = {"provider": ..., "base_url": ..., "api_key_env": ...}` (renamed keys, values from the same sources as today's 300-304), and delete the flat `claude_max_turns`/`executor_opencode_*`/`evaluator_opencode_*` payload entries. Downstream reads at 439/445/512-516 switch to `(launch_payload.get("executor_options") or {}).get("api_key_env")` etc. Until Task 7, the frontend sends no `contender.options`/`shared.evaluator_options` — empty boxes, wiring still flows: GUI keeps working between Tasks 4 and 7 with max-turns temporarily absent from the form ONLY if the old shared field were dropped — so ALSO map the legacy form field for the transition: in `plan_experiment`, before the loop, `shared_max_turns = shared.get("claude_max_turns")`; inside the box merge for claude contenders include `{"max_turns": shared_max_turns}` when set. Mark with `# TRANSITional: removed in the frontend task`. Task 7 deletes it.
- `profile_snapshots.py`: DEFAULTS drops `"claude_max_turns": None` and gains `"evaluator_options": {}`; 200-202 becomes box-normalization (sorted-key dict compare via `_normalized_shared_value` conventions — follow the file's normalization style; per-contender `options` ride the contender entries).
- `contracts.py`: replace the 7 flat fields with `executor_options`/`evaluator_options` typed as `Dict[str, Union[int, str, bool]]` on the corresponding TypedDicts (launch payload, plan, snapshot rows — the 7 sites at 654, 760-761, 1186-1188, 1204). `make gen-types`.

- [ ] **Step 6: Update gui tests** — equivalence/launcher/experiments tests emitting or asserting flat keys now build/assert boxes. The web-search test (`test_experiments.py:752`) is knob-free — must pass untouched.

- [ ] **Step 7: Full suite green (this closes Task 3's allowed red window):**
`PYTHONPATH=src python3 -m unittest discover -s tests` → green, no exceptions.

- [ ] **Step 8: Commit**

```bash
git add schemas/ src/starbench/contracts/schemas/ src/starbench/runner/cli.py src/starbench/gui/ gui-frontend/src/lib/api-types.ts tests/
git commit -m "Contracts v2: role option boxes replace flat knob keys end to end"
```

---

### Task 5: `/api/agents` serves the option declarations

**Files:**
- Modify: `src/starbench/gui/agents.py` (`_builtin_row` + `list_agents` builtin passthrough + custom rows get `"options": []`)
- Modify: `src/starbench/gui/contracts.py` (`RuntimeOptionRow` TypedDict + `options` on `BuiltinRuntime`/`CustomRuntime`), `make gen-types`
- Test: extend `tests/gui/test_agents.py`

**Interfaces:**
- Produces: each `/api/agents` runtime row gains `"options": [{"name","type","role","surface","label","help","default","choices"}]`.

- [ ] **Step 1: Failing test** — `test_agents.py`:

```python
    def test_builtin_rows_carry_option_declarations(self) -> None:
        listing = agents.list_agents(self.runtimes_dir)
        by_id = {agent["id"]: agent for agent in listing["builtin"]}
        claude = by_id["claude"]["options"]
        self.assertEqual(claude[0]["name"], "max_turns")
        self.assertEqual(claude[0]["surface"], "user")
        self.assertEqual(
            [o["surface"] for o in by_id["opencode"]["options"]],
            ["wiring", "wiring", "wiring"],
        )
        self.assertEqual(by_id["gemini"]["options"], [])
```

- [ ] **Step 2: Implement** — `agents.py` `_builtin_row` adds:

```python
        "options": [
            {
                "name": option.name,
                "type": option.type,
                "role": option.role,
                "surface": option.surface,
                "label": option.label,
                "help": option.help,
                "default": option.default,
                "choices": list(option.choices),
            }
            for option in info.options
        ],
```

`list_agents` builtin row passes `"options": agent["options"]`; custom rows get `"options": []`. `contracts.py`: `RuntimeOptionRow` TypedDict with those 8 fields (`default: Optional[Union[int, str, bool]]`); `options: List[RuntimeOptionRow]` on both runtime TypedDicts. `make gen-types`.

- [ ] **Step 3: Full suite; commit**

```bash
git add src/starbench/gui/agents.py src/starbench/gui/contracts.py gui-frontend/src/lib/api-types.ts tests/gui/test_agents.py
git commit -m "Serve runtime option declarations through /api/agents"
```

---

### Task 6: profiles.json one-time migration

**Files:**
- Modify: `src/starbench/gui/services/profiles.py` (load path — read the whole file first; hook migration where the JSON is first parsed)
- Test: `tests/gui/test_profile_migration.py` (new)

**Interfaces:**
- Produces: `migrate_profiles_document(document: dict) -> tuple[dict, bool]` (pure; returns migrated doc + whether anything changed). Loader behaviour: if migration reports change → write `profiles.json.v1.bak` (only if not already present), then atomically rewrite `profiles.json` (use the module's existing atomic-write helper — `fsio` / whatever the file already uses for saves).

**Migration rules (pure function, exactly these):**
1. For each profile: if `shared.claude_max_turns` (or the profile's equivalent stored launch-form field — inspect the real file shape first and record it in your report) is set: for every contender with `agent == "claude"`, set `contender.options = {**contender.get("options", {}), "max_turns": int(value)}`. Delete the flat field.
2. Any stored `executor_opencode_*`/`opencode_*` per-contender or shared fields (if present in the real shape — verify with the actual `runs/profiles.json` and a saved fixture): move into the corresponding box keys (`provider/base_url/api_key_env`), delete flat fields.
3. Stamp `document["schema_version"] = 2` at top level (absent today ⇒ treated as v1).
4. Idempotence: a document already stamped 2 returns unchanged (`changed=False`).

- [ ] **Step 1: Capture a real-shaped fixture** — copy the structure (not secrets — there are none by design) of the repo's actual `runs/profiles.json` into the test as a literal, reduced to one profile with a claude + gemini contender and `claude_max_turns` set.
- [ ] **Step 2: Failing tests** — migration correct (claude contender gains `options.max_turns`, gemini contender untouched, flat key gone, version stamped), idempotent second pass, `changed=False` for already-v2, loader writes `.v1.bak` once.
- [ ] **Step 3: Implement; full suite; commit**

```bash
git add src/starbench/gui/services/profiles.py tests/gui/test_profile_migration.py
git commit -m "Migrate profiles.json to option boxes once, with backup"
```

---

### Task 7: Frontend — auto-rendered knob controls

**Files:**
- Create: `gui-frontend/src/components/RuntimeOptionFields.tsx`
- Modify: `gui-frontend/src/features/new-run/steps/AgentsStep.tsx` (contender card), `steps/SharedConfigStep.tsx` (delete Claude max-turns block 504-519; add judge knobs), `gui-frontend/src/pages/NewRun.tsx` + the feature's state module (ContenderDraft gains `options`), `steps/ReviewStep.tsx` (show non-empty boxes read-only if the review lists shared fields — match its existing style)
- Modify: `src/starbench/gui/services/planning.py` — delete the `# TRANSITional` shared_max_turns mapping from Task 4
- Verify: `npm run build`, `make gui-build`, backend suite

**Interfaces:**
- Consumes: `/api/agents` `options` declarations (Task 5 types in api-types.ts), planning's `contender.options` / `shared.evaluator_options` intake (Task 4).
- Produces: component `RuntimeOptionFields({ declarations, role, values, onChange })` rendering `surface === "user" && (role matches || role === "both")` knobs: integer→`<Input type="number">`, boolean→existing switch/checkbox component, enum→existing `Select`, string→`<Input>`; label/help from the declaration; empty string means unset (dropped by planning's cleaner).

- [ ] **Step 1: Build the component** (match the codebase's form-control idioms — copy the Input/Label/help-text pattern from SharedConfigStep's existing fields):

```tsx
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { RuntimeOptionRow } from "@/lib/api"

export function RuntimeOptionFields({
  declarations,
  role,
  values,
  onChange,
}: {
  declarations: RuntimeOptionRow[]
  role: "executor" | "evaluator"
  values: Record<string, string>
  onChange: (name: string, value: string) => void
}) {
  const visible = declarations.filter(
    (option) => option.surface === "user" && (option.role === role || option.role === "both"),
  )
  if (!visible.length) return null
  return (
    <>
      {visible.map((option) => (
        <div key={option.name} className="grid gap-1.5">
          <Label htmlFor={`opt-${option.name}`}>{option.label || option.name}</Label>
          <Input
            id={`opt-${option.name}`}
            type={option.type === "integer" ? "number" : "text"}
            value={values[option.name] ?? ""}
            onChange={(event) => onChange(option.name, event.target.value)}
          />
          {option.help ? (
            <p className="text-xs text-muted-foreground">{option.help}</p>
          ) : null}
        </div>
      ))}
    </>
  )
}
```

(Enum/boolean render paths: only add them if a declaration in the payload can exercise them — today none can (`max_turns` is the only user knob). Per YAGNI leave integer/string only, with a one-line comment noting enum/boolean arrive with the first declaring adapter. The declaration types exist so the backend contract is complete; the frontend grows cases when real knobs need them.)

- [ ] **Step 2: Wire the contender card** — in AgentsStep's contender card (the region with the ProviderModelPicker + thinking-effort controls), for each contender resolve its runtime's declarations from the agents payload (same lookup style as `thinkingEffortsFor`) and render `<RuntimeOptionFields role="executor" values={draft.options ?? {}} onChange={(name, value) => onUpdate(key, { options: { ...draft.options, [name]: value } })} />`. Extend `ContenderDraft` type with `options?: Record<string, string>`.
- [ ] **Step 3: Judge side** — SharedConfigStep: delete the Claude max-turns `div` (504-519); in the judge configuration area render `<RuntimeOptionFields role="evaluator" ...>` bound to `shared.evaluator_options`; drop the legacy `claude_max_turns` from the shared-state type/initial state.
- [ ] **Step 4: Delete planning's transitional mapping** (Task 4 marker) — `rg -n "TRANSITional" src/` → zero hits after.
- [ ] **Step 5: Verify** — `cd gui-frontend && npm run build` exit 0; `rg -n "claude_max_turns" gui-frontend/src src/starbench/gui` → zero hits; `make gui-build`; `PYTHONPATH=src python3 -m unittest discover -s tests` green.
- [ ] **Step 6: Commit**

```bash
git add gui-frontend/src src/starbench/gui/static src/starbench/gui/services/planning.py
git commit -m "Auto-render runtime option controls from adapter declarations"
```

---

## Completion gates (whole plan)

- `rg -n "claude_max_turns|opencode_provider|opencode_base_url|opencode_api_key_env" src/ gui-frontend/src tests/` → zero hits outside `docs/superpowers/`, `docs/archive/`, and the migration function/tests (which necessarily name the legacy keys).
- Full suite green; `npm run build` + `make gui-build` green.
- Spec invariants hold: byte-identical child argv for identical configs (fake-CLI tests), wiring never rendered, `api_key_env` carries names only.
- Final whole-branch review (subagent-driven-development protocol) before declaring done.
