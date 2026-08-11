"""Instruction-ablation summary: aggregate batch results into report structures.

Pure computation, no IO: :func:`build_instruction_ablation_summary` folds the
per-batch task results into per-(task, judge, variant) groups with pass rates and
per-rubric deltas versus the baseline variant, and
:func:`format_instruction_ablation_markdown` renders that structure as the
committed ``instruction_ablation_summary.md`` table. The orchestrator owns the
*writing* of these files; this module only builds their content.

Invariant: the delta rows compare a variant against the ``baseline`` variant of
the same (task, judge) pair; groups with no matching baseline get no delta block.

改什么来这里: the ablation grouping/scoring math or the markdown report layout.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence

from ..domain import aggregate_outcome


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
                        "advisory_executor_skill_ids": task_result.get(
                            "advisory_executor_skill_ids", []
                        ),
                        "advisory_executor_skills": task_result.get(
                            "advisory_executor_skills", []
                        ),
                        "required_executor_skill_ids": task_result.get(
                            "required_executor_skill_ids", []
                        ),
                        "required_executor_skills": task_result.get(
                            "required_executor_skills", []
                        ),
                        "_attempt_ids": [],
                        "_run_task_ids": [],
                        "_inconclusive_count": 0,
                        "_overall_pass_count": 0,
                        "_passed_count_sum": 0,
                        "_total_count_sum": 0,
                        "_rubrics": {},
                    },
                )
                group["_attempt_ids"].append(task_result["run_task_id"])
                outcome = aggregate_outcome(aggregate)
                if outcome is None or not outcome.is_hsw_sample:
                    group["_inconclusive_count"] += 1
                    continue
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
                "advisory_executor_skill_ids": group["advisory_executor_skill_ids"],
                "advisory_executor_skills": group["advisory_executor_skills"],
                "required_executor_skill_ids": group["required_executor_skill_ids"],
                "required_executor_skills": group["required_executor_skills"],
                "attempts": len(group["_attempt_ids"]),
                "inconclusive": group["_inconclusive_count"],
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
