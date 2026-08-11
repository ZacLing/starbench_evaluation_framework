"""Execution primitives in ``starbench.execution.process``."""
from __future__ import annotations

import unittest

from starbench.execution.process import mark_failed
from starbench.runner.models import ProcessResult


class ExecutionPrimitiveTests(unittest.TestCase):
    def test_mark_failed_preserves_timing_and_flips_status(self) -> None:
        ok = ProcessResult(
            command=["x"],
            exit_code=0,
            status="success",
            timed_out=False,
            started_at="a",
            ended_at="b",
            duration_seconds=1.5,
        )
        failed = mark_failed(ok)
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.command, ok.command)
        self.assertEqual(failed.exit_code, ok.exit_code)
        self.assertEqual(failed.started_at, ok.started_at)
        self.assertEqual(failed.duration_seconds, ok.duration_seconds)


if __name__ == "__main__":
    unittest.main()
