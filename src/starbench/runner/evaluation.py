from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..contracts import ARTIFACT_SCHEMA_VERSION
from .models import Rubric, RubricResult


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_single_result(path: Path) -> List[RubricResult]:
    data = load_json(path)
    if isinstance(data, list):
        items: Any = data
    elif isinstance(data, dict):
        items = data.get("results", [])
    else:
        items = None
    if not isinstance(items, list):
        raise ValueError(f"Single judge output has no results array: {path}")
    return [RubricResult.from_dict(item) for item in items]


def normalize_parallel_results(paths: Iterable[Path]) -> List[RubricResult]:
    results: List[RubricResult] = []
    for path in sorted(paths):
        if path.exists():
            results.append(RubricResult.from_dict(load_json(path)))
    return results


def aggregate_results(
    rubrics: List[Rubric],
    results: List[RubricResult],
    *,
    mode: str,
    executor_timing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    rubric_by_id = {rubric.id: rubric for rubric in rubrics}
    result_by_id = {result.rubric_id: result for result in results}

    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    fail_fast_failures: List[str] = []

    for rubric in rubrics:
        result = result_by_id.get(rubric.id)
        if result is None:
            missing.append(rubric.id)
            row = {
                "rubric_id": rubric.id,
                "answer": None,
                "expected": rubric.expected,
                "passed": False,
                "fail_fast": rubric.fail_fast,
                "evidence": "Missing evaluator result.",
            }
        else:
            passed = result.answer == rubric.expected and result.passed
            row = result.to_dict()
            row["expected"] = rubric.expected
            row["fail_fast"] = rubric.fail_fast
            row["passed"] = passed
        if rubric.fail_fast and not row["passed"]:
            fail_fast_failures.append(rubric.id)
        rows.append(row)

    passed_count = sum(1 for row in rows if row["passed"])
    overall_pass = not missing and passed_count == len(rubrics) and not fail_fast_failures
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "mode": mode,
        "overall_pass": overall_pass,
        "passed_count": passed_count,
        "total_count": len(rubrics),
        "missing": missing,
        "fail_fast_failures": fail_fast_failures,
        "executor_timing": executor_timing,
        "results": rows,
    }


def write_aggregate(path: Path, aggregate: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**aggregate, "schema_version": ARTIFACT_SCHEMA_VERSION}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
