"""P5-4: the three model maps carry exactly the four family keys and ship every
family bound; a null provider id stays legal and is marked UNKNOWN by the loader,
never defaulted."""

from __future__ import annotations

import json

from ._paths import ADAPTERS, RUNTIMES, bind_unittest, read_json

import model_map

FAMILY_KEYS = {"fast", "balanced", "strong", "strong-main"}
PERMISSION_CLASSES = {"read-only", "edit", "shell"}


def test_each_map_carries_exactly_the_four_family_keys():
    for runtime in RUNTIMES:
        data = read_json(ADAPTERS / runtime / "model-map.json")
        assert data["schema_version"] == 1
        assert set(data["families"]) == FAMILY_KEYS, f"{runtime}: {sorted(data['families'])}"
        assert PERMISSION_CLASSES <= set(data["permission_classes"]), runtime
        for name in PERMISSION_CLASSES:
            assert isinstance(data["permission_classes"][name], list) and data["permission_classes"][name]


def test_loader_marks_null_ids_unknown_and_never_defaults():
    for runtime in RUNTIMES:
        loaded = model_map.load_model_map(runtime)
        for family, provider_id in loaded["families"].items():
            if provider_id is None:
                assert loaded["resolution"][family] == model_map.UNKNOWN, f"{runtime}:{family}"
                assert family in loaded["unresolved"]
            else:
                assert loaded["resolution"][family] == model_map.RESOLVED
                assert family not in loaded["unresolved"]
        # The loader hands back the null as written; no substitution happened.
        raw = read_json(ADAPTERS / runtime / "model-map.json")["families"]
        assert loaded["families"] == raw


def test_every_shipped_map_resolves_all_four_families():
    # A null id is legal, but the shipped template binds every family on every
    # runtime so native_routing.py renders a complete role set out of the box.
    for runtime in RUNTIMES:
        loaded = model_map.load_model_map(runtime)
        assert loaded["unresolved"] == [], f"{runtime} ships an unresolved family: {loaded['unresolved']}"
    claude = model_map.load_model_map("claude")
    assert set(claude["families"].values()) <= {"haiku", "sonnet", "opus"}
    opencode = model_map.load_model_map("opencode")
    for family, provider_id in opencode["families"].items():
        assert "/" in provider_id and not provider_id.startswith("/"), f"opencode {family} must be provider/model"


def test_loader_marks_a_null_id_unknown(tmp_path):
    target = tmp_path / "harness" / "adapters" / "codex"
    target.mkdir(parents=True)
    partial = {
        "schema_version": 1,
        "runtime": "codex",
        "families": {"fast": "a", "balanced": "b", "strong": None, "strong-main": None},
        "permission_classes": {"read-only": ["a"], "edit": ["a"], "shell": ["a"]},
    }
    (target / "model-map.json").write_text(json.dumps(partial), encoding="utf-8")
    loaded = model_map.load_model_map("codex", tmp_path)
    assert loaded["unresolved"] == ["strong", "strong-main"]
    assert loaded["resolution"]["strong"] == model_map.UNKNOWN
    assert loaded["families"]["strong"] is None
    states = {line[2].split(":")[0].replace("model family ", ""): line[1] for line in model_map.doctor_lines("codex", tmp_path)[1:]}
    assert states == {"fast": "OK", "balanced": "OK", "strong": "UNKNOWN", "strong-main": "UNKNOWN"}


def test_doctor_lines_print_unknown_for_unresolved_families():
    for runtime in RUNTIMES:
        lines = model_map.doctor_lines(runtime)
        assert lines[0][:2] == ("configured", "OK")
        states = {line[2].split(":")[0].replace("model family ", ""): line[1] for line in lines[1:]}
        loaded = model_map.load_model_map(runtime)
        for family in FAMILY_KEYS:
            expected = "UNKNOWN" if loaded["resolution"][family] == model_map.UNKNOWN else "OK"
            assert states[family] == expected, f"{runtime}:{family} printed {states[family]}"
        for layer, state, _ in lines:
            assert layer == "configured"
            assert state in {"OK", "WARN", "FAIL", "UNKNOWN"}


def test_loader_rejects_a_missing_or_extra_family(tmp_path):
    root = tmp_path
    target = root / "harness" / "adapters" / "claude"
    target.mkdir(parents=True)
    bad = {
        "schema_version": 1,
        "runtime": "claude",
        "families": {"fast": "haiku", "balanced": "sonnet", "strong": "opus"},
        "permission_classes": {"read-only": ["Read"], "edit": ["Edit"], "shell": ["Bash"]},
    }
    (target / "model-map.json").write_text(json.dumps(bad), encoding="utf-8")
    try:
        model_map.load_model_map("claude", root)
    except model_map.ModelMapError as exc:
        assert "exactly" in str(exc)
    else:
        raise AssertionError("a map missing strong-main was accepted")
    bad["families"]["strong-main"] = "opus"
    bad["families"]["persona"] = "opus"
    (target / "model-map.json").write_text(json.dumps(bad), encoding="utf-8")
    try:
        model_map.load_model_map("claude", root)
    except model_map.ModelMapError:
        pass
    else:
        raise AssertionError("a map with an extra family was accepted")


def test_loader_rejects_an_empty_string_id(tmp_path):
    target = tmp_path / "harness" / "adapters" / "codex"
    target.mkdir(parents=True)
    bad = {
        "schema_version": 1,
        "runtime": "codex",
        "families": {"fast": "", "balanced": None, "strong": None, "strong-main": None},
        "permission_classes": {"read-only": ["a"], "edit": ["a"], "shell": ["a"]},
    }
    (target / "model-map.json").write_text(json.dumps(bad), encoding="utf-8")
    try:
        model_map.load_model_map("codex", tmp_path)
    except model_map.ModelMapError:
        pass
    else:
        raise AssertionError("an empty-string id was accepted as resolved")


bind_unittest(globals(), "ModelMapsBridge")
