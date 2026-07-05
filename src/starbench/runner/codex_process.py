from __future__ import annotations

import asyncio
import json
import os
import subprocess
import shlex
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .custom_runtime import CustomRuntimeSpec
from .models import ProcessResult


def split_command(command: str) -> List[str]:
    return shlex.split(command)


def prepare_auth_home(codex_home: Path, auth_mode: str) -> Dict[str, str]:
    env = os.environ.copy()
    if auth_mode == "global":
        return env

    codex_home.mkdir(parents=True, exist_ok=True)
    env["CODEX_HOME"] = str(codex_home)

    if auth_mode == "copy-auth":
        source = Path.home() / ".codex" / "auth.json"
        if source.exists():
            shutil.copy2(source, codex_home / "auth.json")
    elif auth_mode != "env":
        raise ValueError(f"Unknown auth mode: {auth_mode}")

    return env


def prepare_isolated_auth_home(codex_home: Path, auth_mode: str) -> Dict[str, str]:
    """Prepare an isolated CODEX_HOME even when the caller selected global auth."""
    env = os.environ.copy()
    codex_home.mkdir(parents=True, exist_ok=True)
    env["CODEX_HOME"] = str(codex_home)

    if auth_mode in {"global", "copy-auth"}:
        source = Path.home() / ".codex" / "auth.json"
        if source.exists():
            shutil.copy2(source, codex_home / "auth.json")
    elif auth_mode != "env":
        raise ValueError(f"Unknown auth mode: {auth_mode}")

    return env


def build_codex_exec_command(
    codex_bin: str,
    *,
    cwd: Path,
    final_path: Path,
    sandbox: str,
    output_schema: Path | None = None,
    model: str | None = None,
    allow_web_search: bool = False,
    include_trace_config: bool = True,
) -> List[str]:
    command = split_command(codex_bin)
    if allow_web_search:
        command.append("--search")
    command.append("exec")
    if model:
        command.extend(["-m", model])
    command.extend(
        [
            "--cd",
            str(cwd),
            "--skip-git-repo-check",
            "--ephemeral",
            "--json",
            "--output-last-message",
            str(final_path),
            "-c",
            'approval_policy="never"',
            "--sandbox",
            sandbox,
            "--ignore-rules",
            "--disable",
            "plugins",
            "--disable",
            "memories",
        ]
    )
    if include_trace_config:
        command.extend(
            [
                "-c",
                'model_reasoning_summary="detailed"',
                "-c",
                "show_raw_agent_reasoning=true",
            ]
        )
    if output_schema is not None:
        command.extend(["--output-schema", str(output_schema)])
    command.append("-")
    return command


def build_claude_print_command(
    claude_bin: str,
    *,
    cwd: Path,
    model: str | None = None,
    output_schema: Path | None = None,
    permission_mode: str | None = None,
    allowed_tools: str | None = None,
    max_turns: int | None = None,
    output_format: str = "json",
) -> List[str]:
    command = split_command(claude_bin)
    command.extend(["-p", "--output-format", output_format, "--no-session-persistence"])
    if output_format == "stream-json":
        # Claude Code print mode requires --verbose for stream-json output.
        command.append("--verbose")
    if model:
        command.extend(["--model", model])
    if permission_mode:
        command.extend(["--permission-mode", permission_mode])
    if allowed_tools:
        command.extend(["--allowedTools", allowed_tools])
    if max_turns is not None:
        command.extend(["--max-turns", str(max_turns)])
    if output_schema is not None:
        command.extend(["--json-schema", output_schema.read_text(encoding="utf-8")])
    return command


def build_opencode_run_command(
    opencode_bin: str,
    *,
    cwd: Path,
    model: str | None = None,
    agent: str = "build",
    output_format: str = "json",
) -> List[str]:
    command = split_command(opencode_bin)
    command.extend(["run", "--dir", str(cwd), "--agent", agent, "--format", output_format])
    if model:
        command.extend(["--model", model])
    command.append("--dangerously-skip-permissions")
    return command


def build_grok_headless_command(
    grok_bin: str,
    *,
    cwd: Path,
    prompt: str,
    model: str | None = None,
    permission_mode: str = "bypassPermissions",
    sandbox: str = "workspace",
    output_format: str = "json",
) -> List[str]:
    command = split_command(grok_bin)
    command.extend(
        [
            "--no-auto-update",
            "--no-alt-screen",
            "--cwd",
            str(cwd),
            "--output-format",
            output_format,
            "--permission-mode",
            permission_mode,
            "--sandbox",
            sandbox,
        ]
    )
    if permission_mode == "bypassPermissions":
        command.append("--always-approve")
    if model:
        command.extend(["-m", model])
    command.extend(["-p", prompt])
    return command


def build_gemini_headless_command(
    gemini_bin: str,
    *,
    prompt: str = "",
    model: str | None = None,
    approval_mode: str = "yolo",
    output_format: str = "json",
) -> List[str]:
    command = split_command(gemini_bin)
    command.extend(["--output-format", output_format, "--skip-trust"])
    if model:
        command.extend(["-m", model])
    if approval_mode == "yolo":
        command.append("--yolo")
    elif approval_mode:
        command.extend(["--approval-mode", approval_mode])
    command.extend(["-p", prompt])
    return command


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


def prepare_claude_env(claude_home: Path, auth_mode: str) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("Claude agent currently supports --auth-mode env or global")
    env = os.environ.copy()
    env.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    if auth_mode == "global":
        # Keep the host CLAUDE_CONFIG_DIR: Claude Code login credentials are
        # bound to the config dir, so overriding it would break host login.
        return env
    claude_home.mkdir(parents=True, exist_ok=True)
    env["CLAUDE_CONFIG_DIR"] = str(claude_home)
    return env


def prepare_grok_env(grok_home: Path, auth_mode: str) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("Grok agent currently supports --auth-mode env or global")
    env = os.environ.copy()
    grok_home.mkdir(parents=True, exist_ok=True)
    return env


def prepare_gemini_env(gemini_home: Path, auth_mode: str) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("Gemini agent currently supports --auth-mode env or global")
    env = os.environ.copy()
    gemini_home.mkdir(parents=True, exist_ok=True)
    return env


def _opencode_model_id(model: str | None) -> str | None:
    if not model:
        return None
    return model.split("/", 1)[1] if "/" in model else model


def prepare_opencode_env(
    opencode_home: Path,
    auth_mode: str,
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: str | None = None,
) -> Dict[str, str]:
    if auth_mode not in {"env", "global"}:
        raise ValueError("OpenCode agent currently supports --auth-mode env or global")
    env = os.environ.copy()
    if auth_mode == "env":
        opencode_home.mkdir(parents=True, exist_ok=True)
        env["OPENCODE_CONFIG_DIR"] = str(opencode_home)
    env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")
    env.setdefault("OPENCODE_DISABLE_PRUNE", "1")

    if provider and base_url:
        provider_config: Dict[str, Any] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider,
            "options": {"baseURL": base_url},
            "models": {},
        }
        if api_key_env:
            provider_config["options"]["apiKey"] = f"{{env:{api_key_env}}}"
        model_id = _opencode_model_id(model)
        if model_id:
            provider_config["models"][model_id] = {
                "name": model_id,
                "limit": {"context": 128000, "output": 8192},
            }
        inline_config = {
            "$schema": "https://opencode.ai/config.json",
            "provider": {provider: provider_config},
        }
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps(inline_config, sort_keys=True)
    return env


def _extract_claude_payload(stdout_path: Path) -> Dict[str, Any]:
    data = json.loads(stdout_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Claude output was not a JSON object")
    _raise_on_claude_error_result(data)
    return data


def _raise_on_claude_error_result(result_event: Dict[str, Any]) -> None:
    # Claude Code can exit 0 while reporting a failed run (e.g. "Not logged
    # in"). Treat is_error results as failures instead of grading them.
    if result_event.get("is_error"):
        result_text = result_event.get("result")
        detail = result_text if isinstance(result_text, str) and result_text else result_event.get("subtype", "unknown error")
        raise ValueError(f"Claude reported an error result: {detail}")


def write_claude_final_output(stdout_path: Path, final_path: Path, *, output_schema: Path | None = None) -> None:
    data = _extract_claude_payload(stdout_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is not None:
        structured = data.get("structured_output")
        if structured is None:
            result_text = data.get("result")
            if isinstance(result_text, str):
                structured = json.loads(result_text)
        if structured is None:
            raise ValueError("Claude JSON output did not include structured_output")
        final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        final_path.write_text(str(data.get("result", "")), encoding="utf-8")


def _read_jsonl_events(path: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def write_claude_stream_final_output(stdout_path: Path, final_path: Path) -> None:
    """Extract the final assistant text from Claude Code stream-json events."""
    result_event: Dict[str, Any] | None = None
    for event in _read_jsonl_events(stdout_path):
        if event.get("type") == "result":
            result_event = event
    if result_event is None:
        raise ValueError("Claude stream-json output did not include a result event")
    _raise_on_claude_error_result(result_event)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    result_text = result_event.get("result")
    final_path.write_text(result_text if isinstance(result_text, str) else "", encoding="utf-8")


_CLAUDE_FILE_CHANGE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}


def _claude_tool_result_text(block: Dict[str, Any]) -> str | None:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        if parts:
            return "".join(parts)
    return None


def append_claude_compat_events(events_path: Path) -> None:
    """Append Codex-style item.completed events derived from Claude stream-json events.

    This keeps trace_summary.json comparable across runtimes: agent messages,
    reasoning, command executions, file changes, and usage all become visible
    to summarize_events just like Codex/OpenCode traces.
    """
    events = _read_jsonl_events(events_path)

    tool_results: Dict[str, Dict[str, Any]] = {}
    for event in events:
        if event.get("type") != "user":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_use_id = block.get("tool_use_id")
            if not isinstance(tool_use_id, str):
                continue
            text = _claude_tool_result_text(block)
            if text is None:
                tool_use_result = event.get("tool_use_result")
                if isinstance(tool_use_result, dict) and isinstance(tool_use_result.get("stdout"), str):
                    text = tool_use_result["stdout"]
            tool_results[tool_use_id] = {
                "output": text,
                "is_error": bool(block.get("is_error", False)),
            }

    compat_events: List[Dict[str, Any]] = []
    usage: Any = None
    for event in events:
        event_type = event.get("type")
        if event_type == "result":
            usage = event.get("usage")
            continue
        if event_type != "assistant":
            continue
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "id": block.get("id"), "text": block.get("text")},
                    }
                )
            elif block_type == "thinking":
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {"type": "reasoning", "id": block.get("id"), "text": block.get("thinking")},
                    }
                )
            elif block_type == "tool_use":
                tool = block.get("name")
                input_data = block.get("input")
                input_data = input_data if isinstance(input_data, dict) else {}
                tool_use_id = block.get("id")
                result = tool_results.get(tool_use_id) if isinstance(tool_use_id, str) else None
                status = None
                if result is not None:
                    status = "failed" if result["is_error"] else "completed"
                if tool == "Bash":
                    compat_events.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "command_execution",
                                "id": tool_use_id,
                                "command": input_data.get("command"),
                                "status": status,
                                "exit_code": None,
                                "aggregated_output": result["output"] if result else None,
                            },
                        }
                    )
                elif tool in _CLAUDE_FILE_CHANGE_TOOLS:
                    file_path = input_data.get("file_path") or input_data.get("notebook_path")
                    compat_events.append(
                        {
                            "type": "item.completed",
                            "item": {
                                "type": "file_change",
                                "id": tool_use_id,
                                "status": status,
                                "changes": [{"path": file_path}] if file_path else [],
                            },
                        }
                    )

    if usage is not None:
        compat_events.append({"type": "turn.completed", "usage": usage})
    if not compat_events:
        return
    with events_path.open("a", encoding="utf-8") as handle:
        for event in compat_events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _extract_json_object(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        raise ValueError("No JSON object found in OpenCode text output")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("OpenCode text output did not contain parseable JSON")


def _extract_opencode_session_id(stdout_path: Path) -> str:
    for line in stdout_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            session_id = event.get("sessionID") or event.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return session_id
    raise ValueError("OpenCode JSON output did not include a sessionID")


def _extract_opencode_text_from_events(stdout_path: Path) -> str | None:
    text_parts: List[str] = []
    for line in stdout_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "text":
            continue
        part = event.get("part")
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)
    if text_parts:
        return "".join(text_parts).strip()
    return None


def append_opencode_compat_events(events_path: Path) -> None:
    compat_events: List[Dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type")
        part = event.get("part")
        if event_type == "text" and isinstance(part, dict):
            compat_events.append(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "id": part.get("id"),
                        "text": part.get("text"),
                    },
                }
            )
        elif event_type == "tool_use" and isinstance(part, dict):
            state = part.get("state")
            state = state if isinstance(state, dict) else {}
            input_data = state.get("input")
            input_data = input_data if isinstance(input_data, dict) else {}
            metadata = state.get("metadata")
            metadata = metadata if isinstance(metadata, dict) else {}
            tool = part.get("tool")
            if tool == "bash":
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": part.get("callID") or part.get("id"),
                            "command": input_data.get("command"),
                            "status": state.get("status"),
                            "exit_code": metadata.get("exit"),
                            "aggregated_output": state.get("output") or metadata.get("output"),
                        },
                    }
                )
            elif tool in {"write", "edit"}:
                file_path = input_data.get("filePath") or input_data.get("file_path")
                compat_events.append(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "file_change",
                            "id": part.get("callID") or part.get("id"),
                            "status": state.get("status"),
                            "changes": [{"path": file_path}] if file_path else [],
                        },
                    }
                )

    if not compat_events:
        return
    with events_path.open("a", encoding="utf-8") as handle:
        for event in compat_events:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def _load_opencode_export(opencode_bin: str, session_id: str, *, env: Dict[str, str]) -> Dict[str, Any]:
    command = split_command(opencode_bin) + ["export", session_id]
    result = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise ValueError(f"opencode export failed with exit code {result.returncode}: {result.stderr.strip()}")
    output = result.stdout
    json_start = output.find("{")
    if json_start < 0:
        raise ValueError("opencode export did not return JSON")
    data = json.loads(output[json_start:])
    if not isinstance(data, dict):
        raise ValueError("opencode export JSON was not an object")
    return data


def _extract_opencode_text(export_data: Dict[str, Any]) -> str:
    messages = export_data.get("messages")
    if not isinstance(messages, list):
        raise ValueError("opencode export JSON has no messages array")

    for message in reversed(messages):
        info = message.get("info") if isinstance(message, dict) else None
        if not isinstance(info, dict) or info.get("role") != "assistant":
            continue
        parts = message.get("parts")
        if not isinstance(parts, list):
            continue
        text_parts = [
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text") is not None
        ]
        text = "".join(text_parts).strip()
        if text:
            return text
    raise ValueError("opencode export did not contain assistant text")


def write_opencode_final_output(
    stdout_path: Path,
    final_path: Path,
    *,
    opencode_bin: str,
    env: Dict[str, str],
    output_schema: Path | None = None,
) -> None:
    text = _extract_opencode_text_from_events(stdout_path)
    if text is None:
        session_id = _extract_opencode_session_id(stdout_path)
        export_data = _load_opencode_export(opencode_bin, session_id, env=env)
        text = _extract_opencode_text(export_data)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_headless_json(stdout_path: Path) -> Dict[str, Any]:
    text = stdout_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Headless agent produced no JSON output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        return data

    last_object: Dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            last_object = event
    if last_object is not None:
        return last_object
    raise ValueError("Headless agent output did not contain a JSON object")


def _extract_headless_response_text(data: Dict[str, Any]) -> str:
    for key in ("response", "text", "output_text", "result", "message", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)

    output = data.get("output")
    if isinstance(output, str) and output.strip():
        return output.strip()
    if isinstance(output, list):
        text_parts: List[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text")
                        if isinstance(text, str):
                            text_parts.append(text)
        if text_parts:
            return "".join(text_parts).strip()

    assistant = data.get("assistant")
    if isinstance(assistant, dict):
        return _extract_headless_response_text(assistant)
    raise ValueError("Headless agent JSON output did not include assistant text")


def write_headless_final_output(
    stdout_path: Path,
    final_path: Path,
    *,
    output_schema: Path | None = None,
) -> None:
    data = _load_headless_json(stdout_path)
    text = _extract_headless_response_text(data)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if output_schema is None:
        final_path.write_text(text, encoding="utf-8")
        return
    structured = _extract_json_object(text)
    final_path.write_text(json.dumps(structured, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def normalize_headless_events(stdout_path: Path, *, provider: str) -> None:
    data = _load_headless_json(stdout_path)
    text = _extract_headless_response_text(data)
    usage = data.get("usage") or data.get("stats")
    events = [
        {"type": f"{provider}.raw", "payload": data},
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "id": f"{provider}-final",
                "text": text,
            },
        },
        {"type": "turn.completed", "usage": usage},
    ]
    stdout_path.write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


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
            "--rm",
            "-i",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "512",
            "--memory",
            "6g",
            "--cpus",
            "4",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=1g",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace",
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


async def _pump_stream(stream: asyncio.StreamReader, path: Path) -> None:
    with path.open("wb") as handle:
        while True:
            chunk = await stream.read(65536)
            if not chunk:
                break
            handle.write(chunk)
            handle.flush()


async def run_codex_process(
    command: Iterable[str],
    *,
    cwd: Path,
    prompt: str,
    env: Dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
    timeout_seconds: int,
) -> ProcessResult:
    command_list = list(command)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    proc = await asyncio.create_subprocess_exec(
        *command_list,
        cwd=str(cwd),
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert proc.stdin is not None
    assert proc.stdout is not None
    assert proc.stderr is not None

    stdout_task = asyncio.create_task(_pump_stream(proc.stdout, stdout_path))
    stderr_task = asyncio.create_task(_pump_stream(proc.stderr, stderr_path))

    proc.stdin.write(prompt.encode("utf-8"))
    await proc.stdin.drain()
    proc.stdin.close()

    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        await proc.wait()

    await asyncio.gather(stdout_task, stderr_task)
    ended_at = datetime.now(timezone.utc).isoformat()
    duration = time.monotonic() - started
    exit_code = proc.returncode
    status = "timeout" if timed_out else ("success" if exit_code == 0 else "failed")
    return ProcessResult(
        command=command_list,
        exit_code=exit_code,
        status=status,
        timed_out=timed_out,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration,
    )


async def run_codex_process_in_docker(
    *,
    codex_bin: str,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    codex_home: Path,
    prompt: str,
    auth_mode: str,
    stdout_path: Path,
    stderr_path: Path,
    host_final_path: Path,
    timeout_seconds: int,
    sandbox: str,
    model: str | None = None,
    allow_web_search: bool = False,
    include_trace_config: bool = True,
    output_schema: Path | None = None,
) -> ProcessResult:
    runner_dir = workspace / ".runner"
    runner_dir.mkdir(parents=True, exist_ok=True)
    docker_auth_home = codex_home / "docker"
    auth_env = prepare_isolated_auth_home(docker_auth_home, auth_mode)
    container_schema = None
    if output_schema is not None:
        raise ValueError("Docker Codex process currently supports executor runs only; evaluator schemas are host-local.")

    container_final_path = Path("/workspace/.runner/final.md")
    inner_command = build_codex_exec_command(
        codex_bin,
        cwd=Path("/workspace"),
        final_path=container_final_path,
        sandbox=sandbox,
        output_schema=container_schema,
        model=model,
        allow_web_search=allow_web_search,
        include_trace_config=include_trace_config,
    )
    container_name = f"starbench-{uuid.uuid4().hex[:12]}"
    command = build_docker_codex_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        codex_home=docker_auth_home,
        inner_command=inner_command,
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
        # Killing the docker CLI client does not stop the container itself;
        # without this the timed-out container keeps running and writing into
        # the mounted workspace.
        subprocess.run(
            split_command(docker_bin) + ["kill", container_name],
            check=False,
            capture_output=True,
        )

    container_final_on_host = workspace / ".runner" / "final.md"
    if container_final_on_host.exists():
        host_final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(container_final_on_host, host_final_path)
    return result


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
        extra_env=dict(spec.env),
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
