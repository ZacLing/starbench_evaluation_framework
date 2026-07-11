"""Launch vocabulary shared by the runner CLI and the console.

One tuple per knob so the argparse choices, the console validators, and the
wizard metadata can never drift apart.
"""

INSTRUCTION_MODES = ("none", "traverse", "select", "ablation")
RIGOR_MODES = ("none", "select")

__all__ = ["INSTRUCTION_MODES", "RIGOR_MODES"]
