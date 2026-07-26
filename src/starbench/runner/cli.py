"""Command-line interface for ``starbench-run``: argument parsing and ``main``.

Responsibility: define every ``--flag``, validate/normalise them (default
backend and docker image are read off the resolved runtime's ``RuntimeInfo``,
never branched on the agent id), resolve ``custom:<id>`` specs, and hand a
finished ``argparse.Namespace`` to :func:`orchestrator.run_benchmark`.

Invariants:
- Defaults live here only; the orchestrator trusts ``args`` to be complete
  (e.g. ``executor_backend`` and ``docker_image`` are always resolved by the
  time ``run_benchmark`` runs).
- Data directories default to the StarBench home layout (``$STARBENCH_HOME``,
  else ``~/.starbench``), never to the working directory: an explicit flag wins,
  otherwise ``parse_args`` fills the gap from :mod:`starbench.home`. The process
  environment is read here (or via an injected ``environ``) and nowhere inward.
- ``main`` is the console-script entry point (``starbench-run``) and the target
  of ``python -m starbench.runner.run_benchmark`` via the compat shim.

改什么来这里: CLI flags, their defaults/validation, or custom-runtime resolution.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..adapters import (
    BUILTIN_AGENTS,
    DEFAULT_DOCKER_IMAGES,
    list_builtin,
    resolve,
    resolve_runtime_options,
)
from ..contracts import ContractValidationError, validate_payload
from ..domain import (
    INSTRUCTION_MODES,
    LEGACY_THINKING_EFFORT,
    RIGOR_MODES,
    THINKING_EFFORTS,
    canonical_thinking_effort,
    parse_safe_id,
)
from ..home import HomeLayout, resolve_home
from .custom_runtime import CustomRuntimeSpec, load_custom_runtime
from .orchestrator import run_benchmark


# Plan fields that expand to repeated flags; every other plan key maps
# mechanically to "--" + key.replace("_", "-"). Public: the console's argv
# renderer uses the same map, so the two transports cannot drift.
PLAN_LIST_FLAGS = {
    "tasks": "--task",
    "instruction_steps": "--instruction-step",
    "rigors": "--rigor",
    "executor_skills": "--executor-skill",
    "executor_skill_groups": "--executor-skill-group",
}
# Plan keys holding role option boxes; each expands to repeated NAME=VALUE flags.
PLAN_OPTION_FLAGS = {
    "executor_options": "--executor-option",
    "evaluator_options": "--evaluator-option",
}
# Plan keys the expansion consumes without emitting a flag.
_PLAN_NON_FLAG_KEYS = {"schema_version", "profile_snapshot"}
# The only argv companions --plan tolerates: everything else must live in the
# plan, so the two transports can never disagree about a knob's value.
_PLAN_COMPANION_FLAGS = {"--runs-dir": True, "--no-progress": False}  # flag -> takes value


def _expand_plan_argv(
    argv: List[str], parser: argparse.ArgumentParser
) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """Expand ``--plan plan.json`` into the equivalent flag argv (fail closed).

    The plan is validated against run_plan.schema.json first, then translated
    deterministically into the same flags a manual invocation would use — both
    transports share every downstream validation and default. ``--plan`` is
    exclusive: only --runs-dir and --no-progress may accompany it.
    """
    retained: List[str] = []
    plan_path: Optional[Path] = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--plan":
            if index + 1 >= len(argv):
                parser.error("--plan requires a path.")
            plan_path = Path(argv[index + 1])
            index += 2
            continue
        if token in _PLAN_COMPANION_FLAGS:
            retained.append(token)
            if _PLAN_COMPANION_FLAGS[token]:
                if index + 1 >= len(argv):
                    parser.error(f"{token} requires a value.")
                retained.append(argv[index + 1])
                index += 2
                continue
            index += 1
            continue
        parser.error(
            f"--plan is exclusive: move {token} into the plan file "
            "(only --runs-dir and --no-progress may accompany --plan)."
        )
    assert plan_path is not None

    try:
        raw = plan_path.read_text(encoding="utf-8")
    except OSError as exc:
        parser.error(f"--plan: cannot read {plan_path}: {exc}")
    try:
        plan = json.loads(raw)
    except ValueError as exc:
        parser.error(f"--plan: {plan_path} is not valid JSON: {exc}")
    if plan.get("schema_version") == 1:
        parser.error(
            f"--plan: {plan_path}: run plan schema_version 1 is no longer accepted. "
            'Move "claude_max_turns" into "executor_options": {"max_turns": ...} and '
            'the opencode_* keys into "executor_options"/"evaluator_options" '
            '({"provider": ..., "base_url": ..., "api_key_env": ...}), then re-emit '
            "with schema_version 2."
        )
    try:
        validate_payload("run_plan.schema.json", plan)
    except ContractValidationError as exc:
        parser.error(f"--plan: {plan_path} violates the run_plan contract: {exc}")

    expanded: List[str] = []
    for key, value in plan.items():
        if key in _PLAN_NON_FLAG_KEYS:
            continue
        if key in PLAN_OPTION_FLAGS:
            for name, item in value.items():
                expanded += [
                    PLAN_OPTION_FLAGS[key],
                    f"{name}={str(item).lower() if isinstance(item, bool) else item}",
                ]
            continue
        if key in PLAN_LIST_FLAGS:
            for item in value:
                expanded += [PLAN_LIST_FLAGS[key], str(item)]
            continue
        expanded += ["--" + key.replace("_", "-"), str(value)]
    return expanded + retained, plan


def parse_args(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run StarBench benchmark tasks and rubric judges.",
        epilog=(
            "Built-in runtimes: "
            + ", ".join(f"{a.info.id} ({a.info.label})" for a in list_builtin())
            + "; or custom:<id> for a runtime defined in --runtimes-dir. "
            "When mixing runtimes, split auth with --executor-auth-mode and "
            "--evaluator-auth-mode."
        ),
    )
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--judge-mode", choices=["both", "single", "parallel"], default="both")
    parser.add_argument("--max-evaluator-parallel", type=int, default=4)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--batch",
        default=None,
        help=(
            "Experiment batch label recorded in run_config.json; runs launched "
            "together share it and the console groups/compares them by it."
        ),
    )
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=None,
        help="Task package library. Defaults to $STARBENCH_HOME/tasks (~/.starbench/tasks).",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Run artifact root. Defaults to $STARBENCH_HOME/runs (~/.starbench/runs).",
    )
    parser.add_argument("--task", action="append", help="Task id or task directory name to include. Repeatable.")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat the selected task list N times.")
    # One --<id>-bin flag per built-in runtime, derived from the adapter
    # registry so a new adapter gets its flag without touching this file.
    for adapter in list_builtin():
        info = adapter.info
        parser.add_argument(
            f"--{info.id}-bin",
            default=info.bin,
            help=(
                f"{info.label} executable, or a shell-like command prefix "
                f"({info.description})."
            ),
        )
    parser.add_argument(
        "--executor-bin",
        help="Role-specific executable override for the selected executor runtime.",
    )
    parser.add_argument(
        "--evaluator-bin",
        help="Role-specific executable override for the selected evaluator runtime.",
    )
    parser.add_argument(
        "--executor-agent",
        default="codex",
        help=(
            "Executor runtime: one of "
            + ", ".join(sorted(BUILTIN_AGENTS))
            + ", or custom:<id> for a runtime defined in --runtimes-dir."
        ),
    )
    parser.add_argument(
        "--evaluator-agent",
        default="codex",
        help=(
            "Evaluator runtime: one of "
            + ", ".join(sorted(BUILTIN_AGENTS))
            + ", or custom:<id> for a runtime defined in --runtimes-dir."
        ),
    )
    parser.add_argument(
        "--runtimes-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing custom runtime configs (<id>.json) for custom:<id> agents. "
            "Defaults to $STARBENCH_HOME/runtimes (~/.starbench/runtimes)."
        ),
    )
    parser.add_argument(
        "--thinking-effort",
        dest="thinking_effort",
        choices=[*THINKING_EFFORTS, LEGACY_THINKING_EFFORT],
        default="default",
        help=(
            "Reasoning effort for the executor, applied through each runtime's native switch "
            "where one exists (Claude Code --effort: low..max; Codex model_reasoning_effort: "
            "minimal..ultra; OpenCode --variant) and as a prompt-level instruction for the "
            "rest (low/medium/high). 'default' leaves the runtime/model default alone "
            "('none' is its deprecated spelling). Levels a runtime does not support are "
            "rejected at start."
        ),
    )
    parser.add_argument(
        "--claude-thinking-effort",
        dest="thinking_effort",
        choices=[*THINKING_EFFORTS, LEGACY_THINKING_EFFORT],
        default="default",
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
    for role in ("executor", "evaluator"):
        parser.add_argument(
            f"--{role}-option",
            action="append",
            default=[],
            metavar="NAME=VALUE",
            help=(
                f"Runtime-specific option for the {role} agent, e.g. max_turns=50. "
                "Repeatable. Valid names are declared by the selected runtime's "
                "adapter; unknown names are rejected before any task runs."
            ),
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
            "Defaults to docker for the codex runtime and local for other runtimes; "
            "docker can be selected for every built-in, and for custom runtimes "
            "whose spec declares a docker section."
        ),
    )
    parser.add_argument("--docker-bin", default="docker", help="Docker executable or shell-like command prefix.")
    parser.add_argument(
        "--docker-image",
        default=None,
        help=(
            "Image used when --executor-backend docker is selected. Defaults to the "
            "runtime's own image ("
            # Host-local-only runtimes (docker_image None) have no default to name.
            + ", ".join(
                DEFAULT_DOCKER_IMAGES[a.info.id] for a in list_builtin() if a.info.docker_capable
            )
            + "); custom runtimes take theirs from the spec's docker section."
        ),
    )
    parser.add_argument("--evaluator-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--instruction-mode",
        choices=list(INSTRUCTION_MODES),
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
        choices=list(RIGOR_MODES),
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
        default=None,
        help=(
            "Shared executor skill registry root containing registry.json and skill "
            "directories. Defaults to $STARBENCH_HOME/skills (~/.starbench/skills)."
        ),
    )
    parser.add_argument(
        "--profile-snapshot",
        type=Path,
        default=None,
        help=(
            "Path to a profile-snapshot JSON (the launch-time measurement contract; "
            "see schemas/starbench/v1/profile_snapshot.schema.json). Validated against "
            "the public contract before anything is written — an invalid snapshot "
            "aborts the start. A valid one is copied atomically to "
            "<run-root>/profile_snapshot.json. The contract carries environment-variable "
            "NAMES only (api_key_env), never key values."
        ),
    )
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars and progress stderr output.")
    # --plan expands into the equivalent flag argv BEFORE parsing, so both
    # transports share every validation and default below. Handled manually
    # (not via add_argument) because it rewrites the argv itself.
    tokens = list(argv) if argv is not None else sys.argv[1:]
    run_plan_data: Optional[Dict[str, Any]] = None
    if "--plan" in tokens:
        tokens, run_plan_data = _expand_plan_argv(tokens, parser)
    args = parser.parse_args(tokens)
    args.run_plan_data = run_plan_data
    # Dir defaults come from the StarBench home layout, resolved once here so
    # everything downstream sees absolute paths and never reads the environment.
    try:
        home = HomeLayout(resolve_home(environ))
    except ValueError as exc:
        parser.error(str(exc))
    if args.tasks_dir is None:
        args.tasks_dir = home.tasks
    if args.runs_dir is None:
        args.runs_dir = home.runs
    if args.executor_skill_root is None:
        args.executor_skill_root = home.skills
    if args.runtimes_dir is None:
        args.runtimes_dir = home.runtimes
    # Legacy spelling: old plans/scripts say "none"; everything downstream
    # (adapters, artifacts, validation) sees only the canonical "default".
    args.thinking_effort = canonical_thinking_effort(args.thinking_effort)
    if args.run_id is not None:
        try:
            args.run_id = parse_safe_id(args.run_id, kind="run id")
        except ValueError as error:
            parser.error(str(error))
    if args.batch:
        try:
            args.batch = parse_safe_id(args.batch, kind="batch label")
        except ValueError as error:
            parser.error(str(error))
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
        # A builtin without an image is host-local by design — there is no spec
        # to add a docker section to, so pointing at one would be bad advice.
        if args.executor_runtime_spec is None:
            parser.error(
                f"--executor-agent {args.executor_agent} does not support "
                "--executor-backend docker (host-local runtime); use --executor-backend local."
            )
        parser.error(
            f"--executor-agent {args.executor_agent} currently requires --executor-backend local; "
            "Docker isolation needs a docker section in the custom runtime spec."
        )
    if args.docker_image is None:
        args.docker_image = DEFAULT_DOCKER_IMAGES.get(args.executor_agent) or ""
    args.executor_auth_mode = args.executor_auth_mode or args.auth_mode
    args.evaluator_auth_mode = args.evaluator_auth_mode or args.auth_mode

    def parse_option_pairs(pairs, flag):
        raw: Dict[str, str] = {}
        for pair in pairs:
            name, sep, value = pair.partition("=")
            if not sep or not name:
                parser.error(f"{flag} expects NAME=VALUE, got {pair!r}")
            raw[name] = value
        return raw

    evaluator_adapter = resolve(
        args.evaluator_agent, spec=args.evaluator_runtime_spec, runtimes_dir=args.runtimes_dir
    )
    try:
        args.executor_options = resolve_runtime_options(
            executor_adapter, "executor", parse_option_pairs(args.executor_option, "--executor-option")
        )
        args.evaluator_options = resolve_runtime_options(
            evaluator_adapter, "evaluator", parse_option_pairs(args.evaluator_option, "--evaluator-option")
        )
    except ValueError as error:
        parser.error(str(error))
    args.tasks_dir = args.tasks_dir.resolve()
    args.runs_dir = args.runs_dir.resolve()
    args.executor_skill_root = args.executor_skill_root.resolve()

    # Profile snapshot: validate at parse time, before the run directory exists.
    # A snapshot that fails its public contract must abort the start (fail
    # closed) rather than be dropped silently or leave half a run behind.
    args.profile_snapshot_data = None
    if args.profile_snapshot is not None:
        try:
            raw_snapshot = args.profile_snapshot.read_text(encoding="utf-8")
        except OSError as exc:
            parser.error(f"--profile-snapshot: cannot read {args.profile_snapshot}: {exc}")
        try:
            snapshot_payload = json.loads(raw_snapshot)
        except ValueError as exc:
            parser.error(f"--profile-snapshot: {args.profile_snapshot} is not valid JSON: {exc}")
        try:
            validate_payload("profile_snapshot.schema.json", snapshot_payload)
        except ContractValidationError as exc:
            parser.error(
                f"--profile-snapshot: {args.profile_snapshot} violates the "
                f"profile_snapshot contract: {exc}"
            )
        args.profile_snapshot_data = snapshot_payload
    if args.run_plan_data is not None and args.run_plan_data.get("profile_snapshot") is not None:
        if args.profile_snapshot_data is not None:
            parser.error("--plan already embeds a profile snapshot; drop --profile-snapshot.")
        embedded = args.run_plan_data["profile_snapshot"]
        try:
            validate_payload("profile_snapshot.schema.json", embedded)
        except ContractValidationError as exc:
            parser.error(f"--plan: embedded profile_snapshot violates its contract: {exc}")
        args.profile_snapshot_data = embedded
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    summary = asyncio.run(run_benchmark(args))
    print(json.dumps({"run_id": summary["run_id"], "run_root": summary["run_root"]}, sort_keys=True))
    return 0
