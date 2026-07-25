"""One-time profiles.json v1->v2 migration (option boxes) and its loader hook.

The pure ``migrate_profiles_document`` folds the legacy flat launch-form knobs
(``claude_max_turns`` and the ``opencode_*`` gateway wiring) into the role
option boxes decided by the C-round runtime-options spec (D2). The loader hook
backs up the pristine v1 file once and atomically installs the migrated shape.
"""
from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.gui.services.profiles import (
    load_profiles,
    migrate_profiles_document,
    profiles_path,
)


def _v1_document() -> dict:
    """A real-shaped v1 profiles.json, reduced to one profile with a claude +
    gemini contender and ``claude_max_turns`` set.

    Structure mirrors the repo's actual ``runs/profiles.json`` (a dict with a
    ``profiles`` list; each profile carries id/rev/name/shared/
    per_contender_fields/roster/task_set; roster entries are agent/model/
    provider_id). The real file carries NO ``claude_max_turns`` and NO
    ``opencode_*`` fields, so on real data rule 1/2 are no-ops and only the
    version stamp applies; ``claude_max_turns`` is added here to exercise rule 1.
    """
    return {
        "profiles": [
            {
                "id": "hsw-frontier",
                "rev": 3,
                "name": "HSW frontier sweep",
                "shared": {
                    "evaluator_agent": "codex",
                    "evaluator_model": "gpt-5.5",
                    "evaluator_auth_mode": "global",
                    "judge_mode": "single",
                    "evaluator_timeout_seconds": 900,
                    "executor_backend": "local",
                    "executor_auth_mode": "env",
                    "seed": 123,
                    "batch_size": 1,
                    "repeat": 5,
                    "claude_max_turns": 30,
                },
                "per_contender_fields": ["model", "credentials", "gateway"],
                "roster": [
                    {
                        "agent": "claude",
                        "model": "claude-opus-4-8",
                        "provider_id": "anthropic",
                    },
                    {
                        "agent": "gemini",
                        "model": "gemini-3.1-pro-preview",
                        "provider_id": "google",
                    },
                ],
                "task_set": {
                    "tasks_dir": "examples/tasks",
                    "task_ids": ["demo_python_cli", "demo_instruction_reference"],
                },
            }
        ]
    }


class MigratePureFunctionTest(unittest.TestCase):
    def test_claude_contender_gains_max_turns_option(self) -> None:
        migrated, changed = migrate_profiles_document(_v1_document())
        self.assertTrue(changed)
        profile = migrated["profiles"][0]
        claude = next(c for c in profile["roster"] if c["agent"] == "claude")
        # Rule 1: the flat cap lands on the claude contender's option box as int.
        self.assertEqual(claude["options"], {"max_turns": 30})
        self.assertIsInstance(claude["options"]["max_turns"], int)
        # The gemini contender is untouched — no options key at all.
        gemini = next(c for c in profile["roster"] if c["agent"] == "gemini")
        self.assertNotIn("options", gemini)
        # The flat field is gone from shared; the version is stamped top-level.
        self.assertNotIn("claude_max_turns", profile["shared"])
        self.assertEqual(migrated["schema_version"], 2)

    def test_string_cap_is_coerced_to_int(self) -> None:
        doc = _v1_document()
        doc["profiles"][0]["shared"]["claude_max_turns"] = "30"
        migrated, changed = migrate_profiles_document(doc)
        self.assertTrue(changed)
        claude = next(
            c for c in migrated["profiles"][0]["roster"] if c["agent"] == "claude"
        )
        self.assertEqual(claude["options"], {"max_turns": 30})
        self.assertIsInstance(claude["options"]["max_turns"], int)

    def test_existing_contender_options_are_preserved(self) -> None:
        doc = _v1_document()
        doc["profiles"][0]["roster"][0]["options"] = {"existing": "keep"}
        migrated, _ = migrate_profiles_document(doc)
        claude = next(
            c for c in migrated["profiles"][0]["roster"] if c["agent"] == "claude"
        )
        # The cap merges into any pre-existing option box, not replacing it.
        self.assertEqual(claude["options"], {"existing": "keep", "max_turns": 30})

    def test_shared_cap_overwrites_a_stale_contender_max_turns(self) -> None:
        # Spec rule 1 is authoritative: the shared value wins over any stale
        # max_turns already on the contender's box.
        doc = _v1_document()
        doc["profiles"][0]["roster"][0]["options"] = {"max_turns": 99, "keep": "me"}
        migrated, _ = migrate_profiles_document(doc)
        claude = next(
            c for c in migrated["profiles"][0]["roster"] if c["agent"] == "claude"
        )
        self.assertEqual(claude["options"], {"max_turns": 30, "keep": "me"})

    def test_two_claude_contenders_each_get_the_cap(self) -> None:
        doc = _v1_document()
        doc["profiles"][0]["roster"].append(
            {"agent": "claude", "model": "claude-sonnet-4-8", "provider_id": "anthropic"}
        )
        migrated, _ = migrate_profiles_document(doc)
        caps = [
            c["options"]["max_turns"]
            for c in migrated["profiles"][0]["roster"]
            if c["agent"] == "claude"
        ]
        self.assertEqual(caps, [30, 30])

    def test_no_legacy_fields_still_stamps_the_version(self) -> None:
        # The repo's real file shape: v1, no claude_max_turns, no opencode.
        doc = _v1_document()
        del doc["profiles"][0]["shared"]["claude_max_turns"]
        migrated, changed = migrate_profiles_document(doc)
        # A bare version stamp is still a change (rule 3), and no contender
        # gains an options box because there was nothing to distribute.
        self.assertTrue(changed)
        self.assertEqual(migrated["schema_version"], 2)
        for contender in migrated["profiles"][0]["roster"]:
            self.assertNotIn("options", contender)

    def test_null_cap_is_dropped_without_creating_options(self) -> None:
        doc = _v1_document()
        doc["profiles"][0]["shared"]["claude_max_turns"] = None
        migrated, changed = migrate_profiles_document(doc)
        self.assertTrue(changed)
        # The legacy key leaves the v2 contract entirely, but an unset value
        # never fabricates a cap on any contender.
        self.assertNotIn("claude_max_turns", migrated["profiles"][0]["shared"])
        for contender in migrated["profiles"][0]["roster"]:
            self.assertNotIn("options", contender)

    def test_opencode_shared_wiring_moves_into_role_boxes(self) -> None:
        # Synthetic: the real file has none of these (gateway wiring is derived
        # at launch, never persisted). Rule 2 is a defensive one-time fold.
        doc = _v1_document()
        del doc["profiles"][0]["shared"]["claude_max_turns"]
        doc["profiles"][0]["shared"].update(
            {
                "executor_opencode_provider": "yunwu",
                "executor_opencode_base_url": "https://yunwu.ai/v1",
                "evaluator_opencode_api_key_env": "OPENAI_API_KEY",
            }
        )
        migrated, changed = migrate_profiles_document(doc)
        self.assertTrue(changed)
        shared = migrated["profiles"][0]["shared"]
        self.assertEqual(
            shared["executor_options"],
            {"provider": "yunwu", "base_url": "https://yunwu.ai/v1"},
        )
        self.assertEqual(shared["evaluator_options"], {"api_key_env": "OPENAI_API_KEY"})
        for key in list(shared):
            self.assertNotIn("opencode", key)

    def test_bare_opencode_wiring_feeds_both_role_boxes(self) -> None:
        doc = _v1_document()
        del doc["profiles"][0]["shared"]["claude_max_turns"]
        doc["profiles"][0]["shared"]["opencode_provider"] = "yunwu"
        migrated, _ = migrate_profiles_document(doc)
        shared = migrated["profiles"][0]["shared"]
        self.assertEqual(shared["executor_options"], {"provider": "yunwu"})
        self.assertEqual(shared["evaluator_options"], {"provider": "yunwu"})

    def test_per_contender_opencode_wiring_moves_into_that_contender(self) -> None:
        doc = _v1_document()
        del doc["profiles"][0]["shared"]["claude_max_turns"]
        doc["profiles"][0]["roster"][1]["executor_opencode_provider"] = "yunwu"
        migrated, _ = migrate_profiles_document(doc)
        gemini = migrated["profiles"][0]["roster"][1]
        self.assertEqual(gemini["options"], {"provider": "yunwu"})
        self.assertNotIn("executor_opencode_provider", gemini)

    def test_already_v2_returns_same_object_unchanged(self) -> None:
        doc = {"schema_version": 2, "profiles": _v1_document()["profiles"]}
        before = copy.deepcopy(doc)
        result, changed = migrate_profiles_document(doc)
        self.assertFalse(changed)
        self.assertIs(result, doc)  # rule 4: already-v2 passes through as-is
        self.assertEqual(doc, before)  # no mutation

    def test_second_pass_is_idempotent(self) -> None:
        migrated, _ = migrate_profiles_document(_v1_document())
        again, changed = migrate_profiles_document(migrated)
        self.assertFalse(changed)
        self.assertEqual(again, migrated)

    def test_input_document_is_never_mutated(self) -> None:
        original = _v1_document()
        snapshot = copy.deepcopy(original)
        migrate_profiles_document(original)
        self.assertEqual(original, snapshot)  # pure: input untouched

    def test_migrated_profile_has_no_spurious_deviations(self) -> None:
        # Data-integrity guard: opening/launching a migrated profile must not
        # read as "modified" in the snapshot deviation comparison.
        from starbench.gui.services.profile_snapshots import (
            _roster_deviates,
            _shared_deviations,
        )

        migrated, _ = migrate_profiles_document(_v1_document())
        profile = migrated["profiles"][0]
        # The transitional launch form still posts a shared claude_max_turns;
        # the migrated profile no longer stores it. That difference must not
        # flag a deviation (claude_max_turns is not a compared shared key).
        launch_shared = dict(profile["shared"])
        launch_shared["claude_max_turns"] = 30
        self.assertEqual(_shared_deviations(launch_shared, profile["shared"]), [])
        # Roster identity ignores the per-contender options box, so a launch
        # of the same contenders matches the migrated baseline.
        self.assertFalse(_roster_deviates(profile["roster"], profile["roster"]))


class MigrateLoaderHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_profile_migrate_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, document: dict) -> Path:
        path = profiles_path(self.runs_dir)
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        return path

    def _backup_path(self) -> Path:
        path = profiles_path(self.runs_dir)
        return path.with_name(f"{path.name}.v1.bak")

    def test_loader_migrates_and_persists_the_v2_shape(self) -> None:
        self._write(_v1_document())
        loaded = load_profiles(self.runs_dir)
        # In-memory payload is migrated.
        claude = next(
            c for c in loaded["profiles"][0]["roster"] if c["agent"] == "claude"
        )
        self.assertEqual(claude["options"], {"max_turns": 30})
        # On-disk file is the migrated v2 shape.
        on_disk = json.loads(profiles_path(self.runs_dir).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["schema_version"], 2)
        self.assertNotIn("claude_max_turns", on_disk["profiles"][0]["shared"])

    def test_loader_backs_up_the_pristine_v1_file(self) -> None:
        original_bytes = self._write(_v1_document()).read_bytes()
        load_profiles(self.runs_dir)
        backup = self._backup_path()
        self.assertTrue(backup.exists())
        # The backup is the byte-for-byte pristine original, not a re-render.
        self.assertEqual(backup.read_bytes(), original_bytes)

    def test_loader_never_overwrites_an_existing_backup(self) -> None:
        # A crashed earlier attempt may have left a backup; it is pristine and
        # must survive a re-entered migration untouched.
        self._backup_path().write_bytes(b'{"sentinel": true}')
        self._write(_v1_document())
        load_profiles(self.runs_dir)
        self.assertEqual(self._backup_path().read_bytes(), b'{"sentinel": true}')

    def test_loader_leaves_a_v2_file_untouched(self) -> None:
        migrated, _ = migrate_profiles_document(_v1_document())
        path = self._write(migrated)
        before = path.read_bytes()
        load_profiles(self.runs_dir)
        # Already-v2: no rewrite, no backup — the loader only writes on change.
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self._backup_path().exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
