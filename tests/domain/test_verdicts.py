"""Pure HSW outcome classification, including legacy artifacts."""

from __future__ import annotations

import unittest

from starbench.domain import TaskRunOutcome, aggregate_outcome


class VerdictCompatibilityTests(unittest.TestCase):
    def test_current_outcome_is_authoritative(self) -> None:
        self.assertEqual(
            aggregate_outcome({"outcome": "agent_pass", "overall_pass": True}),
            TaskRunOutcome.AGENT_PASS,
        )

    def test_legacy_boolean_is_a_valid_sample_without_error(self) -> None:
        self.assertEqual(
            aggregate_outcome({"overall_pass": False}),
            TaskRunOutcome.AGENT_FAIL,
        )

    def test_legacy_error_is_inconclusive_not_agent_failure(self) -> None:
        self.assertEqual(
            aggregate_outcome({"overall_pass": False, "error": "invalid JSON"}),
            TaskRunOutcome.INCONCLUSIVE_JUDGE,
        )

    def test_legacy_missing_answers_are_inconclusive_not_agent_failure(self) -> None:
        # The legacy writer coerced unanswered rubrics to passed=false and
        # listed them under "missing" without any "error" key. That is an
        # incomplete measurement, never a defended HSW sample.
        self.assertEqual(
            aggregate_outcome(
                {
                    "overall_pass": False,
                    "passed_count": 3,
                    "total_count": 5,
                    "missing": ["R4", "R5"],
                }
            ),
            TaskRunOutcome.INCONCLUSIVE_JUDGE,
        )

    def test_legacy_empty_missing_list_is_still_a_valid_sample(self) -> None:
        self.assertEqual(
            aggregate_outcome({"overall_pass": False, "missing": []}),
            TaskRunOutcome.AGENT_FAIL,
        )

    def test_unknown_current_outcome_fails_closed(self) -> None:
        self.assertEqual(
            aggregate_outcome({"outcome": "probably_passed", "overall_pass": True}),
            TaskRunOutcome.INCONCLUSIVE_JUDGE,
        )

    def test_no_recorded_verdict_stays_unclassified(self) -> None:
        self.assertIsNone(aggregate_outcome({"overall_pass": None}))


if __name__ == "__main__":
    unittest.main()
