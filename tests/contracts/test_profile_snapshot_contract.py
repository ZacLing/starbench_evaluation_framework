"""Contract checks for the profile snapshot (the launch-time measurement contract).

The snapshot is the credential-discipline artifact of the profile pipeline:
every object in the schema forbids unknown keys, so a payload smuggling secret
material (an ``api_key`` field anywhere) is rejected, not silently stored. The
only credential-shaped fields are environment-variable NAMES (``api_key_env``).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from starbench.contracts import (
    ContractValidationError,
    load_schema,
    validate_json_schema,
    validate_payload,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas" / "starbench" / "v1"


def valid_snapshot() -> dict:
    """A fully-populated legal sample; each call builds a fresh copy."""
    return {
        "schema_version": 1,
        "captured_at": "2026-07-09T08:00:00+00:00",
        "profile": {"id": "hsw-frontier", "rev": 3, "name": "HSW frontier sweep"},
        "contender": {
            "agent": "claude",
            "model": "claude-opus-4-8",
            "label": "Claude Opus",
            "thinking_effort": "none",
            "auth_mode": "env",
            "provider_id": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key_env": "ANTHROPIC_API_KEY",
        },
        "roster": [
            {
                "agent": "claude",
                "model": "claude-opus-4-8",
                "provider_id": "anthropic",
                "base_url": "https://api.anthropic.com",
                "api_key_env": "ANTHROPIC_API_KEY",
            },
            {"agent": "codex", "model": "gpt-5.5", "api_key_env": "OPENAI_API_KEY"},
        ],
        "instrument": {
            "evaluator_agent": "codex",
            "evaluator_model": "gpt-5.5",
            "evaluator_auth_mode": "env",
            "judge_mode": "single",
            "evaluator_timeout_seconds": 900,
        },
        "execution": {
            "seed": 123,
            "batch_size": 1,
            "repeat": 5,
            "executor_backend": "local",
            "executor_auth_mode": "env",
            "max_evaluator_parallel": 4,
            "web_search": "task",
        },
        "task_set": {"tasks_dir": "tasks", "task_ids": ["task_a", "task_b"]},
    }


class ProfileSnapshotSchemaTests(unittest.TestCase):
    def test_schema_file_follows_v1_conventions(self) -> None:
        payload = json.loads(
            (SCHEMA_ROOT / "profile_snapshot.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(payload["$id"].startswith("https://starbench.dev/schemas/v1/"))
        self.assertEqual(payload["type"], "object")

    def test_schema_uses_only_keywords_the_validator_enforces(self) -> None:
        """Validating a legal sample walks every schema branch; the whitelist
        validator raises on any keyword it does not implement, so a clean pass
        proves the schema stays inside the supported keyword set."""
        validate_json_schema(load_schema("profile_snapshot.schema.json"), valid_snapshot())

    def test_valid_snapshot_passes(self) -> None:
        validate_payload("profile_snapshot.schema.json", valid_snapshot())

    def test_minimal_snapshot_passes(self) -> None:
        snapshot = valid_snapshot()
        snapshot["contender"] = {"agent": "codex", "model": ""}
        snapshot["roster"] = []
        snapshot["instrument"] = {
            "evaluator_agent": "codex",
            "evaluator_model": "gpt-5.5",
            "evaluator_auth_mode": "global",
            "judge_mode": "both",
        }
        snapshot["execution"] = {
            "seed": 0,
            "batch_size": 1,
            "repeat": 1,
            "executor_backend": "docker",
            "executor_auth_mode": "copy-auth",
        }
        snapshot["task_set"] = {"tasks_dir": "tasks", "task_ids": []}
        validate_payload("profile_snapshot.schema.json", snapshot)

    def test_missing_required_sections_rejected(self) -> None:
        for key in (
            "schema_version",
            "captured_at",
            "profile",
            "contender",
            "roster",
            "instrument",
            "execution",
            "task_set",
        ):
            snapshot = valid_snapshot()
            del snapshot[key]
            with self.subTest(missing=key):
                with self.assertRaisesRegex(ContractValidationError, key):
                    validate_payload("profile_snapshot.schema.json", snapshot)

    def test_missing_required_leaves_rejected(self) -> None:
        cases = (
            ("profile", "rev"),
            ("contender", "model"),
            ("instrument", "judge_mode"),
            ("execution", "executor_auth_mode"),
            ("task_set", "task_ids"),
        )
        for section, key in cases:
            snapshot = valid_snapshot()
            del snapshot[section][key]
            with self.subTest(section=section, missing=key):
                with self.assertRaisesRegex(ContractValidationError, key):
                    validate_payload("profile_snapshot.schema.json", snapshot)

    def test_modified_marker_is_optional_both_ways(self) -> None:
        """Ad-hoc launches annotate their deviation from the cited profile;
        snapshots written before the marker existed carry neither key and
        must stay legal (valid_snapshot() itself has no marker)."""
        unmarked = valid_snapshot()
        self.assertNotIn("modified", unmarked)
        self.assertNotIn("modified_fields", unmarked)
        validate_payload("profile_snapshot.schema.json", unmarked)

        marked = valid_snapshot()
        marked["modified"] = True
        marked["modified_fields"] = ["roster", "task_set", "repeat"]
        validate_payload("profile_snapshot.schema.json", marked)
        # Walk the new branches through the whitelist validator too: a clean
        # pass proves they stay inside the supported keyword set.
        validate_json_schema(load_schema("profile_snapshot.schema.json"), marked)

        unmodified = valid_snapshot()
        unmodified["modified"] = False
        validate_payload("profile_snapshot.schema.json", unmodified)

    def test_modified_fields_non_string_items_rejected(self) -> None:
        snapshot = valid_snapshot()
        snapshot["modified"] = True
        snapshot["modified_fields"] = ["roster", 7]
        with self.assertRaisesRegex(ContractValidationError, "modified_fields"):
            validate_payload("profile_snapshot.schema.json", snapshot)

    def test_modified_wrong_type_rejected(self) -> None:
        snapshot = valid_snapshot()
        snapshot["modified"] = "yes"
        with self.assertRaisesRegex(ContractValidationError, "modified"):
            validate_payload("profile_snapshot.schema.json", snapshot)

    def test_secret_material_fields_rejected_everywhere(self) -> None:
        """CREDENTIAL RED LINE: no object in the contract accepts a field that
        could carry a key value. Unknown keys are rejected at every level."""
        contaminated = []
        top = valid_snapshot()
        top["api_key"] = "sk-super-secret"
        contaminated.append(("top-level", top))

        in_contender = valid_snapshot()
        in_contender["contender"]["api_key"] = "sk-super-secret"
        contaminated.append(("contender", in_contender))

        in_roster = valid_snapshot()
        in_roster["roster"][0]["api_key"] = "sk-super-secret"
        contaminated.append(("roster entry", in_roster))

        in_instrument = valid_snapshot()
        in_instrument["instrument"]["evaluator_api_key"] = "sk-super-secret"
        contaminated.append(("instrument", in_instrument))

        in_execution = valid_snapshot()
        in_execution["execution"]["token"] = "sk-super-secret"
        contaminated.append(("execution", in_execution))

        for where, snapshot in contaminated:
            with self.subTest(where=where):
                with self.assertRaisesRegex(ContractValidationError, "unexpected key"):
                    validate_payload("profile_snapshot.schema.json", snapshot)

    def test_enum_and_type_violations_rejected(self) -> None:
        bad_backend = valid_snapshot()
        bad_backend["execution"]["executor_backend"] = "kubernetes"
        with self.assertRaisesRegex(ContractValidationError, "executor_backend"):
            validate_payload("profile_snapshot.schema.json", bad_backend)

        bad_rev = valid_snapshot()
        bad_rev["profile"]["rev"] = 0
        with self.assertRaisesRegex(ContractValidationError, "rev"):
            validate_payload("profile_snapshot.schema.json", bad_rev)

        bad_task_ids = valid_snapshot()
        bad_task_ids["task_set"]["task_ids"] = ["task_a", 7]
        with self.assertRaisesRegex(ContractValidationError, "task_ids"):
            validate_payload("profile_snapshot.schema.json", bad_task_ids)


if __name__ == "__main__":
    unittest.main()
