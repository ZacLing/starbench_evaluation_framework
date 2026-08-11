"""Launch vocabulary shared by the runner CLI and the console.

One tuple per knob so the argparse choices, the console validators, and the
wizard metadata can never drift apart.
"""

INSTRUCTION_MODES = ("none", "traverse", "select", "ablation")
RIGOR_MODES = ("none", "select")

# Thinking-effort tiers, shallow to deep. "default" means "leave the
# runtime/model default alone" — no switch is passed and no prompt instruction
# is injected. "off" is a step below "minimal" and is *not* the same thing:
# it passes the runtime's switch to explicitly disable reasoning (pi's
# `--thinking off`), where "default" passes no switch at all. Each runtime
# narrows this to the tiers its CLI accepts (RuntimeInfo.thinking_efforts);
# models can narrow further via their own published level tables. "none" is the
# legacy spelling of "default" and is still accepted at every input boundary.
THINKING_EFFORTS = (
    "default",
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
)
LEGACY_THINKING_EFFORT = "none"


def canonical_thinking_effort(value: str) -> str:
    """Fold the legacy "none" spelling into "default"; pass everything else through."""
    return "default" if value == LEGACY_THINKING_EFFORT else value


__all__ = [
    "INSTRUCTION_MODES",
    "RIGOR_MODES",
    "THINKING_EFFORTS",
    "LEGACY_THINKING_EFFORT",
    "canonical_thinking_effort",
]
