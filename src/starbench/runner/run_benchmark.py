from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .codex_process import (
    append_claude_compat_events,
    append_opencode_compat_events,
    build_claude_print_command,
    build_codex_exec_command,
    build_custom_command,
    normalize_custom_events,
    write_custom_final_output,
    build_gemini_headless_command,
    build_grok_headless_command,
    build_opencode_run_command,
    normalize_headless_events,
    prepare_claude_env,
    prepare_gemini_env,
    prepare_grok_env,
    prepare_opencode_env,
    prepare_auth_home,
    opencode_docker_export_env,
    run_claude_process_in_docker,
    run_codex_process,
    run_codex_process_in_docker,
    run_custom_process_in_docker,
    run_gemini_process_in_docker,
    run_grok_process_in_docker,
    run_opencode_process_in_docker,
    DEFAULT_DOCKER_IMAGES,
    write_claude_final_output,
    write_claude_stream_final_output,
    write_headless_final_output,
    write_opencode_final_output,
)
from .custom_runtime import CustomRuntimeSpec, load_custom_runtime
from .evaluation import aggregate_results, normalize_parallel_results, normalize_single_result, write_aggregate
from .models import Rubric, TaskRunSpec, TaskSpec
from .progress import BenchmarkProgress, make_benchmark_progress
from starbench.skills.registry import expand_skill_groups, load_registry_skills
from .task_loader import build_task_runs, discover_tasks, duplicate_tasks
from .trace import build_artifact_manifest, write_trace_summary


PROJECT_ROOT = Path.cwd()
DEFAULT_TASKS_DIR = PROJECT_ROOT / "tasks"
DEFAULT_RUNS_DIR = PROJECT_ROOT / "runs"
DEFAULT_EXECUTOR_SKILLS_DIR = PROJECT_ROOT / "executor_skills"
DEFAULT_RUNTIMES_DIR = PROJECT_ROOT / "runtimes"
BUILTIN_AGENTS = {"codex", "claude", "opencode", "grok", "gemini"}
SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
IGNORED_EXECUTOR_SKILL_NAMES = {".DS_Store", ".git", "__pycache__"}
CLAUDE_THINKING_EFFORT_INSTRUCTIONS = {
    "none": "",
    "low": "Before responding, think carefully about the task and check for obvious gaps.",
    "medium": "Before responding, think through the task carefully, including constraints, edge cases, and verification steps.",
    "high": "Before responding, think deeply about the task. Build a complete plan, inspect relevant evidence, consider failure modes and alternatives, and self-check the final deliverable before finishing.",
}
CLAUDE_EXECUTOR_BASE_TOOLS = "Read,Write,Edit,MultiEdit,Bash,Glob,Grep,LS"
CLAUDE_EXECUTOR_WEB_TOOLS = "WebSearch,WebFetch"
# Judges must be read-only across runtimes; OpenCode's built-in plan agent
# matches the read-only sandboxes used for Codex/Grok/Gemini judges.
OPENCODE_JUDGE_AGENT = "plan"


def claude_executor_allowed_tools(allow_web_search: bool) -> str:
    if allow_web_search:
        return f"{CLAUDE_EXECUTOR_BASE_TOOLS},{CLAUDE_EXECUTOR_WEB_TOOLS}"
    return CLAUDE_EXECUTOR_BASE_TOOLS


def rubric_launch_order(rubrics: Sequence[Rubric], *, seed: int, run_task_id: str) -> List[Rubric]:
    """Deterministic per-task rubric launch order, independent of async scheduling."""
    order = list(rubrics)
    random.Random(f"{seed}:{run_task_id}").shuffle(order)
    return order


def json_dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_augmented_prompt_text(task_run: TaskRunSpec) -> str:
    prompt_text = task_run.task.prompt_text
    sections = []

    if task_run.selected_steps:
        instructions = "\n".join(
            f"{index}. {step.instruction}" for index, step in enumerate(task_run.selected_steps, start=1)
        )
        sections.append(f"""Here are some instructions you might find helpful:
{instructions}""")

    if task_run.selected_rigors:
        rigors = "\n".join(
            f"{index}. {rigor.requirement}" for index, rigor in enumerate(task_run.selected_rigors, start=1)
        )
        sections.append(f"""Ensure your answer reaches an equivalent level of rigor and depth to the following requirements:
{rigors}""")

    if not sections:
        return prompt_text
    return f"{prompt_text.rstrip()}\n\n" + "\n\n".join(sections) + "\n"


def build_executor_prompt(
    task_run: TaskRunSpec,
    *,
    executor_skill_location: str = "$CODEX_HOME/skills/<skill-id>/",
) -> str:
    executor_skill_section = ""
    if task_run.selected_executor_skills:
        skills = "\n".join(
            f"- `{skill.id}`: {skill.activation}" for skill in task_run.selected_executor_skills
        )
        executor_skill_section = f"""

Installed executor skills:
{skills}

Skill usage rules:
- Use the installed executor skills as private execution guidance for planning, execution, and final self-checking.
- You may read installed skill files under {executor_skill_location}.
- The task prompt and materials remain authoritative if they conflict with a skill.
- Do not mention installed skills, expert traces, harnesses, or internal checklists in deliverables."""

    return f"""You are running inside an isolated benchmark task workspace.

Rules:
- Read task materials from ./inputs/.
- Write all deliverables under ./outputs/.
- Do not inspect parent directories or sibling benchmark tasks.
- Do not look for or infer hidden rubrics.
- Use only the capabilities requested by the task.
- Before finishing, run the requested sample verification if the task asks for one.{executor_skill_section}

Task prompt from ./inputs/prompt.md:

{build_augmented_prompt_text(task_run)}
"""


def append_claude_thinking_instruction(prompt: str, effort: str) -> str:
    instruction = CLAUDE_THINKING_EFFORT_INSTRUCTIONS[effort]
    if not instruction:
        return prompt
    return f"{prompt.rstrip()}\n\nClaude thinking effort instruction:\n{instruction}\n"


def append_json_schema_instruction(prompt: str, schema_path: Path) -> str:
    schema = schema_path.read_text(encoding="utf-8")
    return f"""{prompt.rstrip()}

Return only one JSON value that matches this JSON schema. Do not wrap it in Markdown fences or add commentary.

JSON schema:
{schema}
"""


def opencode_model_name(model: str | None, provider: str | None) -> str | None:
    if not model or not provider or "/" in model:
        return model
    return f"{provider}/{model}"


def build_single_judge_prompt(task: TaskSpec) -> str:
    rubrics = [rubric.to_dict() for rubric in task.rubrics]
    return f"""You are an evaluator for a StarBench benchmark task.

Inspect this task run directory. The executor deliverables are under ./workspace/outputs/.
The executor trace is available in ./logs/events.jsonl, ./logs/trace_summary.json, ./logs/artifact_manifest.json, and ./logs/final.md.
Executor timing is available in ./logs/status.json.
Raw input materials are intentionally omitted from this evaluator workspace for speed and isolation; use ./manifest.json and the trace/artifact summaries to understand what was available to the executor.

Your job is rubric evidence checking, not solving the original task again.
Use this review order:
1. Read ./workspace/outputs/ and the log summaries first.
2. Read ./workspace/inputs/prompt.md only to understand what the executor was asked to do.
3. Read ./manifest.json and ./logs/artifact_manifest.json for file inventory.
4. If a rubric appears to require raw-material verification that is not present here, judge from the executor-visible evidence and explain the limitation.

Strict evaluator limits:
- Do not redo the task, write a replacement answer, or conduct open-ended analysis.
- Do not browse the web.
- Prefer bounded reads such as file listings, small excerpts, targeted grep/rg, or focused jq queries over reading entire large files.
- If a rubric asks whether the executor cited or used evidence, judge what the executor delivered; do not give credit for evidence you discovered yourself but the executor did not use.
- If a rubric is ambiguous after reasonable bounded inspection, answer using the visible executor package and explain the uncertainty in evidence.

Judge every rubric independently. Each rubric is a yes/no question. For each rubric:
- answer is your yes/no judgment as a boolean.
- expected is the rubric's expected boolean.
- passed is true only when answer == expected.
- fail_fast must match the rubric.
- evidence must cite concrete files, commands, outputs, or trace entries.

Return one JSON object matching the schema, with a result for every rubric.

Task id: {task.id}
Rubrics:
{json.dumps(rubrics, indent=2, sort_keys=True)}
"""


def build_parallel_judge_prompt(task: TaskSpec, rubric: Rubric) -> str:
    return f"""You are an evaluator for one StarBench benchmark rubric.

Inspect this task run directory. The executor deliverables are under ./workspace/outputs/.
The executor trace is available in ./logs/events.jsonl, ./logs/trace_summary.json, ./logs/artifact_manifest.json, and ./logs/final.md.
Executor timing is available in ./logs/status.json.
Raw input materials are intentionally omitted from this evaluator workspace for speed and isolation; use ./manifest.json and the trace/artifact summaries to understand what was available to the executor.

Your job is rubric evidence checking, not solving the original task again.
Use this review order:
1. Read ./workspace/outputs/ and the log summaries first.
2. Read ./workspace/inputs/prompt.md only to understand what the executor was asked to do.
3. Read ./manifest.json and ./logs/artifact_manifest.json for file inventory.
4. If this rubric appears to require raw-material verification that is not present here, judge from the executor-visible evidence and explain the limitation.

Strict evaluator limits:
- Do not redo the task, write a replacement answer, or conduct open-ended analysis.
- Do not browse the web.
- Prefer bounded reads such as file listings, small excerpts, targeted grep/rg, or focused jq queries over reading entire large files.
- If this rubric asks whether the executor cited or used evidence, judge what the executor delivered; do not give credit for evidence you discovered yourself but the executor did not use.
- If this rubric is ambiguous after reasonable bounded inspection, answer using the visible executor package and explain the uncertainty in evidence.

Judge only this rubric. It is a yes/no question.
- answer is your yes/no judgment as a boolean.
- expected is the rubric's expected boolean.
- passed is true only when answer == expected.
- fail_fast must match the rubric.
- evidence must cite concrete files, commands, outputs, or trace entries.

Return one JSON object matching the schema.

Task id: {task.id}
Rubric:
{json.dumps(rubric.to_dict(), indent=2, sort_keys=True)}
"""


def copy_task_material(source: Path, destination: Path) -> None:
    if destination.exists():
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _is_ignored_executor_skill_path(path: Path) -> bool:
    return any(part in IGNORED_EXECUTOR_SKILL_NAMES for part in path.parts)


def hash_executor_skill_directory(source: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(source.rglob("*")):
        relative_path = path.relative_to(source)
        if _is_ignored_executor_skill_path(relative_path):
            continue
        if not path.is_file():
            continue
        hasher.update(str(relative_path).encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def executor_skill_install_root(paths: Dict[str, Path], executor_backend: str, executor_agent: str) -> Path:
    if executor_agent == "codex":
        if executor_backend == "docker":
            return paths["codex_home"] / "docker" / "skills"
        if executor_backend == "local":
            return paths["codex_home"] / "skills"
    if executor_agent == "grok":
        return paths["workspace"] / ".grok" / "skills"
    if executor_agent == "gemini":
        return paths["workspace"] / ".gemini" / "skills"
    if executor_agent == "claude":
        return paths["workspace"] / ".claude" / "skills"
    if executor_agent == "opencode" or executor_agent.startswith("custom:"):
        return paths["workspace"] / ".starbench" / "executor_skills"
    raise ValueError(f"Unknown executor backend: {executor_backend}")


def executor_skill_prompt_location(executor_agent: str) -> str:
    if executor_agent == "codex":
        return "$CODEX_HOME/skills/<skill-id>/"
    if executor_agent == "grok":
        return "./.grok/skills/<skill-id>/"
    if executor_agent == "gemini":
        return "./.gemini/skills/<skill-id>/"
    if executor_agent == "claude":
        return "./.claude/skills/<skill-id>/"
    if executor_agent == "opencode" or executor_agent.startswith("custom:"):
        return "./.starbench/executor_skills/<skill-id>/"
    return "./<skill-id>/"


def install_executor_skills(
    task_run: TaskRunSpec,
    paths: Dict[str, Path],
    *,
    executor_backend: str,
    executor_agent: str = "codex",
) -> List[Dict[str, Any]]:
    installed: List[Dict[str, Any]] = []
    if not task_run.selected_executor_skills:
        return installed

    install_root = executor_skill_install_root(paths, executor_backend, executor_agent)
    install_root.mkdir(parents=True, exist_ok=True)
    for skill in task_run.selected_executor_skills:
        digest = hash_executor_skill_directory(skill.source_path)
        if skill.sha256 is not None and skill.sha256 != digest:
            raise ValueError(
                f"Executor skill {skill.id} sha256 mismatch: expected {skill.sha256}, got {digest}"
            )

        destination = install_root / skill.id
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.copytree(
            skill.source_path,
            destination,
            ignore=shutil.ignore_patterns(*IGNORED_EXECUTOR_SKILL_NAMES),
        )
        try:
            installed_to = str(destination.relative_to(paths["task_root"]))
        except ValueError:
            installed_to = str(destination)
        metadata = skill.public_metadata(installed_to=installed_to)
        metadata["sha256"] = digest
        installed.append(metadata)
    return installed


def prepare_evaluator_workspace(paths: Dict[str, Path], name: str) -> Path:
    """Create a slim judge workspace that omits raw input materials by default."""
    task_root = paths["task_root"]
    source_workspace = paths["workspace"]
    judge_workspace = paths["judges"] / f"{name}_workspace"
    if judge_workspace.exists():
        shutil.rmtree(judge_workspace)
    (judge_workspace / "workspace" / "inputs").mkdir(parents=True, exist_ok=True)
    (judge_workspace / "workspace" / "outputs").mkdir(parents=True, exist_ok=True)
    (judge_workspace / "logs").mkdir(parents=True, exist_ok=True)

    prompt_path = source_workspace / "inputs" / "prompt.md"
    if prompt_path.exists():
        shutil.copy2(prompt_path, judge_workspace / "workspace" / "inputs" / "prompt.md")

    outputs_path = source_workspace / "outputs"
    if outputs_path.exists():
        # Executor outputs may include temporary Python environments or vendored
        # packages created while extracting PDFs. They are not deliverables and
        # can contain container-local symlinks that break host-side copytree.
        shutil.copytree(
            outputs_path,
            judge_workspace / "workspace" / "outputs",
            dirs_exist_ok=True,
            symlinks=True,
            ignore=shutil.ignore_patterns(".venv", "venv", "__pycache__", "_vendor"),
        )

    for path in sorted(source_workspace.iterdir()):
        if path.name in {"inputs", "outputs", ".runner"}:
            continue
        destination = judge_workspace / "workspace" / path.name
        if path.is_file():
            shutil.copy2(path, destination)

    for filename in ("events.jsonl", "final.md", "status.json", "trace_summary.json", "artifact_manifest.json"):
        source = task_root / "logs" / filename
        if source.exists():
            shutil.copy2(source, judge_workspace / "logs" / filename)

    manifest_path = task_root / "manifest.json"
    if manifest_path.exists():
        shutil.copy2(manifest_path, judge_workspace / "manifest.json")

    return judge_workspace


def materialize_task(
    task_run: TaskRunSpec,
    run_root: Path,
    run_task_id: str,
    *,
    executor_backend: str = "docker",
    executor_agent: str = "codex",
) -> Dict[str, Path]:
    task = task_run.task
    task_root = run_root / run_task_id
    workspace = task_root / "workspace"
    inputs = workspace / "inputs"
    outputs = workspace / "outputs"
    logs = task_root / "logs"
    judges = task_root / "judges"
    codex_home = task_root / "codex_home"

    inputs.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    judges.mkdir(parents=True, exist_ok=True)
    codex_home.mkdir(parents=True, exist_ok=True)

    (inputs / "prompt.md").write_text(build_augmented_prompt_text(task_run), encoding="utf-8")
    if task.files_dir is not None:
        destination = inputs / "files"
        copy_task_material(task.files_dir, destination)
    input_materials = []
    for material_path in task.material_paths:
        try:
            relative_path = material_path.relative_to(task.source_dir)
        except ValueError:
            relative_path = Path(material_path.name)
        destination = inputs / relative_path
        copy_task_material(material_path, destination)
        input_materials.append(str(relative_path))

    paths = {
        "task_root": task_root,
        "workspace": workspace,
        "inputs": inputs,
        "outputs": outputs,
        "logs": logs,
        "judges": judges,
        "codex_home": codex_home,
    }
    installed_executor_skills = install_executor_skills(
        task_run,
        paths,
        executor_backend=executor_backend,
        executor_agent=executor_agent,
    )

    json_dump(
        task_root / "manifest.json",
        {
            "task_id": task.id,
            "task_name": task.name,
            "run_task_id": run_task_id,
            "rubric_count": len(task.rubrics),
            "timeout_seconds": task.timeout_seconds,
            "allow_web_search": task.allow_web_search,
            "input_materials": input_materials,
            "installed_executor_skills": installed_executor_skills,
            **task_run.instruction_metadata(),
        },
    )

    return paths


async def run_executor(
    task_run: TaskRunSpec,
    paths: Dict[str, Path],
    *,
    agent: str,
    codex_bin: str,
    claude_bin: str,
    grok_bin: str,
    gemini_bin: str,
    opencode_bin: str,
    opencode_provider: str | None,
    opencode_base_url: str | None,
    opencode_api_key_env: str | None,
    claude_thinking_effort: str,
    claude_max_turns: int | None,
    auth_mode: str,
    model: str | None,
    executor_backend: str,
    docker_bin: str,
    docker_image: str,
    custom_spec: CustomRuntimeSpec | None = None,
) -> Dict[str, Any]:
    task = task_run.task
    logs = paths["logs"]
    if agent.startswith("custom:") and executor_backend != "local":
        if custom_spec is None or custom_spec.docker_image is None:
            raise ValueError(f"{agent} executor requires a docker section for --executor-backend docker")

    if agent.startswith("custom:"):
        if custom_spec is None:
            raise ValueError(f"Custom runtime spec missing for {agent}")
        prompt_text = build_executor_prompt(
            task_run, executor_skill_location=executor_skill_prompt_location(agent)
        )
        if executor_backend == "docker":
            result = await run_custom_process_in_docker(
                custom_spec,
                docker_bin=docker_bin,
                workspace=paths["workspace"],
                prompt=prompt_text,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=model,
            )
        else:
            command = build_custom_command(custom_spec, role="executor", model=model, prompt=prompt_text)
            env = os.environ.copy()
            env.update(custom_spec.env)
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=prompt_text if custom_spec.prompt_via == "stdin" else "",
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )
        if result.status == "success":
            try:
                write_custom_final_output(logs / "events.jsonl", logs / "final.md", parser=custom_spec.parser)
                normalize_custom_events(logs / "events.jsonl", parser=custom_spec.parser, provider=custom_spec.id)
            except Exception as exc:
                result = result.__class__(
                    command=result.command,
                    exit_code=result.exit_code,
                    status="failed",
                    timed_out=result.timed_out,
                    started_at=result.started_at,
                    ended_at=result.ended_at,
                    duration_seconds=result.duration_seconds,
                )
                (logs / "stderr.log").open("a", encoding="utf-8").write(
                    f"\nCustom runtime output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
    elif agent == "claude":
        claude_prompt = append_claude_thinking_instruction(
            build_executor_prompt(
                task_run,
                executor_skill_location=executor_skill_prompt_location(agent),
            ),
            claude_thinking_effort,
        )
        if executor_backend == "docker":
            result = await run_claude_process_in_docker(
                claude_bin=claude_bin,
                docker_bin=docker_bin,
                docker_image=docker_image,
                workspace=paths["workspace"],
                prompt=claude_prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=model,
                allowed_tools=claude_executor_allowed_tools(task.allow_web_search),
                max_turns=claude_max_turns,
            )
        else:
            command = build_claude_print_command(
                claude_bin,
                cwd=paths["workspace"],
                model=model,
                permission_mode="acceptEdits",
                allowed_tools=claude_executor_allowed_tools(task.allow_web_search),
                max_turns=claude_max_turns,
                output_format="stream-json",
            )
            env = prepare_claude_env(paths["codex_home"] / "claude_executor", auth_mode)
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=claude_prompt,
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )
        if result.status == "success":
            try:
                write_claude_stream_final_output(logs / "events.jsonl", logs / "final.md")
                append_claude_compat_events(logs / "events.jsonl")
            except Exception as exc:
                result = result.__class__(
                    command=result.command,
                    exit_code=result.exit_code,
                    status="failed",
                    timed_out=result.timed_out,
                    started_at=result.started_at,
                    ended_at=result.ended_at,
                    duration_seconds=result.duration_seconds,
                )
                (logs / "stderr.log").open("a", encoding="utf-8").write(
                    f"\nClaude output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
    elif agent == "opencode":
        model_name = opencode_model_name(model, opencode_provider)
        opencode_prompt = build_executor_prompt(
            task_run,
            executor_skill_location=executor_skill_prompt_location(agent),
        )
        if executor_backend == "docker":
            result = await run_opencode_process_in_docker(
                opencode_bin=opencode_bin,
                docker_bin=docker_bin,
                docker_image=docker_image,
                workspace=paths["workspace"],
                prompt=opencode_prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=model_name,
                provider=opencode_provider,
                base_url=opencode_base_url,
                api_key_env=opencode_api_key_env,
            )
            env = opencode_docker_export_env(paths["workspace"])
        else:
            command = build_opencode_run_command(
                opencode_bin,
                cwd=paths["workspace"],
                model=model_name,
                agent="build",
            )
            env = prepare_opencode_env(
                paths["codex_home"] / "opencode_executor",
                auth_mode,
                provider=opencode_provider,
                base_url=opencode_base_url,
                model=model_name,
                api_key_env=opencode_api_key_env,
            )
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=opencode_prompt,
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )
        if result.status == "success":
            try:
                append_opencode_compat_events(logs / "events.jsonl")
                write_opencode_final_output(
                    logs / "events.jsonl",
                    logs / "final.md",
                    opencode_bin=opencode_bin,
                    env=env,
                )
            except Exception as exc:
                result = result.__class__(
                    command=result.command,
                    exit_code=result.exit_code,
                    status="failed",
                    timed_out=result.timed_out,
                    started_at=result.started_at,
                    ended_at=result.ended_at,
                    duration_seconds=result.duration_seconds,
                )
                (logs / "stderr.log").open("a", encoding="utf-8").write(
                    f"\nOpenCode output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
    elif agent == "grok":
        prompt = build_executor_prompt(
            task_run,
            executor_skill_location=executor_skill_prompt_location(agent),
        )
        if executor_backend == "docker":
            result = await run_grok_process_in_docker(
                grok_bin=grok_bin,
                docker_bin=docker_bin,
                docker_image=docker_image,
                workspace=paths["workspace"],
                prompt=prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=model,
            )
        else:
            command = build_grok_headless_command(
                grok_bin,
                cwd=paths["workspace"],
                prompt=prompt,
                model=model,
                permission_mode="bypassPermissions",
                sandbox="workspace",
            )
            env = prepare_grok_env(paths["codex_home"] / "grok_executor", auth_mode)
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt="",
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )
        if result.status == "success":
            try:
                write_headless_final_output(logs / "events.jsonl", logs / "final.md")
                normalize_headless_events(logs / "events.jsonl", provider="grok")
            except Exception as exc:
                result = result.__class__(
                    command=result.command,
                    exit_code=result.exit_code,
                    status="failed",
                    timed_out=result.timed_out,
                    started_at=result.started_at,
                    ended_at=result.ended_at,
                    duration_seconds=result.duration_seconds,
                )
                (logs / "stderr.log").open("a", encoding="utf-8").write(
                    f"\nGrok output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
    elif agent == "gemini":
        gemini_prompt = build_executor_prompt(
            task_run,
            executor_skill_location=executor_skill_prompt_location(agent),
        )
        if executor_backend == "docker":
            result = await run_gemini_process_in_docker(
                gemini_bin=gemini_bin,
                docker_bin=docker_bin,
                docker_image=docker_image,
                workspace=paths["workspace"],
                prompt=gemini_prompt,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
                model=model,
            )
        else:
            command = build_gemini_headless_command(
                gemini_bin,
                model=model,
                approval_mode="yolo",
            )
            env = prepare_gemini_env(paths["codex_home"] / "gemini_executor", auth_mode)
            result = await run_codex_process(
                command,
                cwd=paths["workspace"],
                prompt=gemini_prompt,
                env=env,
                stdout_path=logs / "events.jsonl",
                stderr_path=logs / "stderr.log",
                timeout_seconds=task.timeout_seconds,
            )
        if result.status == "success":
            try:
                write_headless_final_output(logs / "events.jsonl", logs / "final.md")
                normalize_headless_events(logs / "events.jsonl", provider="gemini")
            except Exception as exc:
                result = result.__class__(
                    command=result.command,
                    exit_code=result.exit_code,
                    status="failed",
                    timed_out=result.timed_out,
                    started_at=result.started_at,
                    ended_at=result.ended_at,
                    duration_seconds=result.duration_seconds,
                )
                (logs / "stderr.log").open("a", encoding="utf-8").write(
                    f"\nGemini output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
    elif executor_backend == "local":
        command = build_codex_exec_command(
            codex_bin,
            cwd=paths["workspace"],
            final_path=logs / "final.md",
            sandbox="workspace-write",
            model=model,
            allow_web_search=task.allow_web_search,
            include_trace_config=True,
        )
        env = prepare_auth_home(paths["codex_home"], auth_mode)
        result = await run_codex_process(
            command,
            cwd=paths["workspace"],
            prompt=build_executor_prompt(task_run),
            env=env,
            stdout_path=logs / "events.jsonl",
            stderr_path=logs / "stderr.log",
            timeout_seconds=task.timeout_seconds,
        )
    elif executor_backend == "docker":
        result = await run_codex_process_in_docker(
            codex_bin=codex_bin,
            docker_bin=docker_bin,
            docker_image=docker_image,
            workspace=paths["workspace"],
            codex_home=paths["codex_home"],
            prompt=build_executor_prompt(task_run),
            auth_mode=auth_mode,
            stdout_path=logs / "events.jsonl",
            stderr_path=logs / "stderr.log",
            host_final_path=logs / "final.md",
            timeout_seconds=task.timeout_seconds,
            sandbox="danger-full-access",
            model=model,
            allow_web_search=task.allow_web_search,
            include_trace_config=True,
        )
    else:
        raise ValueError(f"Unknown executor backend: {executor_backend}")
    trace_summary = write_trace_summary(logs / "events.jsonl", logs / "trace_summary.json")
    artifact_manifest = build_artifact_manifest(paths["outputs"], logs / "artifact_manifest.json")
    status = {
        **result.to_dict(),
        "executor_backend": executor_backend,
        "docker_image": docker_image if executor_backend == "docker" else None,
        "trace_summary_path": str(logs / "trace_summary.json"),
        "artifact_manifest_path": str(logs / "artifact_manifest.json"),
        "usage": trace_summary.get("usage"),
        "artifact_file_count": artifact_manifest["file_count"],
    }
    json_dump(logs / "status.json", status)
    return status


async def run_single_judge(
    task: TaskSpec,
    paths: Dict[str, Path],
    *,
    agent: str,
    codex_bin: str,
    claude_bin: str,
    grok_bin: str,
    gemini_bin: str,
    opencode_bin: str,
    opencode_provider: str | None,
    opencode_base_url: str | None,
    opencode_api_key_env: str | None,
    claude_thinking_effort: str,
    auth_mode: str,
    model: str | None,
    timeout_seconds: int,
    executor_timing: Dict[str, Any] | None = None,
    semaphore: asyncio.Semaphore | None = None,
    custom_spec: CustomRuntimeSpec | None = None,
) -> Dict[str, Any]:
    judges = paths["judges"]
    final_path = judges / "single_result.json"

    async def run() -> Dict[str, Any]:
        judge_workspace = prepare_evaluator_workspace(paths, "single")
        judge_final_path = judge_workspace / "single_result.json"
        prompt = build_single_judge_prompt(task)
        if agent.startswith("custom:"):
            if custom_spec is None:
                raise ValueError(f"Custom runtime spec missing for {agent}")
            prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "single_result.schema.json")
            command = build_custom_command(custom_spec, role="judge", model=model, prompt=prompt)
            env = os.environ.copy()
            env.update(custom_spec.env)
        elif agent == "claude":
            command = build_claude_print_command(
                claude_bin,
                cwd=judge_workspace,
                model=model,
                output_schema=SCHEMAS_DIR / "single_result.schema.json",
                allowed_tools="Read,Glob,Grep,Bash,LS",
            )
            env = prepare_claude_env(paths["codex_home"] / "judge_single_claude", auth_mode)
        elif agent == "opencode":
            model_name = opencode_model_name(model, opencode_provider)
            command = build_opencode_run_command(
                opencode_bin,
                cwd=judge_workspace,
                model=model_name,
                agent=OPENCODE_JUDGE_AGENT,
            )
            env = prepare_opencode_env(
                paths["codex_home"] / "judge_single_opencode",
                auth_mode,
                provider=opencode_provider,
                base_url=opencode_base_url,
                model=model_name,
                api_key_env=opencode_api_key_env,
            )
            prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "single_result.schema.json")
        elif agent == "grok":
            prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "single_result.schema.json")
            command = build_grok_headless_command(
                grok_bin,
                cwd=judge_workspace,
                prompt=prompt,
                model=model,
                permission_mode="dontAsk",
                sandbox="read-only",
            )
            env = prepare_grok_env(paths["codex_home"] / "judge_single_grok", auth_mode)
        elif agent == "gemini":
            command = build_gemini_headless_command(
                gemini_bin,
                model=model,
                approval_mode="plan",
            )
            env = prepare_gemini_env(paths["codex_home"] / "judge_single_gemini", auth_mode)
            prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "single_result.schema.json")
        else:
            command = build_codex_exec_command(
                codex_bin,
                cwd=judge_workspace,
                final_path=judge_final_path,
                sandbox="read-only",
                output_schema=SCHEMAS_DIR / "single_result.schema.json",
                model=model,
                include_trace_config=False,
            )
            env = prepare_auth_home(paths["codex_home"] / "judge_single", auth_mode)
        prompt_over_stdin = not (
            agent == "grok"
            or (agent.startswith("custom:") and custom_spec is not None and custom_spec.prompt_via == "arg")
        )
        process_result = await run_codex_process(
            command,
            cwd=judge_workspace,
            prompt=append_claude_thinking_instruction(
                prompt,
                claude_thinking_effort if agent == "claude" else "none",
            ) if prompt_over_stdin else "",
            env=env,
            stdout_path=judges / "single_events.jsonl",
            stderr_path=judges / "single_stderr.log",
            timeout_seconds=timeout_seconds,
        )
        if agent.startswith("custom:") and process_result.status == "success":
            try:
                write_custom_final_output(
                    judges / "single_events.jsonl",
                    judge_final_path,
                    parser=custom_spec.parser,
                    output_schema=SCHEMAS_DIR / "single_result.schema.json",
                )
                normalize_custom_events(
                    judges / "single_events.jsonl", parser=custom_spec.parser, provider=custom_spec.id
                )
            except Exception as exc:
                process_result = process_result.__class__(
                    command=process_result.command,
                    exit_code=process_result.exit_code,
                    status="failed",
                    timed_out=process_result.timed_out,
                    started_at=process_result.started_at,
                    ended_at=process_result.ended_at,
                    duration_seconds=process_result.duration_seconds,
                )
                (judges / "single_stderr.log").open("a", encoding="utf-8").write(
                    f"\nCustom runtime output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
        if agent == "claude" and process_result.status == "success":
            try:
                write_claude_final_output(
                    judges / "single_events.jsonl",
                    judge_final_path,
                    output_schema=SCHEMAS_DIR / "single_result.schema.json",
                )
            except Exception as exc:
                process_result = process_result.__class__(
                    command=process_result.command,
                    exit_code=process_result.exit_code,
                    status="failed",
                    timed_out=process_result.timed_out,
                    started_at=process_result.started_at,
                    ended_at=process_result.ended_at,
                    duration_seconds=process_result.duration_seconds,
                )
                (judges / "single_stderr.log").open("a", encoding="utf-8").write(
                    f"\nClaude output post-processing failed: {type(exc).__name__}: {exc}\n"
        )
        if agent == "opencode" and process_result.status == "success":
            try:
                append_opencode_compat_events(judges / "single_events.jsonl")
                write_opencode_final_output(
                    judges / "single_events.jsonl",
                    judge_final_path,
                    opencode_bin=opencode_bin,
                    env=env,
                    output_schema=SCHEMAS_DIR / "single_result.schema.json",
                )
            except Exception as exc:
                process_result = process_result.__class__(
                    command=process_result.command,
                    exit_code=process_result.exit_code,
                    status="failed",
                    timed_out=process_result.timed_out,
                    started_at=process_result.started_at,
                    ended_at=process_result.ended_at,
                    duration_seconds=process_result.duration_seconds,
                )
                (judges / "single_stderr.log").open("a", encoding="utf-8").write(
                    f"\nOpenCode output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
        if agent in {"grok", "gemini"} and process_result.status == "success":
            try:
                write_headless_final_output(
                    judges / "single_events.jsonl",
                    judge_final_path,
                    output_schema=SCHEMAS_DIR / "single_result.schema.json",
                )
                normalize_headless_events(judges / "single_events.jsonl", provider=agent)
            except Exception as exc:
                process_result = process_result.__class__(
                    command=process_result.command,
                    exit_code=process_result.exit_code,
                    status="failed",
                    timed_out=process_result.timed_out,
                    started_at=process_result.started_at,
                    ended_at=process_result.ended_at,
                    duration_seconds=process_result.duration_seconds,
                )
                (judges / "single_stderr.log").open("a", encoding="utf-8").write(
                    f"\n{agent.title()} output post-processing failed: {type(exc).__name__}: {exc}\n"
                )
        if judge_final_path.exists():
            shutil.copy2(judge_final_path, final_path)
        return process_result.to_dict()

    if semaphore is None:
        status = await run()
    else:
        async with semaphore:
            status = await run()

    try:
        aggregate = aggregate_results(
            task.rubrics,
            normalize_single_result(final_path),
            mode="single",
            executor_timing=executor_timing,
        )
    except Exception as exc:
        aggregate = {
            "mode": "single",
            "overall_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
            "executor_timing": executor_timing,
            "results": [],
        }
    write_aggregate(judges / "single_aggregate.json", aggregate)
    json_dump(judges / "single_status.json", status)
    return {"status": status, "aggregate": aggregate}


async def run_parallel_judges(
    task: TaskSpec,
    paths: Dict[str, Path],
    *,
    agent: str,
    codex_bin: str,
    claude_bin: str,
    grok_bin: str,
    gemini_bin: str,
    opencode_bin: str,
    opencode_provider: str | None,
    opencode_base_url: str | None,
    opencode_api_key_env: str | None,
    claude_thinking_effort: str,
    auth_mode: str,
    model: str | None,
    timeout_seconds: int,
    executor_timing: Dict[str, Any] | None,
    semaphore: asyncio.Semaphore,
    launch_order: Sequence[Rubric],
    progress: BenchmarkProgress | None = None,
    run_task_id: str | None = None,
    custom_spec: CustomRuntimeSpec | None = None,
) -> Dict[str, Any]:
    async def run_one(rubric: Rubric) -> None:
        async with semaphore:
            if progress is not None and run_task_id is not None:
                progress.evaluator_started(run_task_id=run_task_id, mode="parallel", rubric_id=rubric.id)
            rubric_dir = paths["judges"] / "parallel" / rubric.id
            rubric_dir.mkdir(parents=True, exist_ok=True)
            judge_workspace = prepare_evaluator_workspace(paths, f"parallel_{rubric.id}")
            judge_final_path = judge_workspace / "result.json"
            prompt = build_parallel_judge_prompt(task, rubric)
            if agent.startswith("custom:"):
                if custom_spec is None:
                    raise ValueError(f"Custom runtime spec missing for {agent}")
                prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "rubric_result.schema.json")
                command = build_custom_command(custom_spec, role="judge", model=model, prompt=prompt)
                env = os.environ.copy()
                env.update(custom_spec.env)
            elif agent == "claude":
                command = build_claude_print_command(
                    claude_bin,
                    cwd=judge_workspace,
                    model=model,
                    output_schema=SCHEMAS_DIR / "rubric_result.schema.json",
                    allowed_tools="Read,Glob,Grep,Bash,LS",
                )
                env = prepare_claude_env(paths["codex_home"] / f"judge_{rubric.id}_claude", auth_mode)
            elif agent == "opencode":
                model_name = opencode_model_name(model, opencode_provider)
                command = build_opencode_run_command(
                    opencode_bin,
                    cwd=judge_workspace,
                    model=model_name,
                    agent=OPENCODE_JUDGE_AGENT,
                )
                env = prepare_opencode_env(
                    paths["codex_home"] / f"judge_{rubric.id}_opencode",
                    auth_mode,
                    provider=opencode_provider,
                    base_url=opencode_base_url,
                    model=model_name,
                    api_key_env=opencode_api_key_env,
                )
                prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "rubric_result.schema.json")
            elif agent == "grok":
                prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "rubric_result.schema.json")
                command = build_grok_headless_command(
                    grok_bin,
                    cwd=judge_workspace,
                    prompt=prompt,
                    model=model,
                    permission_mode="dontAsk",
                    sandbox="read-only",
                )
                env = prepare_grok_env(paths["codex_home"] / f"judge_{rubric.id}_grok", auth_mode)
            elif agent == "gemini":
                command = build_gemini_headless_command(
                    gemini_bin,
                    model=model,
                    approval_mode="plan",
                )
                env = prepare_gemini_env(paths["codex_home"] / f"judge_{rubric.id}_gemini", auth_mode)
                prompt = append_json_schema_instruction(prompt, SCHEMAS_DIR / "rubric_result.schema.json")
            else:
                command = build_codex_exec_command(
                    codex_bin,
                    cwd=judge_workspace,
                    final_path=judge_final_path,
                    sandbox="read-only",
                    output_schema=SCHEMAS_DIR / "rubric_result.schema.json",
                    model=model,
                    include_trace_config=False,
                )
                env = prepare_auth_home(paths["codex_home"] / f"judge_{rubric.id}", auth_mode)
            prompt_over_stdin = not (
                agent == "grok"
                or (agent.startswith("custom:") and custom_spec is not None and custom_spec.prompt_via == "arg")
            )
            process_result = await run_codex_process(
                command,
                cwd=judge_workspace,
                prompt=append_claude_thinking_instruction(
                    prompt,
                    claude_thinking_effort if agent == "claude" else "none",
                ) if prompt_over_stdin else "",
                env=env,
                stdout_path=rubric_dir / "events.jsonl",
                stderr_path=rubric_dir / "stderr.log",
                timeout_seconds=timeout_seconds,
            )
            if agent.startswith("custom:") and process_result.status == "success":
                try:
                    write_custom_final_output(
                        rubric_dir / "events.jsonl",
                        judge_final_path,
                        parser=custom_spec.parser,
                        output_schema=SCHEMAS_DIR / "rubric_result.schema.json",
                    )
                    normalize_custom_events(
                        rubric_dir / "events.jsonl", parser=custom_spec.parser, provider=custom_spec.id
                    )
                except Exception as exc:
                    process_result = process_result.__class__(
                        command=process_result.command,
                        exit_code=process_result.exit_code,
                        status="failed",
                        timed_out=process_result.timed_out,
                        started_at=process_result.started_at,
                        ended_at=process_result.ended_at,
                        duration_seconds=process_result.duration_seconds,
                    )
                    (rubric_dir / "stderr.log").open("a", encoding="utf-8").write(
                        f"\nCustom runtime output post-processing failed: {type(exc).__name__}: {exc}\n"
                    )
            if agent == "claude" and process_result.status == "success":
                try:
                    write_claude_final_output(
                        rubric_dir / "events.jsonl",
                        judge_final_path,
                        output_schema=SCHEMAS_DIR / "rubric_result.schema.json",
                    )
                except Exception as exc:
                    process_result = process_result.__class__(
                        command=process_result.command,
                        exit_code=process_result.exit_code,
                        status="failed",
                        timed_out=process_result.timed_out,
                        started_at=process_result.started_at,
                        ended_at=process_result.ended_at,
                        duration_seconds=process_result.duration_seconds,
                    )
                    (rubric_dir / "stderr.log").open("a", encoding="utf-8").write(
                        f"\nClaude output post-processing failed: {type(exc).__name__}: {exc}\n"
            )
            if agent == "opencode" and process_result.status == "success":
                try:
                    append_opencode_compat_events(rubric_dir / "events.jsonl")
                    write_opencode_final_output(
                        rubric_dir / "events.jsonl",
                        judge_final_path,
                        opencode_bin=opencode_bin,
                        env=env,
                        output_schema=SCHEMAS_DIR / "rubric_result.schema.json",
                    )
                except Exception as exc:
                    process_result = process_result.__class__(
                        command=process_result.command,
                        exit_code=process_result.exit_code,
                        status="failed",
                        timed_out=process_result.timed_out,
                        started_at=process_result.started_at,
                        ended_at=process_result.ended_at,
                        duration_seconds=process_result.duration_seconds,
                    )
                    (rubric_dir / "stderr.log").open("a", encoding="utf-8").write(
                        f"\nOpenCode output post-processing failed: {type(exc).__name__}: {exc}\n"
                    )
            if agent in {"grok", "gemini"} and process_result.status == "success":
                try:
                    write_headless_final_output(
                        rubric_dir / "events.jsonl",
                        judge_final_path,
                        output_schema=SCHEMAS_DIR / "rubric_result.schema.json",
                    )
                    normalize_headless_events(rubric_dir / "events.jsonl", provider=agent)
                except Exception as exc:
                    process_result = process_result.__class__(
                        command=process_result.command,
                        exit_code=process_result.exit_code,
                        status="failed",
                        timed_out=process_result.timed_out,
                        started_at=process_result.started_at,
                        ended_at=process_result.ended_at,
                        duration_seconds=process_result.duration_seconds,
                    )
                    (rubric_dir / "stderr.log").open("a", encoding="utf-8").write(
                        f"\n{agent.title()} output post-processing failed: {type(exc).__name__}: {exc}\n"
                    )
            if judge_final_path.exists():
                shutil.copy2(judge_final_path, rubric_dir / "result.json")
            status = process_result.to_dict()
            json_dump(rubric_dir / "status.json", status)
            if progress is not None and run_task_id is not None:
                progress.evaluator_finished(
                    run_task_id=run_task_id,
                    mode="parallel",
                    rubric_id=rubric.id,
                    status=status,
                    aggregate=None,
                )

    await asyncio.gather(*(run_one(rubric) for rubric in launch_order))
    result_paths = [paths["judges"] / "parallel" / rubric.id / "result.json" for rubric in task.rubrics]
    try:
        aggregate = aggregate_results(
            task.rubrics,
            normalize_parallel_results(result_paths),
            mode="parallel",
            executor_timing=executor_timing,
        )
    except Exception as exc:
        aggregate = {
            "mode": "parallel",
            "overall_pass": False,
            "error": f"{type(exc).__name__}: {exc}",
            "executor_timing": executor_timing,
            "results": [],
        }
    write_aggregate(paths["judges"] / "parallel_aggregate.json", aggregate)
    return {"aggregate": aggregate}


def make_run_task_ids(task_runs: Sequence[TaskRunSpec]) -> List[str]:
    counts: Dict[str, int] = {}
    run_task_ids: List[str] = []
    for task_run in task_runs:
        base_id = task_run.task.id
        if task_run.instruction_variant != "baseline":
            base_id = f"{base_id}__{task_run.instruction_variant}"
        counts[base_id] = counts.get(base_id, 0) + 1
        suffix = counts[base_id]
        run_task_ids.append(base_id if suffix == 1 else f"{base_id}__{suffix:03d}")
    return run_task_ids


def executor_timing_from_status(status: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "started_at": status.get("started_at"),
        "ended_at": status.get("ended_at"),
        "duration_seconds": status.get("duration_seconds"),
        "status": status.get("status"),
        "exit_code": status.get("exit_code"),
        "timed_out": status.get("timed_out"),
    }


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 4)


def _delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None:
        return None
    return round(value - baseline, 4)


def build_instruction_ablation_summary(batch_summaries: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for batch in batch_summaries:
        for task_result in batch.get("tasks", []):
            for judge_mode, judge_data in task_result.get("judges", {}).items():
                aggregate = judge_data.get("aggregate")
                if not isinstance(aggregate, dict):
                    continue
                variant = task_result.get("instruction_variant", "baseline")
                key = (task_result["task_id"], judge_mode, variant)
                group = grouped.setdefault(
                    key,
                    {
                        "task_id": task_result["task_id"],
                        "judge_mode": judge_mode,
                        "instruction_variant": variant,
                        "instruction_step_ids": task_result.get("instruction_step_ids", []),
                        "instruction_step_indices": task_result.get("instruction_step_indices", []),
                        "instruction_steps": task_result.get("instruction_steps", []),
                        "executor_skill_ids": task_result.get("executor_skill_ids", []),
                        "executor_skills": task_result.get("executor_skills", []),
                        "_run_task_ids": [],
                        "_overall_pass_count": 0,
                        "_passed_count_sum": 0,
                        "_total_count_sum": 0,
                        "_rubrics": {},
                    },
                )
                group["_run_task_ids"].append(task_result["run_task_id"])
                if aggregate.get("overall_pass"):
                    group["_overall_pass_count"] += 1
                group["_passed_count_sum"] += int(aggregate.get("passed_count") or 0)
                group["_total_count_sum"] += int(aggregate.get("total_count") or 0)
                for row in aggregate.get("results", []):
                    rubric_id = row.get("rubric_id")
                    if not rubric_id:
                        continue
                    rubric = group["_rubrics"].setdefault(
                        rubric_id,
                        {"rubric_id": rubric_id, "runs": 0, "passed_count": 0},
                    )
                    rubric["runs"] += 1
                    if row.get("passed"):
                        rubric["passed_count"] += 1

    groups: List[Dict[str, Any]] = []
    for group in grouped.values():
        runs = len(group["_run_task_ids"])
        rubrics = []
        for rubric in group["_rubrics"].values():
            rubrics.append(
                {
                    "rubric_id": rubric["rubric_id"],
                    "runs": rubric["runs"],
                    "passed_count": rubric["passed_count"],
                    "pass_rate": _rate(rubric["passed_count"], rubric["runs"]),
                }
            )
        rubrics.sort(key=lambda item: item["rubric_id"])
        groups.append(
            {
                "task_id": group["task_id"],
                "judge_mode": group["judge_mode"],
                "instruction_variant": group["instruction_variant"],
                "instruction_step_ids": group["instruction_step_ids"],
                "instruction_step_indices": group["instruction_step_indices"],
                "instruction_steps": group["instruction_steps"],
                "executor_skill_ids": group["executor_skill_ids"],
                "executor_skills": group["executor_skills"],
                "runs": runs,
                "run_task_ids": group["_run_task_ids"],
                "overall_pass_count": group["_overall_pass_count"],
                "overall_pass_rate": _rate(group["_overall_pass_count"], runs),
                "mean_passed_count": _rate(group["_passed_count_sum"], runs),
                "mean_rubric_pass_rate": _rate(group["_passed_count_sum"], group["_total_count_sum"]),
                "rubrics": rubrics,
            }
        )

    def sort_key(item: Dict[str, Any]) -> tuple[str, str, int, str]:
        indices = item.get("instruction_step_indices") or []
        if item["instruction_variant"] == "baseline":
            order = 0
        elif item["instruction_variant"] == "all_instructions":
            order = 9998
        else:
            order = int(indices[0]) if indices else 9999
        return (item["task_id"], item["judge_mode"], order, item["instruction_variant"])

    groups.sort(key=sort_key)
    by_key = {
        (group["task_id"], group["judge_mode"], group["instruction_variant"]): group
        for group in groups
    }
    for group in groups:
        baseline = by_key.get((group["task_id"], group["judge_mode"], "baseline"))
        if baseline is None or group["instruction_variant"] == "baseline":
            continue
        baseline_rubrics = {item["rubric_id"]: item for item in baseline["rubrics"]}
        rubric_deltas = []
        for rubric in group["rubrics"]:
            baseline_rubric = baseline_rubrics.get(rubric["rubric_id"])
            if baseline_rubric is None:
                continue
            rubric_deltas.append(
                {
                    "rubric_id": rubric["rubric_id"],
                    "pass_rate_delta": _delta(rubric["pass_rate"], baseline_rubric["pass_rate"]),
                    "pass_rate": rubric["pass_rate"],
                    "baseline_pass_rate": baseline_rubric["pass_rate"],
                }
            )
        group["delta_vs_baseline"] = {
            "overall_pass_rate_delta": _delta(group["overall_pass_rate"], baseline["overall_pass_rate"]),
            "mean_rubric_pass_rate_delta": _delta(group["mean_rubric_pass_rate"], baseline["mean_rubric_pass_rate"]),
            "rubrics": rubric_deltas,
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_variant": "baseline",
        "groups": groups,
    }


def format_instruction_ablation_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Instruction Ablation Summary",
        "",
        f"Generated at: `{summary.get('generated_at')}`",
        "",
        "| Task | Judge | Variant | Runs | Overall pass rate | Mean rubric pass rate | Delta vs baseline |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for group in summary.get("groups", []):
        delta_data = group.get("delta_vs_baseline") or {}
        delta = delta_data.get("mean_rubric_pass_rate_delta")
        delta_text = "" if delta is None else f"{delta:+.4f}"
        lines.append(
            "| {task} | {judge} | {variant} | {runs} | {overall} | {mean} | {delta} |".format(
                task=group["task_id"],
                judge=group["judge_mode"],
                variant=group["instruction_variant"],
                runs=group["runs"],
                overall=group["overall_pass_rate"],
                mean=group["mean_rubric_pass_rate"],
                delta=delta_text,
            )
        )

    for group in summary.get("groups", []):
        if group["instruction_variant"] == "baseline" or "delta_vs_baseline" not in group:
            continue
        rubric_deltas = [
            item
            for item in group["delta_vs_baseline"].get("rubrics", [])
            if item.get("pass_rate_delta") is not None
        ]
        rubric_deltas.sort(key=lambda item: item["pass_rate_delta"], reverse=True)
        top_gains = [item for item in rubric_deltas if item["pass_rate_delta"] > 0][:5]
        regressions = [item for item in reversed(rubric_deltas) if item["pass_rate_delta"] < 0][:5]
        lines.extend(["", f"## {group['task_id']} {group['instruction_variant']}"])
        if group.get("instruction_steps"):
            instruction = group["instruction_steps"][0].get("instruction", "")
            lines.extend(["", f"Instruction: {instruction}"])
        if top_gains:
            lines.extend(["", "Top rubric gains:"])
            for item in top_gains:
                lines.append(f"- `{item['rubric_id']}`: {item['pass_rate_delta']:+.4f}")
        if regressions:
            lines.extend(["", "Top rubric regressions:"])
            for item in regressions:
                lines.append(f"- `{item['rubric_id']}`: {item['pass_rate_delta']:+.4f}")

    lines.append("")
    return "\n".join(lines)


async def run_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    tasks = duplicate_tasks(discover_tasks(args.tasks_dir, args.task), args.repeat)
    registry_skills = load_registry_skills(args.executor_skill_root) if args.executor_skill_root.exists() else []
    registry_skill_by_id = {skill.id: skill for skill in registry_skills}
    group_skill_ids = expand_skill_groups(args.executor_skill_root, args.executor_skill_group)
    requested_executor_skill_ids = list(args.executor_skill or []) + group_skill_ids
    duplicate_requested_executor_skill_ids = sorted(
        {
            skill_id
            for skill_id in requested_executor_skill_ids
            if requested_executor_skill_ids.count(skill_id) > 1
        }
    )
    if duplicate_requested_executor_skill_ids:
        raise ValueError(
            "Duplicate executor skill selected from ids/groups: "
            + ", ".join(duplicate_requested_executor_skill_ids)
        )
    external_executor_skills = [
        registry_skill_by_id[skill_id]
        for skill_id in requested_executor_skill_ids
        if skill_id in registry_skill_by_id
    ]
    task_runs = build_task_runs(
        tasks,
        instruction_mode=args.instruction_mode,
        instruction_steps=args.instruction_step,
        rigor_mode=args.rigor_mode,
        rigor_ids=args.rigor,
        executor_skill_ids=requested_executor_skill_ids,
        external_executor_skills=external_executor_skills,
    )
    rng = random.Random(args.seed)
    indexed = list(enumerate(task_runs))
    rng.shuffle(indexed)
    ordered_task_runs = [task_run for _, task_run in indexed]
    run_task_ids = make_run_task_ids(ordered_task_runs)

    run_id = args.run_id or datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    run_root = args.runs_dir / run_id
    try:
        run_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit(
            f"Run directory already exists: {run_root}. Choose a new --run-id or remove the old run."
        )
    selected_instruction_step_ids = task_runs[0].instruction_step_ids if args.instruction_mode == "select" and task_runs else []
    instruction_variants: List[Dict[str, Any]] = []
    seen_instruction_variants = set()
    for task_run in task_runs:
        key = (task_run.task.id, task_run.instruction_variant)
        if key in seen_instruction_variants:
            continue
        seen_instruction_variants.add(key)
        instruction_variants.append(
            {
                "task_id": task_run.task.id,
                **task_run.instruction_metadata(),
            }
        )

    run_config = {
        "run_id": run_id,
        "seed": args.seed,
        "batch_size": args.batch_size,
        "judge_mode": args.judge_mode,
        "max_evaluator_parallel": args.max_evaluator_parallel,
        "auth_mode": args.auth_mode,
        "executor_auth_mode": args.executor_auth_mode,
        "evaluator_auth_mode": args.evaluator_auth_mode,
        "executor_agent": args.executor_agent,
        "evaluator_agent": args.evaluator_agent,
        "runtimes_dir": str(args.runtimes_dir),
        "executor_runtime": args.executor_runtime_spec.public_metadata() if args.executor_runtime_spec else None,
        "evaluator_runtime": args.evaluator_runtime_spec.public_metadata() if args.evaluator_runtime_spec else None,
        "claude_thinking_effort": args.claude_thinking_effort,
        "claude_max_turns": args.claude_max_turns,
        "opencode_provider": args.opencode_provider,
        "opencode_base_url": args.opencode_base_url,
        "opencode_api_key_env": args.opencode_api_key_env,
        "executor_model": args.executor_model,
        "evaluator_model": args.evaluator_model,
        "executor_backend": args.executor_backend,
        "docker_image": args.docker_image if args.executor_backend == "docker" else None,
        "instruction_mode": args.instruction_mode,
        "requested_instruction_step_ids": args.instruction_step or [],
        "instruction_step_ids": selected_instruction_step_ids,
        "instruction_step_order": "human_reference",
        "rigor_mode": args.rigor_mode,
        "requested_rigor_ids": args.rigor or [],
        "requested_executor_skill_ids": requested_executor_skill_ids,
        "requested_executor_skill_groups": args.executor_skill_group or [],
        "executor_skill_root": str(args.executor_skill_root),
        "executor_skill_order": "executor_skills",
        "instruction_variants": instruction_variants,
        "task_order": run_task_ids,
        "codex_bin": args.codex_bin,
        "claude_bin": args.claude_bin,
        "grok_bin": args.grok_bin,
        "gemini_bin": args.gemini_bin,
        "opencode_bin": args.opencode_bin,
    }
    json_dump(run_root / "run_config.json", run_config)

    records = []
    for task_run, run_task_id in zip(ordered_task_runs, run_task_ids):
        records.append(
            {
                "task_run": task_run,
                "task": task_run.task,
                "run_task_id": run_task_id,
                "paths": materialize_task(
                    task_run,
                    run_root,
                    run_task_id,
                    executor_backend=args.executor_backend,
                    executor_agent=args.executor_agent,
                ),
            }
        )

    evaluator_semaphore = asyncio.Semaphore(args.max_evaluator_parallel)
    batch_summaries: List[Dict[str, Any]] = []
    evaluator_total = len(records) if args.judge_mode == "single" else 0
    if args.judge_mode == "parallel":
        evaluator_total = sum(len(record["task"].rubrics) for record in records)
    elif args.judge_mode == "both":
        evaluator_total = len(records) + sum(len(record["task"].rubrics) for record in records)
    progress = make_benchmark_progress(
        run_root=run_root,
        total_executors=len(records),
        total_evaluators=evaluator_total,
        enabled=not args.no_progress,
    )

    try:
        for batch_index, start in enumerate(range(0, len(records), args.batch_size), start=1):
            batch = records[start : start + args.batch_size]
            progress.batch_started(
                batch_index=batch_index,
                run_task_ids=[record["run_task_id"] for record in batch],
            )

            async def execute_record(record: Dict[str, Any]) -> Dict[str, Any]:
                progress.executor_started(run_task_id=record["run_task_id"], task_id=record["task"].id)
                try:
                    status = await run_executor(
                        record["task_run"],
                        record["paths"],
                        agent=args.executor_agent,
                        codex_bin=args.codex_bin,
                        claude_bin=args.claude_bin,
                        grok_bin=args.grok_bin,
                        gemini_bin=args.gemini_bin,
                        opencode_bin=args.opencode_bin,
                        opencode_provider=args.opencode_provider,
                        opencode_base_url=args.opencode_base_url,
                        opencode_api_key_env=args.opencode_api_key_env,
                        claude_thinking_effort=args.claude_thinking_effort,
                        claude_max_turns=args.claude_max_turns,
                        auth_mode=args.executor_auth_mode,
                        model=args.executor_model,
                        executor_backend=args.executor_backend,
                        docker_bin=args.docker_bin,
                        docker_image=args.docker_image,
                        custom_spec=args.executor_runtime_spec,
                    )
                except Exception as exc:
                    # One crashing task must not abort the whole run.
                    logs = record["paths"]["logs"]
                    with (logs / "stderr.log").open("a", encoding="utf-8") as handle:
                        handle.write(f"\nExecutor crashed: {type(exc).__name__}: {exc}\n")
                    status = {
                        "command": [],
                        "exit_code": None,
                        "status": "failed",
                        "timed_out": False,
                        "started_at": None,
                        "ended_at": None,
                        "duration_seconds": None,
                        "error": f"{type(exc).__name__}: {exc}",
                        "executor_backend": args.executor_backend,
                        "docker_image": args.docker_image if args.executor_backend == "docker" else None,
                        "usage": None,
                        "artifact_file_count": 0,
                    }
                    json_dump(logs / "status.json", status)
                progress.executor_finished(
                    run_task_id=record["run_task_id"],
                    task_id=record["task"].id,
                    status=status,
                )
                return status

            executor_statuses = await asyncio.gather(
                *(execute_record(record) for record in batch)
            )

            async def evaluate_record(record: Dict[str, Any], executor_status: Dict[str, Any]) -> Dict[str, Any]:
                task = record["task"]
                paths = record["paths"]
                modes: Dict[str, Any] = {}
                executor_timing = executor_timing_from_status(executor_status)
                if args.judge_mode in ("single", "both"):
                    progress.evaluator_started(run_task_id=record["run_task_id"], mode="single")
                    try:
                        modes["single"] = await run_single_judge(
                            task,
                            paths,
                            agent=args.evaluator_agent,
                            codex_bin=args.codex_bin,
                            claude_bin=args.claude_bin,
                            grok_bin=args.grok_bin,
                            gemini_bin=args.gemini_bin,
                            opencode_bin=args.opencode_bin,
                            opencode_provider=args.opencode_provider,
                            opencode_base_url=args.opencode_base_url,
                            opencode_api_key_env=args.opencode_api_key_env,
                            claude_thinking_effort=args.claude_thinking_effort,
                            auth_mode=args.evaluator_auth_mode,
                            model=args.evaluator_model,
                            timeout_seconds=args.evaluator_timeout_seconds,
                            executor_timing=executor_timing,
                            semaphore=evaluator_semaphore,
                            custom_spec=args.evaluator_runtime_spec,
                        )
                    except Exception as exc:
                        modes["single"] = {
                            "status": {"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
                            "aggregate": {
                                "mode": "single",
                                "overall_pass": False,
                                "error": f"{type(exc).__name__}: {exc}",
                                "executor_timing": executor_timing,
                                "results": [],
                            },
                        }
                    progress.evaluator_finished(
                        run_task_id=record["run_task_id"],
                        mode="single",
                        status=modes["single"].get("status"),
                        aggregate=modes["single"].get("aggregate"),
                    )
                if args.judge_mode in ("parallel", "both"):
                    rubric_order = rubric_launch_order(
                        task.rubrics, seed=args.seed, run_task_id=record["run_task_id"]
                    )
                    try:
                        modes["parallel"] = await run_parallel_judges(
                            task,
                            paths,
                            agent=args.evaluator_agent,
                            codex_bin=args.codex_bin,
                            claude_bin=args.claude_bin,
                            grok_bin=args.grok_bin,
                            gemini_bin=args.gemini_bin,
                            opencode_bin=args.opencode_bin,
                            opencode_provider=args.opencode_provider,
                            opencode_base_url=args.opencode_base_url,
                            opencode_api_key_env=args.opencode_api_key_env,
                            claude_thinking_effort=args.claude_thinking_effort,
                            auth_mode=args.evaluator_auth_mode,
                            model=args.evaluator_model,
                            timeout_seconds=args.evaluator_timeout_seconds,
                            executor_timing=executor_timing,
                            semaphore=evaluator_semaphore,
                            launch_order=rubric_order,
                            progress=progress,
                            run_task_id=record["run_task_id"],
                            custom_spec=args.evaluator_runtime_spec,
                        )
                    except Exception as exc:
                        modes["parallel"] = {
                            "aggregate": {
                                "mode": "parallel",
                                "overall_pass": False,
                                "error": f"{type(exc).__name__}: {exc}",
                                "executor_timing": executor_timing,
                                "results": [],
                            },
                        }
                result = {
                    "run_task_id": record["run_task_id"],
                    "task_id": task.id,
                    **record["task_run"].instruction_metadata(),
                    "executor_timing": executor_timing,
                    "executor": executor_status,
                    "judges": modes,
                }
                json_dump(paths["task_root"] / "task_summary.json", result)
                return result

            judge_results = await asyncio.gather(
                *(evaluate_record(record, executor_status) for record, executor_status in zip(batch, executor_statuses))
            )

            batch_summaries.append(
                {
                    "batch_index": batch_index,
                    "run_task_ids": [record["run_task_id"] for record in batch],
                    "tasks": judge_results,
                }
            )
            progress.batch_finished(
                batch_index=batch_index,
                run_task_ids=[record["run_task_id"] for record in batch],
            )
    finally:
        progress.close()

    summary: Dict[str, Any] = {
        **run_config,
        "run_root": str(run_root),
        "batches": batch_summaries,
    }
    if args.instruction_mode == "ablation":
        ablation_summary = build_instruction_ablation_summary(batch_summaries)
        ablation_json_path = run_root / "instruction_ablation_summary.json"
        ablation_md_path = run_root / "instruction_ablation_summary.md"
        json_dump(ablation_json_path, ablation_summary)
        ablation_md_path.write_text(format_instruction_ablation_markdown(ablation_summary), encoding="utf-8")
        summary["instruction_ablation_summary_path"] = str(ablation_json_path)
        summary["instruction_ablation_report_path"] = str(ablation_md_path)
    json_dump(run_root / "summary.json", summary)
    return summary


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
        "--claude-thinking-effort",
        choices=["none", "low", "medium", "high"],
        default="none",
        help=(
            "Prompt-level thinking instruction for Claude Code. Claude Code does not expose a "
            "native reasoning-effort flag, so this maps to explicit think/deep-think instructions."
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
    def backend_supports_docker(agent: str, spec: CustomRuntimeSpec | None) -> bool:
        if agent in BUILTIN_AGENTS:
            return True
        return agent.startswith("custom:") and spec is not None and spec.docker_image is not None

    if args.executor_backend is None:
        args.executor_backend = "docker" if args.executor_agent == "codex" else "local"
    elif args.executor_backend == "docker" and not backend_supports_docker(
        args.executor_agent, args.executor_runtime_spec
    ):
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


if __name__ == "__main__":
    raise SystemExit(main())
