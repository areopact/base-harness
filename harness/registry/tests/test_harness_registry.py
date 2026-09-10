"""Tests for the registry validators, the junctions cross-check, and the CLI.

Plain pytest-style functions (bare asserts, tmp_path only). A unittest bridge
at the bottom runs the same functions under ``python -m unittest discover``.
"""

from __future__ import annotations

import copy
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "harness" / "tools"
REGISTRY = ROOT / "harness" / "registry"
sys.path.insert(0, str(TOOLS))

import harness_registry as registry  # noqa: E402

JSON_FILES = (
    REGISTRY / "structure.json",
    REGISTRY / "structure.schema.json",
    REGISTRY / "selection.json",
    REGISTRY / "runtimes.json",
    REGISTRY / "capabilities.json",
    REGISTRY / "sources.json",
    REGISTRY / "environment.json",
    ROOT / "harness" / "kernel-manifest.json",
)
TEXT_FILES = JSON_FILES + (
    REGISTRY / "collaborators.yaml",
    REGISTRY / "README.md",
    TOOLS / "harness_registry.py",
    Path(__file__),
    Path(__file__).with_name("test_structure_defaults.py"),
)


def _copy_tree(tmp_path: Path) -> Path:
    """Copy the shipped registry files into a scratch repository root."""
    target = tmp_path / "repo"
    (target / "harness" / "registry").mkdir(parents=True)
    for path in REGISTRY.iterdir():
        if path.is_file():
            shutil.copy(path, target / "harness" / "registry" / path.name)
    shutil.copy(ROOT / "harness" / "kernel-manifest.json", target / "harness" / "kernel-manifest.json")
    return target


def _load(name: str):
    return json.loads((REGISTRY / name).read_text(encoding="utf-8"))


def _host_adopted() -> bool:
    """True when this checkout's own structure.json declares host.adopted."""
    try:
        data = _load("structure.json")
    except (OSError, ValueError):
        return False
    return bool(isinstance(data, dict) and (data.get("host") or {}).get("adopted"))


def test_shipped_registries_validate():
    notes = []
    assert registry.validate_all(ROOT, notes) == []
    assert registry.validate_all.last_check_count >= 8


# T6
def test_environment_forbidden_keys_rejected_at_any_depth(tmp_path):
    base = _load("environment.json")
    assert registry.validate_environment(base) == []
    cases = {
        "top": {"digest": "abc"},
        "principal": {"principals": {"operator": {"kind": "operator", "value": "x"}}},
        "location_nested": {
            "principals": {"operator": {"kind": "operator"}},
            "locations": {
                "repo-env": {
                    "path_template": "repo:.env",
                    "owner_principal": "operator",
                    "consumers": ["operator"],
                    "sync_policy": "manual",
                    "sha256": "deadbeef",
                }
            },
        },
        "binding_deep": {
            "principals": {"operator": {"kind": "operator"}},
            "locations": {
                "repo-env": {
                    "path_template": "repo:.env",
                    "owner_principal": "operator",
                    "consumers": ["operator"],
                    "sync_policy": "manual",
                }
            },
            "bindings": {
                "EXAMPLE_TOKEN": {
                    "class": "secret",
                    "locations": ["repo-env"],
                    "sharing": "isolated",
                    "status": "live",
                    "present": True,
                }
            },
        },
    }
    for name, overlay in cases.items():
        doc = copy.deepcopy(base)
        doc.update(overlay)
        (tmp_path / (name + ".json")).write_text(json.dumps(doc), encoding="utf-8")
        reloaded = json.loads((tmp_path / (name + ".json")).read_text(encoding="utf-8"))
        errors = registry.validate_environment(reloaded)
        assert any("forbidden secret-state field" in item for item in errors), name


def test_environment_policy_block_is_exempt_from_the_walk_but_closed():
    doc = _load("environment.json")
    assert registry.validate_environment(doc) == []
    doc["policy"]["values"] = "allowed"
    assert any("policy.values" in item for item in registry.validate_environment(doc))
    doc = _load("environment.json")
    doc["policy"]["home"] = "anywhere"
    assert any("unknown fields" in item for item in registry.validate_environment(doc))


def test_environment_well_formed_binding_passes():
    doc = _load("environment.json")
    doc["principals"] = {"operator": {"kind": "operator"}}
    doc["locations"] = {
        "repo-env": {
            "path_template": "repo:.env",
            "owner_principal": "operator",
            "consumers": ["operator"],
            "sync_policy": "manual",
        }
    }
    doc["bindings"] = {"EXAMPLE_API_KEY": {"class": "secret", "locations": ["repo-env"], "sharing": "isolated", "status": "planned"}}
    assert registry.validate_environment(doc) == []
    doc["bindings"]["lowercase"] = doc["bindings"]["EXAMPLE_API_KEY"]
    assert any("lowercase" in item for item in registry.validate_environment(doc))
    # Built from parts so the source carries no literal user-directory path.
    doc["locations"]["repo-env"]["path_template"] = "home:" + posixpath.sep + posixpath.join("Users", "someone", "profile.cfg")
    assert any("absolute path" in item for item in registry.validate_environment(doc))


# T7
def test_runtimes_validate_and_implementations_match_pattern():
    runtimes = _load("runtimes.json")
    assert registry.validate_runtimes(runtimes, ROOT) == []
    pattern = re.compile(r"^(session-start|user-prompt-submit|pre-tool-use|post-tool-use|stop)/[a-z0-9-]+$")
    for event, spec in runtimes["hook_events"].items():
        for implementation in spec["implementations"]:
            assert pattern.fullmatch(implementation), implementation
        for runtime_id in ("claude", "codex", "opencode"):
            assert spec["runtimes"][runtime_id]["rung"] in registry.HOOK_RUNGS, (event, runtime_id)
    for runtime_id in ("claude", "codex", "opencode"):
        assert isinstance(runtimes["runtimes"][runtime_id]["identity_context_limit"], int)
    read_deny = runtimes["hook_events"]["PreToolUse"]["runtimes"]
    assert read_deny["claude"]["implementation_support"]["pre-tool-use/read-deny"] == {"support": "native", "default_registered": False}
    assert read_deny["codex"]["implementation_support"]["pre-tool-use/read-deny"]["support"] == "unsupported"
    assert read_deny["opencode"]["implementation_support"]["pre-tool-use/read-deny"]["support"] == "unsupported"
    assert read_deny["claude"]["implementation_support"]["pre-tool-use/write-deny"] == {"support": "native", "default_registered": True}


def test_user_prompt_submit_has_no_implementations_and_no_native_hook_rung():
    # Nothing registers UserPromptSubmit on any of the three runtimes today
    # (Claude ships no wrapper for it, Codex ran a no-op dispatcher); a
    # native-hook rung with an empty implementations list claims live
    # enforcement the repository does not have.
    runtimes = _load("runtimes.json")
    spec = runtimes["hook_events"]["UserPromptSubmit"]
    assert spec["implementations"] == []
    for runtime_id in ("claude", "codex", "opencode"):
        assert spec["runtimes"][runtime_id]["rung"] == "contract-text", runtime_id


def test_runtimes_closed_vocabularies():
    runtimes = _load("runtimes.json")
    doc = copy.deepcopy(runtimes)
    doc["hook_events"]["Stop"]["runtimes"]["codex"]["rung"] = "hope"
    assert any("rung" in item for item in registry.validate_runtimes(doc, ROOT))
    doc = copy.deepcopy(runtimes)
    doc["runtimes"]["claude"]["materializations"][0]["mode"] = "contract-copy"
    assert any("invalid mode" in item for item in registry.validate_runtimes(doc, ROOT))
    doc = copy.deepcopy(runtimes)
    doc["runtimes"]["codex"]["doctor"] = "harness/bootstrap/doctor_codex.py"
    assert any("doctor must be" in item for item in registry.validate_runtimes(doc, ROOT))
    doc = copy.deepcopy(runtimes)
    doc["runtimes"]["codex"]["materializations"].append({"source": "harness/CONTRACT.md", "destination": ".codex/AGENTS.md", "mode": "contract-render"})
    doc["runtimes"]["claude"]["materializations"].append({"source": "harness/CONTRACT.md", "destination": ".codex/AGENTS.md", "mode": "contract-render"})
    errors = registry.validate_runtimes(doc, ROOT)
    assert any("outside the claude runtime surface" in item for item in errors)
    doc = copy.deepcopy(runtimes)
    doc["hook_events"]["PreToolUse"]["implementations"].append("stop/read-deny")
    assert any("another event directory" in item for item in registry.validate_runtimes(doc, ROOT))
    doc = copy.deepcopy(runtimes)
    doc["runtimes"]["opencode"]["identity_context_limit"] = None
    assert any("identity_context_limit" in item for item in registry.validate_runtimes(doc, ROOT))


def test_shared_root_contract_is_the_only_shared_destination():
    runtimes = _load("runtimes.json")
    doc = copy.deepcopy(runtimes)
    doc["runtimes"]["opencode"]["materializations"].append({"source": "harness/adapters/opencode/opencode.json", "destination": ".opencode/skills", "mode": "managed-copy"})
    assert any("already owned" in item for item in registry.validate_runtimes(doc, ROOT))
    assert registry.validate_runtimes(runtimes, ROOT) == []


# T8
def test_capabilities_and_sources_validate():
    capabilities = _load("capabilities.json")
    sources = _load("sources.json")
    assert registry.validate_capabilities(capabilities) == []
    assert registry.validate_sources(sources) == []
    doc = copy.deepcopy(capabilities)
    doc["capabilities"]["web-search"]["runtimes"]["claude"] = "maybe"
    assert any("invalid state 'maybe'" in item for item in registry.validate_capabilities(doc))
    doc = copy.deepcopy(capabilities)
    doc["capabilities"]["web-search"]["probe"] = {"type": "command", "value": "/usr/bin/curl"}
    assert any("bare executable name" in item for item in registry.validate_capabilities(doc))
    doc = copy.deepcopy(sources)
    doc["sources"]["base-harness-internal"]["license"] = "GPL-3.0"
    assert any("invalid license" in item for item in registry.validate_sources(doc))
    doc = copy.deepcopy(sources)
    doc["sources"]["base-harness-internal"]["assets"] = [posixpath.join(posixpath.pardir, "outside")]
    assert any("unsafe asset path" in item for item in registry.validate_sources(doc))


@unittest.skipIf(_host_adopted(), "asserts the template's own shipped selection.json; not valid on an adopted host")
def test_shipped_selection_packs():
    selection = _load("selection.json")
    assert selection["packs"] == ["core", "maintain"]


def test_selection_validates_and_rejects_overlap():
    selection = _load("selection.json")
    assert registry.validate_selection(selection) == []
    doc = copy.deepcopy(selection)
    doc["include"] = ["doctor"]
    doc["exclude"] = ["doctor"]
    assert any("both name doctor" in item for item in registry.validate_selection(doc))
    doc = copy.deepcopy(selection)
    doc["packs"] = ["Core"]
    assert any("invalid slug" in item for item in registry.validate_selection(doc))


# T9
def test_kernel_manifest_shape():
    manifest = registry.load_kernel_manifest(ROOT)
    assert registry.validate_kernel_manifest(manifest) == []
    assert manifest["version"] == "0.1.1"
    paths = [item["path"] for item in manifest["files"]]
    assert len(paths) == len(set(paths))
    for item in manifest["files"]:
        assert item["state"] in {"ported", "new"}
        assert (item["source"] is not None) == (item["state"] == "ported"), item["path"]
        assert not item["path"].startswith("/") and ".." not in item["path"].split("/")
    assert "harness/tools/harness_registry.py" in paths
    assert "harness/registry/structure.json" in paths
    doc = copy.deepcopy(manifest)
    doc["files"].append({"path": "harness/tools/harness_registry.py", "state": "new", "source": "x"})
    errors = registry.validate_kernel_manifest(doc)
    assert any("duplicate path" in item for item in errors)
    assert any("null source" in item for item in errors)
    doc = copy.deepcopy(manifest)
    doc["files"].append({"path": "harness/tools/other.py", "state": "adopted", "source": None})
    assert any("ported or new" in item for item in registry.validate_kernel_manifest(doc))
    doc = copy.deepcopy(manifest)
    doc["files"].append({"path": "harness/tools/other.py", "state": "ported", "source": None})
    assert any("names its source" in item for item in registry.validate_kernel_manifest(doc))


# T10
def test_materialization_manifest_absent_returns_empty_with_note(tmp_path):
    repo = _copy_tree(tmp_path)
    notes = []
    assert registry.validate_materialization_manifest(_load("runtimes.json"), repo, notes) == []
    assert len(notes) == 1
    assert "junctions.json absent" in notes[0]


def _junctions_from_runtimes(runtimes):
    rows = []
    seen = set()
    for runtime_id, runtime in runtimes["runtimes"].items():
        for item in runtime["materializations"]:
            key = (item["source"], item["destination"], item["mode"])
            if key in seen:
                continue
            seen.add(key)
            rows.append({"src": key[0], "dst": key[1], "mode": key[2], "runtime": runtime_id, "description": "seeded"})
    retired = [
        {"dst": item["destination"], "replacement": item["replacement"], "description": "seeded"}
        for item in runtimes["retired_materializations"]
    ]
    return {"schema_version": 1, "junctions": rows, "retired_destinations": retired}


def test_materialization_manifest_parity_and_mismatch(tmp_path):
    repo = _copy_tree(tmp_path)
    runtimes = _load("runtimes.json")
    bootstrap = repo / "harness" / "bootstrap"
    bootstrap.mkdir()
    good = _junctions_from_runtimes(runtimes)
    (bootstrap / "junctions.json").write_text(json.dumps(good, indent=2) + "\n", encoding="utf-8")
    notes = []
    assert registry.validate_materialization_manifest(runtimes, repo, notes) == []
    assert notes == []
    bad = copy.deepcopy(good)
    bad["junctions"][0]["dst"] = ".claude/settings.local.json"
    (bootstrap / "junctions.json").write_text(json.dumps(bad, indent=2) + "\n", encoding="utf-8")
    errors = registry.validate_materialization_manifest(runtimes, repo)
    assert any("missing from junctions.json" in item for item in errors)
    assert any("undeclared junction" in item for item in errors)
    worse = copy.deepcopy(good)
    worse["junctions"][0]["mode"] = "contract-copy"
    (bootstrap / "junctions.json").write_text(json.dumps(worse, indent=2) + "\n", encoding="utf-8")
    assert any("mode must be one of" in item for item in registry.validate_materialization_manifest(runtimes, repo))


# T11
def _run_cli(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOLS / "harness_registry.py"), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_zero_on_shipped_tree():
    result = _run_cli(ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^registries OK \(\d+ checks\)$", result.stdout, re.MULTILINE)


def test_cli_exit_one_on_corrupt_copy(tmp_path):
    repo = _copy_tree(tmp_path)
    target = repo / "harness" / "registry" / "runtimes.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["runtimes"]["codex"]["status"] = "shipping"
    target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    result = _run_cli(repo)
    assert result.returncode == 1
    assert "ERROR runtimes.codex: invalid status 'shipping'" in result.stdout
    (repo / "harness" / "registry" / "capabilities.json").write_text("{", encoding="utf-8")
    result = _run_cli(repo)
    assert result.returncode == 1
    assert "cannot load capabilities.json" in result.stdout


def _full_tracked_copy(tmp_path: Path) -> Path:
    """A scratch checkout of every git-tracked file, so validate_all can pass."""
    target = tmp_path / "repo"
    archive = tmp_path / "repo.zip"
    subprocess.run(["git", "archive", "-o", str(archive), "HEAD"], cwd=str(ROOT), check=True)
    import zipfile

    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    return target


def test_cli_notes_host_profile_absent_on_disk_without_changing_exit_or_writing(tmp_path):
    repo = _full_tracked_copy(tmp_path)
    target = repo / "harness" / "registry" / "structure.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    del doc["host"]["profile"]
    before = json.dumps(doc, indent=2) + "\n"
    target.write_text(before, encoding="utf-8")

    result = _run_cli(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "note: host.profile absent in harness/registry/structure.json; defaulting to solo "
        "(set it with python harness/tools/init.py --profile)"
    ) in result.stdout
    assert target.read_text(encoding="utf-8") == before

    quiet = subprocess.run(
        [sys.executable, str(TOOLS / "harness_registry.py"), "--root", str(repo), "--quiet-notes"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert quiet.returncode == 0
    assert "host.profile absent" not in quiet.stdout


# Byte discipline
def test_json_files_round_trip_to_two_space_indent_with_trailing_newline():
    for path in JSON_FILES:
        raw = path.read_bytes()
        rendered = (json.dumps(json.loads(raw.decode("utf-8")), indent=2) + "\n").encode("utf-8")
        assert raw == rendered, path.name


def test_text_files_are_ascii_lf_without_dashes():
    for path in TEXT_FILES:
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), path.name + ": BOM"
        assert b"\r" not in raw, path.name + ": CR"
        text = raw.decode("utf-8")
        assert "\u2014" not in text and "\u2013" not in text, path.name + ": dash"
        assert all(ord(ch) < 128 for ch in text), path.name + ": non-ASCII"
        for number, line in enumerate(text.split("\n"), 1):
            assert line == line.rstrip(), path.name + ":" + str(number) + ": trailing whitespace"


def test_collaborators_registry_declares_empty_list():
    assert registry.validate_collaborators(ROOT) == []
    text = (REGISTRY / "collaborators.yaml").read_text(encoding="utf-8")
    assert re.search(r"^collaborators: \[\]$", text, re.MULTILINE)


if "pytest" not in sys.modules:

    class HarnessRegistryBridge(unittest.TestCase):
        pass

    def _bind(name, function):
        def method(self):
            if "tmp_path" in function.__code__.co_varnames[: function.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as tmp:
                    function(Path(tmp))
            else:
                function()

        method.__name__ = name
        setattr(HarnessRegistryBridge, name, method)

    for _name, _function in list(globals().items()):
        if _name.startswith("test_") and callable(_function):
            _bind(_name, _function)
