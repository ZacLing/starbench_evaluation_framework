"""Console HTTP route surface after the task-library collapse.

These bind an ephemeral loopback port (port 0) against a throwaway
``STARBENCH_HOME`` so no test ever reads or writes the operator's real home.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from starbench.gui.server import build_state, serve


class SingleLibraryRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp(prefix="starbench_routes_home_"))
        state = build_state(environ={"STARBENCH_HOME": str(self.home)})
        self.server, self.thread = serve(state, "127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        shutil.rmtree(self.home, ignore_errors=True)

    def _probe(self, path: str, body: object = None):
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read().decode("utf-8"))

    def test_history_tolerates_a_legacy_dir_query(self) -> None:
        # A stale frontend still sends ?dir=; history is global now, so the
        # query is accepted and ignored rather than answered with a 500.
        plain = self._probe("/api/tasklib/history")
        legacy = self._probe("/api/tasklib/history?dir=/nowhere/tasks")
        self.assertEqual(plain, (200, {"tasks": {}}))
        self.assertEqual(legacy, plain)

    def test_directory_browser_and_registration_routes_are_gone(self) -> None:
        status, _ = self._probe("/api/fs/list?path=/tmp")
        self.assertEqual(status, 404)
        status, _ = self._probe("/api/tasklib/dirs", {"dir": "/tmp"})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
