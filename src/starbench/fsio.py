"""Atomic JSON persistence shared by every console-side writer.

One implementation of the temp-file + ``os.replace`` discipline instead of a
private copy per module: a crash mid-write must never leave a torn JSON file,
regardless of which writer was involved.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional, Tuple


def atomic_write_json(
    path: Path,
    payload: Any,
    *,
    indent: Optional[int] = None,
    sort_keys: bool = True,
    separators: Optional[Tuple[str, str]] = None,
    fsync: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=indent,
                sort_keys=sort_keys,
                separators=separators,
            )
            handle.write("\n")
            if fsync:
                handle.flush()
                os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


__all__ = ["atomic_write_json"]
