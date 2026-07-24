"""Agent runtimes: the second resource side of the console.

The console knows two kinds of runtimes. Built-in runtimes are the five
coding-agent CLIs the runner supports natively. Custom runtimes are
`runtimes/<id>.json` spec files — the exact files `starbench-run` consumes
via `--executor-agent custom:<id>` — so the console and the CLI share one
source of truth and cannot drift.

The shared ``CustomRuntimeSpec`` owns presentation, protocol, credential,
command, parser, and Docker metadata. The GUI consumes that normalized object
rather than reparsing raw JSON, so a spec the console accepts is exactly a spec
the CLI accepts.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..adapters import list_builtin, provider_filter_for_protocol
from ..adapters.base import ProviderFilter, RuntimeInfo
from ..execution.probe import extract_version, run_probe, tail
from ..runner.custom_runtime import load_custom_runtime
from . import contracts
from .data import SAFE_ID

DEFAULT_RUNTIMES_DIR = Path(__file__).resolve().parents[3] / "runtimes"

PROTOCOL_CHOICES = ("openai", "anthropic", "gemini", "none")

CLI_VERSION_TIMEOUT_SECONDS = 3
NPM_VIEW_TIMEOUT_SECONDS = 8
INSTALL_TIMEOUT_SECONDS = 300
STATUS_PROBE_MAX_WORKERS = 8

# Local `--version` probes are cheap but not free (a subprocess per runtime);
# npm lookups hit the network. Cache both so the Agents page stays fast and
# an offline machine does not stall on every paint. Keyed by (agent_id, bin).
LOCAL_STATUS_TTL_SECONDS = 60.0
NPM_LATEST_TTL_SECONDS = 600.0
_STATUS_CACHE_LOCK = threading.Lock()
_LOCAL_STATUS_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_NPM_LATEST_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}

# Two concurrent `npm install -g` runs write into the same global prefix;
# serialize installs and reject the second click instead of queueing it.
_INSTALL_LOCK = threading.Lock()


def _npm_spec(package: str, docs_url: str = "") -> Dict[str, Any]:
    return {
        "manager": "npm",
        "name": package,
        "install_command": ["npm", "install", "-g", f"{package}@latest", "--no-fund", "--no-audit"],
        "update_command": ["npm", "install", "-g", f"{package}@latest", "--no-fund", "--no-audit"],
        "docs_url": docs_url,
    }


INSTALL_SPECS: Dict[str, Dict[str, Any]] = {
    "claude": _npm_spec(
        "@anthropic-ai/claude-code",
        "https://docs.anthropic.com/en/docs/claude-code/setup",
    ),
    "codex": _npm_spec("@openai/codex", "https://developers.openai.com/codex/cli"),
    "gemini": _npm_spec(
        "@google/gemini-cli",
        "https://github.com/google-gemini/gemini-cli",
    ),
    "grok": _npm_spec("@xai-official/grok", "https://www.npmjs.com/package/@xai-official/grok"),
    "opencode": _npm_spec("opencode-ai", "https://opencode.ai/docs"),
    "custom:qwen-code": _npm_spec(
        "@qwen-code/qwen-code",
        "https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/",
    ),
    "custom:kimi-code": _npm_spec(
        "@moonshot-ai/kimi-code",
        "https://moonshotai.github.io/kimi-cli/en/customization/print-mode.html",
    ),
}


def _provider_filter_dict(pf: ProviderFilter) -> Dict[str, Any]:
    return {
        "kinds": list(pf.kinds),
        "accepts_anthropic_endpoint": pf.accepts_anthropic_endpoint,
        "accepts_gemini_endpoint": pf.accepts_gemini_endpoint,
    }


def _builtin_row(info: RuntimeInfo) -> Dict[str, Any]:
    # Every built-in runtime executes in Docker isolation, each in its own image
    # (resolved from the adapter registry's RuntimeInfo, the single source).
    return {
        "id": info.id,
        "label": info.label,
        "note": info.description,
        "protocol": info.protocol,
        "docker_capable": info.docker_capable,
        "docker_image": info.docker_image,
        "bin": info.bin,
        "provider_filter": _provider_filter_dict(info.provider_filter),
        "thinking_channel": info.thinking_channel,
        "thinking_efforts": list(info.thinking_efforts),
        "enforces_web_search": info.enforces_web_search,
    }


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

BUILTIN_IDS = {agent["id"] for agent in BUILTIN_AGENTS}

CONSOLE_FIELDS = ("label", "description", "icon", "protocol", "base_url_env", "api_key_env")


class AgentError(ValueError):
    pass


def _cli_probe(command: str) -> Dict[str, Any]:
    try:
        first = shlex.split(command)[0] if command.strip() else ""
    except ValueError:
        first = command.split()[0] if command.split() else ""
    path = shutil.which(first) if first else None
    return {"bin": first, "present": bool(path), "path": path}


def _run(command: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess:
    # Thin seam over the shared probe helper (tests monkeypatch this).
    # Env sanitisation (forced NO_COLOR/TERM) lives in execution.probe.
    return run_probe(command, timeout=timeout)


def _version_key(version: str) -> tuple:
    """Approximate-semver sort key: (numbers, is_final_release, prerelease).

    A final release outranks any pre-release with the same numbers, so
    `1.0.0-rc1` installed with `1.0.0` published reports an update. Two
    pre-release strings compare lexically — an approximation of semver's
    identifier-by-identifier rules, good enough for update hints.
    """
    base, sep, prerelease = version.partition("-")
    parts = [int(part) for part in re.findall(r"\d+", base)[:3]]
    while len(parts) < 3:
        parts.append(0)
    is_final = not sep
    return (tuple(parts), is_final, "" if is_final else prerelease)


def _is_newer(latest: Optional[str], current: Optional[str]) -> Optional[bool]:
    if not latest or not current:
        return None
    return _version_key(latest) > _version_key(current)


def _local_version(cli: Dict[str, Any]) -> Dict[str, Optional[str]]:
    if not cli.get("present"):
        return {"version": None, "version_output": None, "version_error": None}
    command = [str(cli.get("path") or cli.get("bin")), "--version"]
    try:
        result = _run(command, timeout=CLI_VERSION_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "version": None,
            "version_output": None,
            "version_error": f"Could not read version: {error}",
        }
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    version = extract_version(output)
    return {
        "version": version,
        "version_output": tail(output, 500) or None,
        "version_error": None if version else "Version output did not include a semver.",
    }


def _latest_npm_version(package: str) -> Dict[str, Optional[str]]:
    checked_at = datetime.now(timezone.utc).isoformat()
    if not shutil.which("npm"):
        return {
            "latest_version": None,
            "latest_checked_at": checked_at,
            "latest_error": "`npm` is not on PATH.",
        }
    try:
        result = _run(["npm", "view", package, "version", "--silent"], timeout=NPM_VIEW_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "latest_version": None,
            "latest_checked_at": checked_at,
            "latest_error": f"Could not check npm registry: {error}",
        }
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    if result.returncode != 0:
        return {
            "latest_version": None,
            "latest_checked_at": checked_at,
            "latest_error": tail(output, 500) or f"npm exited with {result.returncode}.",
        }
    version = extract_version(output)
    return {
        "latest_version": version,
        "latest_checked_at": checked_at,
        "latest_error": None if version else "npm did not return a semver.",
    }


def _runtime_targets(runtimes_dir: Path) -> List[Dict[str, str]]:
    targets = [
        {"id": agent["id"], "bin": agent["bin"]}
        for agent in BUILTIN_AGENTS
        if str(agent.get("bin") or "")
    ]
    if runtimes_dir.is_dir():
        for path in sorted(runtimes_dir.glob("*.json")):
            spec_id = path.stem
            try:
                spec = load_custom_runtime(runtimes_dir, spec_id)
            except (ValueError, OSError):
                continue
            cli = _cli_probe(spec.command)
            if cli["bin"]:
                targets.append({"id": f"custom:{spec_id}", "bin": cli["bin"]})
    return targets


_LATEST_NOT_CHECKED = {
    "latest_version": None,
    "latest_checked_at": None,
    "latest_error": None,
}


def _clear_status_caches() -> None:
    """Drop cached probe results (used by tests and nowhere else)."""
    with _STATUS_CACHE_LOCK:
        _LOCAL_STATUS_CACHE.clear()
        _NPM_LATEST_CACHE.clear()


def _cached_local_status(agent_id: str, bin_name: str) -> Dict[str, Any]:
    key = (agent_id, bin_name)
    now = time.monotonic()
    with _STATUS_CACHE_LOCK:
        cached = _LOCAL_STATUS_CACHE.get(key)
        if cached and now - cached[0] < LOCAL_STATUS_TTL_SECONDS:
            return dict(cached[1])
    cli = _cli_probe(bin_name)
    status = {**cli, **_local_version(cli)}
    with _STATUS_CACHE_LOCK:
        _LOCAL_STATUS_CACHE[key] = (time.monotonic(), dict(status))
    return status


def _cached_npm_latest(agent_id: str, bin_name: str, package_name: str) -> Dict[str, Any]:
    cached = _npm_latest_from_cache(agent_id, bin_name)
    if cached is not None:
        return cached
    latest = _latest_npm_version(package_name)
    with _STATUS_CACHE_LOCK:
        _NPM_LATEST_CACHE[(agent_id, bin_name)] = (time.monotonic(), dict(latest))
    return latest


def _npm_latest_from_cache(agent_id: str, bin_name: str) -> Optional[Dict[str, Any]]:
    """A still-fresh npm answer, or None. Never touches the network."""
    with _STATUS_CACHE_LOCK:
        cached = _NPM_LATEST_CACHE.get((agent_id, bin_name))
        if cached and time.monotonic() - cached[0] < NPM_LATEST_TTL_SECONDS:
            return dict(cached[1])
    return None


def agent_statuses(
    runtimes_dir: Path, *, check_updates: bool = False
) -> "contracts.AgentStatusPayload":
    """Probe every runtime's local CLI; optionally check npm for updates.

    Probes run in parallel (a serial pass over ~8 runtimes at multi-second
    timeouts kept the page hostage), and npm — the only network hop — runs
    only when the caller explicitly asks for an update check. When it did not
    ask, a still-fresh cached npm answer is served anyway (the console already
    knows it; hiding it just made pages forget updates on reload), and only
    with a cold cache do the `latest_*` fields stay None, which the UI renders
    as "not checked", distinct from a failed check.
    """

    def probe(target: Dict[str, str]) -> Dict[str, Any]:
        local = _cached_local_status(target["id"], target["bin"])
        package = INSTALL_SPECS.get(target["id"])
        if package and package.get("manager") == "npm":
            if check_updates:
                latest = _cached_npm_latest(target["id"], target["bin"], package["name"])
            else:
                latest = (
                    _npm_latest_from_cache(target["id"], target["bin"])
                    or dict(_LATEST_NOT_CHECKED)
                )
        else:
            latest = dict(_LATEST_NOT_CHECKED)
        return {
            "id": target["id"],
            "bin": local["bin"],
            "present": local["present"],
            "path": local["path"],
            "version": local["version"],
            "version_output": local["version_output"],
            "version_error": local["version_error"],
            "package": package,
            **latest,
            "update_available": _is_newer(latest.get("latest_version"), local.get("version")),
            "installable": bool(package),
        }

    targets = _runtime_targets(runtimes_dir)
    statuses: Dict[str, Any] = {}
    if targets:
        with ThreadPoolExecutor(max_workers=STATUS_PROBE_MAX_WORKERS) as pool:
            rows = list(pool.map(probe, targets))
        for target, row in zip(targets, rows):
            statuses[target["id"]] = row
    return {"statuses": statuses}


def install_agent(agent_id: str) -> "contracts.AgentInstallResult":
    package = INSTALL_SPECS.get(agent_id)
    if not package:
        raise AgentError(f"No built-in installer is available for {agent_id}.")
    if not _INSTALL_LOCK.acquire(blocking=False):
        raise AgentError("An install is already running; wait for it to finish.")
    try:
        return _install_agent_locked(agent_id, package)
    finally:
        _INSTALL_LOCK.release()


def _install_agent_locked(
    agent_id: str, package: Dict[str, Any]
) -> "contracts.AgentInstallResult":
    command = list(package["install_command"])
    try:
        result = _run(command, timeout=INSTALL_TIMEOUT_SECONDS)
    except FileNotFoundError as error:
        return {
            "id": agent_id,
            "command": command,
            "status": "failed",
            "exit_code": None,
            "stdout_tail": "",
            "stderr_tail": str(error),
        }
    except subprocess.TimeoutExpired as error:
        return {
            "id": agent_id,
            "command": command,
            "status": "failed",
            "exit_code": None,
            "stdout_tail": tail(error.stdout or ""),
            "stderr_tail": tail(error.stderr or "Install timed out."),
        }
    return {
        "id": agent_id,
        "command": command,
        "status": "installed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "stdout_tail": tail(result.stdout),
        "stderr_tail": tail(result.stderr),
    }


def list_agents(runtimes_dir: Path) -> "contracts.AgentsPayload":
    # Response shape is defined once in contracts.AgentsPayload; the TS client
    # type is generated from it (make gen-types).
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
            "provider_filter": agent["provider_filter"],
            "thinking_channel": agent["thinking_channel"],
            "thinking_efforts": agent["thinking_efforts"],
            "enforces_web_search": agent["enforces_web_search"],
        }
        for agent in BUILTIN_AGENTS
    ]
    custom: List[Dict[str, Any]] = []
    if runtimes_dir.is_dir():
        for path in sorted(runtimes_dir.glob("*.json")):
            spec_id = path.stem
            try:
                spec = load_custom_runtime(runtimes_dir, spec_id)
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
            custom.append(
                {
                    "id": f"custom:{spec_id}",
                    "spec_id": spec_id,
                    "builtin": False,
                    "label": spec.label,
                    "description": spec.description,
                    "icon": spec.icon,
                    "protocol": spec.protocol,
                    "provider_filter": _provider_filter_dict(
                        provider_filter_for_protocol(spec.protocol)
                    ),
                    "base_url_env": spec.base_url_env,
                    "api_key_env": spec.api_key_env,
                    "command": spec.command,
                    "args": spec.args,
                    "judge_args": spec.judge_args,
                    "judge_args_inherited": spec.judge_args_inherited,
                    "model_flag": spec.model_flag,
                    "prompt_via": spec.prompt_via,
                    "prompt_flag": spec.prompt_flag,
                    "parser": spec.parser,
                    "env": dict(spec.env),
                    "docker_image": spec.docker_image,
                    "docker_env_passthrough": spec.docker_env_passthrough,
                    "docker_capable": spec.docker_image is not None,
                    # Custom runtimes have no native switch the runner knows
                    # about; thinking effort reaches them as a prompt instruction.
                    "thinking_channel": "prompt",
                    "thinking_efforts": ["none", "low", "medium", "high"],
                    "enforces_web_search": False,
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
    for field in ("label", "description", "icon", "base_url_env", "api_key_env"):
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
            "description": "Alibaba's coding agent (Qwen)",
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
            "output is the final message as plain text. OPENAI_BASE_URL / "
            "OPENAI_API_KEY override the OpenAI-compatible provider in its config "
            "(~/.kimi/config.toml locally; the Docker image ships a seeded config). "
            "No model flag — the model comes from that config."
        ),
        "spec": {
            "id": "kimi-code",
            "label": "Kimi Code CLI",
            "description": "Moonshot AI's coding agent",
            "icon": "kimi",
            "command": "kimi",
            "args": ["--print", "--output-format", "text", "--final-message-only"],
            "prompt_via": "stdin",
            "parser": "text",
            "protocol": "openai",
            "base_url_env": "OPENAI_BASE_URL",
            "api_key_env": "OPENAI_API_KEY",
            "docker": {
                "image": "starbench-kimi:latest",
                "env_passthrough": ["OPENAI_API_KEY", "OPENAI_BASE_URL"],
            },
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
            "description": "ByteDance's open-source coding agent",
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
    "INSTALL_SPECS",
    "PROTOCOL_CHOICES",
    "agent_statuses",
    "agent_templates",
    "delete_custom_agent",
    "get_custom_agent",
    "install_agent",
    "list_agents",
    "save_custom_agent",
]
