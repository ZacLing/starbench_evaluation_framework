"""Task-library services for the console: browse directories, validate and
install task packages, and run environment preflight checks."""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .data import SAFE_ID, _read_json, list_task_packages

MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_DIR_ENTRIES = 200


class LibraryError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Directory browsing (server-side folder picker)
# ---------------------------------------------------------------------------

def _allowed_roots(cwd: Path) -> List[Path]:
    return [Path.home().resolve(), cwd.resolve()]


def _is_allowed(path: Path, cwd: Path) -> bool:
    for root in _allowed_roots(cwd):
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def browse_directories(raw_path: Optional[str], *, cwd: Path) -> Dict[str, Any]:
    path = Path(raw_path).expanduser() if raw_path else Path.home()
    try:
        path = path.resolve()
    except OSError:
        raise LibraryError(f"Cannot resolve path: {raw_path}")
    if not _is_allowed(path, cwd):
        raise LibraryError("Browsing is limited to your home directory and the working directory.")
    if not path.is_dir():
        raise LibraryError(f"Not a directory: {path}")

    entries: List[Dict[str, Any]] = []
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    except OSError as error:
        raise LibraryError(f"Cannot list {path}: {error}")
    for child in children:
        if len(entries) >= MAX_DIR_ENTRIES:
            break
        if not child.is_dir() or child.name.startswith("."):
            continue
        task_count = 0
        try:
            for sub in child.iterdir():
                if sub.is_dir() and (sub / "task.json").is_file():
                    task_count += 1
        except OSError:
            pass
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "task_count": task_count,
                "is_task_package": (child / "task.json").is_file(),
            }
        )

    parent = path.parent if path != path.parent and _is_allowed(path.parent, cwd) else None
    return {
        "path": str(path),
        "parent": str(parent) if parent else None,
        "task_count": sum(1 for entry in entries if entry["is_task_package"]),
        "dirs": entries,
    }


# ---------------------------------------------------------------------------
# Task package import (drag & drop upload)
# ---------------------------------------------------------------------------

def _decode_files(files: Sequence[Dict[str, Any]]) -> List[Tuple[str, bytes]]:
    decoded: List[Tuple[str, bytes]] = []
    total = 0
    for entry in files:
        rel = str(entry.get("path") or "")
        rel = rel.replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            raise LibraryError(f"Unsafe file path in upload: {entry.get('path')!r}")
        try:
            content = base64.b64decode(str(entry.get("content_b64") or ""), validate=True)
        except (binascii.Error, ValueError):
            raise LibraryError(f"File {rel} is not valid base64.")
        total += len(content)
        if total > MAX_IMPORT_BYTES:
            raise LibraryError("Upload exceeds the 20 MB import limit.")
        decoded.append((rel, content))
    if not decoded:
        raise LibraryError("Upload contains no files.")
    return decoded


def _expand_zip(decoded: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    if len(decoded) == 1 and decoded[0][0].lower().endswith(".zip"):
        try:
            archive = zipfile.ZipFile(io.BytesIO(decoded[0][1]))
        except zipfile.BadZipFile:
            raise LibraryError("The uploaded .zip file could not be read.")
        expanded: List[Tuple[str, bytes]] = []
        total = 0
        for info in archive.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("\\", "/").lstrip("/")
            if not rel or ".." in rel.split("/") or rel.startswith("__MACOSX/"):
                continue
            content = archive.read(info)
            total += len(content)
            if total > MAX_IMPORT_BYTES:
                raise LibraryError("Zip contents exceed the 20 MB import limit.")
            expanded.append((rel, content))
        if not expanded:
            raise LibraryError("The zip archive contains no files.")
        return expanded
    return decoded


def _strip_common_root(files: List[Tuple[str, bytes]]) -> List[Tuple[str, bytes]]:
    """Uploads of a dragged folder arrive as <folder>/task.json etc. Strip the
    shared top-level folder so packages normalize to task.json at the root."""
    tops = {rel.split("/", 1)[0] for rel, _ in files}
    if len(tops) == 1 and all("/" in rel for rel, _ in files):
        return [(rel.split("/", 1)[1], content) for rel, content in files]
    return files


def validate_task_package(files: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    decoded = _strip_common_root(_expand_zip(_decode_files(files)))
    by_path = {rel: content for rel, content in decoded}
    errors: List[str] = []
    warnings: List[str] = []
    task: Dict[str, Any] = {}

    if "task.json" not in by_path:
        errors.append("task.json is missing at the package root.")
    else:
        try:
            spec = json.loads(by_path["task.json"].decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            errors.append(f"task.json is not valid JSON: {error}")
            spec = None
        if isinstance(spec, dict):
            task_id = str(spec.get("id") or "")
            if not SAFE_ID.match(task_id):
                errors.append(
                    "task.json needs an `id` of letters, digits, dot, dash, underscore."
                )
            task = {
                "id": task_id,
                "name": str(spec.get("name") or task_id),
                "timeout_seconds": spec.get("timeout_seconds"),
            }
            prompt_name = str(spec.get("prompt") or "prompt.md")
            if prompt_name not in by_path:
                errors.append(f"Prompt file `{prompt_name}` referenced by task.json is missing.")
            rubrics_name = str(spec.get("rubrics") or "rubrics.json")
            if rubrics_name not in by_path:
                errors.append(f"Rubrics file `{rubrics_name}` referenced by task.json is missing.")
            else:
                try:
                    rubrics = json.loads(by_path[rubrics_name].decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as error:
                    errors.append(f"{rubrics_name} is not valid JSON: {error}")
                    rubrics = None
                if isinstance(rubrics, dict):
                    rows = rubrics.get("rubrics")
                    if not isinstance(rows, list) or not rows:
                        errors.append(f"{rubrics_name} has no `rubrics` array.")
                    else:
                        task["rubric_count"] = len(rows)
                        for index, row in enumerate(rows):
                            missing = [
                                key
                                for key in ("id", "fail_fast", "expected", "question")
                                if not isinstance(row, dict) or key not in row
                            ]
                            if missing:
                                errors.append(
                                    f"Rubric #{index + 1} is missing: {', '.join(missing)}."
                                )
                                break
                elif rubrics is not None:
                    errors.append(f"{rubrics_name} must be a JSON object with a `rubrics` array.")
        elif spec is not None:
            errors.append("task.json must be a JSON object.")

    if "human_reference.json" in by_path:
        task["has_human_reference"] = True
    if not errors and "README.md" not in by_path and "materials" not in {
        rel.split("/", 1)[0] for rel in by_path
    }:
        warnings.append("No materials/ directory; fine if the task needs no input files.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "task": task,
        "file_count": len(decoded),
        "_files": decoded,
    }


def install_task_package(
    files: Sequence[Dict[str, Any]], *, target_dir: Path, dry_run: bool = False
) -> Dict[str, Any]:
    report = validate_task_package(files)
    decoded = report.pop("_files")
    if dry_run or not report["valid"]:
        return report

    if not target_dir.is_dir():
        raise LibraryError(f"Task directory not found: {target_dir}")
    package_dir = target_dir / report["task"]["id"]
    if package_dir.exists():
        raise LibraryError(
            f"A package named {report['task']['id']} already exists in {target_dir}."
        )
    try:
        for rel, content in decoded:
            destination = package_dir / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    except OSError as error:
        shutil.rmtree(package_dir, ignore_errors=True)
        raise LibraryError(f"Could not write the package: {error}")
    report["installed_to"] = str(package_dir)
    return report


# ---------------------------------------------------------------------------
# Task package detail (preview drawer)
# ---------------------------------------------------------------------------

PROMPT_PREVIEW_BYTES = 100_000


def task_package_detail(tasks_dir: Path, dir_name: str) -> Dict[str, Any]:
    if not SAFE_ID.match(dir_name):
        raise LibraryError(f"Invalid task package name: {dir_name!r}")
    package_dir = (tasks_dir / dir_name).resolve()
    try:
        package_dir.relative_to(tasks_dir.resolve())
    except ValueError:
        raise LibraryError("Task package is outside the task directory.")
    spec = _read_json(package_dir / "task.json")
    if not isinstance(spec, dict):
        raise LibraryError(f"No task package at {package_dir}.")

    prompt_name = str(spec.get("prompt") or "prompt.md")
    prompt_text: Optional[str] = None
    try:
        prompt_text = (package_dir / prompt_name).read_bytes()[:PROMPT_PREVIEW_BYTES].decode(
            "utf-8", errors="replace"
        )
    except OSError:
        pass

    rubrics_payload = _read_json(package_dir / str(spec.get("rubrics") or "rubrics.json"))
    rubrics = (
        rubrics_payload.get("rubrics")
        if isinstance(rubrics_payload, dict) and isinstance(rubrics_payload.get("rubrics"), list)
        else []
    )

    human_reference = _read_json(package_dir / "human_reference.json")
    steps = (
        human_reference.get("steps")
        if isinstance(human_reference, dict) and isinstance(human_reference.get("steps"), list)
        else []
    )

    return {
        "dir": str(tasks_dir),
        "dir_name": dir_name,
        "id": str(spec.get("id") or dir_name),
        "name": str(spec.get("name") or dir_name),
        "timeout_seconds": spec.get("timeout_seconds"),
        "allow_web_search": spec.get("allow_web_search"),
        "prompt": prompt_text,
        "rubrics": rubrics,
        "human_reference_steps": len(steps),
    }


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------

AGENT_BINS = {
    "codex": "codex",
    "claude": "claude",
    "opencode": "opencode",
    "grok": "grok",
    "gemini": "gemini",
}

AGENT_ENV_KEYS = {
    "codex": ["OPENAI_API_KEY"],
    "claude": ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "grok": ["XAI_API_KEY"],
}


def _check(check_id: str, label: str, status: str, hint: str = "") -> Dict[str, str]:
    return {"id": check_id, "label": label, "status": status, "hint": hint}


def _cli_check(role: str, agent: str) -> Dict[str, str]:
    bin_name = AGENT_BINS.get(agent, agent)
    found = shutil.which(bin_name)
    if found:
        return _check(f"{role}_cli", f"{role.capitalize()} CLI `{bin_name}`", "ok", found)
    return _check(
        f"{role}_cli",
        f"{role.capitalize()} CLI `{bin_name}`",
        "fail",
        f"`{bin_name}` was not found on PATH. Install it or point --{agent}-bin at it via extra flags.",
    )


def _auth_check(role: str, agent: str, auth_mode: str, api_key_env: Optional[str]) -> Dict[str, str]:
    label = f"{role.capitalize()} credentials ({auth_mode})"
    if auth_mode in ("global", "copy-auth"):
        return _check(
            f"{role}_auth",
            label,
            "warn",
            "Uses the CLI's own login. Make sure you are logged in; the console cannot verify this.",
        )
    keys = [api_key_env] if agent == "opencode" and api_key_env else AGENT_ENV_KEYS.get(agent, [])
    if not keys:
        return _check(f"{role}_auth", label, "warn", "No known environment variable to check.")
    present = [key for key in keys if os.environ.get(key)]
    if present:
        return _check(f"{role}_auth", label, "ok", f"{present[0]} is set.")
    return _check(
        f"{role}_auth",
        label,
        "warn",
        f"None of {', '.join(keys)} is set in the console's environment.",
    )


def _docker_checks(docker_image: str) -> List[Dict[str, str]]:
    checks: List[Dict[str, str]] = []
    docker_bin = shutil.which("docker")
    if not docker_bin:
        checks.append(
            _check("docker", "Docker CLI", "fail", "`docker` was not found on PATH.")
        )
        return checks
    checks.append(_check("docker", "Docker CLI", "ok", docker_bin))
    if docker_image:
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", docker_image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            if result.returncode == 0:
                checks.append(_check("docker_image", f"Image {docker_image}", "ok"))
            else:
                checks.append(
                    _check(
                        "docker_image",
                        f"Image {docker_image}",
                        "fail",
                        "Image not found locally. Build it, e.g. "
                        "`docker build -t starbench-codex:latest -f docker/codex-bench.Dockerfile .`",
                    )
                )
        except (OSError, subprocess.TimeoutExpired):
            checks.append(
                _check(
                    "docker_image",
                    f"Image {docker_image}",
                    "warn",
                    "Could not query the Docker daemon. Is it running?",
                )
            )
    return checks


def preflight(
    *,
    executor_agent: str,
    evaluator_agent: str,
    executor_backend: str,
    docker_image: str,
    executor_auth_mode: str,
    evaluator_auth_mode: str,
    opencode_api_key_env: Optional[str] = None,
) -> List[Dict[str, str]]:
    checks: List[Dict[str, str]] = []
    if executor_backend == "docker":
        checks.extend(_docker_checks(docker_image))
    else:
        checks.append(_cli_check("executor", executor_agent))
    checks.append(_auth_check("executor", executor_agent, executor_auth_mode, opencode_api_key_env))
    checks.append(_cli_check("evaluator", evaluator_agent))
    checks.append(_auth_check("evaluator", evaluator_agent, evaluator_auth_mode, opencode_api_key_env))

    deduped: List[Dict[str, str]] = []
    seen = set()
    for check in checks:
        key = (check["id"], check["label"])
        if key not in seen:
            seen.add(key)
            deduped.append(check)
    return deduped


__all__ = [
    "LibraryError",
    "browse_directories",
    "install_task_package",
    "validate_task_package",
    "task_package_detail",
    "preflight",
    "list_task_packages",
]
