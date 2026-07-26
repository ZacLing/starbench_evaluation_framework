"""Tests for pi event-stream normalization and final extraction."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.execution.parsers import normalize_pi_events, write_pi_final_output


def _write_events(path: Path, events: list) -> None:
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def _pi_events(final_text: str = "All done.") -> list:
    return [
        {"type": "session", "version": 3, "id": "s1", "timestamp": "t", "cwd": "/w"},
        {"type": "agent_start"},
        {"type": "turn_start"},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "plan it"},
                    {"type": "text", "text": "working"},
                ],
            },
        },
        {
            "type": "tool_execution_end",
            "toolCallId": "t1",
            "toolName": "bash",
            # AgentToolResult (pi packages/agent/src/types.ts:355)
            "result": {"content": [{"type": "text", "text": "ok"}], "details": {}},
            "isError": False,
        },
        {
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": final_text}]},
        },
        {"type": "agent_end", "messages": []},
    ]


class PiFinalOutputTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.events = self.dir / "events.jsonl"
        self.final = self.dir / "final.md"

    def test_final_takes_last_assistant_message_end(self):
        _write_events(self.events, _pi_events("Final answer."))
        write_pi_final_output(self.events, self.final)
        self.assertEqual(self.final.read_text(encoding="utf-8"), "Final answer.")

    def test_final_falls_back_to_agent_end_messages(self):
        events = [
            {"type": "session", "version": 3, "id": "s1", "timestamp": "t", "cwd": "/w"},
            {
                "type": "agent_end",
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "task"}]},
                    {"role": "assistant", "content": [{"type": "text", "text": "from tail"}]},
                ],
            },
        ]
        _write_events(self.events, events)
        write_pi_final_output(self.events, self.final)
        self.assertEqual(self.final.read_text(encoding="utf-8"), "from tail")

    def test_no_assistant_message_raises(self):
        _write_events(self.events, [{"type": "session"}, {"type": "agent_end", "messages": []}])
        with self.assertRaises(ValueError):
            write_pi_final_output(self.events, self.final)

    def test_final_excludes_thinking_blocks(self):
        events = _pi_events("unused")
        events[-2] = {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "secret chain of thought"},
                    {"type": "text", "text": "Graded answer."},
                ],
            },
        }
        _write_events(self.events, events)
        write_pi_final_output(self.events, self.final)
        final_text = self.final.read_text(encoding="utf-8")
        self.assertEqual(final_text, "Graded answer.")
        self.assertNotIn("secret chain of thought", final_text)

    def test_schema_mode_extracts_json_object(self):
        _write_events(self.events, _pi_events('Result: {"verdict": "pass"} trailing'))
        schema = self.dir / "schema.json"
        schema.write_text("{}", encoding="utf-8")
        write_pi_final_output(self.events, self.final, output_schema=schema)
        self.assertEqual(json.loads(self.final.read_text(encoding="utf-8")), {"verdict": "pass"})


class PiNormalizeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.events = self.dir / "events.jsonl"

    def _normalized(self):
        return [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]

    def test_appends_compat_items_after_raw_events(self):
        _write_events(self.events, _pi_events("done"))
        normalize_pi_events(self.events)
        events = self._normalized()
        types = [e.get("type") for e in events]
        # 原始事件保留在前：最后一条原始 message_end 早于第一条 compat item
        self.assertIn("message_end", types)
        self.assertIn("item.completed", types)
        last_raw = len(types) - 1 - types[::-1].index("message_end")
        first_compat = types.index("item.completed")
        self.assertLess(last_raw, first_compat)
        items = [e["item"] for e in events if e.get("type") == "item.completed"]
        item_types = [i["type"] for i in items]
        self.assertIn("reasoning", item_types)
        self.assertIn("agent_message", item_types)
        self.assertIn("command_execution", item_types)
        self.assertEqual(types[-1], "turn.completed")

    def test_command_execution_item_matches_compat_shape(self):
        _write_events(self.events, _pi_events("done"))
        normalize_pi_events(self.events)
        items = [
            e["item"]
            for e in self._normalized()
            if e.get("type") == "item.completed" and e["item"].get("type") == "command_execution"
        ]
        self.assertEqual(len(items), 1)
        self.assertEqual(
            items[0],
            {
                "type": "command_execution",
                "id": "t1",
                "command": "bash",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": "ok",
            },
        )

    def test_command_execution_output_is_none_without_text_blocks(self):
        for result in ({"content": [], "details": {"exit": 0}}, {"details": {}}, None, "raw"):
            with self.subTest(result=result):
                events = _pi_events("done")
                events[4] = {
                    "type": "tool_execution_end",
                    "toolCallId": "t3",
                    "toolName": "bash",
                    "result": result,
                    "isError": False,
                }
                _write_events(self.events, events)
                normalize_pi_events(self.events)
                item = next(
                    e["item"]
                    for e in self._normalized()
                    if e.get("type") == "item.completed" and e["item"].get("type") == "command_execution"
                )
                self.assertIsNone(item["aggregated_output"])

    def test_command_execution_joins_multiple_text_blocks(self):
        events = _pi_events("done")
        events[4] = {
            "type": "tool_execution_end",
            "toolCallId": "t4",
            "toolName": "bash",
            "result": {
                "content": [
                    {"type": "text", "text": "line one"},
                    {"type": "image", "data": "…"},
                    {"type": "text", "text": "line two"},
                ],
                "details": {},
            },
            "isError": False,
        }
        _write_events(self.events, events)
        normalize_pi_events(self.events)
        item = next(
            e["item"]
            for e in self._normalized()
            if e.get("type") == "item.completed" and e["item"].get("type") == "command_execution"
        )
        self.assertEqual(item["aggregated_output"], "line one\nline two")

    def test_command_execution_marks_tool_errors(self):
        events = _pi_events("done")
        events[4] = {
            "type": "tool_execution_end",
            "toolCallId": "t2",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "boom"}], "details": {}},
            "isError": True,
        }
        _write_events(self.events, events)
        normalize_pi_events(self.events)
        item = next(
            e["item"]
            for e in self._normalized()
            if e.get("type") == "item.completed" and e["item"].get("type") == "command_execution"
        )
        self.assertEqual(item["status"], "failed")
        self.assertEqual(item["exit_code"], 1)

    def test_normalize_is_idempotent(self):
        _write_events(self.events, _pi_events("done"))
        normalize_pi_events(self.events)
        once = self.events.read_text(encoding="utf-8")
        normalize_pi_events(self.events)
        self.assertEqual(self.events.read_text(encoding="utf-8"), once)


if __name__ == "__main__":
    unittest.main()
