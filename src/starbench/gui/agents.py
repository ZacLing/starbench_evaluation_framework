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
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple

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
GITHUB_LATEST_TIMEOUT_SECONDS = 8
INSTALL_TIMEOUT_SECONDS = 300
STATUS_PROBE_MAX_WORKERS = 8

# Local `--version` probes are cheap but not free (a subprocess per runtime);
# latest-version lookups hit the network (npm registry or the GitHub releases
# API, whose anonymous quota is 60 requests/hour — the cache is what keeps the
# console under it). Cache both so the Agents page stays fast and an offline
# machine does not stall on every paint. Keyed by (agent_id, bin).
LOCAL_STATUS_TTL_SECONDS = 60.0
LATEST_TTL_SECONDS = 600.0
_STATUS_CACHE_LOCK = threading.Lock()
_LOCAL_STATUS_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_LATEST_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}

# Two concurrent `npm install -g` runs write into the same global prefix;
# serialize installs and reject the second click instead of queueing it.
_INSTALL_LOCK = threading.Lock()


def _script_domain(script: str) -> Optional[str]:
    match = re.search(r"https?://([^/\s]+)", script)
    return match.group(1) if match else None


def _npm_spec(
    package: str, bin_name: str, docs_url: str = "", *, extra_args: Sequence[str] = ()
) -> Dict[str, Any]:
    command = [
        "npm",
        "install",
        "-g",
        f"{package}@latest",
        "--no-fund",
        "--no-audit",
        *extra_args,
    ]
    return {
        "channel": "npm",
        "name": package,
        "bin": bin_name,
        "install_command": list(command),
        "update_command": list(command),
        "latest_source": {"npm": package},
        "script_domain": None,
        "docs_url": docs_url,
    }


def _standalone_spec(
    bin_name: str,
    script: str,
    github_repo: str,
    docs_url: str = "",
    *,
    update_command: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """A runtime installed through the vendor's own installer script.

    ``update_command`` is the CLI's self-updater when it has one — preferred
    over re-running the script because the CLI identifies its own install
    channel and swaps binaries atomically. Without one, updating re-runs the
    official installer.
    """
    install = ["bash", "-lc", script]
    return {
        "channel": "standalone",
        "name": None,
        "bin": bin_name,
        "install_command": list(install),
        "update_command": list(update_command) if update_command else list(install),
        "latest_source": {"github": github_repo},
        "script_domain": _script_domain(script),
        "docs_url": docs_url,
    }


# Each runtime installs through the channel its vendor officially recommends —
# standalone installer scripts where they exist, npm where npm *is* the
# official channel. A console that installs through a different channel than
# the one already on the operator's machine produces shadowed installs that
# never take effect (the incident that motivated this table).
INSTALL_SPECS: Dict[str, Dict[str, Any]] = {
    "claude": _standalone_spec(
        "claude",
        "curl -fsSL https://claude.ai/install.sh | bash",
        "anthropics/claude-code",
        "https://docs.anthropic.com/en/docs/claude-code/setup",
        update_command=("claude", "update"),
    ),
    "codex": _standalone_spec(
        "codex",
        "curl -fsSL https://chatgpt.com/codex/install.sh | sh",
        "openai/codex",
        "https://developers.openai.com/codex/cli",
        update_command=("codex", "update"),
    ),
    # npm is the Gemini CLI's officially recommended channel (its Homebrew
    # formula carries a deprecation notice).
    "gemini": _npm_spec(
        "@google/gemini-cli",
        "gemini",
        "https://github.com/google-gemini/gemini-cli",
    ),
    # x.ai serves its curl installer behind a Cloudflare challenge that blocks
    # non-browser fetches; npm is the reliable official channel.
    "grok": _npm_spec(
        "@xai-official/grok", "grok", "https://www.npmjs.com/package/@xai-official/grok"
    ),
    "opencode": _standalone_spec(
        "opencode",
        "curl -fsSL https://opencode.ai/install | bash",
        "anomalyco/opencode",
        "https://opencode.ai/docs",
        update_command=("opencode", "upgrade"),
    ),
    # pi pulls an optional native dependency; the console triggers this install
    # on the operator's own machine, so no package lifecycle script from the
    # resolved tree gets to run here.
    "pi": _npm_spec(
        "@earendil-works/pi-coding-agent",
        "pi",
        "https://pi.dev/docs",
        extra_args=("--ignore-scripts",),
    ),
    "custom:qwen-code": _npm_spec(
        "@qwen-code/qwen-code",
        "qwen",
        "https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/",
    ),
    # kimi-code has no self-update subcommand; re-running the installer is the
    # official update path (it fetches the latest release into ~/.kimi-code).
    "custom:kimi-code": _standalone_spec(
        "kimi",
        "curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash",
        "MoonshotAI/kimi-code",
        "https://moonshotai.github.io/kimi-cli/en/customization/print-mode.html",
    ),
}


# ---------------------------------------------------------------------------
# Channel identity. Several install channels can coexist on one machine and
# silently shadow each other through PATH order (the incident this exists
# for: a stale standalone codex shadowing every npm-installed update, so
# updating "succeeded" forever without taking effect). Classification is by
# realpath markers observed in each channel's install layout; shadow
# detection scans each runtime's known install drop points in addition to
# the PATH hit and reports coexistence instead of trusting a single lookup.
# ---------------------------------------------------------------------------

_STANDALONE_REALPATH_MARKERS = (
    "/.codex/packages/standalone/",  # codex official installer
    "/.local/share/claude/versions/",  # Claude Code native installer
    "/.opencode/bin/",  # opencode installer
    "/.kimi-code/",  # kimi-code installer (KIMI_INSTALL_DIR default)
)

# Launch points each standalone installer drops beyond whatever PATH says:
# the entry symlink/binary the installer creates. Keyed like INSTALL_SPECS.
_STANDALONE_PROBE_PATHS: Dict[str, Tuple[str, ...]] = {
    "codex": ("~/.local/bin/codex",),
    "claude": ("~/.local/bin/claude",),
    "opencode": ("~/.opencode/bin/opencode",),
    "custom:kimi-code": ("~/.kimi-code/bin/kimi",),
}


def _classify_real_path(real_path: str) -> str:
    for marker in _STANDALONE_REALPATH_MARKERS:
        if marker in real_path:
            return "standalone"
    # node_modules must be tested before the Homebrew prefix: an
    # npm-under-Homebrew global binary also resolves below /opt/homebrew.
    if "/node_modules/" in real_path:
        return "npm"
    if "/Cellar/" in real_path:
        return "homebrew"
    return "unknown"


def classify_channel(path: str) -> str:
    """Which install channel the binary at ``path`` belongs to, by realpath."""
    return _classify_real_path(os.path.realpath(os.path.expanduser(path)))


# `npm prefix -g` is a subprocess whose answer effectively never changes
# within a console session; probe it once per process (tests reset it).
_NPM_PREFIX_UNSET = object()
_npm_global_bin_cache: Any = _NPM_PREFIX_UNSET


def _npm_global_bin() -> Optional[Path]:
    global _npm_global_bin_cache
    with _STATUS_CACHE_LOCK:
        if _npm_global_bin_cache is not _NPM_PREFIX_UNSET:
            return _npm_global_bin_cache
    bin_dir: Optional[Path] = None
    if shutil.which("npm"):
        try:
            result = _run(["npm", "prefix", "-g"], timeout=NPM_VIEW_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            lines = [line.strip() for line in (result.stdout or "").splitlines()]
            prefix = next((line for line in lines if line), "")
            if prefix:
                bin_dir = Path(prefix) / "bin"
    with _STATUS_CACHE_LOCK:
        _npm_global_bin_cache = bin_dir
    return bin_dir


def _provider_filter_dict(pf: ProviderFilter) -> Dict[str, Any]:
    return {
        "kinds": list(pf.kinds),
        "accepts_anthropic_endpoint": pf.accepts_anthropic_endpoint,
        "accepts_gemini_endpoint": pf.accepts_gemini_endpoint,
    }


def _builtin_row(info: RuntimeInfo) -> Dict[str, Any]:
    # Docker capability and the image are runtime facts read off the adapter
    # registry's RuntimeInfo (the single source); every current built-in
    # carries its own image.
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
    }


# The console's historical display order. Registry entries not named here are
# appended alphabetically, so a newly registered adapter appears without edits.
_PREFERRED_DISPLAY_ORDER = ("claude", "codex", "gemini", "grok", "opencode")
_BUILTIN_INFO = {adapter.info.id: adapter.info for adapter in list_builtin()}


def _display_order(ids: Collection[str]) -> List[str]:
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


def _binary_version(path: str) -> Optional[str]:
    try:
        result = _run([path, "--version"], timeout=CLI_VERSION_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return extract_version(output)


def _install_scan(
    agent_id: str, bin_name: str, cli: Dict[str, Any], version: Optional[str]
) -> Dict[str, Any]:
    """Channel identity for the PATH hit plus every known install drop point.

    The PATH hit alone lied during the shadowing incident; scanning the
    runtime's standalone launch point and the npm global bin as well (the
    collapsed form of cc-switch's candidate enumeration) is what lets the
    console see two copies where `shutil.which` sees one. Copies are
    deduplicated by realpath, so a launch point that *is* the PATH hit does
    not show up twice.
    """
    spec = INSTALL_SPECS.get(agent_id)
    installations: List[Dict[str, Any]] = []
    seen = set()
    if cli.get("present") and cli.get("path"):
        real = os.path.realpath(str(cli["path"]))
        seen.add(real)
        installations.append(
            {
                "channel": _classify_real_path(real),
                "path": str(cli["path"]),
                "real_path": real,
                "version": version,
                "active": True,
            }
        )
    if spec:
        candidates = [
            Path(probe).expanduser()
            for probe in _STANDALONE_PROBE_PATHS.get(agent_id, ())
        ]
        npm_bin = _npm_global_bin()
        if npm_bin is not None:
            candidates.append(npm_bin.expanduser() / bin_name)
        for candidate in candidates:
            if not candidate.is_file():
                continue
            real = os.path.realpath(str(candidate))
            if real in seen:
                continue
            seen.add(real)
            installations.append(
                {
                    "channel": _classify_real_path(real),
                    "path": str(candidate),
                    "real_path": real,
                    "version": _binary_version(str(candidate)),
                    "active": False,
                }
            )
    active_channel = (
        installations[0]["channel"]
        if installations and installations[0]["active"]
        else None
    )
    return {
        "official_channel": spec["channel"] if spec else None,
        "active_channel": active_channel,
        "installations": installations,
        "channel_warnings": _shadow_warnings(bin_name, spec, installations),
    }


def _channel_phrase(channel: str) -> str:
    return {
        "standalone": "the standalone installer",
        "npm": "npm",
        "homebrew": "Homebrew",
    }.get(channel, "an unrecognized channel")


def _copy_phrase(installation: Dict[str, Any]) -> str:
    version = installation.get("version")
    label = f"{installation['channel']} {version}" if version else installation["channel"]
    return f"{label} at {installation['path']}"


def _shadow_warnings(
    bin_name: str,
    spec: Optional[Dict[str, Any]],
    installations: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Structured diagnoses of channel coexistence and PATH/channel mismatch.

    Only runtimes with an INSTALL_SPEC are judged (without an official channel
    there is nothing to mismatch), and only when PATH actually resolves the
    CLI — a copy sitting off PATH is surfaced in ``installations`` without
    being escalated to a warning.
    """
    if not spec or not installations or not installations[0]["active"]:
        return []
    official = spec["channel"]
    active = installations[0]
    extras = installations[1:]
    if active["channel"] != official:
        message = (
            f"PATH runs `{bin_name}` from {_channel_phrase(active['channel'])} "
            f"({_copy_phrase(active)}), but the official channel is {official}."
        )
        official_copy = next(
            (extra for extra in extras if extra["channel"] == official), None
        )
        if official_copy:
            message += (
                f" The {official} copy ({_copy_phrase(official_copy)}) is shadowed —"
                f" installs and updates will not take effect until the"
                f" {active['channel']} copy is removed."
            )
        else:
            message += (
                f" Console installs use the official {official} channel and would"
                f" be shadowed by this copy — remove it first."
            )
        return [{"kind": "channel_mismatch", "message": message}]
    if extras:
        plural = len(extras) > 1
        shadowed = "; ".join(_copy_phrase(extra) for extra in extras)
        message = (
            f"`{bin_name}` is installed through more than one channel. PATH runs"
            f" {_copy_phrase(active)}; also present: {shadowed}. The shadowed"
            f" {'copies' if plural else 'copy'} never"
            f" {'run' if plural else 'runs'} and only confuse"
            f"{'' if plural else 's'} version checks — remove"
            f" {'them' if plural else 'it'}."
        )
        return [{"kind": "shadowed_copies", "message": message}]
    return []


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


def _fetch_json(url: str, *, timeout: float) -> Any:
    # Thin seam over urllib (tests monkeypatch this; nothing else hits HTTP).
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "starbench-console",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _latest_github_version(repo: str) -> Dict[str, Optional[str]]:
    """Newest published version from GitHub's releases/latest endpoint.

    Release tags are vendor-shaped (`rust-v0.146.0`, `v2.1.220`,
    `@moonshot-ai/kimi-code@0.30.0`); ``extract_version`` digs the semver out
    of ``tag_name`` first, then the release ``name``. Failures degrade to an
    error string — the endpoint must never take the status API down with it.
    """
    checked_at = datetime.now(timezone.utc).isoformat()
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        data = _fetch_json(url, timeout=GITHUB_LATEST_TIMEOUT_SECONDS)
    except (OSError, ValueError) as error:
        return {
            "latest_version": None,
            "latest_checked_at": checked_at,
            "latest_error": f"Could not check GitHub releases for {repo}: {error}",
        }
    tag = str(data.get("tag_name") or "") if isinstance(data, dict) else ""
    name = str(data.get("name") or "") if isinstance(data, dict) else ""
    version = extract_version(tag) or extract_version(name)
    return {
        "latest_version": version,
        "latest_checked_at": checked_at,
        "latest_error": (
            None if version else f"GitHub release tag {tag!r} did not include a semver."
        ),
    }


def _latest_version_for(spec: Dict[str, Any]) -> Dict[str, Optional[str]]:
    source = spec.get("latest_source") or {}
    if "npm" in source:
        return _latest_npm_version(source["npm"])
    if "github" in source:
        return _latest_github_version(source["github"])
    return dict(_LATEST_NOT_CHECKED)


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
    global _npm_global_bin_cache
    with _STATUS_CACHE_LOCK:
        _LOCAL_STATUS_CACHE.clear()
        _LATEST_CACHE.clear()
        _npm_global_bin_cache = _NPM_PREFIX_UNSET


def _cached_local_status(agent_id: str, bin_name: str) -> Dict[str, Any]:
    key = (agent_id, bin_name)
    now = time.monotonic()
    with _STATUS_CACHE_LOCK:
        cached = _LOCAL_STATUS_CACHE.get(key)
        if cached and now - cached[0] < LOCAL_STATUS_TTL_SECONDS:
            return dict(cached[1])
    cli = _cli_probe(bin_name)
    local = _local_version(cli)
    scan = _install_scan(agent_id, bin_name, cli, local["version"])
    status = {**cli, **local, **scan}
    with _STATUS_CACHE_LOCK:
        _LOCAL_STATUS_CACHE[key] = (time.monotonic(), dict(status))
    return status


def _cached_latest(agent_id: str, bin_name: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    cached = _latest_from_cache(agent_id, bin_name)
    if cached is not None:
        return cached
    latest = _latest_version_for(spec)
    # Errors are cached at the same TTL on purpose: a failing GitHub lookup
    # retried on every paint would burn the anonymous 60 req/h quota.
    with _STATUS_CACHE_LOCK:
        _LATEST_CACHE[(agent_id, bin_name)] = (time.monotonic(), dict(latest))
    return latest


def _latest_from_cache(agent_id: str, bin_name: str) -> Optional[Dict[str, Any]]:
    """A still-fresh latest-version answer, or None. Never touches the network."""
    with _STATUS_CACHE_LOCK:
        cached = _LATEST_CACHE.get((agent_id, bin_name))
        if cached and time.monotonic() - cached[0] < LATEST_TTL_SECONDS:
            return dict(cached[1])
    return None


def agent_statuses(
    runtimes_dir: Path, *, check_updates: bool = False
) -> "contracts.AgentStatusPayload":
    """Probe every runtime's local CLI; optionally check for updates.

    Probes run in parallel (a serial pass over ~8 runtimes at multi-second
    timeouts kept the page hostage), and the latest-version lookup — the only
    network hop (npm registry or GitHub releases, per the spec's
    ``latest_source``) — runs only when the caller explicitly asks for an
    update check. When it did not ask, a still-fresh cached answer is served
    anyway (the console already knows it; hiding it just made pages forget
    updates on reload), and only with a cold cache do the `latest_*` fields
    stay None, which the UI renders as "not checked", distinct from a failed
    check.
    """

    def probe(target: Dict[str, str]) -> Dict[str, Any]:
        local = _cached_local_status(target["id"], target["bin"])
        package = INSTALL_SPECS.get(target["id"])
        if package:
            if check_updates:
                latest = _cached_latest(target["id"], target["bin"], package)
            else:
                latest = (
                    _latest_from_cache(target["id"], target["bin"])
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
            "official_channel": local["official_channel"],
            "active_channel": local["active_channel"],
            "installations": local["installations"],
            "channel_warnings": local["channel_warnings"],
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
    # A CLI already on PATH gets the spec's update command — for self-updating
    # CLIs (codex/claude/opencode) that is the binary's own updater, which
    # knows its install channel and swaps versions atomically. A missing CLI
    # gets the official install command.
    present = bool(shutil.which(str(package.get("bin") or "")))
    command = list(package["update_command"] if present else package["install_command"])
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
            "options": agent["options"],
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
                    # Custom runtimes declare no runtime-specific knobs (the
                    # spec has no option schema); the frontend renders an empty
                    # option set, matching the builtin passthrough shape.
                    "options": [],
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
    "classify_channel",
    "delete_custom_agent",
    "get_custom_agent",
    "install_agent",
    "list_agents",
    "save_custom_agent",
]
