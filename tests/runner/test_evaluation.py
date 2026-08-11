"""Strict judge-answer parsing and rubric result aggregation."""
from __future__ import annotations

import unittest

from starbench.contracts import validate_payload
from starbench.runner.evaluation import (
    aggregate_results,
    inconclusive_executor_aggregate,
    judge_identity_fields,
)
from starbench.runner.models import JudgeAnswer, Rubric


class JudgeAnswerTests(unittest.TestCase):
    def test_accepts_json_boolean_without_judge_owned_verdict_fields(self) -> None:
        answer = JudgeAnswer.from_dict(
            {"rubric_id": "R001", "answer": False, "evidence": "Missing output."}
        )

        self.assertIs(answer.answer, False)

    def test_rejects_string_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "answer must be a JSON boolean"):
            JudgeAnswer.from_dict(
                {"rubric_id": "R001", "answer": "false", "evidence": "Missing output."}
            )

    def test_rejects_numeric_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "answer must be a JSON boolean"):
            JudgeAnswer.from_dict(
                {"rubric_id": "R001", "answer": 0, "evidence": "Missing output."}
            )

    def test_rejects_judge_forged_verdict_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "unexpected Judge answer fields"):
            JudgeAnswer.from_dict(
                {
                    "rubric_id": "R001",
                    "answer": False,
                    "evidence": "Missing output.",
                    "expected": False,
                    "passed": True,
                    "fail_fast": False,
                }
            )


class AggregationTests(unittest.TestCase):
    def test_fail_fast_failure_fails_overall(self) -> None:
        rubrics = [
            Rubric(id="R001", fail_fast=True, expected=True, question="Required?"),
            Rubric(id="R002", fail_fast=False, expected=False, question="Forbidden?"),
        ]
        answers = [
            JudgeAnswer(rubric_id="R001", answer=False, evidence="Missing."),
            JudgeAnswer(rubric_id="R002", answer=False, evidence="Absent."),
        ]
        aggregate = aggregate_results(rubrics, answers, mode="single", executor_timing={"duration_seconds": 5.0})
        self.assertFalse(aggregate["overall_pass"])
        self.assertEqual(aggregate["outcome"], "agent_fail")
        self.assertEqual(aggregate["fail_fast_failures"], ["R001"])
        self.assertEqual(aggregate["passed_count"], 1)
        self.assertEqual(aggregate["executor_timing"]["duration_seconds"], 5.0)

        first, second = aggregate["results"]
        self.assertEqual(first["expected"], True)
        self.assertEqual(first["fail_fast"], True)
        self.assertEqual(first["passed"], False)
        self.assertEqual(second["expected"], False)
        self.assertEqual(second["passed"], True)

    def test_missing_answer_is_inconclusive_not_agent_failure(self) -> None:
        rubrics = [
            Rubric(id="R001", fail_fast=True, expected=True, question="Required?"),
            Rubric(id="R002", fail_fast=False, expected=True, question="Complete?"),
        ]

        aggregate = aggregate_results(
            rubrics,
            [JudgeAnswer(rubric_id="R001", answer=True, evidence="Present.")],
            mode="single",
        )

        self.assertEqual(aggregate["outcome"], "inconclusive_judge")
        self.assertIsNone(aggregate["overall_pass"])
        self.assertEqual(aggregate["missing"], ["R002"])
        self.assertIsNone(aggregate["results"][1]["passed"])

    def test_complete_success_is_agent_pass(self) -> None:
        rubrics = [Rubric(id="R001", fail_fast=True, expected=True, question="Required?")]

        aggregate = aggregate_results(
            rubrics,
            [JudgeAnswer(rubric_id="R001", answer=True, evidence="Present.")],
            mode="parallel",
        )

        self.assertEqual(aggregate["outcome"], "agent_pass")
        self.assertIs(aggregate["overall_pass"], True)


class JudgeIdentityTests(unittest.TestCase):
    RUBRICS = [Rubric(id="R001", fail_fast=True, expected=True, question="Required?")]
    ANSWERS = [JudgeAnswer(rubric_id="R001", answer=True, evidence="Present.")]

    def test_identity_is_stamped_into_the_aggregate(self) -> None:
        aggregate = aggregate_results(
            self.RUBRICS,
            self.ANSWERS,
            mode="single",
            judge_identity=judge_identity_fields(
                judge_agent="codex", judge_model="gpt-5.5"
            ),
        )
        self.assertEqual(aggregate["judge_agent"], "codex")
        self.assertEqual(aggregate["judge_model"], "gpt-5.5")
        self.assertIn("judged_at", aggregate)
        validate_payload("judge_aggregate.schema.json", aggregate, version=2)

    def test_runtime_default_model_stays_honestly_absent(self) -> None:
        aggregate = aggregate_results(
            self.RUBRICS,
            self.ANSWERS,
            mode="single",
            judge_identity=judge_identity_fields(judge_agent="codex", judge_model=None),
        )
        self.assertEqual(aggregate["judge_agent"], "codex")
        self.assertNotIn("judge_model", aggregate)
        self.assertIn("judged_at", aggregate)

    def test_no_identity_means_no_identity_fields(self) -> None:
        aggregate = aggregate_results(self.RUBRICS, self.ANSWERS, mode="single")
        for key in ("judge_agent", "judge_model", "judged_at"):
            self.assertNotIn(key, aggregate)

    def test_executor_inconclusive_never_claims_a_judge_ran(self) -> None:
        aggregate = inconclusive_executor_aggregate(
            self.RUBRICS, mode="single", error="Executor failed before judging."
        )
        for key in ("judge_agent", "judge_model", "judged_at"):
            self.assertNotIn(key, aggregate)


if __name__ == "__main__":
    unittest.main()
