#!/usr/bin/env python3
"""Mirror the public protocol schemas into the installable package.

`schemas/starbench/` is the single authoring source; the byte-identical copy
under `src/starbench/contracts/schemas/` only exists so wheels ship the
contract files. Never edit the packaged copy by hand — run `make sync-schemas`
after changing a schema. `tests/contracts` asserts the two trees stay equal,
so a forgotten sync fails loudly.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "schemas" / "starbench"
PACKAGED = ROOT / "src" / "starbench" / "contracts" / "schemas"


def main() -> int:
    if not SOURCE.is_dir():
        print(f"missing schema source tree: {SOURCE}", file=sys.stderr)
        return 1
    synced = 0
    removed = 0
    source_files = {
        path.relative_to(SOURCE): path for path in sorted(SOURCE.rglob("*.json"))
    }
    for relative, path in source_files.items():
        target = PACKAGED / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_bytes() != path.read_bytes():
            shutil.copyfile(path, target)
            print(f"synced  {relative}")
            synced += 1
    for stale in sorted(PACKAGED.rglob("*.json")):
        if stale.relative_to(PACKAGED) not in source_files:
            stale.unlink()
            print(f"removed {stale.relative_to(PACKAGED)}")
            removed += 1
    print(f"{synced} synced, {removed} removed, {len(source_files)} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
