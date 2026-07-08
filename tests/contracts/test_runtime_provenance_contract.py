"""Contract check: real capture_run_provenance output matches its schema."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.adapters.base import RuntimeAdapter, RuntimeInfo
from starbench.adapters.spec import SpecAdapter
from starbench.contracts import validate_payload
from starbench.runner.custom_runtime import load_custom_runtime
from starbench.runner.runtime_provenance import capture_run_provenance


class FakeAdapter(RuntimeAdapter):
    info = RuntimeInfo(
        id="fake",
        label="Fake Runtime",
        description="fake",
        protocol="none",
        bin="fakecli",
        docker_image="fake-image:latest",
    )


class RuntimeProvenanceContractTests(unittest.TestCase):
    """Validate the full provenance payload, not a hand-built lookalike.

    The probes stay deterministic without monkeypatching: the CLI is a fake
    executable prepended to PATH, the docker binary is a path that does not
    exist, and cwd is a fresh temp dir outside any git repository.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_provenance_contract_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

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

    def capture(self, **overrides) -> dict:
        base = dict(
            executor_agent="fake",
            executor_adapter=FakeAdapter(),
            executor_model="model-a",
            executor_backend="local",
            executor_bins={"fake": "fakecli"},
            executor_base_env=self.env(),
            executor_docker_bin=str(self.tmp / "missing-docker"),
            executor_docker_image=None,
            executor_custom_spec=None,
            evaluator_agent="fake",
            evaluator_adapter=FakeAdapter(),
            evaluator_model=None,
            evaluator_bins={"fake": "fakecli"},
            evaluator_base_env=self.env(),
            evaluator_custom_spec=None,
            cwd=self.tmp,
        )
        base.update(overrides)
        return capture_run_provenance(**base)

    def test_local_backend_output_matches_schema(self) -> None:
        self.write_fake_cli()
        provenance = self.capture()
        validate_payload("runtime_provenance.schema.json", provenance)
        self.assertEqual(provenance["executor"]["cli_version"], "1.2.3")
        # cwd is not a git repo: nullable git fields must validate as null.
        self.assertIsNone(provenance["starbench"]["git_commit"])

    def test_docker_backend_probe_error_still_matches_schema(self) -> None:
        self.write_fake_cli()
        provenance = self.capture(
            executor_backend="docker",
            executor_docker_image="fake-image:latest",
        )
        validate_payload("runtime_provenance.schema.json", provenance)
        self.assertIn(
            "Could not inspect Docker image",
            provenance["executor"]["docker_image_error"],
        )

    def test_missing_cli_error_still_matches_schema(self) -> None:
        # No fake CLI on PATH: the probe records an error instead of failing.
        env = dict(os.environ)
        env["PATH"] = str(self.tmp)
        provenance = self.capture(executor_base_env=env, evaluator_base_env=env)
        validate_payload("runtime_provenance.schema.json", provenance)
        self.assertIn("not found on PATH", provenance["executor"]["cli_version_error"])

    def test_custom_runtime_spec_matches_schema(self) -> None:
        self.write_fake_cli("customcli", "4.5.6")
        spec_path = self.tmp / "custom.json"
        spec_path.write_text(
            json.dumps(
                {
                    "id": "custom",
                    "command": "customcli",
                    "parser": "text",
                    "prompt_via": "stdin",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        spec = load_custom_runtime(self.tmp, "custom")
        provenance = self.capture(
            executor_agent="custom:custom",
            executor_adapter=SpecAdapter(spec),
            executor_custom_spec=spec,
        )
        validate_payload("runtime_provenance.schema.json", provenance)
        self.assertEqual(provenance["executor"]["custom_runtime_spec"]["id"], "custom")
        self.assertNotIn("env", provenance["executor"]["custom_runtime_spec"]["public_metadata"])


if __name__ == "__main__":
    unittest.main()
