"""Subprocess spawning, stream pumping, and timeout handling.

Runtime-agnostic: every runtime (built-in or custom, local or docker) ends up
calling :func:`run_codex_process` with an already-built argv, env, and prompt.
The name keeps the historical `codex_process` spelling for compatibility; the
function drives any coding-agent CLI, not just Codex.

Invariants:
- stdin receives ``prompt`` (empty string when the runtime takes its prompt on
  the command line, e.g. Grok); stdout/stderr are streamed to files as raw
  bytes so partial output survives a timeout kill.
- On timeout the child is killed but the returned :class:`ProcessResult`
  carries ``timed_out=True`` and ``status="timeout"``; callers that spawn
  containers are responsible for killing the container separately
  (see :mod:`starbench.execution.docker`).

To change spawn/timeout/stream semantics, edit this file.
"""

from __future__ import annotations

import asyncio
import shlex
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List

from ..runner.models import ProcessResult


def split_command(command: str) -> List[str]:
    return shlex.split(command)


def mark_failed(result: ProcessResult) -> ProcessResult:
    """Return a copy of ``result`` with ``status="failed"``.

    Used when a run exited successfully but its output post-processing raised,
    so the run is downgraded to a failure without losing timing metadata.
    """
    return result.__class__(
        command=result.command,
        exit_code=result.exit_code,
        status="failed",
        timed_out=result.timed_out,
        started_at=result.started_at,
        ended_at=result.ended_at,
        duration_seconds=result.duration_seconds,
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
