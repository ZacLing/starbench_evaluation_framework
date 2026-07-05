# Custom Agent Runtime + Generalized Docker Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let any headless agent CLI plug into StarBench via a declarative `runtimes/<id>.json` file (`--executor-agent custom:<id>`), and generalize the Docker execution path beyond Codex.

**Architecture:** A new `CustomRuntimeSpec` (loaded at argument-parse time) drives command construction, prompt delivery, and output parsing through three built-in parsers that reuse the existing normalization helpers in `codex_process.py`. Docker execution is extracted into a runtime-agnostic `run_agent_process_in_docker`; the Codex path delegates to it unchanged, and claude + docker-enabled custom runtimes opt in.

**Tech Stack:** Python stdlib only (json, dataclasses, shlex, asyncio, unittest). No new dependencies.

## Global Constraints

- Python `>=3.9`: every new module starts with `from __future__ import annotations`; no runtime `X | Y` evaluation outside annotations.
- Tests use `unittest` (`PYTHONPATH=src python3 -m unittest ...`), never pytest.
- Fake-CLI closed-loop tests only; no live model calls in the suite.
- Spec: `docs/superpowers/specs/2026-07-04-custom-runtime-design.md`. Parser names exactly: `headless-json`, `jsonl-events`, `text`. Prompt modes exactly: `stdin`, `arg`.
- Do not modify behavior of the five built-in runtimes except where a task explicitly says so (claude docker support in Task 8).
- Commit after every task with the repo's short imperative message style + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: CustomRuntimeSpec + loader

**Files:**
- Create: `src/starbench/runner/custom_runtime.py`
- Test: `tests/test_runner.py` (new class `CustomRuntimeSpecTests`)

**Interfaces:**
- Produces: `CustomRuntimeSpec` frozen dataclass with fields `id: str`, `command: str`, `args: List[str]`, `judge_args: List[str]`, `model_flag: str | None`, `prompt_via: str`, `prompt_flag: str`, `parser: str`, `env: Dict[str, str]`, `docker_image: str | None`, `docker_env_passthrough: List[str]`, `source_path: Path`; and `load_custom_runtime(runtimes_dir: Path, runtime_id: str) -> CustomRuntimeSpec` raising `ValueError` with the offending path on any invalid config.

- [ ] **Step 1: Write the failing tests**

```python
class CustomRuntimeSpecTests(unittest.TestCase):
    def write_runtime(self, root: Path, runtime_id: str, data: dict) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{runtime_id}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_load_custom_runtime_parses_fields_and_defaults(self) -> None:
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            self.write_runtime(
                root,
                "qwen-code",
                {
                    "id": "qwen-code",
                    "command": "qwen --experimental",
                    "args": ["--output-format", "json", "--yolo"],
                    "model_flag": "-m",
                    "parser": "headless-json",
                    "docker": {"image": "starbench-qwen:latest", "env_passthrough": ["OPENAI_API_KEY"]},
                },
            )
            spec = load_custom_runtime(root, "qwen-code")
            self.assertEqual(spec.id, "qwen-code")
            self.assertEqual(spec.command, "qwen --experimental")
            self.assertEqual(spec.args, ["--output-format", "json", "--yolo"])
            self.assertEqual(spec.judge_args, spec.args)  # default fallback
            self.assertEqual(spec.model_flag, "-m")
            self.assertEqual(spec.prompt_via, "stdin")  # default
            self.assertEqual(spec.prompt_flag, "-p")  # default
            self.assertEqual(spec.parser, "headless-json")
            self.assertEqual(spec.env, {})
            self.assertEqual(spec.docker_image, "starbench-qwen:latest")
            self.assertEqual(spec.docker_env_passthrough, ["OPENAI_API_KEY"])

    def test_load_custom_runtime_rejects_bad_configs(self) -> None:
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "missing")  # no file
            self.write_runtime(root, "bad-parser", {"id": "bad-parser", "command": "x", "parser": "yaml"})
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "bad-parser")
            self.write_runtime(root, "bad-via", {"id": "bad-via", "command": "x", "parser": "text", "prompt_via": "file"})
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "bad-via")
            self.write_runtime(root, "mismatch", {"id": "other", "command": "x", "parser": "text"})
            with self.assertRaises(ValueError):
                load_custom_runtime(root, "mismatch")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_runner.CustomRuntimeSpecTests -v`
Expected: ERROR ×2 with `ModuleNotFoundError: No module named 'starbench.runner.custom_runtime'`

- [ ] **Step 3: Implement `custom_runtime.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

VALID_PARSERS = {"headless-json", "jsonl-events", "text"}
VALID_PROMPT_VIA = {"stdin", "arg"}


@dataclass(frozen=True)
class CustomRuntimeSpec:
    id: str
    command: str
    args: List[str]
    judge_args: List[str]
    model_flag: str | None
    prompt_via: str
    prompt_flag: str
    parser: str
    env: Dict[str, str]
    docker_image: str | None
    docker_env_passthrough: List[str]
    source_path: Path

    def public_metadata(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "command": self.command,
            "args": self.args,
            "judge_args": self.judge_args,
            "model_flag": self.model_flag,
            "prompt_via": self.prompt_via,
            "prompt_flag": self.prompt_flag,
            "parser": self.parser,
            "docker_image": self.docker_image,
            "source_path": str(self.source_path),
        }


def _string_list(value: Any, *, path: Path, key: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Custom runtime {path}: {key} must be a list of strings")
    return list(value)


def load_custom_runtime(runtimes_dir: Path, runtime_id: str) -> CustomRuntimeSpec:
    path = runtimes_dir / f"{runtime_id}.json"
    if not path.exists():
        raise ValueError(f"Missing custom runtime config: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Custom runtime {path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise ValueError(f"Custom runtime {path} must be a JSON object")
    if data.get("id") != runtime_id:
        raise ValueError(f"Custom runtime {path}: id {data.get('id')!r} does not match filename {runtime_id!r}")
    command = data.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"Custom runtime {path}: command is required")
    parser = data.get("parser")
    if parser not in VALID_PARSERS:
        raise ValueError(f"Custom runtime {path}: parser must be one of {sorted(VALID_PARSERS)}, got {parser!r}")
    prompt_via = data.get("prompt_via", "stdin")
    if prompt_via not in VALID_PROMPT_VIA:
        raise ValueError(f"Custom runtime {path}: prompt_via must be one of {sorted(VALID_PROMPT_VIA)}, got {prompt_via!r}")
    env = data.get("env") or {}
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError(f"Custom runtime {path}: env must be an object of string values")
    args = _string_list(data.get("args"), path=path, key="args")
    judge_args_value = data.get("judge_args")
    judge_args = args if judge_args_value is None else _string_list(judge_args_value, path=path, key="judge_args")
    model_flag = data.get("model_flag")
    if model_flag is not None and not isinstance(model_flag, str):
        raise ValueError(f"Custom runtime {path}: model_flag must be a string or null")
    docker = data.get("docker")
    docker_image: str | None = None
    docker_env_passthrough: List[str] = []
    if docker is not None:
        if not isinstance(docker, dict) or not isinstance(docker.get("image"), str) or not docker["image"].strip():
            raise ValueError(f"Custom runtime {path}: docker section requires a non-empty image string")
        docker_image = docker["image"]
        docker_env_passthrough = _string_list(docker.get("env_passthrough"), path=path, key="docker.env_passthrough")
    return CustomRuntimeSpec(
        id=runtime_id,
        command=command,
        args=args,
        judge_args=judge_args,
        model_flag=model_flag,
        prompt_via=prompt_via,
        prompt_flag=str(data.get("prompt_flag", "-p")),
        parser=parser,
        env=dict(env),
        docker_image=docker_image,
        docker_env_passthrough=docker_env_passthrough,
        source_path=path,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src python3 -m unittest tests.test_runner.CustomRuntimeSpecTests -v`
Expected: PASS ×2. Then full suite: `PYTHONPATH=src python3 -m unittest discover -s tests` → all green.

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/custom_runtime.py tests/test_runner.py
git commit -m "Add custom runtime spec loader"
```

---

### Task 2: Custom command construction

**Files:**
- Modify: `src/starbench/runner/codex_process.py` (after `build_gemini_headless_command`)
- Test: `tests/test_runner.py` (extend `CustomRuntimeSpecTests`)

**Interfaces:**
- Consumes: `CustomRuntimeSpec` from Task 1.
- Produces: `build_custom_command(spec, *, role: str, model: str | None, prompt: str) -> List[str]` — argv for the process; caller sends `prompt` on stdin iff `spec.prompt_via == "stdin"`.

- [ ] **Step 1: Write the failing test**

```python
    def test_build_custom_command_covers_prompt_modes_and_judge_args(self) -> None:
        from starbench.runner.codex_process import build_custom_command
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            self.write_runtime(
                root,
                "argy",
                {
                    "id": "argy",
                    "command": "mycli run",
                    "args": ["--json"],
                    "judge_args": ["--json", "--read-only"],
                    "model_flag": "--model",
                    "prompt_via": "arg",
                    "prompt_flag": "-p",
                    "parser": "text",
                },
            )
            spec = load_custom_runtime(root, "argy")
            executor = build_custom_command(spec, role="executor", model="m1", prompt="do the task")
            self.assertEqual(executor, ["mycli", "run", "--json", "--model", "m1", "-p", "do the task"])
            judge = build_custom_command(spec, role="judge", model=None, prompt="judge it")
            self.assertEqual(judge, ["mycli", "run", "--json", "--read-only", "-p", "judge it"])

            self.write_runtime(
                root, "stdiny", {"id": "stdiny", "command": "othercli", "parser": "text"}
            )
            stdin_spec = load_custom_runtime(root, "stdiny")
            command = build_custom_command(stdin_spec, role="executor", model="m2", prompt="ignored on argv")
            self.assertEqual(command, ["othercli"])  # no model_flag, prompt via stdin
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_runner.CustomRuntimeSpecTests.test_build_custom_command_covers_prompt_modes_and_judge_args -v`
Expected: ERROR `ImportError: cannot import name 'build_custom_command'`

- [ ] **Step 3: Implement in `codex_process.py`**

Add import at top: `from .custom_runtime import CustomRuntimeSpec`

```python
def build_custom_command(
    spec: CustomRuntimeSpec,
    *,
    role: str,
    model: str | None,
    prompt: str,
) -> List[str]:
    if role not in {"executor", "judge"}:
        raise ValueError(f"Unknown custom runtime role: {role}")
    command = split_command(spec.command)
    command.extend(spec.judge_args if role == "judge" else spec.args)
    if model and spec.model_flag:
        command.extend([spec.model_flag, model])
    if spec.prompt_via == "arg":
        command.extend([spec.prompt_flag, prompt])
    return command
```

- [ ] **Step 4: Run tests, expect PASS; run full suite, expect all green**

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/codex_process.py tests/test_runner.py
git commit -m "Build custom runtime commands from spec"
```

---

### Task 3: Custom output parsers (final + trace normalization)

**Files:**
- Modify: `src/starbench/runner/codex_process.py`
- Test: `tests/test_runner.py` (extend `CustomRuntimeSpecTests`)

**Interfaces:**
- Consumes: existing `write_headless_final_output`, `normalize_headless_events`, `_read_jsonl_events`, `_extract_json_object`.
- Produces:
  - `write_custom_final_output(stdout_path: Path, final_path: Path, *, parser: str, output_schema: Path | None = None) -> None`
  - `normalize_custom_events(stdout_path: Path, *, parser: str, provider: str) -> None` (`jsonl-events` = no-op)

- [ ] **Step 1: Write the failing tests**

```python
    def test_custom_text_parser_writes_final_and_synthetic_events(self) -> None:
        from starbench.runner.codex_process import normalize_custom_events, write_custom_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stdout_path = tmp_path / "events.jsonl"
            stdout_path.write_text("Built the deliverable.\nAll checks passed.\n", encoding="utf-8")
            final_path = tmp_path / "final.md"
            write_custom_final_output(stdout_path, final_path, parser="text")
            self.assertEqual(final_path.read_text(encoding="utf-8"), "Built the deliverable.\nAll checks passed.")
            normalize_custom_events(stdout_path, parser="text", provider="mycli")
            summary = summarize_events(read_jsonl(stdout_path))
            self.assertEqual(summary["agent_messages"][0]["text"], "Built the deliverable.\nAll checks passed.")

    def test_custom_jsonl_events_parser_extracts_last_agent_message(self) -> None:
        from starbench.runner.codex_process import write_custom_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stdout_path = tmp_path / "events.jsonl"
            stdout_path.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "id": "m1", "text": "draft"}}),
                        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "id": "m2", "text": "final answer"}}),
                        json.dumps({"type": "turn.completed", "usage": {"output_tokens": 3}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            final_path = tmp_path / "final.md"
            write_custom_final_output(stdout_path, final_path, parser="jsonl-events")
            self.assertEqual(final_path.read_text(encoding="utf-8"), "final answer")

    def test_custom_headless_json_parser_supports_schema_output(self) -> None:
        from starbench.runner.codex_process import write_custom_final_output

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            stdout_path = tmp_path / "events.jsonl"
            stdout_path.write_text(json.dumps({"response": "{\"results\": []}"}), encoding="utf-8")
            final_path = tmp_path / "result.json"
            schema_path = ROOT / "src" / "starbench" / "runner" / "schemas" / "single_result.schema.json"
            write_custom_final_output(stdout_path, final_path, parser="headless-json", output_schema=schema_path)
            self.assertEqual(json.loads(final_path.read_text(encoding="utf-8")), {"results": []})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_runner.CustomRuntimeSpecTests -v`
Expected: ERROR ×3 `ImportError: cannot import name 'write_custom_final_output'`

- [ ] **Step 3: Implement in `codex_process.py`**

```python
def _extract_last_agent_message_text(events_path: Path) -> str:
    text: str | None = None
    for event in _read_jsonl_events(events_path):
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            candidate = item.get("text")
            if isinstance(candidate, str) and candidate.strip():
                text = candidate
    if text is None:
        raise ValueError("JSONL events output did not include an agent_message with text")
    return text


def write_custom_final_output(
    stdout_path: Path,
    final_path: Path,
    *,
    parser: str,
    output_schema: Path | None = None,
) -> None:
    if parser == "headless-json":
        write_headless_final_output(stdout_path, final_path, output_schema=output_schema)
        return
    if parser == "jsonl-events":
        text = _extract_last_agent_message_text(stdout_path)
    elif parser == "text":
        text = stdout_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("Custom text runtime produced empty stdout")
    else:
        raise ValueError(f"Unknown custom runtime parser: {parser}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_custom_events(stdout_path: Path, *, parser: str, provider: str) -> None:
    if parser == "headless-json":
        normalize_headless_events(stdout_path, provider=provider)
        return
    if parser == "jsonl-events":
        return
    if parser != "text":
        raise ValueError(f"Unknown custom runtime parser: {parser}")
    raw = stdout_path.read_text(encoding="utf-8")
    events = [
        {"type": f"{provider}.raw", "payload": {"stdout": raw}},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "id": f"{provider}-final", "text": raw.strip()},
        },
        {"type": "turn.completed", "usage": None},
    ]
    stdout_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run tests, expect PASS; full suite green**

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/codex_process.py tests/test_runner.py
git commit -m "Add custom runtime output parsers"
```

---

### Task 4: CLI resolution of custom agents

**Files:**
- Modify: `src/starbench/runner/run_benchmark.py` (`parse_args`, constants near top)
- Test: `tests/test_runner.py` (extend `CustomRuntimeSpecTests`)

**Interfaces:**
- Consumes: `load_custom_runtime` from Task 1.
- Produces: `parse_args` accepts `custom:<id>` for `--executor-agent`/`--evaluator-agent`, new flag `--runtimes-dir` (default `PROJECT_ROOT / "runtimes"`), and sets `args.executor_runtime_spec` / `args.evaluator_runtime_spec` (`CustomRuntimeSpec | None`). Custom agents default `--executor-backend` to `local`; `docker` is rejected in this task (relaxed in Task 7). `BUILTIN_AGENTS = {"codex", "claude", "opencode", "grok", "gemini"}` module constant.

- [ ] **Step 1: Write the failing tests**

```python
    def test_parse_args_resolves_custom_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "runtimes"
            self.write_runtime(root, "fake", {"id": "fake", "command": "fakecli", "parser": "text"})
            args = parse_args(
                [
                    "--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                    "--runtimes-dir", str(root),
                    "--executor-agent", "custom:fake",
                    "--evaluator-agent", "codex",
                ]
            )
            self.assertEqual(args.executor_agent, "custom:fake")
            self.assertEqual(args.executor_runtime_spec.id, "fake")
            self.assertIsNone(args.evaluator_runtime_spec)
            self.assertEqual(args.executor_backend, "local")

    def test_parse_args_rejects_unknown_or_invalid_custom_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with self.assertRaises(SystemExit):
                parse_args(
                    ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                     "--runtimes-dir", str(tmp_path), "--executor-agent", "custom:missing"]
                )
            with self.assertRaises(SystemExit):
                parse_args(
                    ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                     "--executor-agent", "franken-cli"]
                )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_runner.CustomRuntimeSpecTests -v`
Expected: the two new tests FAIL — argparse `choices` rejects `custom:fake` with SystemExit where the first test expects success (and `--runtimes-dir` is an unknown flag).

- [ ] **Step 3: Implement in `run_benchmark.py`**

Add near the top constants:

```python
BUILTIN_AGENTS = {"codex", "claude", "opencode", "grok", "gemini"}
DEFAULT_RUNTIMES_DIR = PROJECT_ROOT / "runtimes"
```

Add import: `from starbench.runner.custom_runtime import CustomRuntimeSpec, load_custom_runtime`

In `parse_args`, replace both agent flags' `choices=[...]` with plain `type=str` (keep help text, mention `custom:<id>`), add:

```python
    parser.add_argument(
        "--runtimes-dir",
        type=Path,
        default=DEFAULT_RUNTIMES_DIR,
        help="Directory containing custom runtime configs (<id>.json) for custom:<id> agents.",
    )
```

After `args = parser.parse_args(argv)` add resolution (before the backend-default block):

```python
    args.runtimes_dir = args.runtimes_dir.resolve()

    def resolve_runtime_spec(value: str, flag: str) -> CustomRuntimeSpec | None:
        if value in BUILTIN_AGENTS:
            return None
        if value.startswith("custom:"):
            try:
                return load_custom_runtime(args.runtimes_dir, value.split(":", 1)[1])
            except ValueError as exc:
                parser.error(str(exc))
        parser.error(
            f"{flag} must be one of {sorted(BUILTIN_AGENTS)} or custom:<id>, got {value!r}"
        )
        return None

    args.executor_runtime_spec = resolve_runtime_spec(args.executor_agent, "--executor-agent")
    args.evaluator_runtime_spec = resolve_runtime_spec(args.evaluator_agent, "--evaluator-agent")
```

Update the backend-default block: `"docker" if args.executor_agent == "codex" else "local"` already handles custom (any non-codex → local); the explicit-docker rejection message stays valid for this task.

- [ ] **Step 4: Run tests, expect PASS; full suite green**

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/run_benchmark.py tests/test_runner.py
git commit -m "Resolve custom:<id> agents at argument parsing"
```

---

### Task 5: Executor + judge integration, fake-CLI closed loop

**Files:**
- Modify: `src/starbench/runner/run_benchmark.py` (`run_executor`, `run_single_judge`, `run_parallel_judges`, `executor_skill_install_root`, `executor_skill_prompt_location`, `run_config`, executor/judge call sites)
- Test: `tests/test_runner.py` (new closed-loop test in `ClosedLoopTests`)

**Interfaces:**
- Consumes: Tasks 1–4 (`build_custom_command`, `write_custom_final_output`, `normalize_custom_events`, `args.*_runtime_spec`).
- Produces: `run_executor(..., custom_spec: CustomRuntimeSpec | None)` and judge functions gain the same keyword; `agent` values may be `custom:<id>` end to end. Custom executor skills install to `workspace/.starbench/executor_skills`.

- [ ] **Step 1: Write the failing closed-loop test** (in `ClosedLoopTests`; the fake CLI reuses the fake_gemini headless-json shape)

```python
    def test_closed_loop_with_custom_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tasks_dir = tmp_path / "tasks"
            runs_dir = tmp_path / "runs"
            runtimes_dir = tmp_path / "runtimes"
            runtimes_dir.mkdir()
            shutil.copytree(DEMO_TASK, tasks_dir / "demo_python_cli")
            fake_cli = self.make_fake_gemini(tmp_path)
            (runtimes_dir / "fakecli.json").write_text(
                json.dumps(
                    {
                        "id": "fakecli",
                        "command": f"{sys.executable} {fake_cli}",
                        "parser": "headless-json",
                        "prompt_via": "stdin",
                    }
                ),
                encoding="utf-8",
            )
            cmd = [
                sys.executable, "-m", "starbench.runner.run_benchmark",
                "--tasks-dir", str(tasks_dir), "--runs-dir", str(runs_dir),
                "--runtimes-dir", str(runtimes_dir),
                "--run-id", "custom_run", "--seed", "123",
                "--judge-mode", "single", "--auth-mode", "global",
                "--executor-agent", "custom:fakecli",
                "--evaluator-agent", "custom:fakecli",
                "--no-progress",
            ]
            completed = subprocess.run(cmd, cwd=ROOT, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.assertEqual(completed.returncode, 0, msg=completed.stderr)
            task_root = runs_dir / "custom_run" / "demo_python_cli"
            final = (task_root / "logs" / "final.md").read_text(encoding="utf-8")
            self.assertIn("Created outputs/stellar_measure", final)
            summary = json.loads((task_root / "logs" / "trace_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["agent_messages"][0]["text"], final)
            aggregate = json.loads((task_root / "judges" / "single_aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["passed_count"], aggregate["total_count"])
            run_config = json.loads((runs_dir / "custom_run" / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(run_config["executor_runtime"]["id"], "fakecli")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_runner.ClosedLoopTests.test_closed_loop_with_custom_runtime -v`
Expected: FAIL — the subprocess exits non-zero (`Unknown executor backend` / unknown agent branch) before artifacts exist.

- [ ] **Step 3: Implement integration**

3a. `executor_skill_install_root` and `executor_skill_prompt_location`: change the opencode condition to also cover custom:

```python
    if executor_agent == "opencode" or executor_agent.startswith("custom:"):
        return paths["workspace"] / ".starbench" / "executor_skills"
```
(and the same pattern returning `"./.starbench/executor_skills/<skill-id>/"` in `executor_skill_prompt_location`.)

3b. `run_executor`: add keyword `custom_spec: CustomRuntimeSpec | None = None`, extend the local-only guard set membership test to `agent.startswith("custom:")`, and add the branch before the codex fallthrough:

```python
    elif agent.startswith("custom:"):
        assert custom_spec is not None
        prompt_text = build_executor_prompt(
            task_run, executor_skill_location=executor_skill_prompt_location(agent)
        )
        command = build_custom_command(custom_spec, role="executor", model=model, prompt=prompt_text)
        env = os.environ.copy()
        env.update(custom_spec.env)
        result = await run_codex_process(
            command,
            cwd=paths["workspace"],
            prompt=prompt_text if custom_spec.prompt_via == "stdin" else "",
            env=env,
            stdout_path=logs / "events.jsonl",
            stderr_path=logs / "stderr.log",
            timeout_seconds=task.timeout_seconds,
        )
        if result.status == "success":
            try:
                write_custom_final_output(logs / "events.jsonl", logs / "final.md", parser=custom_spec.parser)
                normalize_custom_events(logs / "events.jsonl", parser=custom_spec.parser, provider=custom_spec.id)
            except Exception as exc:
                result = result.__class__(
                    command=result.command,
                    exit_code=result.exit_code,
                    status="failed",
                    timed_out=result.timed_out,
                    started_at=result.started_at,
                    ended_at=result.ended_at,
                    duration_seconds=result.duration_seconds,
                )
                (logs / "stderr.log").open("a", encoding="utf-8").write(
                    f"\nCustom runtime output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
```

Add `import os` to `run_benchmark.py` imports. Add `build_custom_command`, `normalize_custom_events`, `write_custom_final_output` to the `.codex_process` import block.

3c. `run_single_judge` and `run_parallel_judges`: add keyword `custom_spec: CustomRuntimeSpec | None = None`; inside each judge's agent dispatch add (before the codex else):

```python
        elif agent.startswith("custom:"):
            assert custom_spec is not None
            prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "single_result.schema.json")
            command = build_custom_command(custom_spec, role="judge", model=model, prompt=prompt)
            env = os.environ.copy()
            env.update(custom_spec.env)
```
(parallel variant uses `rubric_result.schema.json`.) After the process, mirror the grok/gemini post-processing block with the custom parser:

```python
        if agent.startswith("custom:") and process_result.status == "success":
            try:
                write_custom_final_output(
                    judges / "single_events.jsonl",
                    judge_final_path,
                    parser=custom_spec.parser,
                    output_schema=SCHEMAS_DIR / "single_result.schema.json",
                )
                normalize_custom_events(
                    judges / "single_events.jsonl", parser=custom_spec.parser, provider=custom_spec.id
                )
            except Exception as exc:
                process_result = process_result.__class__(
                    command=process_result.command,
                    exit_code=process_result.exit_code,
                    status="failed",
                    timed_out=process_result.timed_out,
                    started_at=process_result.started_at,
                    ended_at=process_result.ended_at,
                    duration_seconds=process_result.duration_seconds,
                )
                (judges / "single_stderr.log").open("a", encoding="utf-8").write(
                    f"\nCustom runtime output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
```
(parallel variant writes to `rubric_dir / "events.jsonl"` / `stderr.log`.) The stdin prompt passed to `run_codex_process` for custom judges is `prompt if custom_spec.prompt_via == "stdin" else ""` — fold into the existing conditional that already special-cases grok:

```python
            prompt="" if agent == "grok" or (agent.startswith("custom:") and custom_spec.prompt_via == "arg") else append_claude_thinking_instruction(
                prompt,
                claude_thinking_effort if agent == "claude" else "none",
            ),
```

3d. Call sites: `execute_record` passes `custom_spec=args.executor_runtime_spec`; both judge calls pass `custom_spec=args.evaluator_runtime_spec`.

3e. `run_config` in `run_benchmark()` gains:

```python
        "runtimes_dir": str(args.runtimes_dir),
        "executor_runtime": args.executor_runtime_spec.public_metadata() if args.executor_runtime_spec else None,
        "evaluator_runtime": args.evaluator_runtime_spec.public_metadata() if args.evaluator_runtime_spec else None,
```

- [ ] **Step 4: Run the closed-loop test, expect PASS; full suite green**

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/run_benchmark.py tests/test_runner.py
git commit -m "Run executors and judges through custom runtimes"
```

---

### Task 6: Custom runtime docs + sample config

**Files:**
- Create: `runtimes/README.md`, `runtimes/qwen-code.json.example`
- Modify: `README.md` (runtime convention section), `docs/runner_reference.md` (Agent Runtimes section)

**Interfaces:** none (documentation).

- [ ] **Step 1: Write `runtimes/README.md`** — field-by-field schema table copied from the spec (id/command/args/judge_args/model_flag/prompt_via/prompt_flag/parser/env/docker), the three parser contracts, one full example, ARG_MAX warning for `prompt_via: "arg"`.

- [ ] **Step 2: Write `runtimes/qwen-code.json.example`** — the spec's example verbatim (`.example` suffix so `custom:qwen-code` fails loudly until the user verifies flags against the real CLI and renames the file; note this in the file's `_comment` field is not possible in strict JSON → put the caveat in README).

- [ ] **Step 3: Update `README.md` + `docs/runner_reference.md`** — add `custom:<id>` to the runtime convention lists, a short "Custom runtimes" subsection pointing to `runtimes/README.md`, and `--runtimes-dir` in the flag list.

- [ ] **Step 4: Full suite still green** (docs only)

- [ ] **Step 5: Commit**

```bash
git add runtimes/ README.md docs/runner_reference.md
git commit -m "Document custom runtime configuration"
```

**Milestone 1 complete — custom runtimes work end to end on the local backend.**

---

### Task 7: Extract generic Docker runner + custom docker support

**Files:**
- Modify: `src/starbench/runner/codex_process.py` (`build_docker_codex_command` → thin wrapper over new `build_docker_agent_command`; new `run_custom_process_in_docker`)
- Modify: `src/starbench/runner/run_benchmark.py` (custom executor docker path; parse_args backend validation)
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces:
  - `build_docker_agent_command(*, docker_bin, docker_image, workspace, inner_command, env_whitelist: List[str], auth_env, container_name=None, extra_mounts: Dict[str, str] | None = None, extra_env: Dict[str, str] | None = None) -> List[str]` — all hardening flags from the current codex builder; `extra_mounts` maps host path → container path; `extra_env` sets literal values (e.g. `CODEX_HOME=/codex-home`).
  - `run_custom_process_in_docker(spec, *, docker_bin, workspace, prompt, stdout_path, stderr_path, timeout_seconds, model) -> ProcessResult` — builds the inner command with `cwd`-independent argv, runs with the timeout `docker kill` behavior.
  - `build_docker_codex_command(...)` keeps its exact current signature and behavior by delegating.

- [ ] **Step 1: Write the failing tests**

```python
    def test_generic_docker_command_uses_whitelist_and_mounts(self) -> None:
        from starbench.runner.codex_process import build_docker_agent_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_docker_agent_command(
                docker_bin="docker",
                docker_image="starbench-qwen:latest",
                workspace=tmp_path,
                inner_command=["qwen", "--yolo"],
                env_whitelist=["OPENAI_API_KEY", "UNSET_VAR"],
                auth_env={"OPENAI_API_KEY": "x"},
                container_name="starbench-custom-1",
                extra_env={"HOME": "/tmp"},
            )
            self.assertIn("starbench-qwen:latest", command)
            self.assertIn("OPENAI_API_KEY", command)
            self.assertNotIn("UNSET_VAR", command)  # unset host vars are not forwarded
            self.assertIn("HOME=/tmp", command)
            name_index = command.index("--name")
            self.assertEqual(command[name_index + 1], "starbench-custom-1")
            self.assertEqual(command[-2:], ["qwen", "--yolo"])

    def test_codex_docker_command_unchanged_by_extraction(self) -> None:
        from starbench.runner.codex_process import build_docker_codex_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_docker_codex_command(
                docker_bin="docker",
                docker_image="starbench-codex:latest",
                workspace=tmp_path,
                codex_home=tmp_path,
                inner_command=["codex", "exec"],
                auth_env={"OPENAI_API_KEY": "x"},
                container_name="starbench-abc",
            )
            self.assertIn("CODEX_HOME=/codex-home", command)
            self.assertIn("--read-only", command)
            self.assertIn("OPENAI_API_KEY", command)

    def test_parse_args_allows_docker_for_docker_enabled_custom_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "runtimes"
            self.write_runtime(
                root, "dockery",
                {"id": "dockery", "command": "x", "parser": "text",
                 "docker": {"image": "img:latest", "env_passthrough": ["OPENAI_API_KEY"]}},
            )
            self.write_runtime(root, "plain", {"id": "plain", "command": "x", "parser": "text"})
            args = parse_args(
                ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                 "--runtimes-dir", str(root),
                 "--executor-agent", "custom:dockery", "--executor-backend", "docker"]
            )
            self.assertEqual(args.executor_backend, "docker")
            with self.assertRaises(SystemExit):
                parse_args(
                    ["--tasks-dir", str(tmp_path), "--runs-dir", str(tmp_path),
                     "--runtimes-dir", str(root),
                     "--executor-agent", "custom:plain", "--executor-backend", "docker"]
                )
```

- [ ] **Step 2: Run tests, expect ImportError / SystemExit-vs-success failures**

- [ ] **Step 3: Implement**

3a. In `codex_process.py`, rename the body of `build_docker_codex_command` into:

```python
def build_docker_agent_command(
    *,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    inner_command: Iterable[str],
    env_whitelist: List[str],
    auth_env: Dict[str, str],
    container_name: str | None = None,
    extra_mounts: Dict[str, str] | None = None,
    extra_env: Dict[str, str] | None = None,
) -> List[str]:
    workspace = workspace.resolve()
    command = split_command(docker_bin)
    command.append("run")
    if container_name:
        command.extend(["--name", container_name])
    command.extend(
        [
            "--rm", "-i", "--read-only", "--cap-drop=ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "512", "--memory", "6g", "--cpus", "4",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=1g",
            "--mount", f"type=bind,src={workspace},dst=/workspace",
        ]
    )
    for host_path, container_path in (extra_mounts or {}).items():
        command.extend(["--mount", f"type=bind,src={Path(host_path).resolve()},dst={container_path}"])
    command.extend(["-w", "/workspace"])
    for key, value in (extra_env or {}).items():
        command.extend(["-e", f"{key}={value}"])
    for key in env_whitelist:
        if auth_env.get(key):
            command.extend(["-e", key])
    command.append(docker_image)
    command.extend(inner_command)
    return command


def build_docker_codex_command(
    *,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    codex_home: Path,
    inner_command: Iterable[str],
    auth_env: Dict[str, str],
    container_name: str | None = None,
) -> List[str]:
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=["CODEX_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL"],
        auth_env=auth_env,
        container_name=container_name,
        extra_mounts={str(codex_home.resolve()): "/codex-home"},
        extra_env={"CODEX_HOME": "/codex-home"},
    )
```

3b. Add `run_custom_process_in_docker` (mirrors the codex docker runner incl. timeout `docker kill`):

```python
async def run_custom_process_in_docker(
    spec: CustomRuntimeSpec,
    *,
    docker_bin: str,
    workspace: Path,
    prompt: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    model: str | None = None,
) -> ProcessResult:
    if not spec.docker_image:
        raise ValueError(f"Custom runtime {spec.id} has no docker image configured")
    inner_command = build_custom_command(spec, role="executor", model=model, prompt=prompt)
    auth_env = os.environ.copy()
    auth_env.update(spec.env)
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=spec.docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(spec.docker_env_passthrough),
        auth_env=auth_env,
        container_name=container_name,
        extra_env={key: value for key, value in spec.env.items()},
    )
    result = await run_codex_process(
        command,
        cwd=workspace,
        prompt=prompt if spec.prompt_via == "stdin" else "",
        env=auth_env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
    )
    if result.timed_out:
        subprocess.run(
            split_command(docker_bin) + ["kill", container_name],
            check=False,
            capture_output=True,
        )
    return result
```

3c. `run_benchmark.py`:
- Local-only guard in `run_executor` becomes: custom agents allowed on docker when `custom_spec.docker_image` is set; the custom executor branch dispatches on backend:

```python
        if executor_backend == "docker":
            result = await run_custom_process_in_docker(
                custom_spec,
                docker_bin=docker_bin,
                workspace=paths["workspace"],
                prompt=prompt_text,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=model,
            )
        else:
            ... existing local run_codex_process call ...
```
- `parse_args` backend validation:

```python
    def backend_supports_docker(agent: str, spec: CustomRuntimeSpec | None) -> bool:
        if agent == "codex":
            return True
        return agent.startswith("custom:") and spec is not None and spec.docker_image is not None

    if args.executor_backend is None:
        args.executor_backend = "docker" if args.executor_agent == "codex" else "local"
    elif args.executor_backend == "docker" and not backend_supports_docker(args.executor_agent, args.executor_runtime_spec):
        parser.error(...)
```
(keep the existing error message text, extended with "or a custom runtime with a docker section".)

- [ ] **Step 4: Run tests, expect PASS; full suite green**

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/codex_process.py src/starbench/runner/run_benchmark.py tests/test_runner.py
git commit -m "Generalize Docker execution and enable it for custom runtimes"
```

---

### Task 8: Claude Docker support

**Files:**
- Modify: `src/starbench/runner/run_benchmark.py` (claude executor docker path; parse validation)
- Modify: `src/starbench/runner/codex_process.py` (`run_claude_process_in_docker`)
- Modify: `docker/claude-code.Dockerfile` (drop `ENTRYPOINT`)
- Test: `tests/test_runner.py` (update `test_executor_backend_defaults_follow_runtime` — claude+docker is now allowed, so that assertion moves to expect success; add claude docker command test)

**Interfaces:**
- Consumes: `build_docker_agent_command`, `build_claude_print_command` (stream-json executor form).
- Produces: `run_claude_process_in_docker(*, claude_bin, docker_bin, docker_image, workspace, prompt, stdout_path, stderr_path, timeout_seconds, model, allowed_tools, max_turns) -> ProcessResult`; claude executor accepts `--executor-backend docker` with `--docker-image` (default claude image `starbench-claude-code:latest` documented, not defaulted).

- [ ] **Step 1: Update/write the failing tests**

In `test_executor_backend_defaults_follow_runtime`, replace the `assertRaises(SystemExit)` block for claude+docker with:

```python
            args = parse_args(
                ["--tasks-dir", tmp, "--runs-dir", tmp,
                 "--executor-agent", "claude", "--executor-backend", "docker",
                 "--docker-image", "starbench-claude-code:latest"]
            )
            self.assertEqual(args.executor_backend, "docker")
            with self.assertRaises(SystemExit):
                parse_args(
                    ["--tasks-dir", tmp, "--runs-dir", tmp,
                     "--executor-agent", "grok", "--executor-backend", "docker"]
                )
```

New test:

```python
    def test_claude_docker_command_isolates_config_dir_in_workspace(self) -> None:
        from starbench.runner.codex_process import build_claude_docker_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_claude_docker_command(
                claude_bin="claude",
                docker_bin="docker",
                docker_image="starbench-claude-code:latest",
                workspace=tmp_path,
                model="claude-opus-4-8",
                allowed_tools="Read,Bash",
                max_turns=None,
                auth_env={"ANTHROPIC_API_KEY": "x"},
                container_name="starbench-claude-1",
            )
            self.assertIn("CLAUDE_CONFIG_DIR=/workspace/.runner/claude_home", command)
            self.assertIn("ANTHROPIC_API_KEY", command)
            self.assertIn("starbench-claude-code:latest", command)
            format_index = command.index("--output-format")
            self.assertEqual(command[format_index + 1], "stream-json")
```

- [ ] **Step 2: Run tests, expect failures** (ImportError for `build_claude_docker_command`; parse test fails because claude+docker still errors)

- [ ] **Step 3: Implement**

3a. `codex_process.py` — build + run helpers:

```python
CLAUDE_DOCKER_ENV_WHITELIST = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"]


def build_claude_docker_command(
    *,
    claude_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    model: str | None,
    allowed_tools: str | None,
    max_turns: int | None,
    auth_env: Dict[str, str],
    container_name: str | None = None,
) -> List[str]:
    inner_command = build_claude_print_command(
        claude_bin,
        cwd=Path("/workspace"),
        model=model,
        permission_mode="acceptEdits",
        allowed_tools=allowed_tools,
        max_turns=max_turns,
        output_format="stream-json",
    )
    return build_docker_agent_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        inner_command=inner_command,
        env_whitelist=list(CLAUDE_DOCKER_ENV_WHITELIST),
        auth_env=auth_env,
        container_name=container_name,
        extra_env={
            "CLAUDE_CONFIG_DIR": "/workspace/.runner/claude_home",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        },
    )


async def run_claude_process_in_docker(
    *,
    claude_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    prompt: str,
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
    model: str | None,
    allowed_tools: str | None,
    max_turns: int | None,
) -> ProcessResult:
    (workspace / ".runner" / "claude_home").mkdir(parents=True, exist_ok=True)
    auth_env = os.environ.copy()
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_claude_docker_command(
        claude_bin=claude_bin,
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        model=model,
        allowed_tools=allowed_tools,
        max_turns=max_turns,
        auth_env=auth_env,
        container_name=container_name,
    )
    result = await run_codex_process(
        command,
        cwd=workspace,
        prompt=prompt,
        env=auth_env,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        timeout_seconds=timeout_seconds,
    )
    if result.timed_out:
        subprocess.run(
            split_command(docker_bin) + ["kill", container_name],
            check=False,
            capture_output=True,
        )
    return result
```

3b. `run_benchmark.py` claude executor branch dispatches on backend (docker → `run_claude_process_in_docker` with the same prompt text and post-processing as the local path); `backend_supports_docker` adds `agent == "claude"`. Note: `.runner/claude_home` lives inside the workspace mount, so `--read-only` still permits writes there; `prepare_evaluator_workspace` already skips non-`inputs`/`outputs` directories, so judge workspaces stay clean; `.runner` is already excluded from top-level file copies.

3c. `docker/claude-code.Dockerfile`: delete the `ENTRYPOINT ["claude"]` line (runner invokes `claude` explicitly); keep `WORKDIR /workspace`.

- [ ] **Step 4: Run tests, expect PASS; full suite green**

- [ ] **Step 5: Commit**

```bash
git add src/starbench/runner/codex_process.py src/starbench/runner/run_benchmark.py docker/claude-code.Dockerfile tests/test_runner.py
git commit -m "Add Docker backend support for the Claude runtime"
```

---

### Task 9: Docker docs + real-container smoke checklist

**Files:**
- Modify: `docs/docker.md`, `docs/runner_reference.md`, `README.md`, `runtimes/README.md`

- [ ] **Step 1: Update docs** — docker.md: which runtimes support docker now (codex, claude, docker-enabled custom), env whitelists, `.runner/claude_home` note; runner_reference.md: claude docker invocation example; runtimes/README.md: `docker` section semantics; README: one-line status update replacing "Codex-only".

- [ ] **Step 2: Add a "Real-container smoke checklist" subsection in docker.md** (deferred items, daemon was down at build time):

```markdown
## Real-container smoke checklist

- [ ] `colima start` (or Docker Desktop) and `docker info` succeeds.
- [ ] `make docker-build`; `docker build -t starbench-claude-code:latest -f docker/claude-code.Dockerfile .`
- [ ] Codex regression: demo task with `--executor-backend docker` still passes.
- [ ] Claude: demo task with `--executor-agent claude --executor-backend docker --docker-image starbench-claude-code:latest --auth-mode env` (requires ANTHROPIC_API_KEY).
- [ ] Timeout kill: run with `timeout_seconds: 5` on a long task; verify `docker ps` shows no leftover container.
```

- [ ] **Step 3: Full suite green; commit**

```bash
git add docs/docker.md docs/runner_reference.md README.md runtimes/README.md
git commit -m "Document generalized Docker backend"
```

**Milestone 2 complete.**
