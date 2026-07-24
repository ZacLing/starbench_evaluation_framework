# Runtime Registry Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the adapter registry (`src/starbench/adapters/`) the single source every runtime fact actually flows from — delete the hand-maintained parallel copies in the runner CLI, orchestrator, GUI backend, and React frontend, so adding a runtime means touching the registry (plus a Dockerfile) and nothing else.

**Architecture:** `RuntimeInfo` (in `adapters/base.py`) already declares per-runtime facts and `registry.list_builtin()` already enumerates adapters in stable order. Each task below replaces one hand-copied table or name-branch with a derivation from that registry. The frontend keeps exactly one per-runtime table: the icon/visual mapping in `brand.tsx` (React components cannot come from an API); labels, notes, docker capability, and the runtime list itself move to the `/api/agents` payload, which the backend already derives from the registry.

**Tech Stack:** Python 3 stdlib (unittest, argparse, dataclasses), React + TypeScript + @tanstack/react-query, generated TS API types via `make gen-types`.

## Global Constraints

- Tests must be green after every task: `PYTHONPATH=src python3 -m unittest discover -s tests` (this is `make test`).
- Frontend must compile after every frontend change: `cd gui-frontend && npm run build`.
- After changing `src/starbench/gui/contracts.py`, run `make gen-types` and include the regenerated `gui-frontend/src/lib/api-types.ts` in the same commit.
- After any `gui-frontend/src` change is complete, run `make gui-build` and include the regenerated `src/starbench/gui/static/` output in the same commit (build output is committed in this repo).
- Do not add new runtimes, change any `RuntimeInfo` values that exist today, or alter run semantics (verdicts, aggregation, seeds).
- Do not touch `README.zh-CN.md` (unrelated untracked file in the worktree).
- Work on the current branch `codex/frontend-decomposition` in the current worktree. Commit policy: per-task commits, message style matches `git log` (imperative, no prefix tags), ending with the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.
- Language: code comments in English, matching the existing files.
- `docs/ARCHITECTURE.md` is the structure authority; nothing in this plan crosses the console/core contract boundary (§3) — all changes stay within existing contracts. `run_config.json` has no JSON schema (verified), so deriving its `*_bin` keys is safe as long as the same five keys come out.

---

### Task 1: Derive the `--<id>-bin` flags and `runtime_bins` from the registry

The runner CLI hardcodes five `--codex-bin`/`--claude-bin`/… flag definitions and the orchestrator hardcodes a five-entry `runtime_bins` dict. Both must iterate `list_builtin()` instead, so a sixth registered adapter automatically gets its flag and its bins entry (today it would `KeyError` at `ctx.bins["<id>"]`).

**Files:**
- Modify: `src/starbench/runner/cli.py:147-171` (flag definitions), `cli.py:127-137` (epilog), `cli.py:180-197` (agent help texts), `cli.py:296-305` (docker-image help)
- Modify: `src/starbench/runner/orchestrator.py:287-292` (run_config bins), `orchestrator.py:310-316` (runtime_bins)
- Test: `tests/runner/test_cli_bins.py` (new)

**Interfaces:**
- Consumes: `list_builtin()` from `starbench.adapters` (returns `List[RuntimeAdapter]`, stable order codex, claude, gemini, grok, opencode; each has `.info: RuntimeInfo` with `.id`, `.label`, `.description`, `.bin`).
- Produces: unchanged `argparse.Namespace` attributes (`args.codex_bin`, `args.claude_bin`, `args.grok_bin`, `args.gemini_bin`, `args.opencode_bin`) — argparse derives dest `<id>_bin` from flag `--<id>-bin` automatically, so downstream code and the run_config keys stay identical.

- [ ] **Step 1: Write the failing test**

Create `tests/runner/test_cli_bins.py`:

```python
"""The per-runtime --<id>-bin flags are derived from the adapter registry."""
from __future__ import annotations

import unittest

from starbench.adapters import list_builtin
from starbench.runner.cli import parse_args


class CliBinFlagsTests(unittest.TestCase):
    def test_every_builtin_gets_a_bin_flag_with_registry_default(self) -> None:
        args = parse_args([])
        for adapter in list_builtin():
            info = adapter.info
            self.assertEqual(getattr(args, f"{info.id}_bin"), info.bin, info.id)

    def test_bin_flag_override_is_respected(self) -> None:
        args = parse_args(["--gemini-bin", "/opt/custom/gemini"])
        self.assertEqual(args.gemini_bin, "/opt/custom/gemini")
```

- [ ] **Step 2: Run it — it must pass already (characterization), then keep it as the guard**

Run: `PYTHONPATH=src python3 -m unittest tests.runner.test_cli_bins -v`
Expected: PASS (the current hardcoded flags satisfy it). This test pins behavior through the refactor; it is the contract, written first.

- [ ] **Step 3: Replace the five flag definitions in `cli.py` with a registry loop**

In `src/starbench/runner/cli.py`, change the import line 27 to include `list_builtin`:

```python
from ..adapters import BUILTIN_AGENTS, DEFAULT_DOCKER_IMAGES, list_builtin, resolve
```

Delete the five `parser.add_argument("--codex-bin", ...)` … `parser.add_argument("--opencode-bin", ...)` blocks (lines 147-171) and replace with:

```python
    # One --<id>-bin flag per built-in runtime, derived from the adapter
    # registry so a new adapter gets its flag without touching this file.
    for adapter in list_builtin():
        info = adapter.info
        parser.add_argument(
            f"--{info.id}-bin",
            default=info.bin,
            help=(
                f"{info.label} executable, or a shell-like command prefix "
                f"({info.description})."
            ),
        )
```

- [ ] **Step 4: Derive the enumerating help texts in the same file**

Replace the epilog literal (lines 129-136) with:

```python
        epilog=(
            "Built-in runtimes: "
            + ", ".join(f"{a.info.id} ({a.info.label})" for a in list_builtin())
            + "; or custom:<id> for a runtime defined in --runtimes-dir. "
            "When mixing runtimes, split auth with --executor-auth-mode and "
            "--evaluator-auth-mode."
        ),
```

Replace the `--executor-agent` help (lines 183-187) with:

```python
        help=(
            "Executor runtime: one of "
            + ", ".join(sorted(BUILTIN_AGENTS))
            + ", or custom:<id> for a runtime defined in --runtimes-dir."
        ),
```

and the `--evaluator-agent` help (lines 192-196) with the same text, s/Executor/Evaluator/.

Replace the `--docker-image` help (lines 299-304) with:

```python
        help=(
            "Image used when --executor-backend docker is selected. Defaults to the "
            "runtime's own image ("
            + ", ".join(DEFAULT_DOCKER_IMAGES[a.info.id] for a in list_builtin())
            + "); custom runtimes take theirs from the spec's docker section."
        ),
```

- [ ] **Step 5: Derive `runtime_bins` and the run_config bins in `orchestrator.py`**

`src/starbench/runner/orchestrator.py` — add `list_builtin` to the existing `from ..adapters import ...` line (whatever symbols it already imports stay). Replace lines 310-316:

```python
    runtime_bins = {
        adapter.info.id: getattr(args, f"{adapter.info.id}_bin") for adapter in list_builtin()
    }
```

Replace the five run_config literals (lines 287-291, `"codex_bin": args.codex_bin,` …) with a merge in the same dict position:

```python
        **{
            f"{adapter.info.id}_bin": getattr(args, f"{adapter.info.id}_bin")
            for adapter in list_builtin()
        },
```

(`run_config.json` has no schema; the same five keys come out, only their order changes.)

- [ ] **Step 6: Run the new test and the full suite**

Run: `PYTHONPATH=src python3 -m unittest tests.runner.test_cli_bins -v` → PASS
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green.
If a test asserts on the old help strings, update its expectation to the derived text.

- [ ] **Step 7: Commit**

```bash
git add src/starbench/runner/cli.py src/starbench/runner/orchestrator.py tests/runner/test_cli_bins.py
git commit -m "Derive per-runtime bin flags and runtime_bins from the adapter registry"
```

---

### Task 2: Derive the GUI backend's label/bin tables and make the display order additive

`gui/providers.py` keeps hand-copied `AGENT_LABELS`/`AGENT_BINS` literals (the registry already owns label and bin; `gui/library.py:382` shows the derived pattern). `gui/agents.py` builds `BUILTIN_AGENTS` by iterating a fixed `_BUILTIN_DISPLAY_ORDER` tuple, so an adapter not named there silently never appears in `/api/agents`.

**Files:**
- Modify: `src/starbench/gui/providers.py:41-63`
- Modify: `src/starbench/gui/agents.py:118-125`
- Test: `tests/gui/test_agents.py` (add one test)

**Interfaces:**
- Consumes: `list_builtin()` from `starbench.adapters`.
- Produces: `agents._display_order(ids: Iterable[str]) -> List[str]` (pure function, importable by tests); `providers.AGENT_LABELS: Dict[str, str]` and `providers.AGENT_BINS: Dict[str, str]` keep their names and current contents (now derived).

- [ ] **Step 1: Write the failing test for the additive display order**

Append to `tests/gui/test_agents.py` (inside the existing test class or a new one, matching the file's style):

```python
    def test_display_order_appends_unknown_ids_alphabetically(self) -> None:
        from starbench.gui.agents import _display_order

        self.assertEqual(
            _display_order(["opencode", "zeta-agent", "claude", "alpha-agent"]),
            ["claude", "opencode", "alpha-agent", "zeta-agent"],
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_agents -v`
Expected: FAIL with `ImportError: cannot import name '_display_order'`.

- [ ] **Step 3: Implement the additive order in `gui/agents.py`**

Replace lines 118-125 of `src/starbench/gui/agents.py`:

```python
# The console's historical display order. Registry entries not named here are
# appended alphabetically, so a newly registered adapter appears without edits.
_PREFERRED_DISPLAY_ORDER = ("claude", "codex", "gemini", "grok", "opencode")
_BUILTIN_INFO = {adapter.info.id: adapter.info for adapter in list_builtin()}


def _display_order(ids) -> List[str]:
    known = [agent_id for agent_id in _PREFERRED_DISPLAY_ORDER if agent_id in ids]
    rest = sorted(set(ids) - set(_PREFERRED_DISPLAY_ORDER))
    return [*known, *rest]


BUILTIN_AGENTS: List[Dict[str, Any]] = [
    _builtin_row(_BUILTIN_INFO[agent_id]) for agent_id in _display_order(_BUILTIN_INFO)
]
```

- [ ] **Step 4: Derive the two tables in `gui/providers.py`**

Add `list_builtin` to providers.py's existing adapters import if not present (line 30 area already has `from ..adapters import ...` — extend it), then replace the `AGENT_LABELS` and `AGENT_BINS` literals (lines 49-63):

```python
# Presentation facts owned by the adapter registry (single source of truth).
AGENT_LABELS = {adapter.info.id: adapter.info.label for adapter in list_builtin()}
AGENT_BINS = {adapter.info.id: adapter.info.bin for adapter in list_builtin()}
```

Keep `KIND_TO_CLI_AGENT` as a literal — it is a policy choice (which runtime drives a provider kind by default), not a copy of a registry fact; add that sentence as its comment.

- [ ] **Step 5: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: all green (`tests/adapters/test_registry.py` and `tests/gui/test_equivalence.py` pin labels/order; they must pass unchanged — if they fail, the derivation is wrong, not the tests).

- [ ] **Step 6: Commit**

```bash
git add src/starbench/gui/providers.py src/starbench/gui/agents.py tests/gui/test_agents.py
git commit -m "Derive GUI label/bin tables from the registry; make display order additive"
```

---

### Task 3: Make web-search enforcement a `RuntimeInfo` fact

`gui/services/planning.py:461` hardcodes `agent not in ("claude", "codex")` to decide which runtimes enforce the web-search override. That capability belongs in `RuntimeInfo`, next to `thinking_channel`.

**Files:**
- Modify: `src/starbench/adapters/base.py` (RuntimeInfo, after `thinking_efforts`)
- Modify: `src/starbench/adapters/claude.py:210` area, `src/starbench/adapters/codex.py:261` area (set the flag)
- Modify: `src/starbench/gui/services/planning.py:456-466`
- Modify: `src/starbench/gui/agents.py` (`_builtin_row`, `list_agents` builtin + custom rows)
- Modify: `src/starbench/gui/contracts.py` (`BuiltinRuntime`, `CustomRuntime`), then `make gen-types`
- Test: `tests/adapters/test_registry.py` (add one test); existing planning warning tests (update if they assert the old string)

**Interfaces:**
- Consumes: nothing new.
- Produces: `RuntimeInfo.enforces_web_search: bool = False`; `/api/agents` rows gain `"enforces_web_search": bool` (builtin: from the registry; custom: always `False`).

- [ ] **Step 1: Write the failing registry test**

Append to `tests/adapters/test_registry.py`:

```python
    def test_web_search_enforcement_is_a_registry_fact(self) -> None:
        by_id = {adapter.info.id: adapter.info for adapter in list_builtin()}
        enforcing = {agent_id for agent_id, info in by_id.items() if info.enforces_web_search}
        self.assertEqual(enforcing, {"claude", "codex"})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_registry -v`
Expected: FAIL with `AttributeError: 'RuntimeInfo' object has no attribute 'enforces_web_search'`.

- [ ] **Step 3: Add the field and set it in the two adapters**

`src/starbench/adapters/base.py`, inside `RuntimeInfo` directly after the `thinking_efforts` field:

```python
    # Whether the runner can actually enforce the run-level --web-search
    # override for this runtime (Claude Code's tool allowlist, Codex's
    # --search flag). Runtimes without an enforcement hook leave web access
    # to their own tooling; planning warns instead of pretending.
    enforces_web_search: bool = False
```

`adapters/claude.py`: add `enforces_web_search=True,` after `thinking_efforts=(...)` in its `RuntimeInfo`. `adapters/codex.py`: same. Do not touch gemini/grok/opencode (default False).

- [ ] **Step 4: Derive the planning warning from the registry**

`src/starbench/gui/services/planning.py`: add `from ...adapters import list_builtin` next to the module's other starbench imports (match the existing relative-import depth: planning.py sits in `gui/services/`, so three dots reach `starbench`). Replace lines 457-466:

```python
        # The web-search override is only enforceable where the runner controls
        # web access; which runtimes those are is a registry fact
        # (RuntimeInfo.enforces_web_search), not a name list kept here.
        web_search_mode = str(shared.get("web_search_mode") or "task")
        enforcer_labels = sorted(
            adapter.info.label for adapter in list_builtin() if adapter.info.enforces_web_search
        )
        enforcer_ids = {
            adapter.info.id for adapter in list_builtin() if adapter.info.enforces_web_search
        }
        if web_search_mode != "task" and agent not in enforcer_ids:
            warnings.append(
                f"Contender {label}: the web-search override ({web_search_mode}) is not "
                f"enforceable for {agent} — its own tooling decides web access. Only "
                f"{' and '.join(enforcer_labels)} enforce it."
            )
```

(`sorted` yields "Claude Code and Codex", byte-identical to today's message.)

- [ ] **Step 5: Surface the fact in `/api/agents` and the contract**

`src/starbench/gui/agents.py` — in `_builtin_row`, after `"thinking_efforts": ...`:

```python
        "enforces_web_search": info.enforces_web_search,
```

In `list_agents`, builtin row dict, after `"thinking_efforts": agent["thinking_efforts"],`:

```python
            "enforces_web_search": agent["enforces_web_search"],
```

Custom row dict, after its `"thinking_efforts": [...]` line:

```python
                    "enforces_web_search": False,
```

`src/starbench/gui/contracts.py` — `BuiltinRuntime`: add `enforces_web_search: bool` after `thinking_efforts`. `CustomRuntime` (the `total=False` class): add `enforces_web_search: bool` after `thinking_efforts`.

Run: `make gen-types` (regenerates `gui-frontend/src/lib/api-types.ts`).

- [ ] **Step 6: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: all green. The behavioral coverage for this task already exists:
`tests/gui/test_experiments.py:752` `test_web_search_override_flag_and_unenforceable_warning`
asserts codex gets no web-search warning and gemini gets exactly one containing
"not enforceable". It must pass **unchanged** — the warning string is preserved
byte-for-byte by the `sorted(...)` join. If it fails, fix the implementation,
not the test.

- [ ] **Step 7: Commit**

```bash
git add src/starbench/adapters/base.py src/starbench/adapters/claude.py src/starbench/adapters/codex.py \
  src/starbench/gui/services/planning.py src/starbench/gui/agents.py src/starbench/gui/contracts.py \
  gui-frontend/src/lib/api-types.ts tests/
git commit -m "Make web-search enforcement a RuntimeInfo fact"
```

---

### Task 4: Frontend reads runtimes from `/api/agents`; delete the parallel copies

The New Run selectors build their built-in list from a hardcoded `BUILTIN_RUNTIMES` array, and ten files label agents through hand-copied `AGENT_LABELS`/`AGENT_NOTES` maps in `brand.tsx`. `/api/agents` already carries id, label, note, docker_capable for every runtime. Only the icon/visual mappings legitimately stay in the frontend.

**Files:**
- Create: `gui-frontend/src/hooks/useAgentCatalog.ts`
- Modify: `gui-frontend/src/features/new-run/constants.ts` (delete `BUILTIN_RUNTIMES`)
- Modify: `gui-frontend/src/components/brand.tsx` (delete `AGENT_LABELS`, `AGENT_NOTES`; keep `AgentIcon`, `FamilyIcon`, `AGENT_TO_FAMILY`, `CUSTOM_ICONS`)
- Modify: `gui-frontend/src/pages/NewRun.tsx` (runtimeLabel, dockerCapable, pass builtin list down)
- Modify: `gui-frontend/src/features/new-run/steps/AgentsStep.tsx`, `steps/SharedConfigStep.tsx`, `steps/ReviewStep.tsx`
- Modify: `gui-frontend/src/pages/Runs.tsx`, `RunDetail.tsx`, `Compare.tsx`, `Coverage.tsx`, `Dashboard.tsx`, `Providers.tsx`, `gui-frontend/src/features/run-inspector/RunRail.tsx`

**Interfaces:**
- Consumes: `api.agents` (`/api/agents`, react-query key `["agents"]` — the same key NewRun already uses, so the cache is shared and no extra requests happen).
- Produces: hook `useAgentCatalog(): { builtin: BuiltinRuntime[]; custom: CustomRuntime[]; agentLabel(id: string): string; agentNote(id: string): string; dockerCapableFor(id: string): boolean; builtinIds: string[] }`.

- [ ] **Step 1: Create the hook**

`gui-frontend/src/hooks/useAgentCatalog.ts`:

```tsx
import { useCallback, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"

import { api, type BuiltinRuntime, type CustomRuntime } from "@/lib/api"

/* One catalog for "what runtimes exist and what are they called" — fed by
   /api/agents, which the backend derives from the adapter registry. The only
   per-runtime knowledge that stays hardcoded in the frontend is the icon
   mapping in components/brand.tsx (React components cannot travel over JSON).
   While the query is loading, labels fall back to the raw id (honest absence,
   never an invented name). */
export function useAgentCatalog() {
  const query = useQuery({ queryKey: ["agents"], queryFn: api.agents })
  const builtin = useMemo(() => query.data?.builtin ?? [], [query.data])
  const custom = useMemo(
    () => (query.data?.custom ?? []).filter((agent) => !agent.error),
    [query.data],
  )
  const byId = useMemo(() => {
    const map: Record<string, { label: string; note: string; dockerCapable: boolean }> = {}
    for (const agent of builtin)
      map[agent.id] = { label: agent.label, note: agent.note, dockerCapable: agent.docker_capable }
    for (const agent of custom)
      map[agent.id] = {
        label: agent.label ?? agent.spec_id,
        note: agent.description ?? "",
        dockerCapable: Boolean(agent.docker_capable),
      }
    return map
  }, [builtin, custom])
  const agentLabel = useCallback((id: string) => byId[id]?.label ?? id, [byId])
  const agentNote = useCallback((id: string) => byId[id]?.note ?? "", [byId])
  const dockerCapableFor = useCallback(
    (id: string) => byId[id]?.dockerCapable ?? !id.startsWith("custom:"),
    [byId],
  )
  const builtinIds = useMemo(() => builtin.map((agent) => agent.id), [builtin])
  return { query, builtin, custom, agentLabel, agentNote, dockerCapableFor, builtinIds }
}
```

If `@/lib/api` does not re-export the `BuiltinRuntime`/`CustomRuntime` types, import them from `@/lib/api-types` instead — check how `AgentsStep.tsx:21` imports them and match it.

- [ ] **Step 2: Delete the copies and let the compiler enumerate every consumer**

- `constants.ts`: delete the `BUILTIN_RUNTIMES` export (line 15).
- `brand.tsx`: delete the `AGENT_LABELS` and `AGENT_NOTES` exports (lines 69-83). Keep `AGENT_TO_FAMILY`, `AgentIcon`, `FamilyIcon`, `CUSTOM_ICONS` and add this comment above `AGENT_TO_FAMILY`:

```tsx
/* Icon/visual mappings are the frontend's only per-runtime tables — everything
   else (labels, notes, capability facts, the runtime list itself) comes from
   /api/agents via useAgentCatalog. */
```

Run: `cd gui-frontend && npx tsc -b --noEmit 2>&1 | head -60` (or `npm run build`)
Expected: compile errors at every remaining consumer — that list is Step 3's exact worklist. Do not proceed with a green build and remaining `AGENT_LABELS` references.

- [ ] **Step 3: Rewire the New Run wizard (the only structural consumers)**

`NewRun.tsx` — it already holds `agentsQuery`. Add `const builtinRuntimes = agentsQuery.data?.builtin ?? []` and a lookup `const builtinById = useMemo(...Record<string, BuiltinRuntime>...)`. Then:

- `runtimeLabel` (lines 70-77): replace the `AGENT_LABELS[runtime] ?? runtime` fallback with `builtinById[runtime]?.label ?? runtime` (custom branch unchanged).
- `dockerCapable` (lines 78-84): replace the hardcoded `: true` for builtins with `: (builtinById[runtime]?.docker_capable ?? true)` (`?? true` keeps today's behavior during the initial load; the API value wins once present).
- Pass `builtinRuntimes` down to `StepContenders` and `SharedConfigStep` as a new prop.

`steps/AgentsStep.tsx` — add `builtinRuntimes: BuiltinRuntime[]` to `StepContenders` props; build the options from it (replaces the `BUILTIN_RUNTIMES.map` at lines 121-127):

```tsx
  const options: RuntimeOption[] = [
    ...builtinRuntimes.map((agent) => ({
      id: agent.id,
      label: agent.label,
      note: agent.note,
      cliMissing: agent.cli.present === false,
    })),
    ...customRuntimes.map((agent) => ({
      id: agent.id,
      label: agent.label ?? agent.spec_id,
      note: agent.description || (agent.command ?? ""),
      icon: agent.icon,
      protocol: agent.protocol ?? "none",
      cliMissing: agent.cli ? !agent.cli.present : false,
      localOnly: !agent.docker_capable,
    })),
  ]
```

(The custom half is today's code, kept verbatim.)

If `builtinCliPresent` has no other consumer after this, remove the prop and its `useMemo` in NewRun.tsx; if it does, leave it.

`steps/SharedConfigStep.tsx` — add the same `builtinRuntimes` prop; the judge `Select` at lines 213-220 maps over it:

```tsx
                      {builtinRuntimes.map((agent) => (
                        <SelectItem key={agent.id} value={agent.id}>
                          <span className="flex items-center gap-2">
                            <AgentIcon agent={agent.id} size={14} />
                            {agent.label}
                          </span>
                        </SelectItem>
                      ))}
```

- [ ] **Step 4: Rewire the display pages via the hook**

For each remaining compile error (`Runs.tsx`, `RunDetail.tsx`, `Compare.tsx`, `Coverage.tsx`, `Dashboard.tsx`, `Providers.tsx`, `RunRail.tsx`, `ReviewStep.tsx`), apply the same mechanical transformation inside the component:

```tsx
import { useAgentCatalog } from "@/hooks/useAgentCatalog"
// inside the component:
const { agentLabel, agentNote } = useAgentCatalog()
```

- `AGENT_LABELS[x]` / `AGENT_LABELS[x] ?? x` → `agentLabel(x)`
- `AGENT_NOTES[x]` → `agentNote(x)`
- `RunDetail.tsx:911` `const RUNTIME_KEY_PREFIXES = Object.keys(AGENT_LABELS)` (module scope) → delete; inside the component use `const { builtinIds } = useAgentCatalog()` and replace `RUNTIME_KEY_PREFIXES.some(...)` at line 1085 with `builtinIds.some(...)`. While the catalog is loading `builtinIds` is `[]`, so runtime-prefixed config keys show unfiltered for a moment and settle once loaded — acceptable, honest.
- If a usage sits in a helper function outside a component, lift the label lookup to the component and pass the resolved string down (hooks only run in components).

- [ ] **Step 5: Build, rebuild static, verify**

Run: `cd gui-frontend && npm run build` → exits 0.
Run: `rg -n "AGENT_LABELS|AGENT_NOTES|BUILTIN_RUNTIMES" gui-frontend/src` → zero hits.
Run: `make gui-build` → regenerates `src/starbench/gui/static/`.
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green (backend untouched, still run it).

- [ ] **Step 6: Commit**

```bash
git add gui-frontend/src src/starbench/gui/static
git commit -m "Front end reads the runtime catalog from /api/agents; keep only icon maps local"
```

---

### Task 5: Move the Claude executor tool allowlist into the Claude adapter

`runner/prompts.py:33-43` holds `CLAUDE_EXECUTOR_BASE_TOOLS`, `CLAUDE_EXECUTOR_WEB_TOOLS`, and `claude_executor_allowed_tools()` — Claude-specific policy living in the shared prompts module.

**Files:**
- Modify: `src/starbench/runner/prompts.py` (delete the three), `src/starbench/adapters/claude.py` (add them), plus every importer found by `rg -n "claude_executor_allowed_tools|CLAUDE_EXECUTOR" src/ tests/` (today: `src/starbench/runner/run_benchmark.py`, `tests/runner/test_regressions.py`).

**Interfaces:**
- Produces: `starbench.adapters.claude.claude_executor_allowed_tools(allow_web_search: bool) -> str` — same signature, same output strings.

- [ ] **Step 1: Move the code**

Cut from `prompts.py` (lines 33-34 and 40-43), paste into `adapters/claude.py` above the `ClaudeAdapter` class, verbatim:

```python
CLAUDE_EXECUTOR_BASE_TOOLS = "Read,Write,Edit,MultiEdit,Bash,Glob,Grep,LS"
CLAUDE_EXECUTOR_WEB_TOOLS = "WebSearch,WebFetch"


def claude_executor_allowed_tools(allow_web_search: bool) -> str:
    if allow_web_search:
        return f"{CLAUDE_EXECUTOR_BASE_TOOLS},{CLAUDE_EXECUTOR_WEB_TOOLS}"
    return CLAUDE_EXECUTOR_BASE_TOOLS
```

Remove the now-unused import of `claude_executor_allowed_tools` from claude.py's `from ..runner.prompts import (...)` block (it becomes module-local).

- [ ] **Step 2: Update every importer**

`rg -n "claude_executor_allowed_tools|CLAUDE_EXECUTOR" src/ tests/` — update each hit to import from `starbench.adapters.claude`. `run_benchmark.py` is a compat re-export shim: keep its re-export working, just change the source module.

- [ ] **Step 3: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green.
Run: `rg -n "CLAUDE_EXECUTOR" src/starbench/runner/` → zero hits (prompts.py is Claude-free).

- [ ] **Step 4: Commit**

```bash
git add src/starbench/runner/prompts.py src/starbench/adapters/claude.py src/starbench/runner/run_benchmark.py tests/
git commit -m "Move the Claude executor tool allowlist into the Claude adapter"
```

---

### Task 6: Rename the codex-era fossils (`run_codex_process`, `codex_home`)

Generic infrastructure still carries Codex's name: the process runner every adapter calls is `run_codex_process`, and the per-task home directory every runtime uses is `paths["codex_home"]` / on-disk `codex_home`. Rename the generic identifiers; leave everything that is genuinely Codex-specific (`CODEX_HOME` env var handling in the codex adapter and `gui/providers.py`, `$CODEX_HOME/skills` prompt text) untouched.

**Rename map (generic → new):**
- `run_codex_process` → `run_cli_process` (defined in `src/starbench/execution/process.py`; imported by all six adapter modules and re-exported by `src/starbench/runner/codex_process.py`)
- `paths["codex_home"]` dict key and the on-disk directory `task_root / "codex_home"` → `"agent_home"` / `task_root / "agent_home"` (created in `src/starbench/runner/executor.py:164-195`)

**Explicitly NOT renamed:** the `CODEX_HOME` environment variable (the codex CLI's real env var — the codex adapter keeps setting it, now pointing at the renamed dir), `runner/codex_process.py` the module (it is the historical compat surface tests import; it keeps working, contents re-export the new names), docs references to the codex CLI's own `$CODEX_HOME`.

**Files:**
- Modify: `src/starbench/execution/process.py`, all of `src/starbench/adapters/*.py`, `src/starbench/runner/executor.py`, `src/starbench/runner/judge.py`, `src/starbench/runner/codex_process.py`, tests under `tests/` that reference either name, docs `docs/docker.md`, `docs/executor_skills.md`, `docs/use_skills_in_eval.md` where they describe the run directory layout (not where they describe the codex CLI's `$CODEX_HOME`).

- [ ] **Step 1: Verify nothing reads `codex_home` back from run artifacts**

Run: `rg -n "codex_home" src/starbench/gui/read_models/ src/starbench/gui/services/ schemas/` → expected zero hits (providers.py's `_codex_home` is the operator's own `~/.codex`, different concept, untouched). If a read-model hit appears, STOP and report — the disk rename would then need a compatibility read, and the task must shrink to code-identifier-only.

- [ ] **Step 2: Rename `run_codex_process` → `run_cli_process`**

In `execution/process.py` rename the function. Then `rg -ln "run_codex_process" src/ tests/` and update every import/call. In `runner/codex_process.py` keep a compat alias so the historical surface stays whole:

```python
from ..execution.process import run_cli_process
run_codex_process = run_cli_process
```

(matching however that shim currently re-exports; extend, don't restructure).

- [ ] **Step 3: Rename the paths key and directory**

In `executor.py:164-195` rename the local, the mkdir target, and the dict key to `agent_home`. Then `rg -n '"codex_home"|codex_home' src/ tests/` and update every generic hit (adapter `paths["codex_home"]` subscripts, judge home derivations, test path assertions). Leave `CODEX_HOME` env-var lines alone.

- [ ] **Step 4: Update the three docs where they describe the run layout**

`rg -n "codex_home" docs/docker.md docs/executor_skills.md docs/use_skills_in_eval.md` — rewrite layout mentions to `agent_home`; keep codex-CLI `$CODEX_HOME` prose.

- [ ] **Step 5: Full suite + zero-hit checks**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green.
Run: `rg -nw "run_codex_process" src/ | rg -v "codex_process.py"` → zero hits.
Run: `rg -n '"codex_home"' src/ tests/` → zero hits.

- [ ] **Step 6: Commit**

```bash
git add -A src tests docs
git commit -m "Rename codex-era fossils: run_cli_process and agent_home"
```

---

## Deferred (out of scope for this plan)

- **Knob namespacing (the "C surgery"):** moving `claude_max_turns` / `opencode_provider|base_url|api_key_env` out of `ExecutorContext`/`JudgeContext`/plan schema into a per-runtime `runtime_options` namespace with adapter-declared knob schemas and auto-rendered GUI controls. Contract change (run_plan + profile_snapshot v-bump); needs its own design round.
- Runtime-specific UI branches (`judgeRuntime === "codex"` notes, Claude max-turns input) — they move when the knob namespace lands.
- CLI login-status probes (`providers.py CLI_STATUS_COMMANDS`) as an adapter-declared capability.
- `INSTALL_SPECS` (npm package per runtime) staying console-owned is acceptable: a missing entry degrades to "not installable", no breakage.
