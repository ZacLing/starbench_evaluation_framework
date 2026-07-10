"""Pure StarBench domain types shared by runners and read models."""

from .identifiers import (
    MAX_SAFE_ID_LENGTH,
    SAFE_ID_PATTERN,
    compact_safe_id,
    parse_safe_id,
)
from .paths import assert_no_symlinks, parse_relative_path, resolve_within, safe_child
from .verdicts import TaskRunOutcome, aggregate_outcome

__all__ = [
    "MAX_SAFE_ID_LENGTH",
    "SAFE_ID_PATTERN",
    "TaskRunOutcome",
    "aggregate_outcome",
    "assert_no_symlinks",
    "compact_safe_id",
    "parse_relative_path",
    "parse_safe_id",
    "resolve_within",
    "safe_child",
]
