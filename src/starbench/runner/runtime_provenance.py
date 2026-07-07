"""Best-effort runtime provenance capture for run artifacts.

This module records environment facts for reproducibility. It deliberately
does not import GUI status helpers: GUI checks describe the current machine,
while provenance must describe the environment the runner is about to use.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .. import __version__ as starbench_version
from ..adapters.base import RuntimeAdapter
from ..execution.process import split_command
from .custom_runtime import CustomRuntimeSpec

RUNTIME_PROVENANCE_SCHEMA = 1
VERSION_TIMEOUT_SECONDS = 3
DOCKER_INSPECT_TIMEOUT_SECONDS = 3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(text: str, limit: int = 2000) -> str:
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


def _extract_version(output: str) -> Optional[str]:
    match = re.search(r"(?<![A-Za-z0-9])v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)", output)
    if match:
        return match.group(1)
    match = re.search(r"(?<![A-Za-z0-9])v?(\d+\.\d+)(?![A-Za-z0-9])", output)
    return match.group(1) if match else None


def _command_parts(command: str) -> list[str]:
    try:
        return split_command(command)
    except ValueError:
        return command.split()


def _cli_command_for(agent: str, adapter: RuntimeAdapter, bins: Dict[str, str], spec: CustomRuntimeSpec | None) -> str:
    if spec is not None:
        return spec.command
    return bins.get(agent) or adapter.info.bin


def _probe_local_cli(command: str, base_env: Dict[str, str]) -> Dict[str, Any]:
    parts = _command_parts(command)
    cli_bin = parts[0] if parts else ""
    cli_path = shutil.which(cli_bin, path=base_env.get("PATH")) if cli_bin else None
    result: Dict[str, Any] = {
        "cli_command": command,
        "cli_bin": cli_bin or None,
        "cli_path": cli_path,
        "cli_version": None,
        "cli_version_output": None,
        "cli_version_error": None,
    }
    if not cli_bin:
        result["cli_version_error"] = "No CLI command configured."
        return result
    if cli_path is None:
        result["cli_version_error"] = f"`{cli_bin}` not found on PATH."
        return result

    env = dict(base_env)
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")
    try:
        completed = subprocess.run(
            [cli_path, "--version"],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=VERSION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        result["cli_version_error"] = f"Could not read version: {error}"
        return result

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    version = _extract_version(output)
    result["cli_version"] = version
    result["cli_version_output"] = _tail(output, 500) or None
    if version is None:
        detail = _tail(output, 500) or f"exit code {completed.returncode}"
        result["cli_version_error"] = f"Version output did not include a semver: {detail}"
    return result


def _docker_image_provenance(
    *,
    docker_bin: str,
    docker_image: str | None,
    base_env: Dict[str, str],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "docker_image": docker_image,
        "docker_image_id": None,
        "docker_repo_digests": [],
        "docker_image_error": None,
    }
    if not docker_image:
        result["docker_image_error"] = "No Docker image configured."
        return result

    command = _command_parts(docker_bin) + ["image", "inspect", docker_image]
    try:
        completed = subprocess.run(
            command,
            env=base_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=DOCKER_INSPECT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        result["docker_image_error"] = f"Could not inspect Docker image: {error}"
        return result

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode != 0:
        result["docker_image_error"] = _tail(output, 500) or f"docker image inspect exited with {completed.returncode}."
        return result
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        result["docker_image_error"] = f"Docker image inspect returned invalid JSON: {error}"
        return result
    image = payload[0] if isinstance(payload, list) and payload else {}
    if not isinstance(image, dict):
        result["docker_image_error"] = "Docker image inspect did not return an object."
        return result
    result["docker_image_id"] = image.get("Id")
    digests = image.get("RepoDigests")
    result["docker_repo_digests"] = [str(item) for item in digests] if isinstance(digests, list) else []
    return result


def _custom_spec_provenance(spec: CustomRuntimeSpec | None) -> Dict[str, Any] | None:
    if spec is None:
        return None
    result: Dict[str, Any] = {
        "id": spec.id,
        "path": str(spec.source_path),
        "sha256": None,
        "sha256_error": None,
        "public_metadata": spec.public_metadata(),
    }
    try:
        result["sha256"] = hashlib.sha256(spec.source_path.read_bytes()).hexdigest()
    except OSError as error:
        result["sha256_error"] = str(error)
    return result


def capture_runtime_provenance(
    *,
    role: str,
    agent: str,
    adapter: RuntimeAdapter,
    model: str | None,
    backend: str,
    bins: Dict[str, str],
    base_env: Dict[str, str],
    docker_bin: str,
    docker_image: str | None,
    custom_spec: CustomRuntimeSpec | None = None,
) -> Dict[str, Any]:
    """Capture one executor/evaluator runtime snapshot without failing the run."""
    cli_command = _cli_command_for(agent, adapter, bins, custom_spec)
    effective_docker_image = (
        custom_spec.docker_image if backend == "docker" and custom_spec and custom_spec.docker_image else docker_image
    )
    docker = (
        _docker_image_provenance(
            docker_bin=docker_bin,
            docker_image=effective_docker_image,
            base_env=base_env,
        )
        if backend == "docker"
        else {
            "docker_image": None,
            "docker_image_id": None,
            "docker_repo_digests": [],
            "docker_image_error": None,
        }
    )
    cli = (
        _probe_local_cli(cli_command, base_env)
        if backend == "local"
        else {
            "cli_command": cli_command,
            "cli_bin": (_command_parts(cli_command)[0] if _command_parts(cli_command) else None),
            "cli_path": None,
            "cli_version": None,
            "cli_version_output": None,
            "cli_version_error": "Container CLI version is not captured in schema 1.",
        }
    )
    return {
        "role": role,
        "agent": agent,
        "label": adapter.info.label,
        "model": model,
        "backend": backend,
        **docker,
        **cli,
        "custom_runtime_spec": _custom_spec_provenance(custom_spec),
    }


def _git_output(args: list[str], cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def capture_starbench_provenance(*, cwd: Path) -> Dict[str, Any]:
    status = _git_output(["status", "--porcelain"], cwd)
    return {
        "version": starbench_version,
        "git_commit": _git_output(["rev-parse", "--short", "HEAD"], cwd),
        "git_dirty": bool(status) if status is not None else None,
    }


def capture_run_provenance(
    *,
    executor_agent: str,
    executor_adapter: RuntimeAdapter,
    executor_model: str | None,
    executor_backend: str,
    executor_bins: Dict[str, str],
    executor_base_env: Dict[str, str],
    executor_docker_bin: str,
    executor_docker_image: str | None,
    executor_custom_spec: CustomRuntimeSpec | None,
    evaluator_agent: str,
    evaluator_adapter: RuntimeAdapter,
    evaluator_model: str | None,
    evaluator_bins: Dict[str, str],
    evaluator_base_env: Dict[str, str],
    evaluator_custom_spec: CustomRuntimeSpec | None,
    cwd: Path,
) -> Dict[str, Any]:
    return {
        "schema": RUNTIME_PROVENANCE_SCHEMA,
        "captured_at": utc_now(),
        "starbench": capture_starbench_provenance(cwd=cwd),
        "executor": capture_runtime_provenance(
            role="executor",
            agent=executor_agent,
            adapter=executor_adapter,
            model=executor_model,
            backend=executor_backend,
            bins=executor_bins,
            base_env=executor_base_env,
            docker_bin=executor_docker_bin,
            docker_image=executor_docker_image,
            custom_spec=executor_custom_spec,
        ),
        "evaluator": capture_runtime_provenance(
            role="evaluator",
            agent=evaluator_agent,
            adapter=evaluator_adapter,
            model=evaluator_model,
            backend="local",
            bins=evaluator_bins,
            base_env=evaluator_base_env,
            docker_bin=executor_docker_bin,
            docker_image=None,
            custom_spec=evaluator_custom_spec,
        ),
    }
