"""HSW task-run outcomes and compatibility classification.

This module has no IO and no dependency on the runner or GUI. New aggregate
writers store an explicit outcome; readers use :func:`aggregate_outcome` to
classify both current and legacy artifacts without turning measurement errors
into agent failures.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


class TaskRunOutcome(str, Enum):
    AGENT_PASS = "agent_pass"
    AGENT_FAIL = "agent_fail"
    INCONCLUSIVE_JUDGE = "inconclusive_judge"
    INCONCLUSIVE_EXECUTOR = "inconclusive_executor"
    INVALID_TASK = "invalid_task"

    @property
    def is_hsw_sample(self) -> bool:
        return self in {TaskRunOutcome.AGENT_PASS, TaskRunOutcome.AGENT_FAIL}


def aggregate_outcome(aggregate: Mapping[str, Any]) -> TaskRunOutcome | None:
    """Read current outcomes and conservatively classify legacy aggregates."""
    raw = aggregate.get("outcome")
    if isinstance(raw, str):
        try:
            return TaskRunOutcome(raw)
        except ValueError:
            return TaskRunOutcome.INCONCLUSIVE_JUDGE
    if raw is not None:
        return TaskRunOutcome.INCONCLUSIVE_JUDGE
    if aggregate.get("error"):
        return TaskRunOutcome.INCONCLUSIVE_JUDGE
    # Legacy writers coerced unanswered rubrics to passed=false and recorded
    # them under "missing" without setting "error". Those aggregates are
    # incomplete measurements, not agent failures — a false AGENT_FAIL here
    # would count as a "defended" HSW sample the judge never actually produced.
    if aggregate.get("missing"):
        return TaskRunOutcome.INCONCLUSIVE_JUDGE
    overall_pass = aggregate.get("overall_pass")
    if type(overall_pass) is bool:
        return TaskRunOutcome.AGENT_PASS if overall_pass else TaskRunOutcome.AGENT_FAIL
    return None
