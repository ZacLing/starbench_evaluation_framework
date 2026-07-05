"""Docker command construction for built-in and custom runtimes."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.runner.run_benchmark import parse_args


class DockerCommandTests(unittest.TestCase):
    def write_runtime(self, root: Path, runtime_id: str, data: dict) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{runtime_id}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_generic_docker_command_uses_whitelist_and_mounts(self) -> None:
        from starbench.runner.codex_process import build_docker_agent_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_docker_agent_command(
                docker_bin="docker",
                docker_image="starbench-qwen:latest",
                workspace=tmp_path,
                inner_command=["qwen", "--yolo"],
                env_whitelist=["OPENAI_API_KEY", "UNSET_VAR"],
                auth_env={"OPENAI_API_KEY": "x"},
                container_name="starbench-custom-1",
                extra_env={"HOME": "/tmp"},
            )
            self.assertIn("starbench-qwen:latest", command)
            self.assertIn("OPENAI_API_KEY", command)
            self.assertNotIn("UNSET_VAR", command)
            self.assertIn("HOME=/tmp", command)
            name_index = command.index("--name")
            self.assertEqual(command[name_index + 1], "starbench-custom-1")
            self.assertEqual(command[-2:], ["qwen", "--yolo"])

    def test_codex_docker_command_unchanged_by_extraction(self) -> None:
        from starbench.runner.codex_process import build_docker_codex_command

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_docker_codex_command(
                docker_bin="docker",
                docker_image="starbench-codex:latest",
                workspace=tmp_path,
                codex_home=tmp_path,
                inner_command=["codex", "exec"],
                auth_env={"OPENAI_API_KEY": "x"},
                container_name="starbench-abc",
            )
            self.assertIn("CODEX_HOME=/codex-home", command)
            self.assertIn("--read-only", command)
            self.assertIn("OPENAI_API_KEY", command)

    def test_parse_args_allows_docker_for_every_builtin_and_picks_its_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            expected = {
                "codex": "starbench-codex:latest",
                "claude": "starbench-claude-code:latest",
                "gemini": "starbench-gemini-cli:latest",
                "grok": "starbench-grok:latest",
                "opencode": "starbench-opencode:latest",
            }
            for agent, image in expected.items():
                args = parse_args(
                    ["--tasks-dir", tmp, "--runs-dir", tmp,
                     "--executor-agent", agent, "--executor-backend", "docker"]
                )
                self.assertEqual(args.executor_backend, "docker")
                self.assertEqual(args.docker_image, image)
            args = parse_args(
                ["--tasks-dir", tmp, "--runs-dir", tmp,
                 "--executor-agent", "gemini", "--executor-backend", "docker",
                 "--docker-image", "my-gemini:dev"]
            )
            self.assertEqual(args.docker_image, "my-gemini:dev")

    def test_gemini_docker_command_shape(self) -> None:
        from starbench.runner.codex_process import build_gemini_docker_command

        with tempfile.TemporaryDirectory() as tmp:
            command = build_gemini_docker_command(
                gemini_bin="gemini",
                docker_bin="docker",
                docker_image="starbench-gemini-cli:latest",
                workspace=Path(tmp),
                model="gemini-2.5-pro",
                auth_env={"GEMINI_API_KEY": "x"},
                container_name="starbench-g1",
            )
            self.assertIn("starbench-gemini-cli:latest", command)
            self.assertIn("HOME=/workspace/.runner/gemini_home", command)
            self.assertIn("GEMINI_API_KEY", command)
            self.assertIn("--yolo", command)
            self.assertIn("--read-only", command)

    def test_grok_docker_command_runs_in_container_cwd(self) -> None:
        from starbench.runner.codex_process import build_grok_docker_command

        with tempfile.TemporaryDirectory() as tmp:
            command = build_grok_docker_command(
                grok_bin="grok",
                docker_bin="docker",
                docker_image="starbench-grok:latest",
                workspace=Path(tmp),
                prompt="fix the bug",
                model="grok-build-0.1",
                auth_env={"XAI_API_KEY": "x"},
                container_name="starbench-k1",
            )
            cwd_index = command.index("--cwd")
            self.assertEqual(command[cwd_index + 1], "/workspace")
            self.assertIn("HOME=/workspace/.runner/grok_home", command)
            self.assertIn("XAI_API_KEY", command)
            self.assertEqual(command[-2:], ["-p", "fix the bug"])

    def test_opencode_docker_command_carries_inline_gateway_config(self) -> None:
        from starbench.runner.codex_process import build_opencode_docker_command

        with tempfile.TemporaryDirectory() as tmp:
            command = build_opencode_docker_command(
                opencode_bin="opencode",
                docker_bin="docker",
                docker_image="starbench-opencode:latest",
                workspace=Path(tmp),
                model="openrouter/qwen3-coder",
                auth_env={"OPENROUTER_API_KEY": "x"},
                provider="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                container_name="starbench-o1",
            )
            dir_index = command.index("--dir")
            self.assertEqual(command[dir_index + 1], "/workspace")
            self.assertIn("HOME=/workspace/.runner/opencode_home", command)
            self.assertIn("OPENROUTER_API_KEY", command)
            config_entry = next(
                item for item in command if item.startswith("OPENCODE_CONFIG_CONTENT=")
            )
            self.assertIn("https://openrouter.ai/api/v1", config_entry)
            self.assertIn("{env:OPENROUTER_API_KEY}", config_entry)

    def test_custom_docker_command_defaults_home_into_workspace(self) -> None:
        from starbench.runner.codex_process import build_custom_docker_command
        from starbench.runner.custom_runtime import load_custom_runtime

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runtimes"
            self.write_runtime(
                root,
                "boxed",
                {
                    "id": "boxed",
                    "command": "boxcli",
                    "parser": "text",
                    "docker": {"image": "boxed:latest", "env_passthrough": ["OPENAI_API_KEY"]},
                },
            )
            spec = load_custom_runtime(root, "boxed")
            command = build_custom_docker_command(
                spec,
                docker_bin="docker",
                workspace=Path(tmp),
                prompt="do it",
                model=None,
                auth_env={"OPENAI_API_KEY": "x"},
                container_name="starbench-b1",
            )
            self.assertIn("HOME=/workspace/.runner/custom_home", command)
            self.assertIn("OPENAI_API_KEY", command)

            # A spec that sets HOME itself wins over the default.
            self.write_runtime(
                root,
                "homed",
                {
                    "id": "homed",
                    "command": "boxcli",
                    "parser": "text",
                    "env": {"HOME": "/tmp/elsewhere"},
                    "docker": {"image": "boxed:latest"},
                },
            )
            homed = load_custom_runtime(root, "homed")
            command = build_custom_docker_command(
                homed,
                docker_bin="docker",
                workspace=Path(tmp),
                prompt="do it",
                model=None,
                auth_env={},
            )
            self.assertIn("HOME=/tmp/elsewhere", command)
            self.assertNotIn("HOME=/workspace/.runner/custom_home", command)

    def test_opencode_docker_export_env_points_at_workspace_home(self) -> None:
        from starbench.runner.codex_process import opencode_docker_export_env

        with tempfile.TemporaryDirectory() as tmp:
            env = opencode_docker_export_env(Path(tmp))
            self.assertEqual(env["HOME"], str(Path(tmp) / ".runner" / "opencode_home"))
            self.assertTrue(env["XDG_DATA_HOME"].endswith("opencode_home/.local/share"))


if __name__ == "__main__":
    unittest.main()
