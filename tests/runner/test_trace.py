"""Trace parsing: ``read_jsonl`` and ``summarize_events``."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from starbench.runner.trace import read_jsonl, summarize_events


class TraceParserTests(unittest.TestCase):
    def test_read_jsonl_does_not_split_on_unicode_line_separator_like_characters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            event = {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "aggregated_output": "before\u0084after",
                },
            }
            path.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
            self.assertEqual(read_jsonl(path), [event])

    def test_trace_summary_preserves_reasoning_commands_files_and_usage(self) -> None:
        events = [
            {"type": "thread.started", "thread_id": "thread_1"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {"type": "reasoning", "id": "r1", "text": "Reasoning summary."}},
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "id": "c1",
                    "command": "python -m stellar_measure",
                    "exit_code": 0,
                    "status": "completed",
                    "aggregated_output": "122.1 400.591",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "id": "f1",
                    "status": "completed",
                    "changes": [{"path": "outputs/stellar_measure/README.md"}],
                },
            },
            {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}},
        ]
        summary = summarize_events(events)
        self.assertEqual(summary["thread_id"], "thread_1")
        self.assertEqual(summary["reasoning_items"][0]["text"], "Reasoning summary.")
        self.assertEqual(summary["command_executions"][0]["aggregated_output"], "122.1 400.591")
        self.assertEqual(summary["file_changes"][0]["changes"][0]["path"], "outputs/stellar_measure/README.md")
        self.assertEqual(summary["usage"]["output_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
