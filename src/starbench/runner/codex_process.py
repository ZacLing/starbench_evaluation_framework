from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

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


def build_docker_codex_command(
    *,
    docker_bin: str,
    docker_image: str,
    workspace: Path,
    codex_home: Path,
    inner_command: Iterable[str],
    auth_env: Dict[str, str],
) -> List[str]:
    workspace = workspace.resolve()
    codex_home = codex_home.resolve()
    command = split_command(docker_bin)
    command.extend(
        [
            "run",
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
            "--mount",
            f"type=bind,src={codex_home},dst=/codex-home",
            "-w",
            "/workspace",
            "-e",
            "CODEX_HOME=/codex-home",
        ]
    )
    for key in ("CODEX_API_KEY", "OPENAI_API_KEY"):
        if auth_env.get(key):
            command.extend(["-e", key])
    command.append(docker_image)
    command.extend(inner_command)
    return command


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
    command = build_docker_codex_command(
        docker_bin=docker_bin,
        docker_image=docker_image,
        workspace=workspace,
        codex_home=docker_auth_home,
        inner_command=inner_command,
        auth_env=auth_env,
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

    container_final_on_host = workspace / ".runner" / "final.md"
    if container_final_on_host.exists():
        host_final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(container_final_on_host, host_final_path)
    return result
