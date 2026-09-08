#!/usr/bin/env python3
"""Minimal JSON Schema (draft-07 subset) validator for generated runtime files.

Stdlib only. Covers the keywords the adapter schemas use: type, properties,
required, additionalProperties, propertyNames, items, minItems, enum, const,
pattern, not, anyOf, allOf, and local ``$ref`` into ``definitions``. Every
adapter schema closes its objects and rejects property names that start with
an underscore, so a seeded comment key fails here instead of being ignored by
a lenient runtime parser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class SchemaError(ValueError):
    """The schema itself is unusable (bad ref, unknown type)."""


def _resolve_ref(ref: str, root_schema: dict) -> dict:
    if not ref.startswith("#/"):
        raise SchemaError(f"only local refs are supported: {ref}")
    node: object = root_schema
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f"unresolved ref: {ref}")
        node = node[part]
    if not isinstance(node, dict):
        raise SchemaError(f"ref does not point at a schema object: {ref}")
    return node


def validate(instance: object, schema: dict, root_schema: dict | None = None, path: str = "$") -> list[str]:
    """Return error strings; an empty list means the instance is valid."""
    root_schema = root_schema if root_schema is not None else schema
    if "$ref" in schema:
        return validate(instance, _resolve_ref(schema["$ref"], root_schema), root_schema, path)
    errors: list[str] = []

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        for name in types:
            if name not in TYPE_CHECKS:
                raise SchemaError(f"unknown type {name!r} at {path}")
        if not any(TYPE_CHECKS[name](instance) for name in types):
            errors.append(f"{path}: expected type {types}")
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum")
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} != const {schema['const']!r}")
    if "pattern" in schema and isinstance(instance, str) and re.search(schema["pattern"], instance) is None:
        errors.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")
    if "not" in schema and not validate(instance, schema["not"], root_schema, path):
        errors.append(f"{path}: matches a forbidden 'not' schema")
    if "anyOf" in schema and all(validate(instance, sub, root_schema, path) for sub in schema["anyOf"]):
        errors.append(f"{path}: matches none of anyOf")
    if "allOf" in schema:
        for sub in schema["allOf"]:
            errors.extend(validate(instance, sub, root_schema, path))

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required {key!r}")
        if "propertyNames" in schema:
            for key in instance:
                if validate(key, schema["propertyNames"], root_schema, f"{path}.{key}"):
                    errors.append(f"{path}: property name {key!r} rejected")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate(value, properties[key], root_schema, f"{path}.{key}"))
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: additional property {key!r} not allowed")
                elif isinstance(extra, dict):
                    errors.extend(validate(value, extra, root_schema, f"{path}.{key}"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], root_schema, f"{path}[{index}]"))
    return errors


def underscore_keys(instance: object, path: str = "$") -> list[str]:
    """Return every object key starting with an underscore, at any depth."""
    found: list[str] = []
    if isinstance(instance, dict):
        for key, value in instance.items():
            child = f"{path}.{key}"
            if isinstance(key, str) and key.startswith("_"):
                found.append(child)
            found.extend(underscore_keys(value, child))
    elif isinstance(instance, list):
        for index, value in enumerate(instance):
            found.extend(underscore_keys(value, f"{path}[{index}]"))
    return found


def validate_file(path: Path, schema: dict) -> list[str]:
    """Load a JSON file and validate it; unreadable input is one error."""
    try:
        instance = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"{Path(path).as_posix()}: unreadable or invalid JSON ({exc})"]
    errors = validate(instance, schema)
    for key in underscore_keys(instance):
        message = f"{key}: underscore-prefixed key rejected"
        if message not in errors:
            errors.append(message)
    return errors
