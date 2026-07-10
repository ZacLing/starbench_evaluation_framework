from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..contracts import (
    JUDGE_AGGREGATE_SCHEMA_VERSION,
    ContractValidationError,
    validate_json_schema,
)
from ..domain import TaskRunOutcome
from .models import JudgeAnswer, Rubric, RubricResult


SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_judge_payload(payload: Any, schema_name: str, *, path: Path) -> None:
    schema = load_json(SCHEMAS_DIR / schema_name)
    try:
        validate_json_schema(schema, payload, path=str(path))
    except ContractValidationError as exc:
        raise ValueError(f"Judge output contract: {exc}") from exc


def normalize_single_result(path: Path) -> List[JudgeAnswer]:
    data = load_json(path)
    _validate_judge_payload(data, "single_result.schema.json", path=path)
    return [JudgeAnswer.from_dict(item) for item in data["results"]]


def normalize_parallel_results(paths: Iterable[Path]) -> List[JudgeAnswer]:
    results: List[JudgeAnswer] = []
    for path in sorted(paths):
        if path.exists():
            data = load_json(path)
            _validate_judge_payload(data, "rubric_result.schema.json", path=path)
            results.append(JudgeAnswer.from_dict(data))
    return results


def aggregate_results(
    rubrics: List[Rubric],
    answers: List[JudgeAnswer],
    *,
    mode: str,
    executor_timing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    rubric_by_id = {rubric.id: rubric for rubric in rubrics}
    answer_by_id: Dict[str, JudgeAnswer] = {}
    for answer in answers:
        if answer.rubric_id not in rubric_by_id:
            raise ValueError(f"Judge returned unknown rubric_id: {answer.rubric_id}")
        if answer.rubric_id in answer_by_id:
            raise ValueError(f"Judge returned duplicate rubric_id: {answer.rubric_id}")
        answer_by_id[answer.rubric_id] = answer

    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    fail_fast_failures: List[str] = []

    for rubric in rubrics:
        answer = answer_by_id.get(rubric.id)
        if answer is None:
            missing.append(rubric.id)
            result = RubricResult.missing(rubric)
        else:
            result = RubricResult.from_answer(rubric, answer)
        row = result.to_dict()
        if rubric.fail_fast and row["passed"] is False:
            fail_fast_failures.append(rubric.id)
        rows.append(row)

    passed_count = sum(1 for row in rows if row["passed"] is True)
    if missing:
        outcome = TaskRunOutcome.INCONCLUSIVE_JUDGE
        overall_pass = None
    elif passed_count == len(rubrics) and not fail_fast_failures:
        outcome = TaskRunOutcome.AGENT_PASS
        overall_pass = True
    else:
        outcome = TaskRunOutcome.AGENT_FAIL
        overall_pass = False

    aggregate = {
        "schema_version": JUDGE_AGGREGATE_SCHEMA_VERSION,
        "mode": mode,
        "outcome": outcome.value,
        "overall_pass": overall_pass,
        "passed_count": passed_count,
        "total_count": len(rubrics),
        "missing": missing,
        "fail_fast_failures": fail_fast_failures,
        "executor_timing": executor_timing,
        "results": rows,
    }
    if missing:
        aggregate["error"] = f"Missing evaluator results: {', '.join(missing)}"
    return aggregate


def inconclusive_judge_aggregate(
    rubrics: List[Rubric],
    *,
    mode: str,
    error: str,
    executor_timing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    aggregate = aggregate_results(
        rubrics,
        [],
        mode=mode,
        executor_timing=executor_timing,
    )
    aggregate["outcome"] = TaskRunOutcome.INCONCLUSIVE_JUDGE.value
    aggregate["overall_pass"] = None
    aggregate["error"] = error
    return aggregate


def write_aggregate(path: Path, aggregate: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**aggregate, "schema_version": JUDGE_AGGREGATE_SCHEMA_VERSION}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
