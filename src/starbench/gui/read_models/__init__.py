"""Read-model infrastructure for the filesystem-backed console."""

from .catalog import CatalogRecord, RunCatalog
from .jsonl import JsonlPage, read_json_objects_page, read_nonempty_lines_page

__all__ = [
    "CatalogRecord",
    "JsonlPage",
    "RunCatalog",
    "read_json_objects_page",
    "read_nonempty_lines_page",
]
