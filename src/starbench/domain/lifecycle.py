"""Shared names for the persisted run lifecycle control plane."""

RUN_STATE_FILENAME = "run_state.json"
RUN_CLAIM_FILENAME = ".runner_claim"
RUN_LAUNCH_TOKEN_ENV = "STARBENCH_RUN_LAUNCH_TOKEN"
RUN_ID_ENV = "STARBENCH_RUN_ID"

ACTIVE_RUN_STATES = frozenset({"prepared", "starting", "running", "stopping"})
TERMINAL_RUN_STATES = frozenset(
    {"completed", "exited", "stopped", "rolled_back", "launch_failed", "orphaned"}
)

__all__ = [
    "ACTIVE_RUN_STATES",
    "RUN_CLAIM_FILENAME",
    "RUN_ID_ENV",
    "RUN_LAUNCH_TOKEN_ENV",
    "RUN_STATE_FILENAME",
    "TERMINAL_RUN_STATES",
]
