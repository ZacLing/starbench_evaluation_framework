"""Prompt assembly shared by the orchestrator and the runtime adapters.

These builders are runtime-neutral in shape (the executor prompt and the two
judge prompts are the same text for every runtime); the small per-runtime
*tweaks* — Claude's thinking instruction, the JSON-schema instruction appended
for runtimes that lack a native schema flag — also live here so that adapters
can apply them without importing the orchestrator (``run_benchmark``). That
keeps the dependency arrow pointing down: ``run_benchmark`` and ``adapters``
both import ``prompts``; ``prompts`` imports only models.

Invariant: ``run_benchmark`` re-exports every public name here, so existing
``from ...run_benchmark import build_executor_prompt`` call sites keep working.

To change prompt wording or the schema/thinking wrapping, edit this file.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Rubric, TaskRunSpec, TaskSpec

THINKING_EFFORT_INSTRUCTIONS = {
    "default": "",  # leave the model's own reasoning behavior alone
    "none": "",  # legacy spelling of "default"
    "low": "Before responding, think carefully about the task and check for obvious gaps.",
    "medium": "Before responding, think through the task carefully, including constraints, edge cases, and verification steps.",
    "high": "Before responding, think deeply about the task. Build a complete plan, inspect relevant evidence, consider failure modes and alternatives, and self-check the final deliverable before finishing.",
}
# Back-compat name; prefer THINKING_EFFORT_INSTRUCTIONS.
CLAUDE_THINKING_EFFORT_INSTRUCTIONS = THINKING_EFFORT_INSTRUCTIONS
# Judges must be read-only across runtimes; OpenCode's built-in plan agent
# matches the read-only sandboxes used for Codex/Grok/Gemini judges.
OPENCODE_JUDGE_AGENT = "plan"


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
        if not task_run.required_executor_skills:
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
        else:
            sections = []
            if task_run.advisory_executor_skills:
                advisory_skills = "\n".join(
                    f"- `{skill.id}`: {skill.activation}"
                    for skill in task_run.advisory_executor_skills
                )
                sections.append(f"Installed executor skills:\n{advisory_skills}")
            required_skills = "\n".join(
                f"- `{skill.id}`: {skill.activation}"
                for skill in task_run.required_executor_skills
            )
            sections.append(f"Required executor skills:\n{required_skills}")
            executor_skill_section = f"""

{chr(10).join(sections)}

Required skill usage rules:
- Before beginning task work, read the complete SKILL.md for every required executor skill under {executor_skill_location}.
- You must follow each required skill's applicable workflow during planning, execution, and final self-checking.
- Do not skip a required skill because it appears optional or because the task seems simple.
- Available executor skills may be used as private execution guidance when relevant.
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


def append_thinking_instruction(prompt: str, effort: str) -> str:
    """Prompt-level thinking request: the fallback for runtimes without a
    native reasoning switch (Claude injects MAX_THINKING_TOKENS, Codex sets
    model_reasoning_effort; every other executor gets this instruction)."""
    instruction = THINKING_EFFORT_INSTRUCTIONS[effort]
    if not instruction:
        return prompt
    return f"{prompt.rstrip()}\n\nThinking effort instruction:\n{instruction}\n"


# Back-compat name; prefer append_thinking_instruction.
append_claude_thinking_instruction = append_thinking_instruction


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
- evidence must cite concrete files, commands, outputs, or trace entries.

Return only your observations. Do not copy or infer expected, passed, or fail_fast fields;
the benchmark derives those from its authoritative task rubric.

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
- evidence must cite concrete files, commands, outputs, or trace entries.

Return only your observation. Do not copy or infer expected, passed, or fail_fast fields;
the benchmark derives those from its authoritative task rubric.

Return one JSON object matching the schema.

Task id: {task.id}
Rubric:
{json.dumps(rubric.to_dict(), indent=2, sort_keys=True)}
"""
