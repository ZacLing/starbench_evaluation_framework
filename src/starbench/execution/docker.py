"""Generic hardened-container command construction and timeout cleanup.

Runtime-agnostic: :func:`build_docker_agent_command` assembles the shared
``docker run`` invocation (read-only rootfs, dropped caps, resource limits,
workspace bind mount, env whitelist) that every runtime's docker path reuses.
Per-runtime specifics — which image, which env vars, which extra mounts — are
supplied by the caller in :mod:`starbench.adapters`.

Invariants:
- The workspace is always mounted at ``/workspace`` and is the container CWD.
- Only env keys in ``env_whitelist`` that are actually set in ``auth_env`` are
  forwarded (by name, so the value is read inside the container's env).
- Killing the ``docker`` client on timeout does not stop the container; use
  :func:`kill_container_on_timeout` to stop the named container as well.

To change container sandbox flags/limits, edit :func:`build_docker_agent_command`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Iterable, List

from ..runner.models import ProcessResult
from .process import split_command


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


def kill_container_on_timeout(result: ProcessResult, docker_bin: str, container_name: str) -> None:
    if result.timed_out:
        subprocess.run(
            split_command(docker_bin) + ["kill", container_name],
            check=False,
            capture_output=True,
        )


# Backwards-compatible private alias (historic name used inside the runner).
_kill_container_on_timeout = kill_container_on_timeout
