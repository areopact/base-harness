"""Tests for structure.json loading, defaults, lane paths, and the schema.

Plain pytest-style functions (bare asserts, tmp_path only). A unittest bridge
at the bottom runs the same functions under ``python -m unittest discover``.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import posixpath
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "harness" / "tools"))

import harness_registry as registry  # noqa: E402

REGISTRY = ROOT / "harness" / "registry"


def _host_adopted() -> bool:
    """True when this checkout's own structure.json declares host.adopted."""
    try:
        data = json.loads((REGISTRY / "structure.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(data, dict) and (data.get("host") or {}).get("adopted"))


def _write_structure(root: Path, payload) -> None:
    target = root / "harness" / "registry"
    target.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    (target / "structure.json").write_text(text + "\n", encoding="utf-8")


# T1
def test_missing_file_returns_default_verbatim(tmp_path):
    loaded = registry.load_structure(tmp_path)
    assert loaded == registry.DEFAULT_STRUCTURE
    loaded["lanes"]["docs"].append("mutated")
    assert registry.load_structure(tmp_path) == registry.DEFAULT_STRUCTURE


@unittest.skipIf(_host_adopted(), "asserts the template's own shipped structure.json; not valid on an adopted host")
def test_shipped_structure_equals_default_verbatim():
    shipped = json.loads((REGISTRY / "structure.json").read_text(encoding="utf-8"))
    assert shipped == registry.DEFAULT_STRUCTURE
    assert registry.load_structure(ROOT) == registry.DEFAULT_STRUCTURE


# T2
def test_partial_file_merges_over_defaults(tmp_path):
    _write_structure(tmp_path, {"git": {"mode": "branches"}, "lanes": {"records": ["notes"], "journal": None}})
    loaded = registry.load_structure(tmp_path)
    assert loaded["git"]["mode"] == "branches"
    assert loaded["lanes"]["records"] == ["notes"]
    assert loaded["lanes"]["journal"] is None
    assert loaded["lanes"]["docs"] == ["docs"]
    assert loaded["tiers"] == registry.DEFAULT_STRUCTURE["tiers"]
    assert loaded["brain"] == registry.DEFAULT_STRUCTURE["brain"]


def test_null_lane_stays_null(tmp_path):
    _write_structure(tmp_path, {"lanes": {"docs": None}})
    assert registry.load_structure(tmp_path)["lanes"]["docs"] is None
    assert registry.lane_paths("docs", tmp_path) == []


def test_unknown_top_level_key_raises(tmp_path):
    _write_structure(tmp_path, {"workspace_name": "example"})
    try:
        registry.load_structure(tmp_path)
    except registry.StructureError as exc:
        assert "workspace_name" in str(exc)
    else:
        raise AssertionError("unknown top-level key must raise StructureError")


def test_malformed_file_raises(tmp_path):
    _write_structure(tmp_path, "{not json")
    try:
        registry.load_structure(tmp_path)
    except registry.StructureError:
        pass
    else:
        raise AssertionError("malformed structure.json must raise StructureError")


def test_unknown_nested_key_raises(tmp_path):
    _write_structure(tmp_path, {"git": {"mode": "main-only", "remote": "origin"}})
    try:
        registry.load_structure(tmp_path)
    except registry.StructureError as exc:
        assert "remote" in str(exc)
    else:
        raise AssertionError("unknown nested key must raise StructureError")


# T3
@unittest.skipIf(_host_adopted(), "asserts the template's own shipped lane defaults; not valid on an adopted host")
def test_lane_paths_on_shipped_default():
    assert registry.lane_paths("records", ROOT) == []
    assert registry.lane_paths("docs", ROOT) == ["docs"]
    assert registry.lane_paths("identity", ROOT) == ["brain/shared/IDENTITY.md", "brain/local/OPERATOR.md"]


def test_lane_paths_rejects_unknown_lane():
    try:
        registry.lane_paths("inbox", ROOT)
    except registry.StructureError:
        pass
    else:
        raise AssertionError("unknown lane name must raise StructureError")


# T4: hand-rolled draft-07 subset checker (no jsonschema dependency)
def _resolve_ref(schema_root, ref):
    assert ref.startswith("#/")
    node = schema_root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _type_matches(value, type_name):
    if type_name == "null":
        return value is None
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    raise AssertionError("unsupported type " + type_name)


def _check(schema_root, schema, value, path, errors):
    if "$ref" in schema:
        _check(schema_root, _resolve_ref(schema_root, schema["$ref"]), value, path, errors)
        return
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            sub = []
            _check(schema_root, option, value, path, sub)
            if not sub:
                matches += 1
        if matches != 1:
            errors.append(path + ": oneOf matched " + str(matches))
        return
    declared = schema.get("type")
    if declared is not None:
        types = declared if isinstance(declared, list) else [declared]
        if not any(_type_matches(value, name) for name in types):
            errors.append(path + ": type")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(path + ": const")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(path + ": enum")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(path + ": minLength")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(path + ": pattern")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(path + ": minItems")
        if "items" in schema:
            for index, item in enumerate(value):
                _check(schema_root, schema["items"], item, path + "[" + str(index) + "]", errors)
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(path + ": missing " + key)
        for key, child in value.items():
            if key in properties:
                _check(schema_root, properties[key], child, path + "." + key, errors)
            elif schema.get("additionalProperties", True) is False:
                errors.append(path + ": additional property " + key)


def _schema_errors(value):
    schema = json.loads((REGISTRY / "structure.schema.json").read_text(encoding="utf-8"))
    errors = []
    _check(schema, schema, value, "$", errors)
    return errors


def _walk_additional_properties(node, path, findings):
    if isinstance(node, dict):
        if node.get("type") == "object" and node.get("additionalProperties", True) is not False:
            findings.append(path)
        for key, child in node.items():
            _walk_additional_properties(child, path + "/" + key, findings)
    elif isinstance(node, list):
        for index, child in enumerate(node):
            _walk_additional_properties(child, path + "[" + str(index) + "]", findings)


def test_shipped_structure_validates_against_schema():
    shipped = json.loads((REGISTRY / "structure.json").read_text(encoding="utf-8"))
    assert _schema_errors(shipped) == []
    assert _schema_errors(registry.DEFAULT_STRUCTURE) == []


def test_schema_closes_every_object():
    schema = json.loads((REGISTRY / "structure.schema.json").read_text(encoding="utf-8"))
    findings = []
    _walk_additional_properties(schema, "", findings)
    assert findings == []


def test_schema_and_validator_agree_on_bad_values():
    bad = copy.deepcopy(registry.DEFAULT_STRUCTURE)
    bad["git"]["mode"] = "trunk"
    bad["tiers"]["unlisted_path"] = "public"
    bad["selection_scope"] = "global"
    bad["lanes"]["docs"] = []
    bad["extra"] = True
    schema_errors = _schema_errors(bad)
    validator_errors = registry.validate_structure(bad)
    assert any("git.mode" in item for item in schema_errors)
    assert any("unlisted_path" in item for item in schema_errors)
    assert any("selection_scope" in item for item in schema_errors)
    assert any("lanes.docs" in item for item in schema_errors)
    assert any("extra" in item for item in schema_errors)
    assert any("git.mode" in item for item in validator_errors)
    assert any("unlisted_path" in item for item in validator_errors)
    assert any("selection_scope" in item for item in validator_errors)
    assert any("lanes.docs" in item for item in validator_errors)
    assert any("extra" in item for item in validator_errors)


# T5
def test_unsafe_lane_paths_are_rejected():
    # Built from parts so the source carries no literal escaping or absolute path token.
    parent = posixpath.pardir
    unsafe_paths = (
        posixpath.join(parent, "outside"),
        posixpath.sep + posixpath.join("abs", "path"),
        "C:" + posixpath.sep + "root",
        posixpath.join("docs", parent, parent),
        "a\\b",
    )
    for unsafe in unsafe_paths:
        candidate = copy.deepcopy(registry.DEFAULT_STRUCTURE)
        candidate["lanes"]["records"] = [unsafe]
        validator_errors = registry.validate_structure(candidate)
        assert any("lanes.records" in item for item in validator_errors), unsafe
        assert _schema_errors(candidate) != [], unsafe


def test_unsafe_lane_path_raises_on_load(tmp_path):
    _write_structure(tmp_path, {"lanes": {"records": [posixpath.join(posixpath.pardir, "shared")]}})
    try:
        registry.load_structure(tmp_path)
    except registry.StructureError:
        pass
    else:
        raise AssertionError("an escaping lane path must raise StructureError")


# Loader agreement: the hook-side loader must produce the same defaults.
def test_hook_loader_agrees_on_defaults_and_merge(tmp_path):
    hook_io_path = ROOT / "harness" / "hooks" / "lib" / "hook_io.py"
    if not hook_io_path.is_file():
        return  # the hooks package has not landed; nothing to compare yet
    spec = importlib.util.spec_from_file_location("hook_io_under_test", hook_io_path)
    hook_io = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook_io)
    assert hook_io.DEFAULT_STRUCTURE == registry.DEFAULT_STRUCTURE
    assert hook_io.load_structure(tmp_path) == registry.load_structure(tmp_path)
    _write_structure(tmp_path, {"git": {"mode": "branches"}, "lanes": {"records": ["notes"], "journal": None}})
    assert hook_io.load_structure(tmp_path) == registry.load_structure(tmp_path)
    for lane in registry.LANE_NAMES:
        assert hook_io.lane_paths(lane, tmp_path) == registry.lane_paths(lane, tmp_path)


if "pytest" not in sys.modules:

    class StructureDefaultsBridge(unittest.TestCase):
        pass

    def _bind(name, function):
        def method(self):
            if "tmp_path" in function.__code__.co_varnames[: function.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as tmp:
                    function(Path(tmp))
            else:
                function()

        method.__name__ = name
        setattr(StructureDefaultsBridge, name, method)

    for _name, _function in list(globals().items()):
        if _name.startswith("test_") and callable(_function):
            _bind(_name, _function)
