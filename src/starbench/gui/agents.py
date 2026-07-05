"""Agent runtimes: the second resource side of the console.

The console knows two kinds of runtimes. Built-in runtimes are the five
coding-agent CLIs the runner supports natively. Custom runtimes are
`runtimes/<id>.json` spec files — the exact files `starbench-run` consumes
via `--executor-agent custom:<id>` — so the console and the CLI share one
source of truth and cannot drift.

The console stores a few presentation-only keys in the same JSON (`label`,
`icon`, `protocol`, `base_url_env`, `api_key_env`); the runner's loader
ignores unknown keys. `protocol` decides which AI providers the console
offers for the runtime, and `base_url_env` / `api_key_env` name the
environment variables through which the selected provider's endpoint and
credential are injected at launch. Validation is delegated to the runner's
own loader so a spec the console accepts is a spec the CLI accepts.
"""

from __future__ import annotations

import json
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runner.codex_process import DEFAULT_DOCKER_IMAGES
from ..runner.custom_runtime import load_custom_runtime
from .data import SAFE_ID

DEFAULT_RUNTIMES_DIR = Path(__file__).resolve().parents[3] / "runtimes"

PROTOCOL_CHOICES = ("openai", "anthropic", "gemini", "none")

# Every built-in runtime executes in Docker isolation, each in its own image
# (the runner resolves the image per runtime; see DEFAULT_DOCKER_IMAGES).
BUILTIN_AGENTS: List[Dict[str, Any]] = [
    {
        "id": "claude",
        "label": "Claude Code",
        "note": "Anthropic's coding agent",
        "protocol": "anthropic",
        "docker_capable": True,
        "docker_image": DEFAULT_DOCKER_IMAGES["claude"],
        "bin": "claude",
    },
    {
        "id": "codex",
        "label": "Codex",
        "note": "OpenAI's coding agent",
        "protocol": "openai",
        "docker_capable": True,
        "docker_image": DEFAULT_DOCKER_IMAGES["codex"],
        "bin": "codex",
    },
    {
        "id": "gemini",
        "label": "Gemini CLI",
        "note": "Google's coding agent",
        "protocol": "gemini",
        "docker_capable": True,
        "docker_image": DEFAULT_DOCKER_IMAGES["gemini"],
        "bin": "gemini",
    },
    {
        "id": "grok",
        "label": "Grok Build",
        "note": "xAI's coding agent",
        "protocol": "xai",
        "docker_capable": True,
        "docker_image": DEFAULT_DOCKER_IMAGES["grok"],
        "bin": "grok",
    },
    {
        "id": "opencode",
        "label": "OpenCode",
        "note": "Open-source agent for OpenAI-compatible models",
        "protocol": "openai",
        "docker_capable": True,
        "docker_image": DEFAULT_DOCKER_IMAGES["opencode"],
        "bin": "opencode",
    },
]

BUILTIN_IDS = {agent["id"] for agent in BUILTIN_AGENTS}

CONSOLE_FIELDS = ("label", "icon", "protocol", "base_url_env", "api_key_env")


class AgentError(ValueError):
    pass


def _cli_probe(command: str) -> Dict[str, Any]:
    try:
        first = shlex.split(command)[0] if command.strip() else ""
    except ValueError:
        first = command.split()[0] if command.split() else ""
    path = shutil.which(first) if first else None
    return {"bin": first, "present": bool(path), "path": path}


def _read_raw_spec(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def list_agents(runtimes_dir: Path) -> Dict[str, Any]:
    builtin = [
        {
            "id": agent["id"],
            "label": agent["label"],
            "note": agent["note"],
            "protocol": agent["protocol"],
            "docker_capable": agent["docker_capable"],
            "docker_image": agent["docker_image"],
            "builtin": True,
            "cli": _cli_probe(agent["bin"]),
        }
        for agent in BUILTIN_AGENTS
    ]
    custom: List[Dict[str, Any]] = []
    if runtimes_dir.is_dir():
        for path in sorted(runtimes_dir.glob("*.json")):
            spec_id = path.stem
            try:
                spec = load_custom_runtime(runtimes_dir, spec_id)
                raw = _read_raw_spec(path)
            except (ValueError, OSError) as error:
                custom.append(
                    {
                        "id": f"custom:{spec_id}",
                        "spec_id": spec_id,
                        "builtin": False,
                        "error": str(error),
                        "source_path": str(path),
                    }
                )
                continue
            protocol = str(raw.get("protocol") or "none")
            custom.append(
                {
                    "id": f"custom:{spec_id}",
                    "spec_id": spec_id,
                    "builtin": False,
                    "label": str(raw.get("label") or spec_id),
                    "icon": str(raw.get("icon") or ""),
                    "protocol": protocol if protocol in PROTOCOL_CHOICES else "none",
                    "base_url_env": str(raw.get("base_url_env") or ""),
                    "api_key_env": str(raw.get("api_key_env") or ""),
                    "command": spec.command,
                    "args": spec.args,
                    "judge_args": spec.judge_args,
                    "judge_args_inherited": raw.get("judge_args") is None,
                    "model_flag": spec.model_flag,
                    "prompt_via": spec.prompt_via,
                    "prompt_flag": spec.prompt_flag,
                    "parser": spec.parser,
                    "env": dict(spec.env),
                    "docker_image": spec.docker_image,
                    "docker_env_passthrough": spec.docker_env_passthrough,
                    "docker_capable": spec.docker_image is not None,
                    "cli": _cli_probe(spec.command),
                    "source_path": str(path),
                    "error": None,
                }
            )
    return {
        "runtimes_dir": str(runtimes_dir),
        "builtin": builtin,
        "custom": custom,
    }


def get_custom_agent(runtimes_dir: Path, spec_id: str) -> Optional[Dict[str, Any]]:
    for agent in list_agents(runtimes_dir)["custom"]:
        if agent["spec_id"] == spec_id and not agent.get("error"):
            return agent
    return None


def _string_list(value: Any, label: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AgentError(f"{label} must be a list of strings.")
    return [item for item in value if item.strip()]


def save_custom_agent(runtimes_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    spec_id = str(payload.get("id") or "").strip()
    if not SAFE_ID.match(spec_id):
        raise AgentError(
            "Runtime id is required and may contain only letters, digits, dot, dash, underscore."
        )
    if spec_id in BUILTIN_IDS:
        raise AgentError(f"`{spec_id}` is a built-in runtime; pick a different id.")

    command = str(payload.get("command") or "").strip()
    if not command:
        raise AgentError("Command is required (the CLI executable, e.g. `qwen`).")

    protocol = str(payload.get("protocol") or "none")
    if protocol not in PROTOCOL_CHOICES:
        raise AgentError(f"Protocol must be one of {', '.join(PROTOCOL_CHOICES)}.")

    env = payload.get("env") or {}
    if not isinstance(env, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise AgentError("Static env must be an object of string values.")

    data: Dict[str, Any] = {
        "id": spec_id,
        "command": command,
        "args": _string_list(payload.get("args"), "args"),
        "parser": str(payload.get("parser") or ""),
        "prompt_via": str(payload.get("prompt_via") or "stdin"),
    }
    if payload.get("judge_args") is not None:
        data["judge_args"] = _string_list(payload.get("judge_args"), "judge_args")
    model_flag = str(payload.get("model_flag") or "").strip()
    if model_flag:
        data["model_flag"] = model_flag
    if data["prompt_via"] == "arg":
        data["prompt_flag"] = str(payload.get("prompt_flag") or "")
    if env:
        data["env"] = {key: value for key, value in env.items() if key.strip()}
    docker_image = str(payload.get("docker_image") or "").strip()
    if docker_image:
        data["docker"] = {
            "image": docker_image,
            "env_passthrough": _string_list(
                payload.get("docker_env_passthrough"), "docker_env_passthrough"
            ),
        }

    data["protocol"] = protocol
    for field in ("label", "icon", "base_url_env", "api_key_env"):
        value = str(payload.get(field) or "").strip()
        if value:
            data[field] = value

    # The runner's loader is the single validator: a spec the console writes
    # is exactly a spec `starbench-run` will accept.
    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / f"{spec_id}.json"
        candidate.write_text(json.dumps(data), encoding="utf-8")
        try:
            load_custom_runtime(Path(tmp), spec_id)
        except ValueError as error:
            raise AgentError(str(error).replace(str(candidate), f"{spec_id}.json"))

    runtimes_dir.mkdir(parents=True, exist_ok=True)
    (runtimes_dir / f"{spec_id}.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    saved = get_custom_agent(runtimes_dir, spec_id)
    assert saved is not None
    return saved


def delete_custom_agent(runtimes_dir: Path, spec_id: str) -> Dict[str, Any]:
    if not SAFE_ID.match(spec_id):
        raise AgentError(f"Invalid runtime id: {spec_id!r}")
    path = runtimes_dir / f"{spec_id}.json"
    if not path.exists():
        raise AgentError(f"No custom runtime named {spec_id}.")
    path.unlink()
    return {"deleted": spec_id}


# ---------------------------------------------------------------------------
# Templates: verified starting points. Flags drift between CLI versions, so
# every template is a draft the user confirms against `<cli> --help`.
# ---------------------------------------------------------------------------

AGENT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "template_id": "qwen-code",
        "title": "Qwen Code",
        "docs_url": "https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/",
        "description": (
            "Gemini CLI fork by the Qwen team. Documented headless mode with JSON "
            "output; speaks the OpenAI protocol through OPENAI_BASE_URL / "
            "OPENAI_API_KEY, so any OpenAI-compatible provider works."
        ),
        "spec": {
            "id": "qwen-code",
            "label": "Qwen Code",
            "icon": "qwen",
            "command": "qwen",
            "args": ["--output-format", "json", "--yolo"],
            "judge_args": ["--output-format", "json", "--approval-mode", "plan"],
            "model_flag": "-m",
            "prompt_via": "stdin",
            "parser": "headless-json",
            "protocol": "openai",
            "base_url_env": "OPENAI_BASE_URL",
            "api_key_env": "OPENAI_API_KEY",
            "docker": {
                "image": "starbench-qwen:latest",
                "env_passthrough": ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
            },
        },
    },
    {
        "template_id": "kimi-code",
        "title": "Kimi Code CLI",
        "docs_url": "https://moonshotai.github.io/kimi-cli/en/customization/print-mode.html",
        "description": (
            "Moonshot AI's terminal agent. Print mode reads the prompt from stdin; "
            "output is the final message as plain text. Speaks to API providers "
            "through an OpenAI-compatible entry in ~/.kimi/config.toml (run /login "
            "once); OPENAI_BASE_URL / OPENAI_API_KEY override that entry per run. "
            "No model flag — the model comes from the CLI's config. Host-local for "
            "now: starting in a fresh container without its config file is "
            "unverified."
        ),
        "spec": {
            "id": "kimi-code",
            "label": "Kimi Code CLI",
            "icon": "kimi",
            "command": "kimi",
            "args": ["--print", "--output-format", "text", "--final-message-only"],
            "prompt_via": "stdin",
            "parser": "text",
            "protocol": "openai",
            "base_url_env": "OPENAI_BASE_URL",
            "api_key_env": "OPENAI_API_KEY",
        },
    },
    {
        "template_id": "trae-agent",
        "title": "Trae Agent",
        "docs_url": "https://github.com/bytedance/trae-agent",
        "description": (
            "ByteDance's open-source research agent (`trae-cli`). The task is a "
            "positional argument — very large prompts can exceed the OS argv "
            "limit. Providers are configured through OPENAI_BASE_URL / "
            "OPENAI_API_KEY (or trae_config.yaml)."
        ),
        "spec": {
            "id": "trae-agent",
            "label": "Trae Agent",
            "icon": "trae",
            "command": "trae-cli",
            "args": ["run", "--provider", "openai"],
            "model_flag": "--model",
            "prompt_via": "arg",
            "prompt_flag": "",
            "parser": "text",
            "protocol": "openai",
            "base_url_env": "OPENAI_BASE_URL",
            "api_key_env": "OPENAI_API_KEY",
            "docker": {
                "image": "starbench-trae-agent:latest",
                "env_passthrough": ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
            },
        },
    },
]


def agent_templates() -> List[Dict[str, Any]]:
    return AGENT_TEMPLATES


__all__ = [
    "AgentError",
    "AGENT_TEMPLATES",
    "BUILTIN_AGENTS",
    "BUILTIN_IDS",
    "DEFAULT_RUNTIMES_DIR",
    "PROTOCOL_CHOICES",
    "agent_templates",
    "delete_custom_agent",
    "get_custom_agent",
    "list_agents",
    "save_custom_agent",
]
