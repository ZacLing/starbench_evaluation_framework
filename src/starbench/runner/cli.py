"""Command-line interface for ``starbench-run``: argument parsing and ``main``.

Responsibility: define every ``--flag``, validate/normalise them (default
backend and docker image are read off the resolved runtime's ``RuntimeInfo``,
never branched on the agent id), resolve ``custom:<id>`` specs, and hand a
finished ``argparse.Namespace`` to :func:`orchestrator.run_benchmark`.

Invariants:
- Defaults live here only; the orchestrator trusts ``args`` to be complete
  (e.g. ``executor_backend`` and ``docker_image`` are always resolved by the
  time ``run_benchmark`` runs).
- ``main`` is the console-script entry point (``starbench-run``) and the target
  of ``python -m starbench.runner.run_benchmark`` via the compat shim.

改什么来这里: CLI flags, their defaults/validation, or custom-runtime resolution.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Sequence

from ..adapters import BUILTIN_AGENTS, DEFAULT_DOCKER_IMAGES, resolve
from .custom_runtime import CustomRuntimeSpec, load_custom_runtime
from .orchestrator import run_benchmark

PROJECT_ROOT = Path.cwd()
DEFAULT_TASKS_DIR = PROJECT_ROOT / "tasks"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_EXECUTOR_SKILLS_DIR = PROJECT_ROOT / "executor_skills"
DEFAULT_RUNTIMES_DIR = PROJECT_ROOT / "runtimes"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run StarBench benchmark tasks and rubric judges.",
        epilog=(
            "Runtime convention: use Claude Code (`--*-agent claude`) for Claude-family models, "
            "Codex (`--*-agent codex`) for GPT/OpenAI-family models, and OpenCode "
            "(`--*-agent opencode`) for other OpenAI-compatible models such as Doubao or Qwen. "
            "Use Grok Build (`--*-agent grok`) or Gemini CLI (`--*-agent gemini`) when those "
            "host CLIs are installed and authenticated. "
            "When mixing runtimes, split auth with --executor-auth-mode and --evaluator-auth-mode."
        ),
    )
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--judge-mode", choices=["both", "single", "parallel"], default="both")
    parser.add_argument("--max-evaluator-parallel", type=int, default=4)
    parser.add_argument("--run-id")
    parser.add_argument("--tasks-dir", type=Path, default=DEFAULT_TASKS_DIR)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--task", action="append", help="Task id or task directory name to include. Repeatable.")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat the selected task list N times.")
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex executable, or a shell-like command prefix. Use for GPT/OpenAI-family models.",
    )
    parser.add_argument(
        "--claude-bin",
        default="claude",
        help="Claude Code executable, or a shell-like command prefix. Use for Claude-family models.",
    )
    parser.add_argument(
        "--grok-bin",
        default="grok",
        help="Grok Build executable, or a shell-like command prefix. Use for xAI Grok Build models.",
    )
    parser.add_argument(
        "--gemini-bin",
        default="gemini",
        help="Gemini CLI executable, or a shell-like command prefix. Use for Gemini CLI models.",
    )
    parser.add_argument(
        "--opencode-bin",
        default="opencode",
        help="OpenCode executable, or a shell-like command prefix. Use for other OpenAI-compatible models.",
    )
    parser.add_argument(
        "--executor-agent",
        default="codex",
        help=(
            "Executor runtime: codex for GPT/OpenAI-family, claude for Claude-family, "
            "opencode for other OpenAI-compatible models, grok for Grok Build, gemini for Gemini CLI, "
            "or custom:<id> for a runtime defined in --runtimes-dir."
        ),
    )
    parser.add_argument(
        "--evaluator-agent",
        default="codex",
        help=(
            "Evaluator runtime: codex for GPT/OpenAI-family, claude for Claude-family, "
            "opencode for other OpenAI-compatible models, grok for Grok Build, gemini for Gemini CLI, "
            "or custom:<id> for a runtime defined in --runtimes-dir."
        ),
    )
    parser.add_argument(
        "--runtimes-dir",
        type=Path,
        default=DEFAULT_RUNTIMES_DIR,
        help="Directory containing custom runtime configs (<id>.json) for custom:<id> agents.",
    )
    parser.add_argument(
        "--thinking-effort",
        dest="thinking_effort",
        choices=["none", "low", "medium", "high"],
        default="none",
        help=(
            "Reasoning effort for the executor, applied through each runtime's native switch "
            "where one exists (Claude Code: MAX_THINKING_TOKENS budget; Codex: "
            "model_reasoning_effort) and as a prompt-level instruction for the rest."
        ),
    )
    parser.add_argument(
        "--claude-thinking-effort",
        dest="thinking_effort",
        choices=["none", "low", "medium", "high"],
        default="none",
        help="Deprecated alias for --thinking-effort.",
    )
    parser.add_argument(
        "--web-search",
        dest="web_search",
        choices=["task", "allow", "deny"],
        default="task",
        help=(
            "Run-level web-search override. 'task' (default) follows each task package's "
            "allow_web_search; 'allow'/'deny' force it for runtimes that enforce web access "
            "(Claude Code's tool allowlist, Codex's --search). Other runtimes decide via "
            "their own tooling and are not affected."
        ),
    )
    parser.add_argument(
        "--claude-max-turns",
        type=int,
        default=None,
        help=(
            "Optional agentic turn cap for the Claude Code executor. Defaults to no cap so "
            "Claude runs are comparable with other runtimes."
        ),
    )
    parser.add_argument(
        "--opencode-provider",
        help="OpenCode provider id for generated OpenAI-compatible config, e.g. yunwu.",
    )
    parser.add_argument(
        "--opencode-base-url",
        help="OpenCode OpenAI-compatible base URL, e.g. https://yunwu.ai/v1.",
    )
    parser.add_argument(
        "--opencode-api-key-env",
        default="OPENAI_API_KEY",
        help="Environment variable name that OpenCode should read as the provider API key.",
    )
    parser.add_argument("--auth-mode", choices=["env", "global", "copy-auth"], default="env")
    parser.add_argument(
        "--executor-auth-mode",
        choices=["env", "global", "copy-auth"],
        help="Auth mode for the executor runtime. Defaults to --auth-mode.",
    )
    parser.add_argument(
        "--evaluator-auth-mode",
        choices=["env", "global", "copy-auth"],
        help="Auth mode for the evaluator runtime. Defaults to --auth-mode.",
    )
    parser.add_argument("--executor-model", help="Exact model id passed to the selected executor runtime.")
    parser.add_argument("--evaluator-model", help="Exact model id passed to the selected evaluator runtime.")
    parser.add_argument(
        "--executor-backend",
        choices=["local", "docker"],
        default=None,
        help=(
            "Run executor directly on the host or inside a per-task Docker container. "
            "Defaults to docker for the codex runtime and local for other runtimes "
            "(Docker support is currently Codex-only)."
        ),
    )
    parser.add_argument("--docker-bin", default="docker", help="Docker executable or shell-like command prefix.")
    parser.add_argument(
        "--docker-image",
        default=None,
        help=(
            "Image used when --executor-backend docker is selected. Defaults to the "
            "runtime's own image (starbench-codex:latest, starbench-claude-code:latest, "
            "starbench-gemini-cli:latest, starbench-grok:latest, starbench-opencode:latest); "
            "custom runtimes take theirs from the spec's docker section."
        ),
    )
    parser.add_argument("--evaluator-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--instruction-mode",
        choices=["none", "traverse", "select", "ablation"],
        default="none",
        help="Append human_reference instructions: none, one run per step, selected step bundle, or baseline plus one run per step.",
    )
    parser.add_argument(
        "--instruction-step",
        action="append",
        help="Human reference step_id to include. Repeatable. Implies select mode when mode is none.",
    )
    parser.add_argument(
        "--rigor-mode",
        choices=["none", "select"],
        default="none",
        help="Append selected rigors from rigors.json to the executor prompt.",
    )
    parser.add_argument(
        "--rigor",
        action="append",
        help="Rigor id to include from rigors.json. Repeatable. Implies select mode when mode is none.",
    )
    parser.add_argument(
        "--executor-skill",
        action="append",
        help=(
            "Executor skill id to install from task executor_skills.json or the shared "
            "executor skill registry. Repeatable."
        ),
    )
    parser.add_argument(
        "--executor-skill-group",
        action="append",
        help="Executor skill group id to expand from the shared executor skill registry. Repeatable.",
    )
    parser.add_argument(
        "--executor-skill-root",
        type=Path,
        default=DEFAULT_EXECUTOR_SKILLS_DIR,
        help="Shared executor skill registry root containing registry.json and skill directories.",
    )
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars and progress stderr output.")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")
    if args.max_evaluator_parallel < 1:
        parser.error("--max-evaluator-parallel must be at least 1")
    if args.instruction_step and args.instruction_mode == "none":
        args.instruction_mode = "select"
    if args.instruction_mode == "select" and not args.instruction_step:
        parser.error("--instruction-mode select requires at least one --instruction-step")
    if args.rigor and args.rigor_mode == "none":
        args.rigor_mode = "select"
    if args.rigor_mode == "select" and not args.rigor:
        parser.error("--rigor-mode select requires at least one --rigor")
    args.runtimes_dir = args.runtimes_dir.resolve()

    def resolve_runtime_spec(value: str, flag: str) -> CustomRuntimeSpec | None:
        if value in BUILTIN_AGENTS:
            return None
        if value.startswith("custom:"):
            try:
                return load_custom_runtime(args.runtimes_dir, value.split(":", 1)[1])
            except ValueError as exc:
                parser.error(str(exc))
        parser.error(f"{flag} must be one of {sorted(BUILTIN_AGENTS)} or custom:<id>, got {value!r}")
        return None

    args.executor_runtime_spec = resolve_runtime_spec(args.executor_agent, "--executor-agent")
    args.evaluator_runtime_spec = resolve_runtime_spec(args.evaluator_agent, "--evaluator-agent")
    executor_adapter = resolve(
        args.executor_agent, spec=args.executor_runtime_spec, runtimes_dir=args.runtimes_dir
    )
    # Docker capability and the default backend are facts of the runtime, read
    # off its RuntimeInfo rather than branched on the agent id here.
    if args.executor_backend is None:
        args.executor_backend = executor_adapter.info.default_executor_backend
    elif args.executor_backend == "docker" and not executor_adapter.info.docker_capable:
        parser.error(
            f"--executor-agent {args.executor_agent} currently requires --executor-backend local; "
            "Docker isolation needs a docker section in the custom runtime spec."
        )
    if args.docker_image is None:
        args.docker_image = DEFAULT_DOCKER_IMAGES.get(args.executor_agent, "")
    args.executor_auth_mode = args.executor_auth_mode or args.auth_mode
    args.evaluator_auth_mode = args.evaluator_auth_mode or args.auth_mode
    args.tasks_dir = args.tasks_dir.resolve()
    args.runs_dir = args.runs_dir.resolve()
    args.executor_skill_root = args.executor_skill_root.resolve()
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = asyncio.run(run_benchmark(args))
    print(json.dumps({"run_id": summary["run_id"], "run_root": summary["run_root"]}, sort_keys=True))
    return 0
