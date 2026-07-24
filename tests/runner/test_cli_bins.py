"""The per-runtime --<id>-bin flags are derived from the adapter registry."""
from __future__ import annotations

import unittest

from starbench.adapters import list_builtin
from starbench.runner.cli import parse_args


class CliBinFlagsTests(unittest.TestCase):
    def test_every_builtin_gets_a_bin_flag_with_registry_default(self) -> None:
        args = parse_args([])
        for adapter in list_builtin():
            info = adapter.info
            self.assertEqual(getattr(args, f"{info.id}_bin"), info.bin, info.id)

    def test_bin_flag_override_is_respected(self) -> None:
        args = parse_args(["--gemini-bin", "/opt/custom/gemini"])
        self.assertEqual(args.gemini_bin, "/opt/custom/gemini")
