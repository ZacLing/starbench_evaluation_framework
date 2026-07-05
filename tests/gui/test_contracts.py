"""Guard: the committed TS client types stay in sync with contracts.py.

``gui-frontend/src/lib/api-types.ts`` is generated from
``starbench.gui.contracts`` by ``scripts/gen_api_types.py``. This test fails if
someone edits the contracts (or the generator) without re-running
``make gen-types`` and committing the result, so the front/back ends cannot
silently drift on a field name or nullability.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_api_types", ROOT / "scripts" / "gen_api_types.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ContractsTest(unittest.TestCase):
    def test_api_types_ts_is_up_to_date(self) -> None:
        gen = _load_generator()
        committed = gen.OUT_PATH.read_text(encoding="utf-8")
        self.assertEqual(
            committed,
            gen.generate(),
            "api-types.ts is stale — run `make gen-types` and commit the result.",
        )

    def test_contracts_cover_the_core_shapes(self) -> None:
        from starbench.gui import contracts

        for name in ("AgentsPayload", "AiProvider", "ExperimentPlanItem", "Contender"):
            self.assertIn(name, contracts.GENERATED_TYPES)


if __name__ == "__main__":
    unittest.main()
