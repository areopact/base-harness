"""lint: one seeded violation per check id, plus strict promotion and the CLI.

Each test builds a minimal repository under tmp_path, seeds exactly one
violation, and runs only the check under test through lint.run_checks so the
finding id is unambiguous. Soft checks (L6, L9, L11, L13, L14) must report
WARN without --strict and ERROR with it.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

from ._repo import ROOT, copy_files, install_bridge  # noqa: F401

import lint

# The two lane-token tests below need a structure.json with populated lanes
# to seed a plausible lane path; copy_files() would copy this checkout's own
# harness/registry/structure.json, which on an adopted host can carry unset
# lanes and breaks the seed. The template's fixed default always ships
# populated lanes (see harness/hooks/lib/hook_io.py's matching test-only use).
STRUCTURE_DEFAULT_SOURCE = ROOT / "harness" / "tools" / "templates" / "structure.default.json"


def _write_default_structure(repo: Path) -> None:
    destination = repo / "harness" / "registry" / "structure.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STRUCTURE_DEFAULT_SOURCE, destination)

REGISTRY_FILES = (
    "harness/registry/structure.json",
    "harness/registry/structure.schema.json",
    "harness/registry/selection.json",
    "harness/registry/runtimes.json",
    "harness/registry/capabilities.json",
    "harness/registry/sources.json",
    "harness/registry/environment.json",
    "harness/registry/collaborators.yaml",
    "harness/kernel-manifest.json",
)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _write(repo: Path, relative: str, content: str | bytes) -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _ids(findings, level=None):
    return [item.id for item in findings if level is None or item.level == level]


def _only(repo: Path, check_id: str, strict: bool = False, release: bool = False, all_scope: bool = False):
    return lint.run_checks(repo, strict=strict, only={check_id}, release=release, all_scope=all_scope)


def _skill(repo: Path, name: str, *, triggers: bool = True, license_value: str = "MIT", distribution: str = "native", requires: str = "") -> None:
    trigger_block = f'  triggers: ["run {name}"]\n' if triggers else ""
    requires_block = f"  requires: [{requires}]\n" if requires else ""
    _write(
        repo,
        f"harness/skills/{name}/SKILL.md",
        "---\n"
        f"name: {name}\n"
        f"description: Does {name}. WHEN: asked for {name}.\n"
        "metadata:\n"
        "  packs: [core]\n"
        f"{trigger_block}{requires_block}"
        f"  distribution: {distribution}\n"
        "  status: spec-only\n"
        f"  license: {license_value}\n"
        "---\n",
    )


# tracked_files fallback walker (no git) ---------------------------------------

def test_tracked_files_fallback_skips_node_modules_and_junction_destinations(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/bootstrap/junctions.json", json.dumps({"junctions": [
        {"src": "harness/adapters/opencode/plugins", "dst": ".opencode/plugins", "mode": "link"},
    ]}))
    _write(repo, "real.md", "kept\n")
    _write(repo, ".opencode/plugins/harness-bridge.js", "should be skipped\n")
    _write(repo, ".opencode/node_modules/pkg/index.js", "should be skipped\n")
    _write(repo, "node_modules" + "/pkg/index.js", "should be skipped\n")
    _write(repo, "__pycache__" + "/x.pyc", "should be skipped\n")

    def _no_git(*args, **kwargs):
        raise OSError("git unavailable in this test")

    # A plain reassignment (not the pytest-only monkeypatch fixture) so this
    # test also runs under python -m unittest discover via install_bridge.
    original_run = lint.subprocess.run
    lint.subprocess.run = _no_git
    try:
        names = lint.tracked_files(repo)
    finally:
        lint.subprocess.run = original_run
    assert "real.md" in names
    assert not any(name.startswith(".opencode/") for name in names)
    assert not any(name.startswith("node_modules/") for name in names)
    assert not any("__pycache__" in name for name in names)


# L1 --------------------------------------------------------------------------

def test_l1_contract_composition(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, ("harness/bootstrap/contract_files.py", "harness/CONTRACT.md", "harness/CONTRACT.host.md"))
    import importlib.util

    spec = importlib.util.spec_from_file_location("cf_under_test", repo / "harness/bootstrap/contract_files.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.repair_contract(repo)
    assert _ids(_only(repo, "L1"), "ERROR") == []
    _write(repo, "CLAUDE.md", "@AGENTS.md\n\n")
    findings = _only(repo, "L1")
    assert "L1" in _ids(findings, "ERROR")
    assert any("CLAUDE.md" in item.message for item in findings)
    _write(repo, "CLAUDE.md", "@AGENTS.md\n")
    _write(repo, ".codex/AGENTS.md", "copy\n")
    assert any(".codex/AGENTS.md" in item.message for item in _only(repo, "L1"))


# L2 --------------------------------------------------------------------------

def test_l2_byte_budget(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, ("harness/registry/runtimes.json",))
    _write_default_structure(repo)
    _write(repo, "AGENTS.md", "x" * (lint.CONTRACT_BUDGET + 1))
    findings = _only(repo, "L2")
    assert any(item.path == "AGENTS.md" and item.level == "ERROR" for item in findings), [item.render() for item in findings]
    _write(repo, "AGENTS.md", "small\n")
    structure = json.loads((repo / "harness/registry/structure.json").read_text(encoding="utf-8"))
    identity = structure["lanes"]["identity"][0]
    _write(repo, identity, "y" * 100000)
    findings = _only(repo, "L2")
    assert any(item.path == identity and item.level == "ERROR" for item in findings)
    _write(repo, identity, "short identity\n")
    assert _ids(_only(repo, "L2"), "ERROR") == []


# L3 --------------------------------------------------------------------------

def test_l3_em_dash_crlf_trailing_whitespace_and_tabs(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/dash.md", "A line with an em" + chr(0x2014) + "dash\n")
    _write(repo, "harness/rules/crlf.md", b"line one\r\nline two\r\n")
    _write(repo, "harness/rules/trailing.md", "ends with space \nclean\n")
    _write(repo, "harness/tools/tabbed.py", "def f():\n\treturn 1\n")
    _write(repo, "harness/rules/bom.md", b"\xef\xbb\xbfclean\n")
    _write(repo, "docs/clean.md", "clean file\n")
    findings = _only(repo, "L3")
    messages = {(item.path, item.message) for item in findings}
    assert ("harness/rules/dash.md", "em-dash") in messages
    assert any(path == "harness/rules/crlf.md" and "carriage return" in message for path, message in messages)
    assert ("harness/rules/trailing.md", "trailing whitespace") in messages
    assert ("harness/tools/tabbed.py", "tab-indented Python line") in messages
    assert ("harness/rules/bom.md", "byte-order mark") in messages
    assert not any(path == "docs/clean.md" for path, _ in messages)
    assert all(item.level == "ERROR" for item in findings)


# L4 --------------------------------------------------------------------------

def test_l4_skill_missing_triggers(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, ("harness/registry/capabilities.json",))
    _skill(repo, "alpha", triggers=False)
    findings = _only(repo, "L4")
    assert "L4" in _ids(findings, "ERROR")
    assert any("metadata.triggers" in item.message for item in findings)


def test_l4_pack_license_mix_and_runtime_provided_capability(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, ("harness/registry/capabilities.json",))
    _skill(repo, "alpha", license_value="MIT")
    _skill(repo, "beta", license_value="Apache-2.0")
    _skill(repo, "gamma", distribution="runtime-provided", requires='"no-such-capability"')
    findings = _only(repo, "L4")
    assert any("mixes licenses" in item.message for item in findings)
    assert any("unknown capability" in item.message for item in findings)


def test_l4_requires_is_validated_on_every_skill(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, ("harness/registry/capabilities.json",))
    _skill(repo, "alpha", requires='"lane:journal", "web-search"')
    assert _ids(_only(repo, "L4"), "ERROR") == []
    _skill(repo, "beta", requires='"lane:nowhere", "no-such-capability"')
    messages = [item.message for item in _only(repo, "L4") if item.level == "ERROR"]
    assert any("unknown lane 'lane:nowhere'" in message for message in messages), messages
    assert any("unknown capability 'no-such-capability'" in message for message in messages), messages
    _skill(repo, "gamma", distribution="runtime-provided", requires='"lane:journal"')
    messages = [item.message for item in _only(repo, "L4") if item.level == "ERROR"]
    assert any("must name a capability id" in message for message in messages), messages


def test_l4_absent_skills_tree_is_skipped_and_zero_skills_is_a_note(tmp_path):
    repo = _repo(tmp_path)
    assert _ids(_only(repo, "L4"), "SKIPPED") == ["L4"]
    (repo / "harness" / "skills").mkdir(parents=True)
    assert _ids(_only(repo, "L4"), "INFO") == ["L4"]
    assert _ids(_only(repo, "L4"), "ERROR") == []


def test_l4_zero_skills_is_a_ship_gate_not_a_hard_error(tmp_path):
    """Zero skills is a legitimate intermediate build state: --strict must
    only warn on it, never fail the working gate; --release is the ship gate
    that turns it into an ERROR."""
    repo = _repo(tmp_path)
    (repo / "harness" / "skills").mkdir(parents=True)
    default = _only(repo, "L4")
    assert [item.level for item in default] == ["INFO"]
    strict = _only(repo, "L4", strict=True)
    assert [item.level for item in strict] == ["WARN"]
    release = _only(repo, "L4", release=True)
    assert [item.level for item in release] == ["ERROR"]


# L5 --------------------------------------------------------------------------

def test_l5_resolver_row_targets_a_missing_skill(tmp_path):
    repo = _repo(tmp_path)
    _skill(repo, "alpha")
    _write(
        repo,
        "harness/skills/RESOLVER.md",
        "| Intent phrase | Target skill | Neighbor | Pack | Status |\n|---|---|---|---|---|\n"
        '| "run ghost" | `ghost` | none | core | spec-only |\n',
    )
    findings = _only(repo, "L5")
    assert "L5" in _ids(findings, "ERROR")
    assert any("ghost" in item.message for item in findings)


# L6 --------------------------------------------------------------------------

def test_l6_kernel_file_absent_from_manifest_is_soft(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/kernel-manifest.json", json.dumps({"version": "0.1.0", "files": [
        {"path": "harness/hooks/lib/listed.py", "state": "new", "source": None},
        {"path": "harness/hooks/lib/gone.py", "state": "ported", "source": "harness/hooks/lib/gone.py"},
        {"path": "harness/hooks/lib/bad.py", "state": "new", "source": "harness/hooks/lib/bad.py"},
    ]}))
    _write(repo, "harness/hooks/lib/listed.py", "x = 1\n")
    _write(repo, "harness/hooks/lib/bad.py", "x = 1\n")
    _write(repo, "harness/hooks/lib/unlisted.py", "x = 1\n")
    _write(repo, "harness/skills/demo/SKILL.md", "---\nname: demo\n---\n")
    _write(repo, "harness/adapters/claude/agents/routing-x-execute.md", "generated\n")
    soft = _only(repo, "L6")
    messages = [item.message for item in soft]
    assert all(item.level == "WARN" for item in soft)
    assert any("unlisted.py" in item.path for item in soft)
    assert any("gone.py" in item.path and "absent on disk" in item.message for item in soft)
    assert any("bad.py" in item.path and "source must be non-null exactly when" in item.message for item in soft)
    assert not any("skills/demo" in item.path or "agents/routing" in item.path for item in soft)
    strict = _only(repo, "L6", strict=True)
    assert [item.message for item in strict] == messages
    assert all(item.level == "ERROR" for item in strict)


def test_l6_adopted_host_owned_harness_files_are_not_unlisted(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/kernel-manifest.json", json.dumps({"version": "0.1.0", "files": []}))
    _write(repo, "harness/registry/structure.json", json.dumps({
        "host": {"adopted": True, "roots": ["courses"], "harness_owned": ["harness/rules/git-workflow.md"]},
    }))
    _write(repo, "harness/rules/git-workflow.md", "the host's own rule\n")
    _write(repo, "harness/hooks/lib/unlisted.py", "x = 1\n")
    # Default adopted-host scope: ctx.files never sees either host file (neither
    # is in adopted-files.json, the kernel manifest, or structure.json itself),
    # so the completeness loop reports no error for either, and the extra
    # harness/ file (not even in harness_owned) surfaces as one INFO count.
    findings = _only(repo, "L6")
    assert not any("git-workflow.md" in item.path for item in findings)
    assert not any("unlisted.py" in item.path for item in findings)
    # kernel-manifest.json itself is not in its own "files" list (it lists []
    # here) nor in adopted-files.json, so it too is unjudged alongside
    # unlisted.py: 2 host-owned files under harness/, neither an error.
    info = [item for item in findings if item.level == "INFO" and item.path == "harness/"]
    assert len(info) == 1 and "2 host-owned file(s) under harness/ not judged" in info[0].message
    # --all restores the whole-tree scan: git-workflow.md stays exempt via
    # harness_owned, but unlisted.py (in neither harness_owned nor the
    # manifest) is a real unlisted-kernel-file error again.
    findings = _only(repo, "L6", strict=True, all_scope=True)
    assert not any("git-workflow.md" in item.path for item in findings)
    assert any("unlisted.py" in item.path and item.level == "ERROR" for item in findings)


def test_l6_brain_readmes_not_required_when_no_lane_uses_brain(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/kernel-manifest.json", json.dumps({"version": "0.1.0", "files": [
        {"path": "brain/README.md", "state": "new", "source": None},
        {"path": "brain/local/README.md", "state": "new", "source": None},
        {"path": "brain/shared/README.md", "state": "new", "source": None},
        {"path": "harness/kernel-manifest.json", "state": "new", "source": None},
        {"path": "harness/registry/structure.json", "state": "new", "source": None},
    ]}))
    _write(repo, "harness/registry/structure.json", json.dumps({
        "lanes": {"identity": None, "knowledge": None, "journal": None, "decisions": ["docs/decisions"], "records": None, "docs": ["docs"]},
    }))
    findings = _only(repo, "L6")
    assert findings == []


def test_l6_brain_readmes_still_required_when_a_lane_uses_brain(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/kernel-manifest.json", json.dumps({"version": "0.1.0", "files": [
        {"path": "brain/README.md", "state": "new", "source": None},
    ]}))
    _write(repo, "harness/registry/structure.json", json.dumps({
        "lanes": {"identity": ["brain/shared/IDENTITY.md"], "knowledge": None, "journal": None, "decisions": None, "records": None, "docs": ["docs"]},
    }))
    findings = _only(repo, "L6")
    assert any("brain/README.md" in item.path and "absent on disk" in item.message for item in findings)


# L7 --------------------------------------------------------------------------

def _seed_materialization_sources(repo: Path) -> None:
    runtimes = json.loads((repo / "harness/registry/runtimes.json").read_text(encoding="utf-8"))
    for spec in runtimes["runtimes"].values():
        for row in spec.get("materializations") or []:
            source = row["source"]
            if source.startswith("harness/.selected/"):
                continue
            target = repo / source
            if Path(source).suffix:
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("seed\n", encoding="utf-8")
            else:
                target.mkdir(parents=True, exist_ok=True)


def test_l7_registry_error(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, REGISTRY_FILES)
    _seed_materialization_sources(repo)
    assert _ids(_only(repo, "L7"), "ERROR") == []
    structure = json.loads((repo / "harness/registry/structure.json").read_text(encoding="utf-8"))
    structure["unknown_top_level_key"] = True
    _write(repo, "harness/registry/structure.json", json.dumps(structure, indent=2))
    findings = _only(repo, "L7")
    assert "L7" in _ids(findings, "ERROR")


# L8 --------------------------------------------------------------------------

def test_l8_junctions_disagree_with_runtimes(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, ("harness/registry/runtimes.json",))
    assert _ids(_only(repo, "L8"), "SKIPPED") == ["L8"]
    assert _ids(_only(repo, "L8", strict=True), "ERROR") == ["L8"]
    runtimes = json.loads((repo / "harness/registry/runtimes.json").read_text(encoding="utf-8"))
    rows = [
        {"src": row["source"], "dst": row["destination"], "mode": row["mode"], "runtime": name, "description": ""}
        for name, spec in runtimes["runtimes"].items() for row in spec["materializations"]
    ]
    _write(repo, "harness/bootstrap/junctions.json", json.dumps({"schema_version": 1, "junctions": rows}))
    assert _ids(_only(repo, "L8"), "ERROR") == []
    rows.append({"src": "harness/extra", "dst": ".claude/extra", "mode": "link", "runtime": "claude", "description": ""})
    _write(repo, "harness/bootstrap/junctions.json", json.dumps({"schema_version": 1, "junctions": rows}))
    findings = _only(repo, "L8")
    assert "L8" in _ids(findings, "ERROR")
    assert any("harness/extra" in item.message for item in findings)


# L9 --------------------------------------------------------------------------

def test_l9_markdown_link_into_a_bootstrap_path_is_soft(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/guide.md", "See [the skills](.claude/skills/alpha/SKILL.md) for detail.\n")
    _write(repo, "harness/rules/wiki.md", "See [[.opencode/skills/alpha]] too.\n")
    _write(repo, "harness/rules/prose.md", "Bootstrap creates `.claude/skills/` links; that is prose, not a link.\n")
    _write(repo, "docs/allowed.md", "[ok](.claude/skills/alpha/SKILL.md)\n")
    _write(repo, "README.md", "[ok](.agents/skills)\n")
    soft = _only(repo, "L9")
    assert {item.path for item in soft} == {"harness/rules/guide.md", "harness/rules/wiki.md"}
    assert all(item.level == "WARN" for item in soft)
    assert all(item.level == "ERROR" for item in _only(repo, "L9", strict=True))


# L10 -------------------------------------------------------------------------

def test_l10_verification_row_missing_a_date(tmp_path):
    repo = _repo(tmp_path)
    _write(
        repo,
        "docs/VERIFICATION.md",
        "# Verification\n\n## Hooks\n\n"
        "| Runtime | Event | Mechanism | Status | Last live test | Scope | Reproducible in your clone by |\n"
        "|---|---|---|---|---|---|---|\n"
        "| claude | Stop | close-the-loop | verified | 2026-09-01 | this host | run the doctor |\n"
        "| codex | Stop | close-the-loop | documented | not yet | this host | run the doctor |\n"
        "| opencode | Stop | close-the-loop | maybe | 2026-09-01 |  |  |\n",
    )
    findings = _only(repo, "L10")
    assert all(item.level == "ERROR" for item in findings)
    lines = sorted({item.line for item in findings})
    assert lines == [8, 9]
    messages = " ".join(item.message for item in findings)
    assert "not an ISO date" in messages and "'maybe'" in messages and "empty scope" in messages and "reproducible" in messages


def test_l10_docs_absent_is_skipped(tmp_path):
    assert _ids(_only(_repo(tmp_path), "L10"), "SKIPPED") == ["L10"]


def test_l10_zero_rows_is_a_ship_gate_not_a_hard_error(tmp_path):
    repo = _repo(tmp_path)
    _write(
        repo,
        "docs/VERIFICATION.md",
        "# Verification\n\n## Hooks\n\n"
        "| Runtime | Event | Mechanism | Status | Last live test | Scope | Reproducible in your clone by |\n"
        "|---|---|---|---|---|---|---|\n",
    )
    default = _only(repo, "L10")
    assert [item.level for item in default] == ["INFO"]
    strict = _only(repo, "L10", strict=True)
    assert [item.level for item in strict] == ["WARN"]
    release = _only(repo, "L10", release=True)
    assert [item.level for item in release] == ["ERROR"]


# L11 -------------------------------------------------------------------------

def test_l11_generator_drift_is_soft(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/tools/gen_manifest.py", "import sys\nprint('DRIFT seeded')\nsys.exit(1)\n")
    soft = _only(repo, "L11")
    seeded = [item for item in soft if item.path == "harness/tools/gen_manifest.py"]
    assert seeded and seeded[0].level == "WARN" and "DRIFT seeded" in seeded[0].message
    assert all(item.level == "SKIPPED" for item in soft if item.path != "harness/tools/gen_manifest.py")
    strict = _only(repo, "L11", strict=True)
    assert [item for item in strict if item.path == "harness/tools/gen_manifest.py"][0].level == "ERROR"


# L12 -------------------------------------------------------------------------

def test_l12_rules_file_absent_from_index(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/listed.md", "# listed\n")
    _write(repo, "harness/rules/orphan.md", "# orphan\n")
    _write(repo, "harness/rules/README.md", "# readme\n")
    _write(repo, "harness/rules/index.json", json.dumps({"schema_version": 1, "rules": [
        {"slug": "listed", "kind": "always-on", "globs": []},
        {"slug": "dangling", "kind": "path-scoped", "globs": []},
    ]}))
    findings = _only(repo, "L12")
    assert all(item.level == "ERROR" for item in findings)
    messages = " ".join(item.message for item in findings)
    assert "orphan.md" in " ".join(item.path for item in findings)
    assert "dangling entry" in messages and "non-empty globs" in messages
    assert "README" not in messages


def test_l12_adopted_host_own_rule_files_are_not_unlisted(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/kernel-manifest.json", json.dumps({"version": "0.1.0", "files": []}))
    _write(repo, "harness/registry/structure.json", json.dumps({
        "host": {"adopted": True, "roots": [], "harness_owned": []},
    }))
    _write(repo, "harness/rules/listed.md", "# listed\n")
    _write(repo, "harness/registry/adopted-files.json", json.dumps({
        "template_version": "0.1.0", "paths": ["harness/rules/listed.md"],
    }))
    _write(repo, "harness/rules/host-own-rule.md", "# the host's own rule\n")
    _write(repo, "harness/rules/index.json", json.dumps({"schema_version": 1, "rules": [
        {"slug": "listed", "kind": "always-on", "globs": []},
    ]}))
    findings = _only(repo, "L12")
    assert not any("host-own-rule.md" in item.path for item in findings)
    info = [item for item in findings if item.level == "INFO" and item.path == "harness/rules/"]
    assert len(info) == 1 and "1 host-owned rule file(s)" in info[0].message

    findings = _only(repo, "L12", strict=True, all_scope=True)
    assert any("host-own-rule.md" in item.path and item.level == "ERROR" for item in findings)


def test_l12_path_scoped_rule_needs_matching_paths_frontmatter(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/no-frontmatter.md", "# no frontmatter\n")
    _write(repo, "harness/rules/mismatched.md", "---\npaths:\n  - \"other/**\"\n---\n\n# mismatched\n")
    _write(repo, "harness/rules/index.json", json.dumps({"schema_version": 1, "rules": [
        {"slug": "no-frontmatter", "kind": "path-scoped", "globs": ["harness/hooks/**"]},
        {"slug": "mismatched", "kind": "path-scoped", "globs": ["harness/hooks/**"]},
    ]}))
    findings = _only(repo, "L12")
    messages = " ".join(item.message for item in findings)
    assert "needs frontmatter paths:" in messages
    assert "does not match index globs" in messages


def test_l12_always_on_rule_must_not_carry_paths_frontmatter(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/scoped-anyway.md", "---\npaths:\n  - \"**/*.md\"\n---\n\n# scoped anyway\n")
    _write(repo, "harness/rules/index.json", json.dumps({"schema_version": 1, "rules": [
        {"slug": "scoped-anyway", "kind": "always-on", "globs": []},
    ]}))
    findings = _only(repo, "L12")
    assert any("must not carry frontmatter paths:" in item.message for item in findings)


def test_l12_path_scoped_rule_with_matching_frontmatter_is_clean(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/scoped.md", "---\npaths:\n  - \"harness/hooks/**\"\n---\n\n# scoped\n")
    _write(repo, "harness/rules/index.json", json.dumps({"schema_version": 1, "rules": [
        {"slug": "scoped", "kind": "path-scoped", "globs": ["harness/hooks/**"]},
    ]}))
    findings = _only(repo, "L12")
    assert not findings


# L13 -------------------------------------------------------------------------

def test_l13_literal_lane_token_in_a_hook_lib_is_soft(tmp_path):
    repo = _repo(tmp_path)
    _write_default_structure(repo)
    structure = json.loads((repo / "harness/registry/structure.json").read_text(encoding="utf-8"))
    token = structure["lanes"]["journal"][0]
    _write(repo, "harness/hooks/lib/some_hook.py", f'JOURNAL = "{token}"\n')
    _write(repo, "harness/hooks/lib/hook_io.py", f'DEFAULT = "{token}"\n')
    _write(repo, "harness/registry/seed.py", f'X = "{token}"\n')
    _write(repo, "harness/tools/tests/test_seed.py", f'X = "{token}"\n')
    soft = _only(repo, "L13")
    assert [item.path for item in soft] == ["harness/hooks/lib/some_hook.py"], [item.render() for item in soft]
    assert soft[0].level == "WARN" and repr(token) in soft[0].message
    assert _only(repo, "L13", strict=True)[0].level == "ERROR"


# L14 -------------------------------------------------------------------------

def test_l14_deidentify_structural_finding_is_soft(tmp_path):
    repo = _repo(tmp_path)
    address = "@".join(("someone", "private-corp.io"))
    _write(repo, "harness/rules/contact.md", f"Write to {address} for access.\n")
    soft = _only(repo, "L14")
    assert [item.path for item in soft] == ["harness/rules/contact.md"]
    assert soft[0].level == "WARN" and "D1" in soft[0].message
    assert _only(repo, "L14", strict=True)[0].level == "ERROR"


# L15 -------------------------------------------------------------------------

def _sources_json(keys: tuple[str, ...] = ("gbrain",)) -> str:
    sources = {key: {"origin": "https://example.invalid", "license": "MIT", "notice": None, "modified": True, "assets": []} for key in keys}
    return json.dumps({"schema_version": 1, "sources": sources})


def test_l15_source_key_resolves(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/registry/sources.json", _sources_json(("gbrain", "humanizer")))
    _write(repo, "harness/rules/output-quality.md", "Descends from the `gbrain` source and the `humanizer` source there.\n")
    assert _ids(_only(repo, "L15"), "ERROR") == []


def test_l15_unknown_source_key_is_an_error(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/registry/sources.json", _sources_json(("gbrain",)))
    _write(repo, "harness/rules/output-quality.md", "Descends from the `ghost-project` source in the registry.\n")
    findings = _only(repo, "L15")
    assert "L15" in _ids(findings, "ERROR")
    assert any("ghost-project" in item.message for item in findings)


def test_l15_backticked_token_without_the_word_source_is_not_a_citation(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/registry/sources.json", _sources_json(("gbrain",)))
    _write(repo, "harness/rules/other.md", "Run `--strict` before every release; see `docs/VERIFICATION.md`.\n")
    assert _ids(_only(repo, "L15"), "ERROR") == []


def test_l15_rules_tree_absent_is_skipped(tmp_path):
    assert _ids(_only(_repo(tmp_path), "L15"), "SKIPPED") == ["L15"]


def test_l15_missing_registry_is_an_error(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/x.md", "See the `gbrain` source.\n")
    findings = _only(repo, "L15")
    assert findings and findings[0].level == "ERROR" and "sources.json" in findings[0].path


# L16 -------------------------------------------------------------------------

def test_l16_fixture_path_resolves(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/hooks/tests/fixtures/guard/bypass-x.json", "{}\n")
    _write(repo, "SECURITY.md", "Fixture: `harness/hooks/tests/fixtures/guard/*`\n")
    assert _ids(_only(repo, "L16"), "ERROR") == []


def test_l16_fixture_path_missing_is_an_error(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "SECURITY.md", "Fixture: `harness/hooks/tests/fixtures/precommit/*`\n")
    findings = _only(repo, "L16")
    assert "L16" in _ids(findings, "ERROR")
    assert any("precommit" in item.message for item in findings)


def test_l16_security_absent_is_skipped(tmp_path):
    assert _ids(_only(_repo(tmp_path), "L16"), "SKIPPED") == ["L16"]


# L17 -------------------------------------------------------------------------

def test_l17_bracketed_placeholder_tbd_and_literal_date(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "docs/a.md", "Acknowledge within [cadence placeholder: set before v0.1.0].\n")
    _write(repo, "docs/b.md", "Owner: TBD\n")
    _write(repo, "docs/c.md", "Filed on YYYY-MM-DD once known.\n")
    findings = _only(repo, "L17")
    by_path = {item.path: item.message for item in findings}
    assert "bracketed placeholder" in by_path["docs/a.md"]
    assert "TBD" in by_path["docs/b.md"]
    assert "YYYY-MM-DD" in by_path["docs/c.md"]


def test_l17_backticked_pattern_examples_are_not_flagged(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "docs/d.md", "Dated entries follow `YYYY-MM-DD-topic.md`; `TBD` marks an open field.\n")
    assert _ids(_only(repo, "L17"), "ERROR") == []


def test_l17_fenced_code_block_is_not_flagged(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "docs/e.md", "```\nYYYY-MM-DD.md         one entry per day\n```\n")
    assert _ids(_only(repo, "L17"), "ERROR") == []


def test_l17_fixture_and_test_paths_are_exempt(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/hooks/tests/fixtures/precommit/note.md", "Owner: TBD\n")
    _write(repo, "harness/tools/tests/data.md", "Owner: TBD\n")
    assert _ids(_only(repo, "L17"), "ERROR") == []


# L18 -------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_git(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def test_l18_non_executable_sh_is_an_error(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/hooks/foo.sh", "#!/bin/sh\necho hi\n")
    _init_git(repo)
    _git(repo, "add", "harness/hooks/foo.sh")
    _git(repo, "update-index", "--chmod=-x", "harness/hooks/foo.sh")
    findings = _only(repo, "L18")
    assert "L18" in _ids(findings, "ERROR")


def test_l18_executable_sh_and_precommit_hook_pass(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/hooks/foo.sh", "#!/bin/sh\necho hi\n")
    _write(repo, ".githooks/pre-commit", "#!/bin/sh\nexit 0\n")
    _init_git(repo)
    _git(repo, "add", "harness/hooks/foo.sh", ".githooks/pre-commit")
    _git(repo, "update-index", "--chmod=+x", "harness/hooks/foo.sh", ".githooks/pre-commit")
    assert _ids(_only(repo, "L18"), "ERROR") == []


def test_l18_non_executable_precommit_hook_is_an_error(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, ".githooks/pre-commit", "#!/bin/sh\nexit 0\n")
    _init_git(repo)
    _git(repo, "add", ".githooks/pre-commit")
    _git(repo, "update-index", "--chmod=-x", ".githooks/pre-commit")
    findings = _only(repo, "L18")
    assert "L18" in _ids(findings, "ERROR")
    assert findings[0].path == ".githooks/pre-commit"


def test_l18_non_git_repo_is_skipped(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/hooks/foo.sh", "#!/bin/sh\necho hi\n")
    assert _ids(_only(repo, "L18"), "SKIPPED") == ["L18"]


def test_l18_host_owned_sh_outside_harness_is_never_checked(tmp_path):
    """Scope is harness/*.sh plus .githooks/pre-commit, the exact predicate
    materialize.py's _ensure_scripts_executable uses: a host-owned script
    outside harness/ at mode 644 must never produce a finding."""
    repo = _repo(tmp_path)
    host_dir_name = "host" + "scripts"  # kept out of a path-shaped literal
    host_script = host_dir_name + "/" + "env.sh"
    _write(repo, host_script, "# sourced only, never executed directly\n")
    _write(repo, "harness/hooks/foo.sh", "#!/bin/sh\necho hi\n")
    _init_git(repo)
    _git(repo, "add", host_script, "harness/hooks/foo.sh")
    _git(repo, "update-index", "--chmod=-x", host_script)
    _git(repo, "update-index", "--chmod=+x", "harness/hooks/foo.sh")
    findings = _only(repo, "L18")
    assert findings == []


def test_l18_parses_nul_delimited_records_including_a_non_ascii_name(tmp_path):
    """git ls-files -s -z output is NUL-delimited and unquoted: a mocked
    record proves the parser reads a non-ASCII name intact, rather than the
    C-style-quoted stand-in a plain (non -z) `-s` call would return, which
    would never match ctx.files and silently drop the file from the check."""
    from unittest import mock

    repo = _repo(tmp_path)
    name = "harness/hooks/café.sh"
    other = "harness/hooks/foo.sh"
    record = f"100644 abcdef0000000000000000000000000000000000000000 0\t{name}".encode("utf-8")
    passing = f"100755 abcdef0000000000000000000000000000000000000000 0\t{other}".encode("utf-8")
    completed = subprocess.CompletedProcess(
        args=["git"], returncode=0, stdout=record + b"\0" + passing + b"\0", stderr=b""
    )

    ctx = lint.Context(repo, strict=False)
    ctx._files = [name, other]
    ctx._scope_label = "whole tree"

    with mock.patch.object(lint.subprocess, "run", return_value=completed) as run:
        findings = lint.check_executable_bit(ctx)

    called_args = run.call_args.args[0]
    assert "-z" in called_args, "check must request NUL-delimited output"
    errored = [f.path for f in findings if f.id == "L18"]
    assert name in errored
    assert other not in errored


# Adopted-host scope -----------------------------------------------------------

def test_adopted_host_default_scope_excludes_host_file_and_includes_template_file(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/kernel-manifest.json", json.dumps({
        "version": "0.1.0",
        "files": [{"path": "harness/kernel-manifest.json", "state": "new", "source": None}],
    }))
    _write(repo, "harness/registry/adopted-files.json", json.dumps({
        "template_version": "0.1.0",
        "paths": ["harness/rules/git-workflow.md"],
    }))
    _write(repo, "harness/registry/structure.json", json.dumps({
        "host": {"adopted": True, "roots": [], "harness_owned": []},
    }))
    dash = "em" + chr(0x2014) + "dash\n"
    _write(repo, "harness/rules/git-workflow.md", dash)  # template-owned: in the default scope
    _write(repo, "docs/host-only.md", dash)  # host content: out of the default scope

    findings = _only(repo, "L3")
    assert any("git-workflow.md" in item.path for item in findings)
    assert not any("host-only.md" in item.path for item in findings)

    findings = _only(repo, "L3", all_scope=True)
    assert any("git-workflow.md" in item.path for item in findings)
    assert any("host-only.md" in item.path for item in findings)


def test_scope_line_prints_and_reports_the_right_mode(tmp_path):
    repo = _repo(tmp_path)
    code, out = _cli(["--root", str(repo), "--only", "L3"])
    assert code == 0
    assert "lint: scope whole tree (" in out

    _write(repo, "harness/registry/structure.json", json.dumps({
        "host": {"adopted": True, "roots": [], "harness_owned": []},
    }))
    code, out = _cli(["--root", str(repo), "--only", "L3"])
    assert "lint: scope adopted-host (" in out
    code, out = _cli(["--root", str(repo), "--only", "L3", "--all"])
    assert "lint: scope whole tree (" in out


# CLI -------------------------------------------------------------------------

def _cli(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = lint.main(argv)
    return code, out.getvalue()


def test_cli_exit_codes_and_json_format(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "harness/rules/dash.md", "em" + chr(0x2014) + "dash\n")
    code, out = _cli(["--root", str(repo), "--only", "L3"])
    assert code == 1 and "L3   ERROR" in out and "1 error(s)" in out
    code, out = _cli(["--root", str(repo), "--only", "L3", "--format", "json"])
    payload = json.loads(out)
    assert code == 1 and payload["summary"]["ERROR"] == 1 and payload["findings"][0]["id"] == "L3"
    _write(repo, "harness/rules/dash.md", "plain\n")
    code, out = _cli(["--root", str(repo), "--only", "L3"])
    assert code == 0 and "0 error(s)" in out
    assert _cli(["--root", str(repo), "--only", "L99"])[0] == 2


def test_cli_release_flag_promotes_ship_gate_conditions(tmp_path):
    repo = _repo(tmp_path)
    (repo / "harness" / "skills").mkdir(parents=True)
    code, out = _cli(["--root", str(repo), "--only", "L4"])
    assert code == 0 and "L4   INFO" in out
    code, out = _cli(["--root", str(repo), "--only", "L4", "--strict"])
    assert code == 0 and "L4   WARN" in out
    code, out = _cli(["--root", str(repo), "--only", "L4", "--release"])
    assert code == 1 and "L4   ERROR" in out and "release" in out


def test_soft_checks_are_the_declared_set():
    assert lint.SOFT_CHECKS == {"L6", "L9", "L11", "L13", "L14"}
    assert [check_id for check_id, _, _ in lint.CHECKS] == [f"L{n}" for n in range(1, 19)]


def test_schema_validator_rejects_a_comment_key(tmp_path):
    repo = _repo(tmp_path)
    copy_files(repo, (
        "harness/adapters/claude/schema.json", "harness/adapters/claude/settings.base.json",
        "harness/adapters/codex/schema.json", "harness/adapters/codex/hooks.json",
        "harness/adapters/opencode/schema.json", "harness/adapters/opencode/opencode.json",
    ))
    assert not [item for item in lint.check_schemas(lint.Context(repo, False)) if item.level == "ERROR"]
    settings = json.loads((repo / "harness/adapters/claude/settings.base.json").read_text(encoding="utf-8"))
    settings["_comment"] = "seeded"
    _write(repo, ".claude/settings.json", json.dumps(settings, indent=2))
    errors = [item for item in lint.check_schemas(lint.Context(repo, False)) if item.level == "ERROR"]
    assert errors and errors[0].path == ".claude/settings.json"


install_bridge(globals(), "LintBridge")
