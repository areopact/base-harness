"""gen_manifest: resolver and skill-index generation, --check drift, --licenses."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ._repo import ROOT, copy_files, install_bridge  # noqa: F401

import gen_manifest as gm


def _host_adopted() -> bool:
    """True when this checkout's own structure.json declares host.adopted."""
    try:
        data = json.loads((ROOT / "harness" / "registry" / "structure.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(data, dict) and (data.get("host") or {}).get("adopted"))

SOURCES_JSON = {
    "schema_version": 1,
    "sources": {
        "alpha-source": {"origin": "internal", "license": "MIT", "notice": None, "modified": False, "assets": []},
        "beta-source": {"origin": "https://example.com/beta", "license": "Apache-2.0", "notice": "Adapted from beta.", "modified": True, "assets": ["harness/skills/beta"]},
    },
}


def _skill(repo: Path, name: str, pack: str, triggers: list[str], *, status: str = "spec-only", when_not: str = "", neighbor: str | None = None) -> None:
    body = (
        "---\n"
        f"name: {name}\n"
        "description: >\n"
        f"  Does {name}. WHEN: someone asks for {name}.{when_not}\n"
        "metadata:\n"
        f"  packs: [{pack}]\n"
        "  triggers:\n" + "".join(f'    - "{trigger}"\n' for trigger in triggers) +
        (f"  neighbor: {neighbor}\n" if neighbor is not None else "") +
        "  distribution: native\n"
        f"  status: {status}\n"
        "  license: MIT\n"
        "---\n\n"
        f"# {name}\n"
    )
    path = repo / "harness" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "harness" / "skills").mkdir(parents=True)
    (repo / "harness" / "registry").mkdir(parents=True)
    (repo / "harness" / "registry" / "sources.json").write_text(json.dumps(SOURCES_JSON, indent=2), encoding="utf-8")
    return repo


def _run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = gm.main(argv)
    return code, out.getvalue()


def test_zero_skills_produce_a_valid_empty_resolver(tmp_path):
    repo = _repo(tmp_path)
    code, out = _run(["--root", str(repo)])
    assert code == 0, out
    resolver = (repo / gm.RESOLVER).read_text(encoding="utf-8")
    lines = resolver.splitlines()
    header_index = lines.index("| " + " | ".join(gm.RESOLVER_COLUMNS) + " |")
    assert lines[header_index + 1] == "|" + "---|" * len(gm.RESOLVER_COLUMNS)
    assert len(lines) == header_index + 2
    index = json.loads((repo / gm.SKILL_INDEX).read_text(encoding="utf-8"))
    assert index["total"] == 0 and index["skills"] == []
    assert index["counts"] == {"implemented": 0, "spec-only": 0, "stub": 0}
    assert _run(["--root", str(repo), "--check"])[0] == 0


def test_three_skills_produce_rows_in_pack_then_name_order(tmp_path):
    repo = _repo(tmp_path)
    _skill(repo, "zeta", "core", ["run zeta", "zeta please"])
    _skill(repo, "alpha", "maintain", ["run alpha"])
    _skill(repo, "mid", "core", ["run mid"], status="implemented", when_not=" WHEN NOT: use /zeta for zeta work.")
    code, out = _run(["--root", str(repo)])
    assert code == 0, out
    rows = [line for line in (repo / gm.RESOLVER).read_text(encoding="utf-8").splitlines() if line.startswith('| "')]
    assert [row.split("|")[2].strip() for row in rows] == ["`mid`", "`zeta`", "`zeta`", "`alpha`"]
    assert [row.split("|")[1].strip() for row in rows] == ['"run mid"', '"run zeta"', '"zeta please"', '"run alpha"']
    assert rows[0].split("|")[3].strip() == "`zeta`"
    assert rows[1].split("|")[3].strip() == "none"
    assert [row.split("|")[4].strip() for row in rows] == ["core", "core", "core", "maintain"]
    assert [row.split("|")[5].strip() for row in rows] == ["implemented", "spec-only", "spec-only", "spec-only"]
    index = json.loads((repo / gm.SKILL_INDEX).read_text(encoding="utf-8"))
    assert [skill["name"] for skill in index["skills"]] == ["alpha", "mid", "zeta"]
    assert index["counts"] == {"implemented": 1, "spec-only": 2, "stub": 0}


def test_explicit_neighbor_overrides_the_when_not_derivation(tmp_path):
    repo = _repo(tmp_path)
    _skill(repo, "zeta", "core", ["run zeta"])
    _skill(repo, "mid", "core", ["run mid"], when_not=" WHEN NOT: use /zeta for zeta work.", neighbor="none")
    _skill(repo, "odd", "core", ["run odd"], neighbor="ghost")
    _skill(repo, "own", "core", ["run own"], neighbor="own")
    skills = {skill.name: skill for skill in gm.scan_skills(repo)}
    assert skills["mid"].neighbor == "none" and skills["mid"].neighbor_explicit
    assert skills["zeta"].neighbor == "none" and not skills["zeta"].neighbor_explicit
    assert any("metadata.neighbor 'ghost' is not a skill" in problem for problem in skills["odd"].problems)
    assert any("names the skill itself" in problem for problem in skills["own"].problems)


@unittest.skipIf(_host_adopted(), "asserts the template's own README.md and docs prose; not valid on an adopted host")
def test_docs_state_the_built_catalog_counts():
    """README.md, docs/PACKS.md, and docs/ARCHITECTURE.md each spell the
    selected-of-available count; this pins them to the catalog and the
    shipped selection so the prose cannot describe an earlier build."""
    skills = gm.scan_skills(ROOT)
    selection = json.loads((ROOT / "harness" / "registry" / "selection.json").read_text(encoding="utf-8"))
    packs = set(selection.get("packs") or [])
    selected = {skill.name for skill in skills if packs.intersection(skill.packs)}
    selected.update(name for name in selection.get("include") or [] if name in {skill.name for skill in skills})
    selected.difference_update(selection.get("exclude") or [])
    phrase = f"{len(selected)} selected of {len(skills)} available"
    for relative in ("README.md", "docs/PACKS.md", "docs/ARCHITECTURE.md"):
        assert phrase in (ROOT / relative).read_text(encoding="utf-8"), (relative, phrase)


def test_check_exits_one_after_an_edit(tmp_path):
    repo = _repo(tmp_path)
    _skill(repo, "alpha", "core", ["run alpha"])
    assert _run(["--root", str(repo)])[0] == 0
    assert _run(["--root", str(repo), "--check"])[0] == 0
    resolver = repo / gm.RESOLVER
    resolver.write_text(resolver.read_text(encoding="utf-8") + '| "extra" | `alpha` | none | core | spec-only |\n', encoding="utf-8")
    code, out = _run(["--root", str(repo), "--check"])
    assert code == 1 and "DRIFT  harness/skills/RESOLVER.md" in out
    assert _run(["--root", str(repo)])[0] == 0
    (repo / gm.SKILL_INDEX).unlink()
    code, out = _run(["--root", str(repo), "--check"])
    assert code == 0 and "untracked cache" in out
    (repo / gm.SKILL_INDEX).write_text("{}\n", encoding="utf-8")
    assert _run(["--root", str(repo), "--check"])[0] == 1


def test_frontmatter_problems_fail_generation(tmp_path):
    repo = _repo(tmp_path)
    _skill(repo, "alpha", "core", [])
    code, out = _run(["--root", str(repo), "--check"])
    assert code == 1 and "metadata.triggers is required" in out


def test_licenses_output_lists_one_line_per_source(tmp_path):
    repo = _repo(tmp_path)
    code, out = _run(["--root", str(repo), "--licenses"])
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith("# id\t")
    assert len(lines) == 1 + len(SOURCES_JSON["sources"])
    assert lines[1].split("\t")[0] == "alpha-source"
    assert lines[2].split("\t") == ["beta-source", "https://example.com/beta", "Apache-2.0", "modified", "harness/skills/beta", "Adapted from beta."]


def test_third_party_generated_from_sources_json(tmp_path):
    repo = _repo(tmp_path)
    code, out = _run(["--root", str(repo)])
    assert code == 0, out
    third_party = (repo / gm.THIRD_PARTY).read_text(encoding="utf-8")
    lines = third_party.splitlines()
    assert lines[0].startswith("<!-- GENERATED by harness/tools/gen_manifest.py from harness/registry/sources.json.")
    assert "| Source | Origin | License | Modified | Notice | Assets |" in lines
    rows = {line.split("|")[1].strip(): line for line in lines if line.startswith("| `")}
    assert set(rows) == {"`alpha-source`", "`beta-source`"}
    # alpha-source has no notice and no assets: both cells render as a bare
    # single space between their bordering pipes, never a doubled space.
    assert " unmodified |  | |" not in rows["`alpha-source`"]
    assert "| `alpha-source` | internal | MIT | unmodified | | |" == rows["`alpha-source`"]
    assert "harness/skills/beta" in rows["`beta-source`"]
    assert "Adapted from beta." in rows["`beta-source`"]
    assert third_party.endswith("\n") and not third_party.endswith("\n\n")


def test_third_party_check_flags_drift_and_regenerates(tmp_path):
    repo = _repo(tmp_path)
    assert _run(["--root", str(repo)])[0] == 0
    assert _run(["--root", str(repo), "--check"])[0] == 0
    third_party = repo / gm.THIRD_PARTY
    third_party.write_text(third_party.read_text(encoding="utf-8") + "stray hand-edit\n", encoding="utf-8")
    code, out = _run(["--root", str(repo), "--check"])
    assert code == 1 and "DRIFT  THIRD-PARTY.md" in out
    code, out = _run(["--root", str(repo)])
    assert code == 0 and "UPDATED  THIRD-PARTY.md" in out
    assert _run(["--root", str(repo), "--check"])[0] == 0


def test_third_party_missing_file_is_drift_not_a_crash(tmp_path):
    repo = _repo(tmp_path)
    assert _run(["--root", str(repo)])[0] == 0
    (repo / gm.THIRD_PARTY).unlink()
    code, out = _run(["--root", str(repo), "--check"])
    assert code == 1 and "DRIFT  THIRD-PARTY.md (missing)" in out
    assert _run(["--root", str(repo)])[0] == 0
    assert (repo / gm.THIRD_PARTY).is_file()


def test_third_party_absent_sources_json_renders_empty_table(tmp_path):
    repo = tmp_path / "repo"
    (repo / "harness" / "skills").mkdir(parents=True)
    code, out = _run(["--root", str(repo)])
    assert code == 0, out
    third_party = (repo / gm.THIRD_PARTY).read_text(encoding="utf-8")
    assert third_party.splitlines()[-1] == "|---|---|---|---|---|---|"


def test_live_third_party_matches_sources_json():
    """The tracked THIRD-PARTY.md must already equal what --root ROOT would write."""
    generated = gm.render_third_party(ROOT)
    actual = (ROOT / gm.THIRD_PARTY).read_text(encoding="utf-8")
    assert generated == actual


def test_live_tree_check_is_clean():
    code, out = _run(["--root", str(ROOT), "--check"])
    assert code == 0, out


install_bridge(globals(), "GenManifestBridge")
