"""Runtime command/parse helpers for opencode, grok and gemini adapters."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.runner.codex_process import (
    _extract_json_object,
    _extract_opencode_session_id,
    _extract_opencode_text,
    _extract_opencode_text_from_events,
    append_opencode_compat_events,
    build_gemini_headless_command,
    build_grok_headless_command,
    build_opencode_run_command,
    normalize_headless_events,
    prepare_opencode_env,
    write_headless_final_output,
)
from starbench.runner.run_benchmark import opencode_model_name
from starbench.runner.trace import read_jsonl, summarize_events


class RuntimeCommandHelperTests(unittest.TestCase):
    def test_opencode_helpers_build_config_and_extract_export_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            command = build_opencode_run_command(
                "opencode",
                cwd=tmp_path,
                model="yunwu/doubao-seed-2-0-pro-260215",
            )
            self.assertEqual(command[:2], ["opencode", "run"])
            self.assertIn("--dangerously-skip-permissions", command)
            self.assertEqual(opencode_model_name("doubao-seed-2-0-pro-260215", "yunwu"), "yunwu/doubao-seed-2-0-pro-260215")
            self.assertEqual(opencode_model_name("yunwu/doubao-seed-2-0-pro-260215", "yunwu"), "yunwu/doubao-seed-2-0-pro-260215")

            env = prepare_opencode_env(
                tmp_path / "opencode-home",
                "env",
                provider="yunwu",
                base_url="https://yunwu.ai/v1",
                model="yunwu/doubao-seed-2-0-pro-260215",
                api_key_env="ANTHROPIC_AUTH_TOKEN",
            )
            config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
            provider = config["provider"]["yunwu"]
            self.assertEqual(provider["options"]["baseURL"], "https://yunwu.ai/v1")
            self.assertEqual(provider["options"]["apiKey"], "{env:ANTHROPIC_AUTH_TOKEN}")
            self.assertIn("doubao-seed-2-0-pro-260215", provider["models"])

            events_path = tmp_path / "events.jsonl"
            events_path.write_text(
                json.dumps({"type": "step_start", "sessionID": "ses_test"})
                + "\n"
                + json.dumps({"type": "text", "part": {"text": "{\"results\": []}"}})
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(_extract_opencode_session_id(events_path), "ses_test")
            self.assertEqual(_extract_opencode_text_from_events(events_path), "{\"results\": []}")
            export_text = _extract_opencode_text(
                {
                    "messages": [
                        {"info": {"role": "user"}, "parts": [{"type": "text", "text": "prompt"}]},
                        {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "{\"results\": []}"}]},
                    ]
                }
            )
            self.assertEqual(_extract_json_object(export_text), {"results": []})

    def test_grok_and_gemini_helpers_build_commands_and_normalize_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            grok_command = build_grok_headless_command(
                "grok",
                cwd=tmp_path,
                prompt="Write outputs.",
                model="grok-build-0.1",
            )
            self.assertIn("--no-auto-update", grok_command)
            self.assertIn("--always-approve", grok_command)
            self.assertEqual(grok_command[-2:], ["-p", "Write outputs."])

            gemini_command = build_gemini_headless_command(
                "gemini",
                model="gemini-2.5-pro",
                approval_mode="yolo",
            )
            self.assertEqual(gemini_command[:2], ["gemini", "--output-format"])
            self.assertIn("--yolo", gemini_command)
            self.assertIn("--skip-trust", gemini_command)
            self.assertEqual(gemini_command[-2:], ["-p", ""])
            self.assertIn("gemini-2.5-pro", gemini_command)

            stdout_path = tmp_path / "gemini.json"
            final_path = tmp_path / "final.md"
            stdout_path.write_text(
                json.dumps(
                    {
                        "response": "Created outputs/demo.",
                        "stats": {"models": {"gemini-2.5-pro": {"tokens": {"total": 42}}}},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            write_headless_final_output(stdout_path, final_path)
            self.assertEqual(final_path.read_text(encoding="utf-8"), "Created outputs/demo.")
            normalize_headless_events(stdout_path, provider="gemini")
            summary = summarize_events(read_jsonl(stdout_path))
            self.assertEqual(summary["agent_messages"][0]["text"], "Created outputs/demo.")
            self.assertEqual(summary["usage"]["models"]["gemini-2.5-pro"]["tokens"]["total"], 42)

    def test_opencode_compat_events_add_codex_style_trace_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            events_path = Path(tmp) / "events.jsonl"
            events_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "tool_use",
                                "part": {
                                    "tool": "bash",
                                    "callID": "call_1",
                                    "state": {
                                        "status": "completed",
                                        "input": {"command": "python3 -m demo"},
                                        "output": "ok\n",
                                        "metadata": {"exit": 0},
                                    },
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "text",
                                "part": {"id": "txt_1", "text": "done"},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            append_opencode_compat_events(events_path)
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            items = [event.get("item") for event in events if event.get("type") == "item.completed"]
            self.assertIn("command_execution", [item.get("type") for item in items])
            self.assertIn("agent_message", [item.get("type") for item in items])


if __name__ == "__main__":
    unittest.main()
