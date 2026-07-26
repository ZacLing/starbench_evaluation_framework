# Pi Agent 运行时接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pi（pi.dev）成为第六个内置运行时：执行器与评审两角色、四种原生 provider kind、原生思考档，凭证只走环境变量。

**Architecture:** 一等 adapter（`adapters/pi.py` + 注册表一行）；事件归一化进 `execution/parsers.py`；provider 注入经新 `pi_gateway` 通道在 `gui/injection.py` 落一个分支。GUI 零改动（`/api/agents` 数据驱动）。

**Tech Stack:** Python 3.9+ 标准库；unittest；fake-CLI Python 脚本（沿 `tests/runner/test_closed_loop.py` 模式）。

**Spec:** `docs/superpowers/specs/2026-07-26-pi-agent-runtime-design.md`（待核实项已全部消解，勘误见本计划各任务；冲突时以计划为准，计划的事实来自 pi 源码）。

## Global Constraints

- 测试全绿：`PYTHONPATH=src python3 -m unittest discover -s tests`（= `make test`）。
- 凭证红线：auth mode 仅 `env`；`global`/`copy-auth` 带原因拒绝；任何 key 不写入 run 目录内文件；测试不触真实 `~/.pi` 与 `~/.starbench`（一律显式 `environ=`/`base_env=`）。
- 隔离三件套硬设（不可被 base_env 覆盖）：`PI_CODING_AGENT_DIR`（指向 run 目录内隔离 home）、`PI_OFFLINE=1`、`PI_SKIP_VERSION_CHECK=1`。
- 技能防投毒：`--no-skills` 常在；已安装技能逐个显式 `--skill <path>`；评审永不带 `--skill`。
- pi CLI 事实（源码核实，2026-07-26）：`--mode json` JSONL 到 stdout；stdin 单独即构成完整 prompt（`cli/initial-message.ts`）；`--thinking <level>` 专用旗标，档位 `off|minimal|low|medium|high|xhigh|max`，非法值仅告警忽略（`cli/args.ts:130`）；`--provider <name>`、`--model <pattern>`、`--no-skills`、`--skill <path>`（可重复）。
- pi 无内置 web-search 工具（`core/tools/` 仅 bash/edit/find/grep/ls 族）→ `enforces_web_search=False`。
- 提交风格：祈使句单行、无前缀标签、尾注 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- 不碰 `README.zh-CN.md`、`.impeccable/`、`docs/superpowers/`（specs/plans 为控制者所有）。

---

### Task 1: pi 事件归一化与 final 提取（parsers）

**Files:**
- Modify: `src/starbench/execution/parsers.py`（文件末尾追加两个函数）
- Test: `tests/adapters/test_pi_parsers.py`（新建）

**Interfaces:**
- Produces: `write_pi_final_output(events_path: Path, final_path: Path, *, output_schema: Path | None = None) -> None`；`normalize_pi_events(events_path: Path) -> None`。Task 2 的 `_post()` 闭包按此签名调用。
- Consumes: 同文件既有 `_extract_json_object`（schema 模式复用其 JSON 提取语义，先读 `parsers.py` 中 `write_custom_final_output` 的用法再写）。

pi 事件流形状（fixture 依据 `docs/json.md` 与 `agent-session.ts`）：首行 `{"type":"session",...}`；assistant 消息完成为 `{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":...}|{"type":"thinking","thinking":...}]}}`；工具完成为 `{"type":"tool_execution_end","toolCallId":...,"toolName":...,"result":...,"isError":...}`；终止为 `{"type":"agent_end","messages":[...]}`。

- [ ] **Step 1: 写失败测试**

```python
"""Tests for pi event-stream normalization and final extraction."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.execution.parsers import normalize_pi_events, write_pi_final_output


def _write_events(path: Path, events: list) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _pi_events(final_text: str = "All done.") -> list:
    return [
        {"type": "session", "version": 3, "id": "s1", "timestamp": "t", "cwd": "/w"},
        {"type": "agent_start"},
        {"type": "turn_start"},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "plan it"},
                    {"type": "text", "text": "working"},
                ],
            },
        },
        {
            "type": "tool_execution_end",
            "toolCallId": "t1",
            "toolName": "bash",
            "result": {"output": "ok"},
            "isError": False,
        },
        {
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": final_text}]},
        },
        {"type": "agent_end", "messages": []},
    ]


class PiFinalOutputTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.events = self.dir / "events.jsonl"
        self.final = self.dir / "final.md"

    def test_final_takes_last_assistant_message_end(self):
        _write_events(self.events, _pi_events("Final answer."))
        write_pi_final_output(self.events, self.final)
        self.assertEqual(self.final.read_text(encoding="utf-8"), "Final answer.")

    def test_final_falls_back_to_agent_end_messages(self):
        events = [
            {"type": "session", "version": 3, "id": "s1", "timestamp": "t", "cwd": "/w"},
            {
                "type": "agent_end",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "task"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "from tail"}]},
                ],
            },
        ]
        _write_events(self.events, events)
        write_pi_final_output(self.events, self.final)
        self.assertEqual(self.final.read_text(encoding="utf-8"), "from tail")

    def test_no_assistant_message_raises(self):
        _write_events(self.events, [{"type": "session"}, {"type": "agent_end", "messages": []}])
        with self.assertRaises(ValueError):
            write_pi_final_output(self.events, self.final)

    def test_schema_mode_extracts_json_object(self):
        _write_events(self.events, _pi_events('Result: {"verdict": "pass"} trailing'))
        schema = self.dir / "schema.json"
        schema.write_text("{}", encoding="utf-8")
        write_pi_final_output(self.events, self.final, output_schema=schema)
        self.assertEqual(json.loads(self.final.read_text(encoding="utf-8")), {"verdict": "pass"})


class PiNormalizeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.events = self.dir / "events.jsonl"

    def _normalized(self):
        return [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]

    def test_appends_compat_items_after_raw_events(self):
        _write_events(self.events, _pi_events("done"))
        normalize_pi_events(self.events)
        events = self._normalized()
        types = [e.get("type") for e in events]
        self.assertIn("message_end", types)  # 原始事件保留在前
        items = [e["item"] for e in events if e.get("type") == "item.completed"]
        item_types = [i["type"] for i in items]
        self.assertIn("reasoning", item_types)
        self.assertIn("agent_message", item_types)
        self.assertIn("command_execution", item_types)
        self.assertEqual(types[-1], "turn.completed")

    def test_normalize_is_idempotent(self):
        _write_events(self.events, _pi_events("done"))
        normalize_pi_events(self.events)
        once = self.events.read_text(encoding="utf-8")
        normalize_pi_events(self.events)
        self.assertEqual(self.events.read_text(encoding="utf-8"), once)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_pi_parsers -v`
Expected: FAIL（ImportError: cannot import name 'normalize_pi_events'）

- [ ] **Step 3: 实现（parsers.py 末尾追加）**

先读 `parsers.py:280-345`（`append_opencode_compat_events`）对齐 compat item 的字段形态（`agent_message` 带 `id`/`text`；`command_execution`、`reasoning` 同形），然后：

```python
def _pi_assistant_text(message: dict) -> str:
    parts = [
        str(block.get("text") or "")
        for block in message.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part).strip()


def _read_pi_events(events_path: Path) -> list:
    events = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def write_pi_final_output(
    events_path: Path, final_path: Path, *, output_schema: Path | None = None
) -> None:
    """final.md = 最后一条 assistant message_end 文本；回退 agent_end.messages。"""
    events = _read_pi_events(events_path)
    text = ""
    for event in events:
        if event.get("type") == "message_end":
            message = event.get("message") or {}
            if message.get("role") == "assistant":
                candidate = _pi_assistant_text(message)
                if candidate:
                    text = candidate
    if not text:
        for event in events:
            if event.get("type") == "agent_end":
                for message in event.get("messages") or []:
                    if isinstance(message, dict) and message.get("role") == "assistant":
                        candidate = _pi_assistant_text(message)
                        if candidate:
                            text = candidate
    if not text:
        raise ValueError("Pi produced no assistant message")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_pi_events(events_path: Path) -> None:
    """在原始 pi 事件后追加 Codex 兼容 items（幂等：已归一则跳过）。"""
    events = _read_pi_events(events_path)
    if any(event.get("type") == "item.completed" for event in events):
        return
    compat: list = []
    counter = 0
    for event in events:
        etype = event.get("type")
        if etype == "message_end":
            message = event.get("message") or {}
            if message.get("role") != "assistant":
                continue
            for block in message.get("content") or []:
                if not isinstance(block, dict):
                    continue
                counter += 1
                if block.get("type") == "text" and block.get("text"):
                    compat.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "agent_message",
                                "id": f"pi-{counter}",
                                "text": block.get("text"),
                            },
                        }
                    )
                elif block.get("type") == "thinking" and block.get("thinking"):
                    compat.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "reasoning",
                                "id": f"pi-{counter}",
                                "text": block.get("thinking"),
                            },
                        }
                    )
        elif etype == "tool_execution_end":
            counter += 1
            compat.append(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "id": str(event.get("toolCallId") or f"pi-{counter}"),
                        "command": str(event.get("toolName") or ""),
                        "aggregated_output": json.dumps(event.get("result"), ensure_ascii=False),
                        "exit_code": 1 if event.get("isError") else 0,
                    },
                }
            )
    compat.append({"type": "turn.completed", "usage": None})
    with events_path.open("a", encoding="utf-8") as handle:
        for event in compat:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
```

实现后核对 `command_execution` 的字段名与 `append_opencode_compat_events` 产出的一致（`parsers.py:316-333`），不一致以 opencode 形态为准修正本实现与测试。

- [ ] **Step 4: 跑测试确认通过**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_pi_parsers -v`
Expected: PASS（6 tests）

- [ ] **Step 5: 全量测试 + 提交**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → OK

```bash
git add src/starbench/execution/parsers.py tests/adapters/test_pi_parsers.py
git commit -m "Add pi event normalization and final extraction"
```

---

### Task 2: PiAdapter 与注册表登记

**Files:**
- Create: `src/starbench/adapters/pi.py`
- Modify: `src/starbench/adapters/registry.py`（import + `_BUILTIN_ORDER` 追加 `PiAdapter()`）
- Test: `tests/adapters/test_pi_adapter.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `write_pi_final_output` / `normalize_pi_events`；基类 `RuntimeAdapter`、`RuntimeInfo`、`RuntimeOption`、`ProviderFilter`、`InjectionChannel`、`finalize_success`；`execution.process.run_cli_process`、`split_command`；`runner.prompts.build_executor_prompt`、`append_json_schema_instruction`。
- Produces: `PiAdapter`（注册表 id `"pi"`）；`build_pi_command(pi_bin, *, provider=None, model=None, thinking="default", skill_paths=()) -> List[str]`；`prepare_pi_env(pi_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None) -> Dict[str, str]`。Task 3 依赖 `InjectionChannel(kind="pi_gateway")` 与 wiring 旋钮名 `provider`。

**先读**：`src/starbench/adapters/opencode.py`（全文，结构模板）与 `base.py` docstring。

- [ ] **Step 1: 写失败测试**

```python
"""Tests for the Pi runtime adapter (command shape, env isolation, registry)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starbench.adapters.pi import PiAdapter, build_pi_command, prepare_pi_env
from starbench.adapters.registry import get_builtin, list_builtin


class PiCommandTests(unittest.TestCase):
    def test_minimal_command_is_headless_json_and_skill_less(self):
        command = build_pi_command("pi")
        self.assertEqual(command[:3], ["pi", "--mode", "json"])
        self.assertIn("--no-skills", command)
        self.assertNotIn("--skill", command)
        self.assertNotIn("--thinking", command)

    def test_provider_model_thinking_and_skills(self):
        command = build_pi_command(
            "pi",
            provider="anthropic",
            model="claude-sonnet-4-5",
            thinking="high",
            skill_paths=(Path("/w/.starbench/executor_skills/s1"),),
        )
        self.assertIn("--provider", command)
        self.assertEqual(command[command.index("--provider") + 1], "anthropic")
        self.assertEqual(command[command.index("--model") + 1], "claude-sonnet-4-5")
        self.assertEqual(command[command.index("--thinking") + 1], "high")
        self.assertEqual(
            command[command.index("--skill") + 1], "/w/.starbench/executor_skills/s1"
        )

    def test_default_thinking_omits_flag(self):
        for level in ("default", "none"):
            command = build_pi_command("pi", thinking=level)
            self.assertNotIn("--thinking", command)


class PiEnvTests(unittest.TestCase):
    def test_env_mode_isolates_home_and_forces_offline(self):
        home = Path(tempfile.mkdtemp()) / "pi_executor"
        env = prepare_pi_env(home, "env", base_env={"PATH": "/bin", "PI_OFFLINE": "0"})
        self.assertEqual(env["PI_CODING_AGENT_DIR"], str(home))
        self.assertEqual(env["PI_OFFLINE"], "1")
        self.assertEqual(env["PI_SKIP_VERSION_CHECK"], "1")
        self.assertEqual(env["PATH"], "/bin")
        self.assertTrue(home.exists())

    def test_global_and_copy_auth_are_rejected(self):
        home = Path(tempfile.mkdtemp()) / "pi_home"
        for mode in ("global", "copy-auth"):
            with self.assertRaises(ValueError):
                prepare_pi_env(home, mode, base_env={})


class PiInfoTests(unittest.TestCase):
    def test_registered_as_builtin_with_expected_facts(self):
        adapter = get_builtin("pi")
        info = adapter.info
        self.assertEqual(info.id, "pi")
        self.assertIsNone(info.docker_image)
        self.assertEqual(info.injection.kind, "pi_gateway")
        self.assertEqual(info.provider_filter.kinds, ("anthropic", "openai", "google", "xai"))
        self.assertEqual(info.thinking_channel, "native_config")
        self.assertIn("xhigh", info.thinking_efforts)
        self.assertIn("PI_CODING_AGENT_DIR", info.judge_sensitive_env)
        self.assertIn("pi", [a.info.id for a in list_builtin()])
        self.assertEqual([o.name for o in info.options], ["provider"])
        self.assertFalse(info.enforces_web_search)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_pi_adapter -v`
Expected: FAIL（ModuleNotFoundError: starbench.adapters.pi）

- [ ] **Step 3: 实现 `adapters/pi.py`**

```python
"""Pi adapter (pi.dev multi-provider coding agent, host-local).

Pi is headless-friendly: ``--mode json`` streams JSONL events to stdout and a
prompt piped on stdin is the whole initial message (``cli/initial-message.ts``).
Thinking rides the native ``--thinking <level>`` flag. Skills use pi's native
Agent Skills support, poisoning-proof: ``--no-skills`` kills discovery and each
installed executor skill is passed explicitly via ``--skill``.

Invariants:
- Auth mode is ``env`` only. The operator's ``~/.pi/agent/auth.json`` is a
  personal OAuth identity and must never carry benchmark traffic.
- ``PI_CODING_AGENT_DIR`` / ``PI_OFFLINE`` / ``PI_SKIP_VERSION_CHECK`` are
  hard-set (not setdefault): isolation must survive injected base envs.

"改什么来这里": pi command shape, env isolation, provider flag wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

from ..execution.parsers import normalize_pi_events, write_pi_final_output
from ..execution.process import run_cli_process, split_command
from ..runner.models import ProcessResult, TaskRunSpec
from ..runner.prompts import append_json_schema_instruction, build_executor_prompt
from .base import (
    ExecutorContext,
    InjectionChannel,
    JudgeContext,
    ProviderFilter,
    RuntimeAdapter,
    RuntimeInfo,
    RuntimeOption,
    finalize_success,
)

# Provider API-key env vars pi reads natively (docs/providers). A contender
# that injects any of these could reroute pi when it acts as judge; the two
# PI_* vars could redirect its config/session storage outright.
PI_JUDGE_SENSITIVE_ENV = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "PI_CODING_AGENT_DIR",
    "PI_CODING_AGENT_SESSION_DIR",
)


def build_pi_command(
    pi_bin: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    thinking: str = "default",
    skill_paths: Sequence[Path] = (),
) -> List[str]:
    command = split_command(pi_bin)
    command.extend(["--mode", "json", "--no-skills"])
    for skill in skill_paths:
        command.extend(["--skill", str(skill)])
    if provider:
        command.extend(["--provider", provider])
    if model:
        command.extend(["--model", model])
    # pi's native reasoning switch; "default" (legacy "none") leaves the CLI
    # default alone. Levels: off|minimal|low|medium|high|xhigh|max.
    if thinking and thinking not in ("default", "none"):
        command.extend(["--thinking", thinking])
    return command


def prepare_pi_env(
    pi_home: Path, auth_mode: str, *, base_env: Dict[str, str] | None = None
) -> Dict[str, str]:
    if auth_mode != "env":
        raise ValueError(
            "Pi agent supports --auth-mode env only; the operator's ~/.pi OAuth "
            "login must not carry benchmark traffic"
        )
    env = dict(base_env) if base_env is not None else {}
    pi_home.mkdir(parents=True, exist_ok=True)
    env["PI_CODING_AGENT_DIR"] = str(pi_home)
    env["PI_OFFLINE"] = "1"
    env["PI_SKIP_VERSION_CHECK"] = "1"
    return env


def _installed_skill_paths(install_root: Path) -> List[Path]:
    if not install_root.is_dir():
        return []
    return sorted(path for path in install_root.iterdir() if path.is_dir())


class PiAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="pi",
        label="Pi",
        description="Multi-provider coding agent (pi.dev)",
        protocol="multi",
        bin="pi",
        docker_image=None,
        credential_env_keys=(),
        judge_sensitive_env=PI_JUDGE_SENSITIVE_ENV,
        default_executor_backend="local",
        provider_filter=ProviderFilter(kinds=("anthropic", "openai", "google", "xai")),
        injection=InjectionChannel(kind="pi_gateway"),
        thinking_channel="native_config",
        thinking_efforts=(
            "default",
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ),
        options=(RuntimeOption(name="provider", type="string", role="both", surface="wiring"),),
    )

    async def run_executor(
        self,
        task_run: TaskRunSpec,
        paths: Dict[str, Path],
        *,
        ctx: ExecutorContext,
    ) -> ProcessResult:
        task = task_run.task
        logs = paths["logs"]
        if ctx.executor_backend != "local":
            raise ValueError("pi executor supports --executor-backend local only")
        prompt = build_executor_prompt(
            task_run, executor_skill_location=self.executor_skill_prompt_location()
        )
        command = build_pi_command(
            ctx.bins["pi"],
            provider=ctx.options.get("provider"),
            model=ctx.model,
            thinking=ctx.thinking_effort,
            skill_paths=_installed_skill_paths(
                self.executor_skill_install_root(paths, ctx.executor_backend)
            ),
        )
        env = prepare_pi_env(
            paths["agent_home"] / "pi_executor", ctx.auth_mode, base_env=ctx.base_env
        )
        result = await run_cli_process(
            command,
            cwd=paths["workspace"],
            prompt=prompt,
            env=env,
            stdout_path=logs / "events.jsonl",
            stderr_path=logs / "stderr.log",
            timeout_seconds=task.timeout_seconds,
        )

        def _post() -> None:
            write_pi_final_output(logs / "events.jsonl", logs / "final.md")
            normalize_pi_events(logs / "events.jsonl")

        return finalize_success(result, stderr_path=logs / "stderr.log", label="Pi", work=_post)

    async def run_judge(
        self,
        *,
        base_prompt: str,
        schema_path: Path,
        judge_workspace: Path,
        judge_final_path: Path,
        events_path: Path,
        stderr_path: Path,
        judge_home_base: Path,
        model: str | None,
        timeout_seconds: int,
        ctx: JudgeContext,
    ) -> ProcessResult:
        prompt = append_json_schema_instruction(base_prompt, schema_path)
        command = build_pi_command(
            ctx.bins["pi"],
            provider=ctx.options.get("provider"),
            model=model,
            thinking=ctx.thinking_effort,
        )
        env = prepare_pi_env(
            judge_home_base.parent / f"{judge_home_base.name}_pi",
            ctx.auth_mode,
            base_env=ctx.base_env,
        )
        result = await run_cli_process(
            command,
            cwd=judge_workspace,
            prompt=prompt,
            env=env,
            stdout_path=events_path,
            stderr_path=stderr_path,
            timeout_seconds=timeout_seconds,
        )

        def _post() -> None:
            write_pi_final_output(events_path, judge_final_path, output_schema=schema_path)
            normalize_pi_events(events_path)

        return finalize_success(result, stderr_path=stderr_path, label="Pi", work=_post)
```

- [ ] **Step 4: 注册（registry.py）**

`from .pi import PiAdapter`（import 块按现有字母序插入）；`_BUILTIN_ORDER` 末尾追加 `PiAdapter(),`（注释说明历史五家顺序保持不变，pi 追加于尾）。

- [ ] **Step 5: 跑新测试与全量**

Run: `PYTHONPATH=src python3 -m unittest tests.adapters.test_pi_adapter -v` → PASS
Run: `PYTHONPATH=src python3 -m unittest discover -s tests`
Expected: 可能有守卫测试因内置清单/`DEFAULT_DOCKER_IMAGES`/`--pi-bin` 旗标新增而挂——逐个读失败断言，把期望**诚实扩充**（加入 `"pi"` / `"pi": None`），不得删除断言。若挂的是前端契约同步类测试（`gen-types`），按其提示运行 `make gen-types` 并将再生文件纳入同一提交。

- [ ] **Step 6: 提交**

```bash
git add src/starbench/adapters/pi.py src/starbench/adapters/registry.py tests/adapters/test_pi_adapter.py <守卫测试与再生文件>
git commit -m "Add the Pi runtime adapter and register it"
```

---

### Task 3: `pi_gateway` 注入分支

**Files:**
- Modify: `src/starbench/gui/injection.py`（`builtin_settings` 内、`opencode_gateway` 分支之后）
- Test: `tests/gui/test_pi_injection.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `InjectionChannel(kind="pi_gateway")`；`get_builtin("pi").info`。
- Produces: `builtin_settings(info, provider)` 对 pi 返回 `{"auth_mode", "gateway": {"provider": <pi名>}, "env": {<官方var>: {"from_env": ...}} | None}`。gateway 键 `provider` 与 Task 2 声明的 wiring 旋钮同名（planning 折进 option box 后由 `resolve_runtime_options` 校验）。

- [ ] **Step 1: 写失败测试**

```python
"""Tests for the pi_gateway injection branch."""
from __future__ import annotations

import unittest

from starbench.adapters.registry import get_builtin
from starbench.gui.injection import builtin_settings

PI = get_builtin("pi").info


class PiGatewayTests(unittest.TestCase):
    def test_each_native_kind_maps_to_pi_provider_and_official_key_var(self):
        cases = [
            ("anthropic", "anthropic", "ANTHROPIC_API_KEY"),
            ("openai", "openai", "OPENAI_API_KEY"),
            ("google", "google", "GEMINI_API_KEY"),
            ("xai", "xai", "XAI_API_KEY"),
        ]
        for kind, pi_name, official_var in cases:
            with self.subTest(kind=kind):
                provider = {"id": f"my-{kind}", "kind": kind, "api_key_env": "MY_SECRET_KEY"}
                settings = builtin_settings(PI, provider)
                self.assertEqual(settings["auth_mode"], "env")
                self.assertEqual(settings["gateway"], {"provider": pi_name})
                self.assertEqual(settings["env"], {official_var: {"from_env": "MY_SECRET_KEY"}})

    def test_official_key_var_source_stays_named_not_inlined(self):
        provider = {"id": "p", "kind": "anthropic", "api_key_env": "ANTHROPIC_API_KEY"}
        settings = builtin_settings(PI, provider)
        self.assertEqual(settings["env"], {"ANTHROPIC_API_KEY": {"from_env": "ANTHROPIC_API_KEY"}})

    def test_provider_without_key_env_yields_no_env_overrides(self):
        provider = {"id": "p", "kind": "openai", "api_key_env": ""}
        settings = builtin_settings(PI, provider)
        self.assertIsNone(settings["env"])
        self.assertEqual(settings["gateway"], {"provider": "openai"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_pi_injection -v`
Expected: FAIL（pi_gateway 落进 `kind == "none"` 兜底，gateway 为空 dict）

- [ ] **Step 3: 实现（injection.py，`opencode_gateway` 分支后插入）**

模块顶部常量区（`DEFAULT_OPENAI_BASE_URLS` 之后）：

```python
# pi drives four native provider kinds; each maps to pi's --provider name and
# the official API-key env var pi reads for it (pi.dev docs/providers).
PI_PROVIDER_NAMES: Dict[str, str] = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google",
    "xai": "xai",
}
PI_KEY_VARS: Dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "xai": "XAI_API_KEY",
}
```

分支：

```python
    if kind == "pi_gateway":
        provider_kind = str(provider.get("kind") or "")
        env: Dict[str, Any] = {}
        official_var = PI_KEY_VARS.get(provider_kind, "")
        source_var = str(provider.get("api_key_env") or "")
        if official_var and source_var:
            env[official_var] = {"from_env": source_var}
        return {
            "auth_mode": auth_mode,
            "gateway": {"provider": PI_PROVIDER_NAMES.get(provider_kind)},
            "env": env or None,
        }
```

- [ ] **Step 4: 跑测试确认通过 + 全量**

Run: `PYTHONPATH=src python3 -m unittest tests.gui.test_pi_injection -v` → PASS
Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → OK

- [ ] **Step 5: 提交**

```bash
git add src/starbench/gui/injection.py tests/gui/test_pi_injection.py
git commit -m "Wire pi provider injection through the pi_gateway channel"
```

---

### Task 4: 闭环 fake-pi 测试与文档行

**Files:**
- Test: `tests/runner/test_closed_loop.py`（追加 fake-pi 工厂与用例，沿 `make_fake_codex` 模式）
- Modify: `docs/runner_reference.md`（运行时清单/`--pi-bin` 处各一行）、`docs/gui.md`（运行时提及处一行）、`AGENTS.md` Runtime Notes（一行：Pi 宿主本地、auth 仅 env）

**Interfaces:**
- Consumes: 已注册的 `pi` 运行时全链路（CLI 旗标 `--pi-bin` 由注册表自动派生）；`helpers.DEMO_TASK`。

- [ ] **Step 1: 写 fake-pi 工厂与失败用例**

在 `ClosedLoopTests` 追加（先读该文件既有 codex 用例的启动方式——`run_benchmark` 调用形态与断言面——保持同构）：

```python
    def make_fake_pi(self, directory: Path) -> Path:
        script = directory / "fake_pi.py"
        script.write_text(
            textwrap.dedent(
                r'''
                import json
                import os
                import sys
                from pathlib import Path

                def emit(event):
                    print(json.dumps(event), flush=True)

                args = sys.argv[1:]
                assert "--mode" in args and args[args.index("--mode") + 1] == "json", args
                assert "--no-skills" in args, args
                assert os.environ.get("PI_OFFLINE") == "1", "PI_OFFLINE must be forced"
                home = os.environ.get("PI_CODING_AGENT_DIR", "")
                assert home, "PI_CODING_AGENT_DIR must be set"
                prompt = sys.stdin.read()
                assert prompt.strip(), "prompt must arrive on stdin"

                emit({"type": "session", "version": 3, "id": "fake", "timestamp": "t", "cwd": os.getcwd()})
                emit({"type": "agent_start"})
                cwd = Path(os.getcwd())
                outputs = cwd / "outputs" / "demo"
                outputs.mkdir(parents=True, exist_ok=True)
                (outputs / "result.txt").write_text("done")
                emit({
                    "type": "message_end",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": "Fake pi finished the task."}]},
                })
                emit({"type": "agent_end", "messages": []})
                '''
            ),
            encoding="utf-8",
        )
        return script
```

用例（执行器走 pi、评审沿用该测试文件里既有的 fake 评审运行时；断言 `logs/events.jsonl` 含 `item.completed`、`logs/final.md` 内容、`PI_CODING_AGENT_DIR` 落在 run 目录内——从 run 目录树中断言 `agent_home/pi_executor` 存在）：

```python
    def test_pi_executor_closed_loop(self):
        # 组装方式照抄本文件中 codex/custom 既有用例：--executor-agent pi
        # --pi-bin f"{sys.executable} {fake_pi}"，评审配置与既有用例相同。
        ...
```

（实施者按本文件既有用例的真实调用形态补全 `...`——run_benchmark 的参数拼装在既有用例中已有完整先例，逐参照抄，仅替换 executor 侧为 pi。这不是占位符：既有用例是唯一权威形态，照抄比在计划里重复更不易漂移。断言面必须含：run 成功状态、`final.md == "Fake pi finished the task."`、`events.jsonl` 尾部有 `turn.completed`、`agent_home/pi_executor` 目录存在。）

- [ ] **Step 2: 跑用例确认失败**

Run: `PYTHONPATH=src python3 -m unittest tests.runner.test_closed_loop -v -k pi`
Expected: FAIL（用例未补全前为语法/断言失败；补全后首跑应 PASS——若 FAIL，按 stderr 排查 fake 契约断言）

- [ ] **Step 3: 补全用例并跑全量**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests` → OK

- [ ] **Step 4: 文档行**

- `docs/runner_reference.md`：运行时表加 `pi` 行（label、host-local、auth env only、思考档全集）；`--pi-bin` 若旗标表存在则加一行。
- `docs/gui.md`：运行时清单提及处补 Pi。
- `AGENTS.md` Runtime Notes 追加一行：`Pi (pi.dev) executor support is host-local; auth mode env only — the operator's ~/.pi OAuth login must never carry benchmark traffic.`

- [ ] **Step 5: 提交**

```bash
git add tests/runner/test_closed_loop.py docs/runner_reference.md docs/gui.md AGENTS.md
git commit -m "Close the loop on the pi runtime with a fake CLI and document it"
```
