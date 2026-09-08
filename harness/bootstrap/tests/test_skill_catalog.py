"""Skill metadata reader, selection semantics, and validate_skills."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import BOOTSTRAP, bind_unittest, build_repo, write_selection, write_skill

sys.path.insert(0, str(BOOTSTRAP))
import materialize  # noqa: E402
import skill_catalog  # noqa: E402
import validate_skills  # noqa: E402


def test_read_skills_reads_metadata_block(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    skills = skill_catalog.read_skills(root / "harness" / "skills")
    assert sorted(skills) == ["alpha", "beta", "gamma"]
    alpha = skills["alpha"]
    assert alpha.packs == ("core",)
    assert alpha.triggers == ("alpha please",)
    assert alpha.status == "implemented"
    assert alpha.distribution == "native"
    assert alpha.license == "MIT"
    assert alpha.relative == "harness/skills/alpha"
    assert "WHEN:" in alpha.description


def test_select_skills_union_include_minus_exclude(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    skills = skill_catalog.read_skills(root / "harness" / "skills")
    selected, warnings = skill_catalog.select_skills(
        skills, {"packs": ["core"], "include": ["gamma", "missing"], "exclude": ["alpha", "ghost"]}
    )
    assert selected == ["gamma"]
    assert len(warnings) == 2
    assert any("include names a skill that does not exist: missing" in w for w in warnings)


def test_absent_skill_tree_is_empty(tmp_path):
    assert skill_catalog.read_skills(tmp_path / "nope") == {}


def test_malformed_skill_raises_with_its_path(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    (root / "harness" / "skills" / "alpha" / "SKILL.md").write_text("no frontmatter\n", encoding="utf-8")
    try:
        skill_catalog.read_skills(root / "harness" / "skills")
    except skill_catalog.SkillError as exc:
        assert "harness/skills/alpha/SKILL.md" in str(exc)
    else:
        raise AssertionError("SkillError not raised")


def test_name_must_match_directory(tmp_path):
    directory = write_skill(tmp_path, "delta", ["core"])
    text = (directory / "SKILL.md").read_text(encoding="utf-8").replace("name: delta", "name: other")
    (directory / "SKILL.md").write_text(text, encoding="utf-8")
    try:
        skill_catalog.load_skill(directory / "SKILL.md")
    except skill_catalog.SkillError:
        pass
    else:
        raise AssertionError("SkillError not raised")


def test_short_description_keeps_when_text():
    description = "A long summary. " * 20 + "WHEN: the user asks for it. WHEN NOT: anything else."
    compact = skill_catalog.short_description(description)
    assert len(compact) <= skill_catalog.MAX_DESCRIPTION_CHARS
    assert "WHEN:" in compact


def test_short_description_never_cuts_inside_a_quoted_phrase():
    phrases = ", ".join(f'"trigger phrase number {index} with words"' for index in range(12))
    description = "Summary. WHEN: /go, " + phrases + " WHEN NOT: anything else."
    compact = skill_catalog.short_description(description)
    assert len(compact) <= skill_catalog.MAX_DESCRIPTION_CHARS
    assert compact.endswith("...")
    assert compact.count('"') % 2 == 0, compact
    assert '"trigger phrase number 0 with words"' in compact


def test_validate_skills_passes_a_clean_tree_and_exact_catalog(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = validate_skills.main(["--root", str(root), "--require-codex-catalog"])
    assert code == 0, stream.getvalue()
    assert "3 checked" in stream.getvalue()
    assert "exact Codex catalog OK" in stream.getvalue()


def test_validate_skills_reports_a_stale_catalog(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    (root / ".agents" / "skills" / "alpha" / "SKILL.md").write_text("tampered\n", encoding="utf-8")
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = validate_skills.main(["--root", str(root), "--catalog", str(root / ".agents" / "skills")])
    assert code == 1
    assert "byte drift" in stream.getvalue() and "alpha" in stream.getvalue()


def test_validate_skills_flags_missing_when_and_bad_pack_slug(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    path = root / "harness" / "skills" / "alpha" / "SKILL.md"
    text = path.read_text(encoding="utf-8").replace("WHEN: the user asks for alpha.", "").replace("packs: [core]", "packs: [Core_Pack]")
    path.write_text(text, encoding="utf-8")
    checked, errors = validate_skills.validate_source(root)
    assert checked == 3
    assert any("must contain 'WHEN:'" in e for e in errors)
    assert any("not kebab-case" in e for e in errors)


def test_validate_skills_tolerates_zero_skills(tmp_path):
    root = build_repo(tmp_path, with_git=False, with_skills_dir=False)
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = validate_skills.main(["--root", str(root)])
    assert code == 0
    assert "0 checked" in stream.getvalue()


def test_load_selection_defaults_and_shape(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    (root / "harness" / "registry" / "selection.json").unlink()
    assert skill_catalog.load_selection(root)["packs"] == ["core", "maintain"]
    write_selection(root, ["decks"])
    assert skill_catalog.load_selection(root)["packs"] == ["decks"]
    (root / "harness" / "registry" / "selection.json").write_text('{"packs": "core"}', encoding="utf-8")
    try:
        skill_catalog.load_selection(root)
    except skill_catalog.SkillError:
        pass
    else:
        raise AssertionError("SkillError not raised")


bind_unittest(globals(), "SkillCatalogBridge")
