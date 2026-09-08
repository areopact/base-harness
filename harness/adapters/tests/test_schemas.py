"""P5-2: each adapter's source config satisfies its own schema.json.

A hand-rolled draft-07 subset validator (no jsonschema dependency) covers the
keywords the adapter schemas use: type, properties, required,
additionalProperties, propertyNames, items, minItems, enum, const, pattern,
not, anyOf, allOf, and local $ref into definitions. A seeded "_comment" key and
an unknown top-level key must both fail.
"""

from __future__ import annotations

import copy
import re
import unittest

try:
    import tomllib
except ImportError:  # Python 3.10: TOML parsing unavailable in the stdlib
    tomllib = None  # type: ignore[assignment]

from ._paths import ADAPTERS, bind_unittest, read_json, read_text

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _resolve_ref(ref: str, root_schema: dict) -> dict:
    assert ref.startswith("#/"), f"only local refs are supported: {ref}"
    node = root_schema
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(instance, schema: dict, root_schema: dict | None = None, path: str = "$") -> list[str]:
    """Return a list of error strings; empty means valid."""
    root_schema = root_schema if root_schema is not None else schema
    if "$ref" in schema:
        return validate(instance, _resolve_ref(schema["$ref"], root_schema), root_schema, path)
    errors: list[str] = []

    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(TYPE_CHECKS[t](instance) for t in types):
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
    if "anyOf" in schema and all(validate(instance, s, root_schema, path) for s in schema["anyOf"]):
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


JSON_CASES = {
    "claude": (ADAPTERS / "claude" / "settings.base.json", ADAPTERS / "claude" / "schema.json", None),
    "codex": (ADAPTERS / "codex" / "hooks.json", ADAPTERS / "codex" / "schema.json", "hooks_json"),
    "opencode": (ADAPTERS / "opencode" / "opencode.json", ADAPTERS / "opencode" / "schema.json", None),
}


def _schema_for(runtime: str) -> dict:
    _, schema_path, key = JSON_CASES[runtime]
    schema = read_json(schema_path)
    return schema[key] if key else schema


def _find_object_with_key(node, key):
    """Depth-first search for the first dict carrying `key`; returns that dict."""
    if isinstance(node, dict):
        if key in node:
            return node
        for child in node.values():
            found = _find_object_with_key(child, key)
            if found is not None:
                return found
    if isinstance(node, list):
        for child in node:
            found = _find_object_with_key(child, key)
            if found is not None:
                return found
    return None


def test_each_source_config_validates_against_its_schema():
    for runtime, (config_path, _, _) in JSON_CASES.items():
        errors = validate(read_json(config_path), _schema_for(runtime))
        assert errors == [], f"{runtime}: {errors}"


def test_seeded_comment_key_fails_at_top_level():
    for runtime, (config_path, _, _) in JSON_CASES.items():
        seeded = copy.deepcopy(read_json(config_path))
        seeded["_comment"] = "seeded"
        assert validate(seeded, _schema_for(runtime)), f"{runtime}: _comment at top level was accepted"


def test_seeded_comment_key_fails_at_a_nested_level():
    # Seed into a nested hook entry (claude, codex) or the permission block (opencode).
    for runtime, (config_path, _, _) in JSON_CASES.items():
        seeded = copy.deepcopy(read_json(config_path))
        target = _find_object_with_key(seeded, "command") or _find_object_with_key(seeded, "read")
        assert target is not None, f"{runtime}: no nested object to seed"
        target["_comment"] = "seeded"
        assert validate(seeded, _schema_for(runtime)), f"{runtime}: nested _comment was accepted"


def test_unknown_top_level_key_fails():
    for runtime, (config_path, _, _) in JSON_CASES.items():
        seeded = copy.deepcopy(read_json(config_path))
        seeded["unexpectedKey"] = True
        assert validate(seeded, _schema_for(runtime)), f"{runtime}: unknown top-level key was accepted"


def test_claude_posture_regression_fails_schema_not_only_the_posture_test():
    schema = _schema_for("claude")
    base = read_json(ADAPTERS / "claude" / "settings.base.json")
    for key in ("defaultMode", "skipDangerousModePermissionPrompt", "autoMode", "dangerouslySkipPermissions"):
        seeded = copy.deepcopy(base)
        seeded[key] = "seeded"
        assert validate(seeded, schema), f"top-level {key} was accepted by the schema"
        seeded = copy.deepcopy(base)
        seeded["permissions"][key] = "seeded"
        assert validate(seeded, schema), f"permissions.{key} was accepted by the schema"
    seeded = copy.deepcopy(base)
    seeded["permissions"]["allow"].append("Bash(*)")
    assert validate(seeded, schema), "a wildcard Bash allow was accepted by the schema"


def test_validator_accepts_the_valid_shapes_it_rejects_when_broken():
    # Guard against a validator that rejects everything: a minimal valid claude file passes.
    minimal = {"permissions": {"allow": ["Read(*)"], "deny": []}, "hooks": {}}
    assert validate(minimal, _schema_for("claude")) == []


def _toml_paths(value, prefix=""):
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        yield path
        if isinstance(child, dict):
            yield from _toml_paths(child, path)


@unittest.skipIf(tomllib is None, "requires Python 3.11+ (tomllib is stdlib-only from 3.11)")
def test_codex_config_toml_keys_are_in_the_closed_allowed_list():
    schema = read_json(ADAPTERS / "codex" / "schema.json")
    allowed = set(schema["config_toml_allowed_keys"])
    forbidden = set(schema["config_toml_forbidden_keys"])
    assert allowed.isdisjoint(forbidden)
    data = tomllib.loads(read_text(ADAPTERS / "codex" / "config.toml"))
    paths = list(_toml_paths(data))
    unknown = [p for p in paths if p not in allowed]
    assert unknown == [], f"config.toml keys outside the allowed list: {unknown}"
    assert not any(p.split(".")[-1] in forbidden for p in paths)


@unittest.skipIf(tomllib is None, "requires Python 3.11+ (tomllib is stdlib-only from 3.11)")
def test_codex_config_toml_seeded_keys_fail_the_allowed_list():
    schema = read_json(ADAPTERS / "codex" / "schema.json")
    allowed = set(schema["config_toml_allowed_keys"])
    data = tomllib.loads(read_text(ADAPTERS / "codex" / "config.toml"))
    for key in ("_comment", "unexpected_key", "sandbox_mode"):
        seeded = copy.deepcopy(data)
        seeded[key] = "seeded"
        assert any(p not in allowed for p in _toml_paths(seeded)), f"{key} was accepted"


bind_unittest(globals(), "SchemasBridge")
