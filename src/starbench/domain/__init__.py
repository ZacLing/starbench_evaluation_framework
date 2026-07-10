"""Pure StarBench domain types shared by runners and read models."""

from .verdicts import TaskRunOutcome, aggregate_outcome

__all__ = ["TaskRunOutcome", "aggregate_outcome"]
