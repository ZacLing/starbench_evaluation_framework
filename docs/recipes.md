# Recipes

Cookbook for the common changes. Each recipe names **the one file** you edit
(plus, where unavoidable, its registration line), the test to add, and the exact
command to prove it. If a recipe tells you to touch a second copy of the same
fact, that is a bug in the recipe — the fact should live in one place (see the
["Where facts live" table in DESIGN.md](DESIGN.md#where-facts-live--事实源速查表)).

Baseline both test commands must stay green and at the same count (≥ 148):

```bash
uv run --with pytest pytest tests/ -q          # or: python3 -m pytest tests/ -q
make test                                      # PYTHONPATH=src unittest discover
```

---

## 1. Add a data-driven runtime (zero code)

A headless agent CLI that fits the generic shape (build an argv, deliver the
prompt over stdin or as an arg, parse stdout as one of three formats) needs
**no Python** — just a JSON spec.

**Edit (only file):** `runtimes/<id>.json`

```json
{
  "id": "<id>",
  "label": "My Agent",
  "command": "my-agent",
  "args": ["--headless", "--json"],
  "judge_args": ["--headless", "--json", "--read-only"],
  "model_flag": "-m",
  "prompt_via": "stdin",
  "parser": "headless-json",
  "protocol": "openai",
  "base_url_env": "OPENAI_BASE_URL",
  "api_key_env": "OPENAI_API_KEY",
  "docker": { "image": "starbench-my-agent:latest", "env_passthrough": ["OPENAI_API_KEY", "OPENAI_BASE_URL"] }
}
```

- `prompt_via` ∈ `{stdin, arg}`; `parser` ∈ `{headless-json, jsonl-events, text}`
  (validated in `runner/custom_runtime.py`).
- `protocol` ∈ `{openai, anthropic, gemini, none}` drives which providers the GUI
  offers (via `provider_filter_for_protocol`); `none` = the CLI uses its own login.
- Omit `docker` to run host-local only. If you add `docker`, also add a
  `docker/<id>.Dockerfile` and a `docker-images-custom` line in the `Makefile`.
- The bundled examples are `runtimes/{qwen-code,kimi-code,trae-agent}.json`; see
  [runtimes/README.md](../runtimes/README.md) for the full field reference.

**Test to add:** none required — the JSON is data, and the generic path is
already covered by `tests/runner/test_closed_loop.py::ClosedLoopTests::test_closed_loop_with_custom_runtime`.
If you *bundle* the spec in `runtimes/` and want it guarded, add its `id` to
`tests/gui/test_agents.py::AgentRegistryTest::test_bundled_runtime_specs_are_valid_and_labeled`.

**Verify:**

```bash
python3 -c "from starbench.runner.custom_runtime import load_custom_runtime; \
print(load_custom_runtime('runtimes', '<id>').command)"
# then a real run:
starbench-run --tasks-dir examples/tasks --task demo_python_cli --runs-dir runs \
  --run-id smoke_<id> --runtimes-dir runtimes \
  --executor-agent custom:<id> --evaluator-agent codex --auth-mode env
```

---

## 2. Add a deep-adapter runtime (real code)

When the CLI needs bespoke command flags, home isolation, streaming output
normalization, or a special judge invocation, it earns an adapter class.

**Edit two files:**

1. `src/starbench/adapters/<id>.py` — a `RuntimeAdapter` subclass whose
   `info = RuntimeInfo(...)` carries **every** per-runtime fact (label, protocol,
   bin, `docker_image`, `docker_env_whitelist`, `credential_env_keys`,
   `judge_sensitive_env`, `provider_filter`, `injection`), plus `run_executor` /
   `run_judge`. Copy the closest sibling (`adapters/claude.py`) as a template.
2. `src/starbench/adapters/registry.py` — add the adapter to `_BUILTIN_ORDER`
   (**one line**).

That is the whole change. The GUI agents table, launcher/CLI choices, preflight
credential keys, judge-sensitive env set, and docker-capable set all **derive**
from `list_builtin()` — you do not touch `gui/agents.py`, `gui/library.py`,
`gui/experiments.py`, `gui/launcher.py`, or `runner/cli.py`. If `docker_capable`,
add a `docker/<id>.Dockerfile` + a `Makefile` `docker-images` line. If the
runtime introduces a *new* provider protocol/kind, extend `PROVIDER_KINDS` and
`KIND_TO_AGENT` in `gui/providers.py`.

**Test to add:** `tests/adapters/test_<id>.py` — assert the registry resolves it
and pin its `RuntimeInfo` facts:

```python
from starbench.adapters import get_builtin
def test_registers_and_pins_facts(self):
    info = get_builtin("<id>").info
    self.assertEqual(info.protocol, "openai")
    self.assertEqual(info.docker_image, "starbench-<id>:latest")
```

`tests/adapters/test_registry.py` already iterates every built-in and cross-checks
its `RuntimeInfo` against the derived GUI tables, so a mismatch fails there too.

**Verify:** `make test` and `uv run --with pytest pytest tests/adapters -q`.

---

## 3. Add or change an API field

The `/api` request/response shapes shared with the TypeScript client have one
definition; the client types are generated and committed.

**Edit (only file):** `src/starbench/gui/contracts.py` — add/rename the field on
the relevant `TypedDict` (and list a brand-new type in `GENERATED_TYPES`).

Then regenerate and use it:

```bash
make gen-types      # rewrites gui-frontend/src/lib/api-types.ts (committed)
```

The frontend consumes it via `lib/api.ts` (which re-exports the generated types).
Populate the field in whichever service builds that payload
(`gui/agents.py`, `gui/experiments.py`, `gui/providers.py`, …).

**Test to add:** none usually — `tests/gui/test_contracts.py` already fails if
`api-types.ts` is stale (you forgot `make gen-types`) or if a core type is
dropped from `GENERATED_TYPES`. Add a service-level assertion in the owning
module's test if the field carries logic.

**Verify:**

```bash
make gen-types && git diff --exit-code gui-frontend/src/lib/api-types.ts \
  || echo "regenerated — commit the result"
make test
```

---

## 4. Add a Provider preset

Built-in AI providers (endpoint + credential env var name + model catalog) are a
single list.

**Edit (only file):** `src/starbench/gui/providers.py` — append an entry to
`BUILTIN_PROVIDERS`:

```python
{
    "id": "my-gateway",
    "name": "My Gateway",
    "kind": "openai-compatible",
    "auth": "api_key",
    "base_url": "https://my-gw.example/v1",
    "anthropic_base_url": "https://my-gw.example/anthropic",  # optional
    "api_key_env": "MY_GW_API_KEY",
    "models": [],
},
```

`kind` ∈ `PROVIDER_KINDS`; `KIND_TO_AGENT` maps it to the runtime that drives it.
The console never stores keys — only the *name* of the env var. An empty
`models` list is fine; the catalog is refreshed from the provider's models API.

**Test to add:** extend `tests/gui/test_providers.py::ProviderTest::test_builtin_presets_until_saved`
with an `assertIn("my-gateway", ids)` (and any endpoint assertion).

**Verify:** `uv run --with pytest pytest tests/gui/test_providers.py -q`.

---

## 5. Change a runtime's injection channel

"Injection" = how a chosen provider's endpoint/key is wired into a runtime at
launch (the logic that used to live in the frontend `providerSettings()`). It is
a fact on the runtime, computed in one backend module.

**Edit (only file):** `src/starbench/adapters/<id>.py` — the `injection=InjectionChannel(...)`
on that adapter's `RuntimeInfo` (`kind`, `base_url_var`, `api_key_var`,
`default_api_key_env`). The channel→settings mapping itself lives in
`src/starbench/gui/injection.py`; edit that only if you are adding a **new
channel kind**, not re-pointing an existing runtime.

**Test to add / update:** `tests/gui/test_equivalence.py::ReferenceShapeEquivalenceTest`
— it asserts a reference-shaped contender (`{agent, provider_id, model}`)
produces byte-for-byte the same `argv` / `env_spec` as the explicit shape. Add
or adjust a case for the runtime you changed so the injected endpoint/key is
pinned.

**Verify:** `uv run --with pytest pytest tests/gui/test_equivalence.py -q`.

---

## 6. Add a GUI page

The console is a `stdlib` HTTP backend (`gui/server.py`) + service modules
(`gui/*.py`) + a React SPA (`gui-frontend/`). A new page threads through four
spots.

**Edit:**

1. **Service** — a new `gui/<feature>.py` (or a function on an existing service)
   that reads/writes the run directory and returns a JSON-able dict. Keep it pure
   editorial/validation logic; the run directory is the source of truth.
2. **Route** — register it in `gui/server.py`: add a branch in `_route_api_get`
   (GET) or `do_POST` / a `_handle_*` method (POST). Follow the existing
   `segments == ["providers"]` pattern.
3. **Frontend page** — add `gui-frontend/src/pages/<Feature>.tsx` and a
   `<Route path="/<feature>" element={<Feature />} />` in
   `gui-frontend/src/App.tsx`; add the nav link in the app shell.
4. **Types** — if the page needs a shared shape, define it in `gui/contracts.py`
   and run `make gen-types` (recipe 3); otherwise type it locally in `lib/api.ts`.

**Test to add:** `tests/gui/test_<feature>.py` exercising the service function
against a temp run directory (see `tests/gui/test_data.py` for the
`make_run` / temp-dir fixture pattern from `tests/helpers.py`). Route wiring is
thin; test the service, not the socket.

**Verify:**

```bash
make test                                   # backend service test
cd gui-frontend && npm install && npm run build   # SPA compiles; output committed
```

The committed SPA lives in `src/starbench/gui/static/`; rebuild it with
`make gui-build` when `gui-frontend/` sources change.

---

## 7. Add expert steps to a task (human_reference.json)

Expert steps power the **Instruction** research sweep: the console can append a
task's human expert process to the executor prompt (none / one run per step /
a chosen bundle / a full ablation). They live inside the task package.

**Edit (only file, plus its registration line):** `<task>/human_reference.json`

```json
{
  "steps": [
    {
      "step_id": "H001",
      "step_type": "structure",
      "instruction": "Organize the answer around the required headings before drafting.",
      "reasoning": "PRIVATE expert trace — never shown to the executor or the GUI."
    }
  ]
}
```

Register it in `task.json` (default name is already `human_reference.json`, so
this line is only needed for a non-default filename):

```json
{ "human_reference": "human_reference.json" }
```

- `instruction` is executor-facing and is what gets injected. `reasoning` is a
  **PRIVACY RED LINE**: the runner reads it for validation but it never crosses
  the API — `gui.data.read_human_reference_steps` is the single reasoning-free
  reader and the test suite asserts the text never leaks.
- **Where it shows in the GUI:** New run → *Prompt assistance (research)* →
  **Expert instructions**. The task card/detail shows an `expert steps ×N`
  badge; the mode cards (None/Selected steps/Traverse/Ablation) and the step
  multi-selector appear once a selected task ships steps.

**Verify:**

```bash
python3 -c "from pathlib import Path; from starbench.gui.data import read_human_reference_steps, _read_json; \
d=Path('examples/tasks/demo_instruction_reference'); \
print(read_human_reference_steps(d, _read_json(d/'task.json')))"
# and a real sweep:
starbench-run --tasks-dir examples/tasks --task demo_instruction_reference --runs-dir runs \
  --run-id smoke_instr --executor-agent codex --evaluator-agent codex --auth-mode env \
  --instruction-mode select --instruction-step H001
```

---

## 8. Add rigor requirements to a task (rigors.json)

Rigor requirements power the **Rigor** research knob: the console can restate a
few rubric-level requirements as hard requirements in the executor prompt
(prefixed with *"Ensure your answer reaches an equivalent level of rigor…"*).
It is a controlled experiment, not part of the default benchmark score, and it
does **not** multiply executor variants — the requirements are injected into
whatever run the instruction mode already produces.

**Edit (only file, plus its registration line):** `<task>/rigors.json`

```json
{
  "rigors": [
    {
      "id": "U004",
      "rubric_id": "U004",
      "requirement": "The memo must include all five exact section headings, each carrying a distinct part of the plan."
    }
  ]
}
```

Register it in `task.json` (default name is already `rigors.json`, so this line
is only needed for a non-default filename):

```json
{ "rigors": "rigors.json" }
```

- Rewrite each rubric question as an executor-facing "must" requirement; keep
  `id` equal to the `rubric_id` when you can so experiment commands stay
  readable. Every rigor field is public content — there is no private field to
  withhold. See [rigor_prompt_injection.md](rigor_prompt_injection.md) for the
  conversion rules.
- **Where it shows in the GUI:** New run → *Prompt assistance (research)* →
  **Rigor requirements** (off by default). The task card/detail shows a
  `rigor ×N` badge; turning the knob on reveals the requirement multi-selector.

**Verify:**

```bash
python3 -c "from pathlib import Path; from starbench.gui.data import read_rigors, _read_json; \
d=Path('examples/tasks/demo_instruction_reference'); \
print(read_rigors(d, _read_json(d/'task.json')))"
# and a real run:
starbench-run --tasks-dir examples/tasks --task demo_instruction_reference --runs-dir runs \
  --run-id smoke_rigor --executor-agent codex --evaluator-agent codex --auth-mode env \
  --rigor U004
```
