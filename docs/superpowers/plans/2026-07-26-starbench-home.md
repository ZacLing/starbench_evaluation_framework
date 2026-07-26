# StarBench Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `STARBENCH_HOME` (default `~/.starbench`) the single data root for tasks, runs, custom runtimes, and skills; retire the multi-library/registration concepts; promote the `batch` label from console supervision file to runner fact.

**Architecture:** A tiny core module (`src/starbench/home.py`) answers "where is home?"; the two process entrypoints (`runner/cli.py`, `gui/server.py`) resolve it exactly once and pass explicit paths inward. Core code and all existing tests keep explicit path injection and never read the environment. Spec: `docs/superpowers/specs/2026-07-26-starbench-home-design.md` — on conflict the spec wins.

**Tech Stack:** Python 3 stdlib (argparse, dataclasses, unittest), JSON-Schema whitelist validator, React + TypeScript, generated TS types via `make gen-types`.

## Global Constraints

- Tests green after every task: `PYTHONPATH=src python3 -m unittest discover -s tests` (= `make test`).
- Frontend compiles after every frontend change: `cd gui-frontend && npm run build`.
- After changing `src/starbench/gui/contracts.py`: run `make gen-types`, commit the regenerated `gui-frontend/src/lib/api-types.ts` in the same commit.
- After finishing `gui-frontend/src` changes: run `make gui-build`, commit regenerated `src/starbench/gui/static/` in the same commit.
- After changing `schemas/starbench/`: run `make sync-schemas`, commit the mirrored copy under `src/starbench/contracts/schemas/` in the same commit (an equality test guards this).
- Resolution discipline: `os.environ` is read only in `src/starbench/home.py` helpers called from the two entrypoints. Core modules keep explicit path parameters.
- No test may touch the real `~/.starbench`; tests pass an explicit `environ=` mapping or explicit paths.
- Commit style: imperative single line, no prefix tags, trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Do not touch `README.zh-CN.md` or `.impeccable/` (unrelated untracked entries).

---

### Task 1: The home resolution module

**Files:**
- Create: `src/starbench/home.py`
- Test: `tests/test_home.py` (new; `tests/` root already contains `helpers.py`, discovery picks up top-level test modules)

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces: `ENV_VAR: str = "STARBENCH_HOME"`; `resolve_home(environ: Mapping[str, str] | None = None) -> Path` (raises `ValueError` on a relative env value); `HomeLayout` frozen dataclass with `root: Path` and properties `tasks`, `runs`, `runtimes`, `skills` (each `root / <name>`). Tasks 2–3 import exactly these names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_home.py`:

```python
"""STARBENCH_HOME resolution: env decides where data lives, never the cwd."""
from __future__ import annotations

import unittest
from pathlib import Path

from starbench.home import ENV_VAR, HomeLayout, resolve_home


class ResolveHomeTests(unittest.TestCase):
    def test_default_is_dot_starbench_under_user_home(self) -> None:
        self.assertEqual(resolve_home(environ={}), Path.home() / ".starbench")

    def test_env_var_relocates_home(self) -> None:
        self.assertEqual(
            resolve_home(environ={ENV_VAR: "/tmp/sb-exp"}), Path("/tmp/sb-exp")
        )

    def test_tilde_is_expanded(self) -> None:
        self.assertEqual(
            resolve_home(environ={ENV_VAR: "~/bench-home"}),
            Path.home() / "bench-home",
        )

    def test_blank_env_value_falls_back_to_default(self) -> None:
        self.assertEqual(resolve_home(environ={ENV_VAR: "  "}), Path.home() / ".starbench")

    def test_relative_env_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_home(environ={ENV_VAR: "relative/home"})


class HomeLayoutTests(unittest.TestCase):
    def test_layout_paths(self) -> None:
        layout = HomeLayout(Path("/data/sb"))
        self.assertEqual(layout.tasks, Path("/data/sb/tasks"))
        self.assertEqual(layout.runs, Path("/data/sb/runs"))
        self.assertEqual(layout.runtimes, Path("/data/sb/runtimes"))
        self.assertEqual(layout.skills, Path("/data/sb/skills"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_home -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'starbench.home'`.

- [ ] **Step 3: Implement the module**

Create `src/starbench/home.py`:

```python
"""STARBENCH_HOME resolution — the one place the environment decides where data lives.

Precedence is decided at each entrypoint, not here: explicit CLI flag >
$STARBENCH_HOME > ~/.starbench. This module only answers "where is home?".
Entrypoints resolve it once and pass explicit paths inward, so core code and
tests never read the environment. Isolation is an explicit act (point
STARBENCH_HOME elsewhere), never a side effect of the working directory —
which is why a relative env value is an error, not a convenience.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

ENV_VAR = "STARBENCH_HOME"


def resolve_home(environ: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if environ is None else environ
    raw = str(env.get(ENV_VAR) or "").strip()
    if not raw:
        return Path.home() / ".starbench"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(
            f"{ENV_VAR} must be an absolute path, got {raw!r}: data location "
            "must not depend on the working directory."
        )
    return path


@dataclass(frozen=True)
class HomeLayout:
    """Canonical directory layout inside a StarBench home."""

    root: Path

    @property
    def tasks(self) -> Path:
        return self.root / "tasks"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def runtimes(self) -> Path:
        return self.root / "runtimes"

    @property
    def skills(self) -> Path:
        return self.root / "skills"
```

- [ ] **Step 4: Run the test again**

Run: `PYTHONPATH=src python3 -m unittest tests.test_home -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Full suite, then commit**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green.

```bash
git add src/starbench/home.py tests/test_home.py
git commit -m "Add the STARBENCH_HOME resolution module"
```

---

### Task 2: Runner CLI defaults come from home

**Files:**
- Modify: `src/starbench/runner/cli.py` (constants block at ~line 46, the four dir flags, post-parse resolution near `args.tasks_dir.resolve()`)
- Modify: `src/starbench/runner/run_benchmark.py` (compat re-exports of the deleted constants)
- Test: `tests/runner/test_cli_home.py` (new)

**Interfaces:**
- Consumes: `resolve_home`, `HomeLayout` from `starbench.home`.
- Produces: `parse_args` accepts `environ: Mapping[str, str] | None = None` keyword (default reads process env at the entrypoint only) so tests inject a fake environment; `args.tasks_dir/runs_dir/executor_skills_dir/runtimes_dir` resolve to `home.<name>` when their flags are omitted.

- [ ] **Step 1: Write the failing test**

Create `tests/runner/test_cli_home.py`:

```python
"""CLI dir defaults resolve from STARBENCH_HOME; flags stay the top override."""
from __future__ import annotations

import unittest
from pathlib import Path

from starbench.runner.cli import parse_args

_BASE = ["--executor-agent", "codex"]


class CliHomeDefaultTests(unittest.TestCase):
    def test_omitted_dir_flags_resolve_under_home(self) -> None:
        args = parse_args(_BASE, environ={"STARBENCH_HOME": "/tmp/sb-home"})
        self.assertEqual(args.tasks_dir, Path("/tmp/sb-home/tasks"))
        self.assertEqual(args.runs_dir, Path("/tmp/sb-home/runs"))
        self.assertEqual(args.executor_skill_root, Path("/tmp/sb-home/skills"))
        self.assertEqual(args.runtimes_dir, Path("/tmp/sb-home/runtimes"))

    def test_explicit_flag_beats_home(self) -> None:
        args = parse_args(
            [*_BASE, "--tasks-dir", "/elsewhere/tasks"],
            environ={"STARBENCH_HOME": "/tmp/sb-home"},
        )
        self.assertEqual(args.tasks_dir, Path("/elsewhere/tasks"))
        self.assertEqual(args.runs_dir, Path("/tmp/sb-home/runs"))

    def test_relative_home_is_a_parser_error(self) -> None:
        with self.assertRaises(SystemExit):
            parse_args(_BASE, environ={"STARBENCH_HOME": "not/absolute"})


if __name__ == "__main__":
    unittest.main()
```

Note: if `parse_args(_BASE)` needs more required flags to get past validation, extend `_BASE` minimally until the parser returns — assert only on the four dir attributes.

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.runner.test_cli_home -v`
Expected: FAIL — `parse_args() got an unexpected keyword argument 'environ'`.

- [ ] **Step 3: Rewire cli.py**

1. Locate the constants: `rg -n "PROJECT_ROOT|DEFAULT_(TASKS|RUNS|EXECUTOR_SKILLS|RUNTIMES)_DIR" src/starbench/runner/cli.py src/starbench/runner/run_benchmark.py`.
2. Delete from `cli.py` the block (~lines 46–50):

```python
PROJECT_ROOT = Path.cwd()
DEFAULT_TASKS_DIR = PROJECT_ROOT / "tasks"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_EXECUTOR_SKILLS_DIR = PROJECT_ROOT / "executor_skills"
DEFAULT_RUNTIMES_DIR = PROJECT_ROOT / "runtimes"
```

3. Add to the import block: `from ..home import HomeLayout, resolve_home`.
4. Change the four `parser.add_argument` defaults to `default=None` and state the real default in help, e.g. for tasks:

```python
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=None,
        help="Task package library. Defaults to $STARBENCH_HOME/tasks (~/.starbench/tasks).",
    )
```

(same pattern for `--runs-dir` → `runs`, `--executor-skill-root` → `skills`, `--runtimes-dir` → `runtimes`).

5. Give `parse_args` the environ parameter and resolve once, immediately after `args = parser.parse_args(...)` and before any use of the dir attributes:

```python
def parse_args(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> argparse.Namespace:
```

```python
    try:
        home = HomeLayout(resolve_home(environ))
    except ValueError as exc:
        parser.error(str(exc))
    if args.tasks_dir is None:
        args.tasks_dir = home.tasks
    if args.runs_dir is None:
        args.runs_dir = home.runs
    if args.executor_skill_root is None:
        args.executor_skill_root = home.skills
    if args.runtimes_dir is None:
        args.runtimes_dir = home.runtimes
```

(`Mapping` joins the existing `typing` import.)

6. `run_benchmark.py` re-exports: replace each deleted-constant re-export with the home-derived equivalent or drop it — run `rg -n "DEFAULT_TASKS_DIR|DEFAULT_RUNS_DIR" src/ tests/` and update every hit so nothing imports the deleted names.

- [ ] **Step 4: Run the new test and the full suite**

Run: `PYTHONPATH=src python3 -m unittest tests.runner.test_cli_home -v` → PASS.
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green. Existing CLI tests pass because they always supply explicit dirs or only parse flags; any test that asserted the old cwd defaults must be updated to inject `environ={"STARBENCH_HOME": <tmp>}`.

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/cli.py src/starbench/runner/run_benchmark.py tests/runner/test_cli_home.py
git commit -m "Resolve runner CLI dir defaults from STARBENCH_HOME"
```

---

### Task 3: Console server defaults come from home

**Files:**
- Modify: `src/starbench/gui/server.py` (`build_state` ~lines 368–387, `main` argparse defaults ~lines 397–421)
- Test: `tests/gui/test_server_home.py` (new)

**Interfaces:**
- Consumes: `resolve_home`, `HomeLayout` from `starbench.home`.
- Produces: `build_state(runs_dir=None, tasks_dirs=None, cwd=None, runtimes_dir=None, skills_dir=None, environ=None)` — every `None` fills from home; explicit arguments always win. `ConsoleState` signature unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/gui/test_server_home.py`:

```python
"""build_state fills every omitted location from STARBENCH_HOME."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starbench.gui.server import build_state


class BuildStateHomeTests(unittest.TestCase):
    def test_omitted_dirs_fill_from_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = build_state(environ={"STARBENCH_HOME": tmp})
            home = Path(tmp)
            self.assertEqual(state.runs_dir, home / "runs")
            self.assertEqual(state.tasks_dirs, [home / "tasks"])
            self.assertEqual(state.runtimes_dir, home / "runtimes")
            self.assertEqual(state.skills_dir, home / "skills")

    def test_explicit_dirs_beat_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            explicit = Path(tmp) / "elsewhere-runs"
            state = build_state(
                runs_dir=explicit, environ={"STARBENCH_HOME": tmp}
            )
            self.assertEqual(state.runs_dir, explicit.resolve())
            self.assertEqual(state.tasks_dirs, [Path(tmp) / "tasks"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_server_home -v`
Expected: FAIL — `build_state() got an unexpected keyword argument 'environ'` (and `runs_dir` is currently positional-required).

- [ ] **Step 3: Rewire build_state and main**

`build_state` becomes (replacing the current body's default branches; keep the resolve/absolutize logic for explicit values):

```python
def build_state(
    runs_dir: Optional[Path] = None,
    tasks_dirs: Optional[Sequence[Path]] = None,
    cwd: Optional[Path] = None,
    runtimes_dir: Optional[Path] = None,
    skills_dir: Optional[Path] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> ConsoleState:
    cwd = (cwd or Path.cwd()).resolve()
    home = HomeLayout(resolve_home(environ))
    if runs_dir is None:
        runs_dir = home.runs
    if tasks_dirs is None:
        tasks_dirs = [home.tasks]
    if runtimes_dir is None:
        runtimes_dir = home.runtimes
    if skills_dir is None:
        skills_dir = home.skills
    ...
```

The remainder (relative-flag absolutization against `cwd`, `.resolve()` calls, `ConsoleState(...)` construction) stays as-is — home paths are already absolute. In `main`, change the argparse defaults so omission means "let build_state decide": `--runs-dir` default `None` (was `Path("runs")`); `--runtimes-dir` / `--skills-dir` already default `None`; `--tasks-dir` already appends into `None`-or-list. Pass them through unchanged: `build_state(args.runs_dir, args.tasks_dir, runtimes_dir=args.runtimes_dir, skills_dir=args.skills_dir)`. Relative `STARBENCH_HOME` handling in `main`: wrap `build_state(...)` in `try/except ValueError` → `parser.error(str(exc))`. Update the startup print to make the root explicit: `print(f"StarBench Console serving {state.runs_dir}")` already shows the resolved path — no change needed. Add `Mapping`/`HomeLayout`/`resolve_home` imports.

- [ ] **Step 4: Run the new test and the full suite**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_server_home -v` → PASS.
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green (existing gui tests construct `build_state(runs_dir, tasks_dirs, cwd)` positionally with explicit paths — signature stays compatible).

- [ ] **Step 5: Commit**

```bash
git add src/starbench/gui/server.py tests/gui/test_server_home.py
git commit -m "Resolve console server dir defaults from STARBENCH_HOME"
```

---

### Task 4: `batch` becomes a runner fact

**Files:**
- Modify: `schemas/starbench/v1/run_plan.schema.json` (add optional `batch` after `run_id`), then `make sync-schemas`
- Modify: `src/starbench/runner/cli.py` (add `--batch`, validate with `parse_safe_id`)
- Modify: `src/starbench/runner/orchestrator.py:246` (materialize into `run_config`)
- Modify: `src/starbench/gui/services/console.py:263` area (launch payload carries batch)
- Modify: `src/starbench/gui/read_models/runs.py:211-218` (`_batch_marker` fallback chain)
- Test: `tests/gui/test_batch_marker.py` (new), `tests/runner/test_run_plan.py` (one case)

**Interfaces:**
- Consumes: `parse_safe_id` (already imported in cli.py), `_read_json`/`RUN_STATE_FILENAME` (already imported in runs.py).
- Produces: `run_plan` optional property `batch` (string, SafeId pattern); `run_config.json` key `batch` (string or null); `_batch_marker` unchanged signature, new precedence run_config → legacy run_state.

- [ ] **Step 1: Write the failing read-model test**

Create `tests/gui/test_batch_marker.py`:

```python
"""_batch_marker precedence: run_config fact first, legacy run_state fallback."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.gui.read_models.runs import _batch_marker


def _write(root: Path, name: str, payload: dict) -> None:
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


class BatchMarkerTests(unittest.TestCase):
    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_run_config_batch_wins(self) -> None:
        root = self._root()
        _write(root, "run_config.json", {"batch": "exp_a"})
        _write(root, "run_state.json", {"batch": "stale_b"})
        self.assertEqual(_batch_marker(root), "exp_a")

    def test_legacy_run_state_fallback(self) -> None:
        root = self._root()
        _write(root, "run_config.json", {"seed": 1})
        _write(root, "run_state.json", {"batch": "legacy_c"})
        self.assertEqual(_batch_marker(root), "legacy_c")

    def test_run_config_only(self) -> None:
        root = self._root()
        _write(root, "run_config.json", {"batch": "exp_d"})
        self.assertEqual(_batch_marker(root), "exp_d")

    def test_neither_yields_none(self) -> None:
        self.assertIsNone(_batch_marker(self._root()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_batch_marker -v`
Expected: `test_run_config_batch_wins` and `test_run_config_only` FAIL (current code reads only run_state).

- [ ] **Step 3: Implement the chain end to end**

1. Schema — in `schemas/starbench/v1/run_plan.schema.json`, insert directly after the `run_id` property block:

```json
    "batch": {
      "type": "string",
      "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$",
      "maxLength": 128
    },
```

Run `make sync-schemas` (mirrors into `src/starbench/contracts/schemas/`). Optional property = additive change, `schema_version` stays 2.

2. CLI — next to the other run-identity flags in `cli.py`:

```python
    parser.add_argument(
        "--batch",
        default=None,
        help=(
            "Experiment batch label recorded in run_config.json; runs launched "
            "together share it and the console groups/compares them by it."
        ),
    )
```

and beside the existing `args.run_id = parse_safe_id(args.run_id, kind="run id")` (cli.py:365):

```python
    if args.batch:
        args.batch = parse_safe_id(args.batch, kind="batch label")
```

Plan transport is free: `_expand_plan_argv`'s generic scalar branch already renders `"batch": "x"` as `--batch x`.

3. Orchestrator — in the `run_config = {` literal (orchestrator.py:243), after `"batch_size": args.batch_size,`:

```python
        "batch": args.batch,
```

4. Console launch path — `rg -n '"batch"' src/starbench/gui/services/console.py` (today: line 263, `"batch": plan["name"]` handed to the supervisor). In the same `launch_batch` flow, add the key into each run's launch payload dict before it is planned/rendered, sourced identically:

```python
                "batch": plan["name"],
```

so the rendered run_plan carries it and the runner materializes it. Keep the existing supervisor/run_state write untouched (supervision semantics unchanged).

5. Read model — replace `_batch_marker` (runs.py:211-218) with:

```python
def _batch_marker(run_root: Path) -> Optional[str]:
    """The launch batch this run belongs to. run_config.json (runner fact)
    is authoritative; legacy runs recorded it only in run_state.json (console
    supervision file), so fall back for them. None for unlabelled runs."""
    run_config = _read_json(run_root / "run_config.json")
    if isinstance(run_config, dict):
        batch = run_config.get("batch")
        if isinstance(batch, str) and batch:
            return batch
    run_state = _read_json(run_root / RUN_STATE_FILENAME)
    if isinstance(run_state, dict):
        batch = run_state.get("batch")
        if isinstance(batch, str) and batch:
            return batch
    return None
```

6. Plan-transport test — in `tests/runner/test_run_plan.py`, add one case to the existing expansion test class: a valid plan dict plus `"batch": "exp_a"` must expand to argv containing `["--batch", "exp_a"]`, and schema validation must accept it.

- [ ] **Step 4: Run the new tests and the full suite**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_batch_marker tests.runner.test_run_plan -v` → PASS.
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green (schema equality guard passes because of `make sync-schemas`; launch-equivalence tests in `tests/gui/test_equivalence.py` may need the new key added to expected plan dicts — if they fail, extend the expectation, the behavior change is intended).

- [ ] **Step 5: Commit**

```bash
git add schemas/ src/starbench/contracts/schemas/ src/starbench/runner/cli.py \
  src/starbench/runner/orchestrator.py src/starbench/gui/services/console.py \
  src/starbench/gui/read_models/runs.py tests/
git commit -m "Promote the batch label to a runner fact with a legacy fallback"
```

---

### Task 5: Task-library collapse — backend

**Files:**
- Modify: `src/starbench/gui/server.py` (delete routes `POST /api/tasklib/dirs` ~157-158 + handler `_handle_register_tasks_dir` ~356-361, `GET /api/fs/list` ~254-255)
- Modify: `src/starbench/gui/services/console.py` (delete `register_tasks_dir` ~302-310 and the `browse_directories` delegate method; keep `libraries()`)
- Modify: `src/starbench/gui/library.py` (delete `browse_directories` ~43-84 and `MAX_DIR_ENTRIES`)
- Modify: `src/starbench/gui/read_models/runs.py` (delete `_matches_tasks_dir` ~374-384 and its call ~424; `task_history(runs_dir)` drops the `tasks_dir` parameter)
- Modify: `src/starbench/gui/contracts.py` (delete `DirListingEntry`/`DirListing` ~1160-1171 and their `GENERATED_TYPES` entries ~1535-1536), then `make gen-types`
- Modify: `tests/gui/test_library.py` (delete the two browse tests, lines ~155-168)

**Interfaces:**
- Consumes: nothing new.
- Produces: `task_history(runs_dir: Path) -> Dict[str, Any]` (single-library: history is global). `/api/tasklib/history` ignores a legacy `?dir=` query (accepted, unused) so stale frontends do not 500.

- [ ] **Step 1: Write the failing history test**

Append to the test class in `tests/gui/test_library.py` (or the file that currently covers `task_history` — locate with `rg -ln "task_history" tests/`):

```python
    def test_task_history_takes_no_tasks_dir_filter(self) -> None:
        import inspect

        from starbench.gui.read_models.runs import task_history

        self.assertEqual(
            list(inspect.signature(task_history).parameters), ["runs_dir"]
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_library -v`
Expected: the new test FAILS (`['runs_dir', 'tasks_dir']`).

- [ ] **Step 3: Delete the concepts**

Work through the file list above top to bottom. In `server.py`'s `_route_api_get`, the `["tasklib", "history"]` branch becomes:

```python
        elif segments == ["tasklib", "history"]:
            # Legacy ?dir= is accepted and ignored: history is global under
            # the single home library.
            self._send_json(app.task_history())
```

and `console.py`'s `task_history` delegate drops its argument accordingly. Then `rg -n "register_tasks_dir|browse_directories|_matches_tasks_dir|DirListing" src/ tests/` must return zero hits outside this plan file. Run `make gen-types`.

Lazy home creation (spec: reads tolerate absence, first write creates): locate the task-import install target handling (`rg -n "def install" src/starbench/gui/library.py`) and ensure the target library dir is created before files are written:

```python
    target_dir.mkdir(parents=True, exist_ok=True)
```

(if the install path already does this, verify with a fresh-tmp test run and move on). Reads need no change — `list_task_packages` on a missing dir already renders an honest empty library and `meta()` reports `exists: false`.

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green after removing the two browse tests and updating any `task_history(..., tasks_dir=...)` call sites in tests.

- [ ] **Step 5: Commit**

```bash
git add src/starbench/gui/ gui-frontend/src/lib/api-types.ts tests/gui/
git commit -m "Collapse the task library to the single home library (backend)"
```

---

### Task 6: Task-library collapse — frontend

**Files:**
- Modify: `gui-frontend/src/lib/api.ts` (delete `browse` and `registerTasksDir`; `taskHistory()` drops its argument)
- Modify: `gui-frontend/src/components/task-import.tsx` (delete the `FolderPicker`/browse flow ~lines 96-160; the import dialog's target is the single library)
- Modify: `gui-frontend/src/pages/Tasks.tsx` (delete the register-folder button/flow ~127-140; header shows the one library path)
- Modify: `gui-frontend/src/pages/NewRun.tsx` (delete `registerTasksDir` usage ~545 and the library-switcher plumbing; `tasksDir` initializes from the single `/api/tasklib` entry)
- Modify: `gui-frontend/src/features/new-run/steps/TasksStep.tsx` (delete the switcher rows ~82; `taskHistory` query key becomes `["task-history"]`)

**Interfaces:**
- Consumes: Task 5's payload shapes.
- Produces: compiling frontend with zero references to the deleted client methods.

- [ ] **Step 1: Delete the client methods and let the compiler enumerate consumers**

Remove `browse`/`registerTasksDir` from `api.ts`, change `taskHistory: () => request<TaskHistoryPayload>("/api/tasklib/history")`. Run `cd gui-frontend && npx tsc -b --noEmit 2>&1 | head -40` — every remaining consumer is Step 2's exact worklist. Do not proceed with a green build while `rg -n "registerTasksDir|api.browse" gui-frontend/src` still hits.

- [ ] **Step 2: Rewire each consumer**

Apply per file: `task-import.tsx` keeps the dropzone import path only, target prop becomes the single library dir passed by the caller; `Tasks.tsx` and `NewRun.tsx` derive that dir from the existing `["tasklib"]` query's first (only) library entry and render its path as static context instead of a picker; `TasksStep.tsx` drops the switcher list and the `tasksDir` query-key segment. Where a component kept UI copy about registering folders (e.g. Tasks.tsx:127 "No task folders registered…"), replace with import-oriented copy: `No task packages yet — drop a folder or .zip here to import into the library.`

- [ ] **Step 3: Build, rebuild static, verify**

Run: `cd gui-frontend && npm run build` → exit 0.
Run: `rg -n "registerTasksDir|api\.browse|DirListing" gui-frontend/src` → zero hits.
Run: `make gui-build`.
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green.
Manual smoke: `PYTHONPATH=src python3 -m starbench.gui.server --runs-dir runs --tasks-dir examples/tasks --port 8324 --no-browser`, screenshot `/#/tasks` and `/#/new` (headless Chrome), confirm no register/browse affordances remain; kill the server.

- [ ] **Step 4: Commit**

```bash
git add gui-frontend/src src/starbench/gui/static
git commit -m "Collapse the task library to the single home library (frontend)"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md` (Quick Start section, line ~33; flag tables mentioning `--runs-dir`/`--tasks-dir` defaults)
- Modify: `docs/runner_reference.md` (dir flag defaults; new `--batch` row)
- Modify: `docs/ARCHITECTURE.md` (§1 tree: `runs/` line notes home; §2 ownership table unchanged; add one line to §3 intro that data roots resolve flag > `$STARBENCH_HOME` > `~/.starbench`)

**Interfaces:** none (prose only).

- [ ] **Step 1: Write the home-first Quick Start**

README Quick Start opens with the zero-argument path:

```markdown
## Quick Start

StarBench keeps everything — task packages, run results, custom runtimes,
executor skills — under one home: `~/.starbench`, relocatable with
`STARBENCH_HOME`. Explicit `--tasks-dir` / `--runs-dir` flags always win.

    pip install starbench
    cp -r examples/tasks/* ~/.starbench/tasks/   # seed the library
    starbench-gui                                 # zero-argument console

Migrating an existing checkout:

    mkdir -p ~/.starbench
    mv runs ~/.starbench/runs
```

Keep the existing flagged examples below it, updating any prose that claims cwd-relative defaults. `docs/runner_reference.md`: dir-flag rows now read "default: `$STARBENCH_HOME/<name>`"; add `--batch` with the help text from Task 4. `docs/ARCHITECTURE.md` §1: annotate the `runs/` tree line with "（默认解析自 `$STARBENCH_HOME`，见 home 设计）".

- [ ] **Step 2: Verify and commit**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → green (docs only, still run it).

```bash
git add README.md docs/runner_reference.md docs/ARCHITECTURE.md
git commit -m "Document the STARBENCH_HOME data root and batch label"
```
