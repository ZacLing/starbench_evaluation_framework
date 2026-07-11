"""Run lifecycle supervision: reservation, spawn, heartbeat, stop, reconcile.

Core-side by design: any client (the bundled console, a CI script, another
GUI) gets the same lifecycle guarantees by importing this package instead of
re-implementing process babysitting.
"""

from .errors import LaunchError
from .supervisor import LaunchRegistry, launch_transaction

__all__ = ["LaunchError", "LaunchRegistry", "launch_transaction"]
