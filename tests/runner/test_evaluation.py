"""Rubric result aggregation in ``starbench.runner.evaluation``."""
from __future__ import annotations

import unittest

from starbench.runner.evaluation import aggregate_results
from starbench.runner.models import Rubric, RubricResult


class AggregationTests(unittest.TestCase):
    def test_fail_fast_failure_fails_overall(self) -> None:
        rubrics = [
            Rubric(id="R001", fail_fast=True, expected=True, question="Required?"),
            Rubric(id="R002", fail_fast=False, expected=False, question="Forbidden?"),
        ]
        results = [
            RubricResult(rubric_id="R001", answer=False, expected=True, passed=False, fail_fast=True, evidence="Missing."),
            RubricResult(rubric_id="R002", answer=False, expected=False, passed=True, fail_fast=False, evidence="Absent."),
        ]
        aggregate = aggregate_results(rubrics, results, mode="single", executor_timing={"duration_seconds": 5.0})
        self.assertFalse(aggregate["overall_pass"])
        self.assertEqual(aggregate["fail_fast_failures"], ["R001"])
        self.assertEqual(aggregate["passed_count"], 1)
        self.assertEqual(aggregate["executor_timing"]["duration_seconds"], 5.0)


if __name__ == "__main__":
    unittest.main()
