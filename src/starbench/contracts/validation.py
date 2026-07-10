"""Small JSON Schema validator for StarBench artifact contracts.

StarBench keeps the first public artifact schemas dependency-light so the
runner and GUI can share validation without introducing a new runtime package.
This module intentionally supports only the JSON Schema keywords used by the
versioned schemas under ``schemas/starbench``.
"""
from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Dict


ARTIFACT_SCHEMA_VERSION = 1
JUDGE_AGGREGATE_SCHEMA_VERSION = 2
SCHEMA_BASE = resources.files("starbench.contracts").joinpath("schemas")
# Backward-compatible public name for callers that enumerate the v1 inventory.
SCHEMA_ROOT = SCHEMA_BASE.joinpath("v1")


class ContractValidationError(ValueError):
    """Raised when a StarBench artifact fails its public contract schema."""


# Keywords this validator actually enforces. Anything outside this set (or the
# annotation set below) makes validation raise instead of silently passing:
# a schema author must not believe a constraint is active when it is ignored.
SUPPORTED_KEYWORDS = {
    "type",
    "enum",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "minItems",
    "minimum",
    "minLength",
    "maxLength",
    "pattern",
}

# Pure annotations: legal in schemas, never affect validation.
ANNOTATION_KEYWORDS = {
    "$schema",
    "$id",
    "$comment",
    "title",
    "description",
    "examples",
    "default",
    "deprecated",
}


def load_schema(name: str, *, version: int = ARTIFACT_SCHEMA_VERSION) -> Dict[str, Any]:
    resource = SCHEMA_BASE.joinpath(f"v{version}").joinpath(name)
    try:
        payload = resource.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Missing StarBench contract schema: {resource}") from error
    return json.loads(payload)


def validate_payload(
    schema_name: str,
    data: Any,
    *,
    path: str = "$",
    version: int = ARTIFACT_SCHEMA_VERSION,
) -> None:
    validate_json_schema(load_schema(schema_name, version=version), data, path=path)


def validate_json_schema(schema: Dict[str, Any], data: Any, *, path: str = "$") -> None:
    unsupported = {
        key
        for key in schema
        if key not in SUPPORTED_KEYWORDS
        and key not in ANNOTATION_KEYWORDS
        and not key.startswith("x-")
    }
    if unsupported:
        raise ContractValidationError(
            f"{path}: unsupported schema keyword(s): {sorted(unsupported)}"
        )

    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(data, expected_type):
        raise ContractValidationError(
            f"{path}: expected type {expected_type!r}, got {type(data).__name__}"
        )

    if "enum" in schema and data not in schema["enum"]:
        raise ContractValidationError(f"{path}: expected one of {schema['enum']!r}, got {data!r}")

    if isinstance(data, dict):
        _validate_object(schema, data, path=path)

    if isinstance(data, list):
        _validate_array(schema, data, path=path)

    if isinstance(data, (int, float)) and not isinstance(data, bool):
        minimum = schema.get("minimum")
        if minimum is not None and data < minimum:
            raise ContractValidationError(f"{path}: expected >= {minimum}, got {data!r}")

    pattern = schema.get("pattern")
    if pattern is not None and isinstance(data, str) and re.search(pattern, data) is None:
        raise ContractValidationError(f"{path}: {data!r} does not match {pattern!r}")

    if isinstance(data, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(data) < min_length:
            raise ContractValidationError(
                f"{path}: expected at least {min_length} character(s), got {len(data)}"
            )
        max_length = schema.get("maxLength")
        if max_length is not None and len(data) > max_length:
            raise ContractValidationError(
                f"{path}: expected at most {max_length} character(s), got {len(data)}"
            )


def _validate_object(schema: Dict[str, Any], data: Dict[str, Any], *, path: str) -> None:
    for key in schema.get("required", []):
        if key not in data:
            raise ContractValidationError(f"{path}: missing required key {key!r}")

    properties = schema.get("properties", {})
    for key, child_schema in properties.items():
        if key in data:
            validate_json_schema(child_schema, data[key], path=f"{path}.{key}")

    additional = schema.get("additionalProperties", True)
    if additional is False:
        extra = set(data) - set(properties)
        if extra:
            raise ContractValidationError(f"{path}: unexpected key(s): {sorted(extra)}")
    elif additional is not True:
        # Schema-valued additionalProperties is a real constraint this
        # validator does not implement; refuse rather than silently pass.
        raise ContractValidationError(
            f"{path}: unsupported additionalProperties form: {additional!r}"
        )


def _validate_array(schema: Dict[str, Any], data: list, *, path: str) -> None:
    min_items = schema.get("minItems")
    if min_items is not None and len(data) < min_items:
        raise ContractValidationError(f"{path}: expected at least {min_items} item(s)")

    item_schema = schema.get("items")
    if item_schema is not None:
        if not isinstance(item_schema, dict):
            # Boolean/tuple `items` forms are not implemented; refuse rather
            # than silently pass.
            raise ContractValidationError(
                f"{path}: unsupported items form: {item_schema!r}"
            )
        for index, item in enumerate(data):
            validate_json_schema(item_schema, item, path=f"{path}[{index}]")


def _matches_type(data: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_matches_type(data, item) for item in expected_type)
    if expected_type == "object":
        return isinstance(data, dict)
    if expected_type == "array":
        return isinstance(data, list)
    if expected_type == "string":
        return isinstance(data, str)
    if expected_type == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    if expected_type == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    if expected_type == "boolean":
        return isinstance(data, bool)
    if expected_type == "null":
        return data is None
    raise ContractValidationError(f"unsupported JSON Schema type: {expected_type!r}")
