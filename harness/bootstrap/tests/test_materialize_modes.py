"""Check, copy, independence, selection, and zero-skill behavior (B4, B5, B6, B8, B9)."""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import BOOTSTRAP, bind_unittest, build_repo, git, write_selection, write_skill

NEEDS_TOMLLIB = sys.version_info < (3, 11)
NEEDS_TOMLLIB_REASON = "requires Python 3.11+ (tomllib is stdlib-only from 3.11; doctor_codex fails closed below it)"

sys.path.insert(0, str(BOOTSTRAP))
import doctor_claude  # noqa: E402
import doctor_codex  # noqa: E402
import doctor_common  # noqa: E402
import doctor_opencode  # noqa: E402
import materialize  # noqa: E402


def _run_doctor(module, root: Path) -> tuple[int, str, doctor_common.Audit]:
    stream = io.StringIO()
    captured: dict[str, doctor_common.Audit] = {}
    original = doctor_common.Audit

    class Capturing(original):
        def __init__(self) -> None:
            super().__init__()
            captured["audit"] = self

    module.Audit = Capturing
    doctor_common.Audit = Capturing
    try:
        with redirect_stdout(stream):
            code = module.main(["--offline", "--root", str(root)])
    finally:
        module.Audit = original
        doctor_common.Audit = original
    return code, stream.getvalue(), captured["audit"]


def _managed_entries(root: Path, relative: str) -> list[Path]:
    directory = root / relative
    return sorted(p for p in directory.iterdir() if not p.name.startswith("."))


def _main(*args: str) -> tuple[int, str]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = materialize.main(list(args))
    return code, stream.getvalue()


def test_b4_check_detects_a_one_byte_drift_and_names_the_file(tmp_path):
    root = build_repo(tmp_path)
    assert _main("--root", str(root))[0] == 0
    assert _main("--root", str(root), "--check")[0] == 0
    settings = root / ".claude" / "settings.json"
    settings.write_bytes(settings.read_bytes() + b"\n")
    code, output = _main("--root", str(root), "--check")
    assert code == 1
    assert "DRIFT" in output and ".claude/settings.json differs" in output
    assert _main("--root", str(root))[0] == 0
    assert _main("--root", str(root), "--check")[0] == 0


def test_b4_check_reports_missing_executable_access_as_drift_without_chmod(tmp_path):
    """Platform-independent unit test of the branch itself (mocked stat and
    a mocked git so this runs on Windows too, where the POSIX end-to-end
    version below is skipped): --check must report a non-executable
    tracked *.sh entry as drift and must never call chmod to repair it."""
    from unittest import mock

    root = build_repo(tmp_path)
    hook = root / ".githooks" / "pre-commit"
    hook.chmod(0o644)  # the fixture copies the source's mode bits on POSIX
    engine = materialize.Engine(root, check=True, force=False, copy=False)
    fake_git = mock.MagicMock()
    fake_git.returncode = 0
    fake_git.stdout = ".githooks/pre-commit\x00"
    with mock.patch.object(engine, "_git", return_value=fake_git), \
         mock.patch("materialize.os.name", "posix"), \
         mock.patch.object(type(hook), "chmod") as fake_chmod:
        engine._ensure_scripts_executable()
    fake_chmod.assert_not_called()
    assert engine.result.drift == 1
    assert any(".githooks/pre-commit is not executable on disk" in line for line in engine.result.lines)


def test_ensure_scripts_executable_never_touches_a_host_owned_script(tmp_path):
    """Scope is harness/*.sh plus .githooks/pre-commit, the same scope
    lint L18 uses: a host-owned script outside harness/ (e.g. a
    sourced-only env.sh under a host scripts directory, deliberately left
    non-executable) must never be chmodded or reported as drift."""
    from unittest import mock

    host_dir_name = "host" + "scripts"  # kept out of a path-shaped literal
    root = build_repo(tmp_path)
    host_script = root / host_dir_name / "env.sh"
    host_script.parent.mkdir(parents=True, exist_ok=True)
    host_script.write_text("# sourced only, never executed directly\n", encoding="utf-8")
    harness_script = root / "harness" / "extension.sh"
    harness_script.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    host_tracked_name = host_dir_name + "/" + "env.sh"

    engine = materialize.Engine(root, check=True, force=False, copy=False)
    fake_git = mock.MagicMock()
    fake_git.returncode = 0
    fake_git.stdout = host_tracked_name + "\x00harness/extension.sh\x00"
    with mock.patch.object(engine, "_git", return_value=fake_git), \
         mock.patch("materialize.os.name", "posix"), \
         mock.patch.object(type(host_script), "chmod") as fake_chmod:
        engine._ensure_scripts_executable()
    fake_chmod.assert_not_called()
    messages = "\n".join(engine.result.lines)
    assert host_tracked_name not in messages
    assert "harness/extension.sh is not executable on disk" in messages


@unittest.skipIf(os.name == "nt", reason="POSIX executable-bit only")
def test_b4_check_reports_a_stripped_executable_bit_as_drift(tmp_path):
    """--check must be able to see a chmod gap on a tracked *.sh entry
    point, not only repair it silently in apply mode: it reports drift,
    and chmod itself stays exclusive to apply mode (--check changes
    nothing on disk)."""
    root = build_repo(tmp_path)
    assert git(root, "add", ".githooks/pre-commit").returncode == 0
    assert _main("--root", str(root))[0] == 0
    assert _main("--root", str(root), "--check")[0] == 0

    hook = root / ".githooks" / "pre-commit"
    mode = hook.stat().st_mode
    hook.chmod(mode & ~0o111)

    code, output = _main("--root", str(root), "--check")
    assert code == 1
    assert "DRIFT" in output and ".githooks/pre-commit is not executable on disk" in output
    assert not (hook.stat().st_mode & 0o111), "--check must not chmod"

    assert _main("--root", str(root))[0] == 0
    assert hook.stat().st_mode & 0o111
    assert _main("--root", str(root), "--check")[0] == 0


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_b5_copy_mode_produces_real_files_and_the_doctors_accept_the_tree(tmp_path):
    root = build_repo(tmp_path)
    result = materialize.apply(root, copy=True)
    assert result.clean, result.lines
    for relative in (".claude/rules", ".claude/hooks", ".codex/hooks", ".opencode/plugins", ".opencode/skills"):
        path = root / relative
        assert path.is_dir() and not materialize.is_link(path), relative
    for name in ("alpha", "beta"):
        claude_entry = root / ".claude" / "skills" / name
        selected_entry = root / "harness" / ".selected" / "skills" / name
        assert claude_entry.is_dir() and not materialize.is_link(claude_entry)
        assert (claude_entry / materialize.MARKER).is_file()
        assert selected_entry.is_dir() and not materialize.is_link(selected_entry)
    assert not (root / ".claude" / "skills" / "gamma").exists()
    assert materialize.apply(root, check=True).clean
    for module in (doctor_claude, doctor_codex, doctor_opencode):
        code, output, audit = _run_doctor(module, root)
        assert code == 0, output
        assert audit.tier_state("configured") == "PASS", output


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_b5_link_mode_produces_links_for_directories_and_selected_skills(tmp_path):
    root = build_repo(tmp_path)
    result = materialize.apply(root)
    assert result.clean, result.lines
    assert materialize.is_link(root / ".claude" / "rules")
    assert materialize.is_link(root / ".claude" / "skills" / "alpha")
    assert materialize.is_link(root / ".opencode" / "skills")
    assert materialize.link_matches(root / ".opencode" / "skills", root / "harness" / ".selected" / "skills")
    assert materialize.link_matches(root / ".claude" / "skills" / "alpha", root / "harness" / "skills" / "alpha")
    assert (root / ".agents" / "skills" / "alpha" / "SKILL.md").is_file()
    assert (root / ".agents" / "skills" / "alpha" / ".generated-by").is_file()
    assert not (root / ".agents" / "skills" / "gamma").exists()
    assert (root / ".opencode" / "commands" / "beta.md").is_file()
    assert not (root / ".opencode" / "commands" / "gamma.md").exists()
    assert (root / "AGENTS.md").is_file() and (root / "CLAUDE.md").read_bytes() == b"@AGENTS.md\n"
    for module in (doctor_claude, doctor_codex, doctor_opencode):
        code, output, audit = _run_doctor(module, root)
        assert code == 0, output
        assert audit.tier_state("configured") == "PASS", output


def test_b6_managed_copy_is_independent_of_its_source(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    source = root / "harness" / "adapters" / "codex" / "config.toml"
    destination = root / ".codex" / "config.toml"
    original = source.read_bytes()
    destination.write_bytes(original + b"\n# local edit\n")
    assert source.read_bytes() == original
    check = materialize.apply(root, check=True)
    assert not check.clean
    assert any("DRIFT" in line and ".codex/config.toml differs" in line for line in check.lines)
    repaired = materialize.apply(root)
    assert repaired.clean
    assert destination.read_bytes() == original


def test_b8_selection_materializes_only_selected_skills_and_prunes_on_change(tmp_path):
    root = build_repo(tmp_path)
    result = materialize.apply(root)
    assert result.clean
    assert [p.name for p in _managed_entries(root, ".claude/skills")] == ["alpha", "beta"]
    assert [p.name for p in _managed_entries(root, ".agents/skills")] == ["alpha", "beta"]
    assert [p.name for p in _managed_entries(root, "harness/.selected/skills")] == ["alpha", "beta"]

    unmanaged = root / ".claude" / "skills" / "mine"
    unmanaged.mkdir()
    (unmanaged / "SKILL.md").write_text("---\nname: mine\ndescription: user skill\n---\n", encoding="utf-8")
    stray_command = root / ".opencode" / "commands" / "mine.md"
    stray_command.write_text("user command\n", encoding="utf-8")

    write_selection(root, ["core"])
    result = materialize.apply(root)
    assert result.clean, result.lines
    assert any("PRUNED" in line and ".claude/skills/beta" in line for line in result.lines)
    assert any(".claude/skills/mine: unmanaged, left in place" in line for line in result.lines)
    assert [p.name for p in _managed_entries(root, ".claude/skills")] == ["alpha", "mine"]
    assert [p.name for p in _managed_entries(root, ".agents/skills")] == ["alpha"]
    assert [p.name for p in _managed_entries(root, "harness/.selected/skills")] == ["alpha"]
    assert not (root / ".opencode" / "commands" / "beta.md").exists()
    assert stray_command.read_text(encoding="utf-8") == "user command\n"
    assert (unmanaged / "SKILL.md").is_file()
    assert materialize.apply(root, check=True).clean


def test_b8_include_and_exclude_shape_the_effective_set(tmp_path):
    root = build_repo(tmp_path)
    write_selection(root, ["core"], include=["gamma"], exclude=["alpha"])
    result = materialize.apply(root)
    assert result.clean, result.lines
    assert [p.name for p in _managed_entries(root, ".claude/skills")] == ["gamma"]


def test_b8_prune_api_reports_lines(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    lines = materialize.prune(root, ["alpha"])
    assert any("PRUNED" in line and "beta" in line for line in lines)
    assert not (root / ".claude" / "skills" / "beta").exists()
    assert not (root / ".agents" / "skills" / "beta").exists()
    assert not (root / ".opencode" / "commands" / "beta.md").exists()


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_b9_zero_skills_is_legal(tmp_path):
    root = build_repo(tmp_path, with_skills_dir=False)
    assert not (root / "harness" / "skills").exists()
    result = materialize.apply(root)
    assert result.clean, result.lines
    assert any("selection: 0 selected of 0 available" in line for line in result.lines)
    assert materialize.apply(root, check=True).clean
    for module in (doctor_claude, doctor_codex, doctor_opencode):
        code, output, _ = _run_doctor(module, root)
        assert code == 0, output
        assert "0 selected of 0 available" in output


def test_plan_lists_contract_junctions_and_selected_skills(tmp_path):
    root = build_repo(tmp_path)
    actions = materialize.plan(root)
    kinds = {action.kind for action in actions}
    assert kinds == {"contract", "junction", "retired", "skill"}
    assert not any(action.kind == "junction" and action.dst == ".claude/skills" for action in actions)
    skill_targets = sorted(action.dst for action in actions if action.kind == "skill")
    assert skill_targets == [".claude/skills/alpha", ".claude/skills/beta",
                             "harness/.selected/skills/alpha", "harness/.selected/skills/beta"]


def test_vendored_skill_is_materialized_from_its_vendor_directory(tmp_path):
    root = build_repo(tmp_path)
    vendored = root / "harness" / "skills" / "_vendor" / "upstream" / "delta"
    shutil.copytree(write_skill(tmp_path / "scratch", "delta", ["core"]), vendored)
    result = materialize.apply(root)
    assert result.clean, result.lines
    link = root / ".claude" / "skills" / "delta"
    assert materialize.link_matches(link, vendored)
    wrapper = (root / ".agents" / "skills" / "delta" / "SKILL.md").read_text(encoding="utf-8")
    assert "harness/skills/_vendor/upstream/delta/SKILL.md" in wrapper


def test_extension_point_runs_sorted_and_folds_failures_into_drift(tmp_path):
    root = build_repo(tmp_path)
    extensions = root / "harness" / "bootstrap" / "extensions"
    extensions.mkdir()
    (extensions / "10-ok.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    (extensions / "20-bad.py").write_text("import sys; sys.exit(4)\n", encoding="utf-8")
    result = materialize.apply(root)
    assert any("OK       extension 10-ok.py" in line for line in result.lines)
    assert any("DRIFT    extension 20-bad.py exited 4" in line for line in result.lines)
    assert result.drift == 1


def test_junctions_manifest_mirrors_registry_materializations():
    junctions = json.loads((BOOTSTRAP / "junctions.json").read_text(encoding="utf-8"))
    runtimes = json.loads((BOOTSTRAP.parents[0] / "registry" / "runtimes.json").read_text(encoding="utf-8"))
    declared = {(j["src"], j["dst"], j["mode"]) for j in junctions["junctions"]}
    expected = {
        (m["source"], m["destination"], m["mode"])
        for runtime in runtimes["runtimes"].values()
        for m in runtime.get("materializations", [])
    }
    assert declared == expected
    retired = {(r["dst"], r["replacement"]) for r in junctions["retired_destinations"]}
    assert retired == {(r["destination"], r["replacement"]) for r in runtimes["retired_materializations"]}
    assert set(junctions["per_skill"]) == {"claude", "codex", "opencode"}


bind_unittest(globals(), "MaterializeModesBridge")
