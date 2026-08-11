"""Compatibility façade for the split console read models.

New code should import the focused module under ``gui.read_models``. Existing
callers may keep importing ``gui.data`` while the public API remains stable.
"""

from .read_models.base import (
    FINAL_MD_MAX_BYTES, LIVE_TAIL_MAX_BYTES, SAFE_ID, STDERR_TAIL_BYTES,
    NotFound, _read_json, _read_jsonl, _read_jsonl_slice, _read_text, _tail_text,
    resolve_run_dir, resolve_task_run_dir,
)
from .read_models.runs import (
    RUNNING_MTIME_WINDOW_SECONDS, TASK_HISTORY_CONFIG_LIMIT,
    list_runs, progress_snapshot, run_detail, run_overview, run_status, task_history,
)
from .read_models.artifacts import (
    ARTIFACT_BINARY_SNIFF_BYTES, ARTIFACT_MAX_BYTES, read_artifact, task_run_detail,
)
from .read_models.trace import (
    TRACE_BODY_MAX_CHARS, TRACE_DEFAULT_LIMIT, TRACE_MAX_LIMIT, TRACE_TITLE_MAX_CHARS,
    raw_events, task_trace,
)
from .read_models.live import (
    LIVE_EVENT_TAIL_LIMIT, LIVE_SUMMARY_MAX_CHARS, run_live,
)
from .read_models.tasks import (
    list_task_packages, read_human_reference_steps, read_rigors, rigor_count,
)
from .read_models.compare import COMPARE_MAX_RUNS, compare_runs
from .read_models.coverage import COVERAGE_RECENT_REFS_LIMIT, coverage

__all__ = [name for name in globals() if not name.startswith("__")]
