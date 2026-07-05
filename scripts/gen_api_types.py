#!/usr/bin/env python3
"""Render ``starbench.gui.contracts`` into the TypeScript client's api-types.ts.

The contracts module is the single source for the core ``/api`` shapes; this
script turns its TypedDicts (and Literal aliases) into TypeScript ``type`` /
``interface`` declarations so the front end cannot drift from the backend.

Run it via ``make gen-types`` after editing ``contracts.py``. The output file is
committed and carries a "GENERATED — do not edit" banner.

Type mapping: str→string, bool→boolean, int/float→number, None→null,
Optional[X]→X | null, List[X]→X[], Dict[str,V]→Record<string, V>,
Literal[...]→string/boolean literal union, a referenced TypedDict/alias→its name.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Literal, Union, get_args, get_origin, get_type_hints

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from starbench.gui import contracts  # noqa: E402

OUT_PATH = ROOT / "gui-frontend" / "src" / "lib" / "api-types.ts"

NoneType = type(None)


def _ts_literal(value: object) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _is_typeddict(obj: object) -> bool:
    return isinstance(obj, type) and hasattr(obj, "__required_keys__")


def ts_type(tp: object, names: set) -> str:
    origin = get_origin(tp)
    if tp is str:
        return "string"
    if tp is bool:
        return "boolean"
    if tp in (int, float):
        return "number"
    if tp is NoneType:
        return "null"
    if origin is Literal:
        return " | ".join(_ts_literal(arg) for arg in get_args(tp))
    if origin is Union:
        parts = [ts_type(arg, names) for arg in get_args(tp)]
        # Keep null last for readability (mirrors the hand-written client).
        parts = [p for p in parts if p != "null"] + (["null"] if "null" in parts else [])
        return " | ".join(dict.fromkeys(parts))
    if origin in (list, List):
        (inner,) = get_args(tp)
        rendered = ts_type(inner, names)
        # Parenthesize unions inside an array for correct precedence.
        return f"({rendered})[]" if " | " in rendered else f"{rendered}[]"
    if origin in (dict, Dict):
        _, value = get_args(tp)
        return f"Record<string, {ts_type(value, names)}>"
    if _is_typeddict(tp) and getattr(tp, "__name__", None) in names:
        return tp.__name__
    raise TypeError(f"Cannot render TypeScript for {tp!r}")


def render_alias(name: str, alias: object) -> str:
    args = get_args(alias)
    union = " | ".join(_ts_literal(arg) for arg in args)
    return f"export type {name} = {union}\n"


def render_interface(name: str, cls: type, names: set) -> str:
    hints = get_type_hints(cls)
    optional = set(getattr(cls, "__optional_keys__", set()))
    lines = [f"export interface {name} {{"]
    for field, tp in hints.items():
        mark = "?" if field in optional else ""
        lines.append(f"  {field}{mark}: {ts_type(tp, names)}")
    lines.append("}\n")
    return "\n".join(lines)


def generate() -> str:
    names = set(contracts.GENERATED_TYPES)
    banner = (
        "/* GENERATED — do not edit.\n"
        " * Source: src/starbench/gui/contracts.py — regenerate with `make gen-types`.\n"
        " */\n"
    )
    blocks: List[str] = [banner]
    for name in contracts.GENERATED_TYPES:
        obj = getattr(contracts, name)
        if _is_typeddict(obj):
            blocks.append(render_interface(name, obj, names))
        elif get_origin(obj) is Literal:
            blocks.append(render_alias(name, obj))
        else:
            raise TypeError(f"{name} is neither a TypedDict nor a Literal alias.")
    return "\n".join(blocks)


def main() -> int:
    output = generate()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(output, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(ROOT)} ({len(contracts.GENERATED_TYPES)} types).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
