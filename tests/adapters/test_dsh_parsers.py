"""Tests for dsh session-log normalization and final extraction.

The fixture below is a real ``@deepseek-ai/dsh-session`` log shape: a
``SessionHeader`` first line (``type: 'session'``), then one ``SessionEvent``
per line with contiguous ``seq`` — which is what the adapter's
``compression: none`` + ``packChunks: false`` patch guarantees on disk.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from starbench.execution.parsers import (
    find_dsh_session_log,
    normalize_dsh_events,
    write_dsh_final_output,
)


def _session_log(root: Path, *, cwd: str = "--w-demo--", session: str = "session-1") -> Path:
    path = root / cwd / session / "session.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_lines(path: Path, events: list) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _dsh_events(final_text: str = "All done.") -> list:
    return [
        {"type": "session", "version": 0, "id": "session-1", "cwd": "/w", "createdAt": 1},
        {"type": "turn/start", "seq": 1, "time": 2, "data": {"turn": 0}},
        {
            "type": "assistant/message",
            "seq": 2,
            "time": 3,
            "data": {
                "turn": 0,
                "step": 0,
                "message": {
                    "id": "m1",
                    "role": "assistant",
                    "content": [
                        {"type": "reasoning", "text": "plan it"},
                        {"type": "text", "text": "working"},
                        {"type": "tool-call", "id": "call-1", "name": "bash", "arguments": "{}"},
                    ],
                    "source": {"kind": "model"},
                },
                "usage": {"inputTokens": 10, "outputTokens": 4, "cacheReadTokens": 2},
            },
        },
        {
            "type": "tool/call",
            "seq": 3,
            "time": 4,
            "data": {
                "turn": 0,
                "step": 0,
                "callId": "call-1",
                "name": "bash",
                "arguments": '{"command":"ls"}',
            },
        },
        {
            "type": "tool/result",
            "seq": 4,
            "time": 5,
            "data": {
                "turn": 0,
                "step": 0,
                "message": {
                    "id": "m2",
                    "role": "user",
                    "content": [
                        {
                            "type": "tool-result",
                            "toolCallId": "call-1",
                            "content": [{"type": "text", "text": "outputs\n"}],
                        }
                    ],
                    "source": {"kind": "tool"},
                },
            },
        },
        {
            "type": "assistant/message",
            "seq": 5,
            "time": 6,
            "data": {
                "turn": 0,
                "step": 1,
                "message": {
                    "id": "m3",
                    "role": "assistant",
                    "content": [{"type": "text", "text": final_text}],
                    "source": {"kind": "model"},
                },
                "usage": {"inputTokens": 20, "outputTokens": 6},
            },
        },
        {
            "type": "turn/end",
            "seq": 6,
            "time": 7,
            "data": {"turn": 0, "reason": {"kind": "completed"}},
        },
    ]


class DshFinalOutputTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.stdout = self.dir / "dsh_stdout.log"
        self.final = self.dir / "final.md"

    def test_plain_text_stdout_becomes_the_deliverable(self):
        # dsh prints the last non-empty assistant text plus a newline.
        self.stdout.write_text("Created outputs/demo and verified it.\n", encoding="utf-8")
        write_dsh_final_output(self.stdout, self.final)
        self.assertEqual(
            self.final.read_text(encoding="utf-8"), "Created outputs/demo and verified it."
        )

    def test_judge_schema_mode_extracts_json_from_the_text(self):
        verdict = {"mode": "single", "results": [], "overall_notes": "ok"}
        self.stdout.write_text(
            f"Here is the verdict:\n{json.dumps(verdict)}\n", encoding="utf-8"
        )
        write_dsh_final_output(self.stdout, self.final, output_schema=Path("schema.json"))
        self.assertEqual(json.loads(self.final.read_text(encoding="utf-8")), verdict)

    def test_empty_stdout_raises_so_the_run_is_downgraded(self):
        self.stdout.write_text("\n  \n", encoding="utf-8")
        with self.assertRaises(ValueError):
            write_dsh_final_output(self.stdout, self.final)

    def test_missing_stdout_raises(self):
        with self.assertRaises(ValueError):
            write_dsh_final_output(self.dir / "nope.log", self.final)


class DshSessionLogTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.root = self.dir / "dsh_sessions"
        self.events = self.dir / "events.jsonl"

    def _read_events(self) -> list:
        return [
            json.loads(line)
            for line in self.events.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_locates_the_transcript_under_the_project_session_directories(self):
        log = _session_log(self.root)
        _write_lines(log, _dsh_events())
        self.assertEqual(find_dsh_session_log(self.root), log)

    def test_absent_root_and_empty_root_yield_no_log(self):
        self.assertIsNone(find_dsh_session_log(self.root))
        self.root.mkdir(parents=True)
        self.assertIsNone(find_dsh_session_log(self.root))

    def test_raw_events_are_kept_and_compat_items_appended(self):
        _write_lines(_session_log(self.root), _dsh_events("Final answer."))
        normalize_dsh_events(self.root, self.events)
        events = self._read_events()
        # The session log rides verbatim, header line first.
        self.assertEqual(events[0]["type"], "session")
        self.assertEqual([e["type"] for e in events[:7]][-1], "turn/end")
        items = [e["item"] for e in events if e.get("type") == "item.completed"]
        self.assertEqual(
            [(i["type"], i.get("text") or i.get("command")) for i in items],
            [
                ("reasoning", "plan it"),
                ("agent_message", "working"),
                ("command_execution", "bash"),
                ("agent_message", "Final answer."),
            ],
        )
        self.assertEqual(events[-1]["type"], "turn.completed")

    def test_tool_result_carries_its_output_and_success_status(self):
        _write_lines(_session_log(self.root), _dsh_events())
        normalize_dsh_events(self.root, self.events)
        command = next(
            e["item"]
            for e in self._read_events()
            if e.get("type") == "item.completed" and e["item"]["type"] == "command_execution"
        )
        self.assertEqual(command["id"], "call-1")
        self.assertEqual(command["status"], "completed")
        self.assertEqual(command["exit_code"], 0)
        self.assertEqual(command["aggregated_output"], "outputs\n")

    def test_tool_error_is_reported_as_a_failed_command(self):
        events = _dsh_events()
        events[4]["data"]["message"]["content"][0]["isError"] = True
        events[4]["data"]["error"] = {"name": "ToolError", "code": "EACCES"}
        _write_lines(_session_log(self.root), events)
        normalize_dsh_events(self.root, self.events)
        command = next(
            e["item"]
            for e in self._read_events()
            if e.get("type") == "item.completed" and e["item"]["type"] == "command_execution"
        )
        self.assertEqual(command["status"], "failed")
        self.assertEqual(command["exit_code"], 1)

    def test_usage_is_summed_across_steps_into_the_shared_key_names(self):
        _write_lines(_session_log(self.root), _dsh_events())
        normalize_dsh_events(self.root, self.events)
        usage = self._read_events()[-1]["usage"]
        self.assertEqual(
            usage, {"input_tokens": 30, "output_tokens": 10, "cache_read_tokens": 2}
        )

    def test_file_changes_stay_unmapped_until_a_real_smoke_run(self):
        # dsh's fs tools carry their diff in the tool-private `meta` payload;
        # nothing here guesses at that shape, so no file_change item exists.
        _write_lines(_session_log(self.root), _dsh_events())
        normalize_dsh_events(self.root, self.events)
        self.assertEqual(
            [
                e
                for e in self._read_events()
                if e.get("type") == "item.completed" and e["item"]["type"] == "file_change"
            ],
            [],
        )

    def test_normalization_is_idempotent(self):
        _write_lines(_session_log(self.root), _dsh_events())
        normalize_dsh_events(self.root, self.events)
        first = self.events.read_text(encoding="utf-8")
        normalize_dsh_events(self.root, self.events)
        self.assertEqual(self.events.read_text(encoding="utf-8"), first)

    def test_missing_session_log_leaves_the_trace_honestly_absent(self):
        normalize_dsh_events(self.root, self.events)
        self.assertFalse(self.events.exists())

    def test_newest_session_wins_when_a_root_holds_several(self):
        import os

        older = _session_log(self.root, session="session-old")
        _write_lines(older, _dsh_events("older"))
        os.utime(older, (1, 1))
        newer = _session_log(self.root, session="session-new")
        _write_lines(newer, _dsh_events("newer"))
        normalize_dsh_events(self.root, self.events)
        texts = [
            e["item"]["text"]
            for e in self._read_events()
            if e.get("type") == "item.completed" and e["item"]["type"] == "agent_message"
        ]
        self.assertIn("newer", texts)
        self.assertNotIn("older", texts)


if __name__ == "__main__":
    unittest.main()
