"""_batch_marker precedence: run_config fact first, legacy run_state fallback."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.gui.read_models.runs import _batch_marker


def _write(root: Path, name: str, payload: dict) -> None:
    (root / name).write_text(json.dumps(payload), encoding="utf-8")


class BatchMarkerTests(unittest.TestCase):
    def _root(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_run_config_batch_wins(self) -> None:
        root = self._root()
        _write(root, "run_config.json", {"batch": "exp_a"})
        _write(root, "run_state.json", {"batch": "stale_b"})
        self.assertEqual(_batch_marker(root), "exp_a")

    def test_legacy_run_state_fallback(self) -> None:
        root = self._root()
        _write(root, "run_config.json", {"seed": 1})
        _write(root, "run_state.json", {"batch": "legacy_c"})
        self.assertEqual(_batch_marker(root), "legacy_c")

    def test_run_config_only(self) -> None:
        root = self._root()
        _write(root, "run_config.json", {"batch": "exp_d"})
        self.assertEqual(_batch_marker(root), "exp_d")

    def test_neither_yields_none(self) -> None:
        self.assertIsNone(_batch_marker(self._root()))


if __name__ == "__main__":
    unittest.main()
