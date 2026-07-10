from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from starbench.gui import data
from starbench.gui.read_models import catalog as catalog_module
from starbench.gui.read_models import jsonl as jsonl_module
from starbench.gui.read_models.catalog import CATALOG_RELATIVE_PATH, RunCatalog
from starbench.gui.read_models import runs as run_views
from starbench.gui.read_models.jsonl import (
    read_json_objects_page,
    read_nonempty_lines_page,
)
from helpers import make_run, write_json


class RunCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_catalog_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.run_root = self.runs_dir / "run_a"
        self.run_root.mkdir()
        (self.run_root / "run_config.json").write_text(
            json.dumps({"executor_agent": "codex"}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_second_query_reuses_cached_read_model(self) -> None:
        calls = []

        def build(root: Path):
            calls.append(root.name)
            return {"run_id": root.name}

        catalog = RunCatalog(self.runs_dir)
        self.assertEqual(catalog.records(build)[0].value["run_id"], "run_a")
        self.assertEqual(catalog.records(build)[0].value["run_id"], "run_a")
        self.assertEqual(calls, ["run_a"])

    def test_artifact_change_invalidates_only_that_record(self) -> None:
        run_b = self.runs_dir / "run_b"
        run_b.mkdir()
        (run_b / "run_config.json").write_text("{}", encoding="utf-8")
        calls = []

        def build(root: Path):
            calls.append(root.name)
            return {"run_id": root.name}

        catalog = RunCatalog(self.runs_dir)
        catalog.records(build)
        calls.clear()
        (self.run_root / "run_config.json").write_text(
            json.dumps({"executor_agent": "claude", "changed": True}), encoding="utf-8"
        )

        catalog.records(build)

        self.assertEqual(calls, ["run_a"])

    def test_deleted_or_corrupt_catalog_rebuilds_from_artifacts(self) -> None:
        calls = []

        def build(root: Path):
            calls.append(root.name)
            return {"run_id": root.name}

        catalog = RunCatalog(self.runs_dir)
        catalog.records(build)
        catalog.discard()
        catalog.records(build)
        catalog.path.write_text("{broken", encoding="utf-8")
        catalog.records(build)

        self.assertEqual(calls, ["run_a", "run_a", "run_a"])
        self.assertTrue((self.runs_dir / CATALOG_RELATIVE_PATH).is_file())

    def test_concurrent_queries_build_once_and_publish_valid_json(self) -> None:
        calls = 0
        guard = threading.Lock()

        def build(root: Path):
            nonlocal calls
            with guard:
                calls += 1
            return {"run_id": root.name}

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda _index: RunCatalog(self.runs_dir).records(build), range(16))
            )

        self.assertTrue(all(rows[0].value["run_id"] == "run_a" for rows in results))
        self.assertEqual(calls, 1)
        payload = json.loads((self.runs_dir / CATALOG_RELATIVE_PATH).read_text(encoding="utf-8"))
        self.assertIn("run_a", payload["runs"])

    def test_read_only_catalog_path_degrades_to_uncached_response(self) -> None:
        with mock.patch.object(
            catalog_module, "_atomic_write_json", side_effect=PermissionError("read only")
        ):
            records = RunCatalog(self.runs_dir).records(
                lambda root: {"run_id": root.name}
            )

        self.assertEqual([record.value for record in records], [{"run_id": "run_a"}])


class JsonlOffsetIndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_jsonl_index_"))
        self.source = self.tmp / "events.jsonl"
        self.index_root = self.tmp / "indexes"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_json_object_paging_skips_malformed_rows(self) -> None:
        self.source.write_text(
            '{"id": 1}\nnot-json\n\n{"id": 2}\n{"id": 3}\n', encoding="utf-8"
        )

        page = read_json_objects_page(
            self.source, offset=1, limit=1, index_root=self.index_root
        )

        self.assertEqual(page.rows, [{"id": 2}])
        self.assertEqual(page.total, 3)
        self.assertEqual(len(list(self.index_root.glob("*.json"))), 1)

    def test_append_extends_existing_index_without_duplicate_offsets(self) -> None:
        self.source.write_text('{"id": 1}\n{"id": 2}\n', encoding="utf-8")
        first = read_json_objects_page(
            self.source, offset=0, limit=10, index_root=self.index_root
        )
        with self.source.open("a", encoding="utf-8") as handle:
            handle.write('{"id": 3}\n')

        second = read_json_objects_page(
            self.source, offset=1, limit=10, index_root=self.index_root
        )

        self.assertEqual(first.total, 2)
        self.assertEqual(second.total, 3)
        self.assertEqual(second.rows, [{"id": 2}, {"id": 3}])

    def test_truncated_source_resets_stale_offsets(self) -> None:
        self.source.write_text('{"id": 1}\n{"id": 2}\n', encoding="utf-8")
        read_json_objects_page(
            self.source, offset=0, limit=10, index_root=self.index_root
        )
        self.source.write_text('{"id": 9}\n', encoding="utf-8")

        page = read_json_objects_page(
            self.source, offset=0, limit=10, index_root=self.index_root
        )

        self.assertEqual(page.rows, [{"id": 9}])
        self.assertEqual(page.total, 1)

    def test_nonempty_line_index_keeps_unparseable_trace_lines(self) -> None:
        self.source.write_text(
            '{"timestamp":"2026-01-01T00:00:00+00:00"}\ninvalid\n\n',
            encoding="utf-8",
        )

        page = read_nonempty_lines_page(
            self.source, offset=0, limit=10, index_root=self.index_root
        )

        self.assertEqual(len(page.rows), 2)
        self.assertEqual(page.rows[1], "invalid")
        self.assertEqual(page.first_timestamp, "2026-01-01T00:00:00+00:00")

    def test_corrupt_index_is_rebuilt(self) -> None:
        self.source.write_text('{"id": 1}\n', encoding="utf-8")
        read_json_objects_page(self.source, offset=0, limit=1, index_root=self.index_root)
        index_path = next(self.index_root.glob("*.json"))
        index_path.write_text("{bad", encoding="utf-8")

        page = read_json_objects_page(
            self.source, offset=0, limit=1, index_root=self.index_root
        )

        self.assertEqual(page.rows, [{"id": 1}])
        json.loads(index_path.read_text(encoding="utf-8"))

    def test_read_only_index_path_degrades_to_direct_indexing(self) -> None:
        self.source.write_text('{"id": 1}\n{"id": 2}\n', encoding="utf-8")
        with mock.patch.object(
            jsonl_module, "_atomic_write_json", side_effect=PermissionError("read only")
        ):
            page = read_json_objects_page(
                self.source, offset=1, limit=1, index_root=self.index_root
            )

        self.assertEqual(page.rows, [{"id": 2}])
        self.assertEqual(page.total, 2)


class CatalogReadPathIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="starbench_catalog_paths_"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        make_run(self.runs_dir, "run_a")
        self.tasks_dir = self.tmp / "tasks"
        package = self.tasks_dir / "demo_task"
        package.mkdir(parents=True)
        write_json(package / "task.json", {"id": "demo_task", "name": "Demo"})
        write_json(package / "rubrics.json", {"rubrics": []})
        (package / "prompt.md").write_text("Demo\n", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_list_history_and_coverage_share_one_rendered_record(self) -> None:
        with mock.patch.object(
            run_views, "_catalog_run_record", wraps=run_views._catalog_run_record
        ) as build:
            self.assertEqual(len(data.list_runs(self.runs_dir)), 1)
            self.assertIn("demo_task", data.task_history(self.runs_dir)["tasks"])
            self.assertEqual(data.coverage(self.runs_dir, [self.tasks_dir])["runs_scanned"], 1)

        self.assertEqual(build.call_count, 1)


if __name__ == "__main__":
    unittest.main()
