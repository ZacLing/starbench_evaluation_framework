"""Runtime-agnostic execution primitives.

This package holds the parts of process execution that do not depend on which
coding-agent runtime is being driven: spawning a subprocess and pumping its
streams (`process.py`), assembling a hardened `docker run` command
(`docker.py`), and parsing/normalising agent output into `final.md` plus
comparable event streams (`parsers.py`).

Invariants:
- Nothing here knows about a specific runtime (codex/claude/grok/...). Per-runtime
  command construction, env preparation, and docker wrapping live in
  ``starbench.adapters``; this layer is what the adapters call down into.
- This package must not import from ``starbench.adapters`` or
  ``starbench.runner`` (it is the bottom layer; keep the dependency arrow
  pointing down).

To change spawn/timeout/stream behaviour, edit ``process.py``. To change the
container sandbox flags, edit ``docker.py``. To change how an output format is
parsed into ``final.md``/events, edit ``parsers.py``.
"""
