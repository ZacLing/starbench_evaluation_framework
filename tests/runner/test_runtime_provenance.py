from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.adapters.base import RuntimeAdapter, RuntimeInfo
from starbench.adapters.spec import SpecAdapter
from starbench.runner.custom_runtime import load_custom_runtime
from starbench.runner.runtime_provenance import (
    RUNTIME_PROVENANCE_SCHEMA,
    capture_runtime_provenance,
)


class FakeAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="fake",
        label="Fake Runtime",
        description="fake",
        protocol="none",
        bin="fakecli",
        docker_image="fake-image:latest",
    )


class RuntimeProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_provenance_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_fake_cli(self, name: str = "fakecli", version: str = "1.2.3") -> Path:
        path = self.tmp / name
        path.write_text(
            f"#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo '{name} {version}'; exit 0; fi\nexit 0\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PATH"] = f"{self.tmp}{os.pathsep}{env.get('PATH', '')}"
        return env

    def test_local_runtime_records_cli_version(self) -> None:
        self.write_fake_cli()
        provenance = capture_runtime_provenance(
            role="executor",
            agent="fake",
            adapter=FakeAdapter(),
            model="model-a",
            backend="local",
            bins={"fake": "fakecli"},
            base_env=self.env(),
            docker_bin="docker",
            docker_image=None,
        )
        self.assertEqual(provenance["role"], "executor")
        self.assertEqual(provenance["agent"], "fake")
        self.assertEqual(provenance["model"], "model-a")
        self.assertEqual(provenance["backend"], "local")
        self.assertEqual(provenance["cli_bin"], "fakecli")
        self.assertEqual(provenance["cli_version"], "1.2.3")
        self.assertIsNone(provenance["cli_version_error"])

    def test_custom_runtime_records_spec_hash_without_full_env(self) -> None:
        self.write_fake_cli("customcli", "4.5.6")
        spec_path = self.tmp / "custom.json"
        spec_path.write_text(
            json.dumps(
                {
                    "id": "custom",
                    "command": "customcli",
                    "parser": "text",
                    "prompt_via": "stdin",
                    "env": {"SECRET_SHOULD_NOT_BE_COPIED": "token-value"},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        spec = load_custom_runtime(self.tmp, "custom")
        provenance = capture_runtime_provenance(
            role="executor",
            agent="custom:custom",
            adapter=SpecAdapter(spec),
            model=None,
            backend="local",
            bins={},
            base_env=self.env(),
            docker_bin="docker",
            docker_image=None,
            custom_spec=spec,
        )
        custom_spec = provenance["custom_runtime_spec"]
        self.assertEqual(custom_spec["id"], "custom")
        self.assertIsNotNone(custom_spec["sha256"])
        self.assertEqual(custom_spec["public_metadata"]["parser"], "text")
        self.assertNotIn("env", custom_spec["public_metadata"])

    def test_docker_runtime_records_image_inspect_error_without_failing(self) -> None:
        provenance = capture_runtime_provenance(
            role="executor",
            agent="fake",
            adapter=FakeAdapter(),
            model=None,
            backend="docker",
            bins={"fake": "fakecli"},
            base_env=self.env(),
            docker_bin=str(self.tmp / "missing-docker"),
            docker_image="fake-image:latest",
        )
        self.assertEqual(RUNTIME_PROVENANCE_SCHEMA, 1)
        self.assertEqual(provenance["docker_image"], "fake-image:latest")
        self.assertIsNone(provenance["docker_image_id"])
        self.assertIn("Could not inspect Docker image", provenance["docker_image_error"])
        self.assertIsNone(provenance["cli_version"])
        self.assertIn("not captured", provenance["cli_version_error"])


if __name__ == "__main__":
    unittest.main()
