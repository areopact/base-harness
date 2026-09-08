"""Data-loss invariants of the materialization engine (B1, B2, B3, B13)."""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import BOOTSTRAP, bind_unittest, build_repo

sys.path.insert(0, str(BOOTSTRAP))
import materialize  # noqa: E402


def _seed_manifest(root: Path, destinations: list[str]) -> None:
    document = {
        "schema_version": 1,
        "junctions": [
            {"src": "harness/rules", "dst": dst, "mode": "link", "runtime": "all", "description": "seeded"}
            for dst in destinations
        ],
        "retired_destinations": [],
        "per_skill": {},
    }
    (root / "harness" / "bootstrap" / "junctions.json").write_text(json.dumps(document), encoding="utf-8")


def _snapshot(root: Path) -> dict[str, bytes]:
    files = {}
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def test_b1_empty_and_root_destinations_are_refused_and_nothing_is_removed(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    canary = root / "canary.txt"
    canary.write_bytes(b"still here\n")
    _seed_manifest(root, ["", "."])
    before = _snapshot(root)

    result = materialize.apply(root)

    assert result.drift > 0
    aborts = [line for line in result.lines if line.startswith("  ABORT")]
    assert any("refusing dangerous or empty destination ''" in line for line in aborts)
    assert any("refusing dangerous or empty destination '.'" in line for line in aborts)
    assert canary.read_bytes() == b"still here\n"
    after = _snapshot(root)
    removed = set(before) - set(after)
    assert removed == set(), f"files removed: {sorted(removed)}"


def test_b2_destination_outside_root_is_refused(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    outside = tmp_path / "escape"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"outside\n")
    _seed_manifest(root, ["../escape", "../escape/../escape"])

    result = materialize.apply(root)

    assert result.drift >= 2
    assert any("refusing dangerous or empty destination '../escape'" in line for line in result.lines)
    assert (outside / "keep.txt").read_bytes() == b"outside\n"
    assert materialize.safe_destination(root, "../escape") is None
    assert materialize.safe_destination(root, "/absolute") is None
    assert materialize.safe_destination(root, "C:/absolute") is None
    assert materialize.safe_destination(root, ".claude/rules") is not None


def test_b3_unmanaged_real_directory_is_never_removed(tmp_path):
    root = build_repo(tmp_path)
    blocker = root / ".claude" / "rules"
    blocker.mkdir(parents=True)
    (blocker / "mine.md").write_bytes(b"user content\n")

    default = materialize.apply(root)
    assert default.conflicts >= 1
    assert any("CONFLICT" in line and ".claude/rules" in line for line in default.lines)
    assert (blocker / "mine.md").read_bytes() == b"user content\n"

    forced = materialize.apply(root, force=True)
    assert forced.conflicts >= 1
    assert any("refusing to recursively remove" in line and ".claude/rules" in line for line in forced.lines)
    assert blocker.is_dir() and not materialize.is_link(blocker)
    assert (blocker / "mine.md").read_bytes() == b"user content\n"


def test_b3_check_mode_reports_the_unmanaged_directory_as_drift_without_touching_it(tmp_path):
    root = build_repo(tmp_path)
    blocker = root / ".claude" / "rules"
    blocker.mkdir(parents=True)
    (blocker / "mine.md").write_bytes(b"user content\n")
    result = materialize.apply(root, check=True)
    assert result.drift >= 1
    assert (blocker / "mine.md").read_bytes() == b"user content\n"


def test_manifest_parse_failure_aborts_with_exit_3_not_zero_entries(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    (root / "harness" / "bootstrap" / "junctions.json").write_text("{not json", encoding="utf-8")
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = materialize.main(["--root", str(root)])
    assert code == materialize.EXIT_MANIFEST == 3
    assert "ABORT" in out.getvalue()
    assert "manifest parse error" in err.getvalue()


def test_manifest_missing_aborts_with_exit_3(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    (root / "harness" / "bootstrap" / "junctions.json").unlink()
    assert materialize.main(["--root", str(root)]) == 3


def test_main_refuses_below_the_python_311_floor(tmp_path):
    """README says bootstrap refuses to run below Python 3.11; bootstrap.sh
    and bootstrap.ps1 only probe for a working Python 3 and delegate here,
    so this module must be the one that actually enforces the floor, before
    doing anything else (argument parsing, manifest reads, ...)."""
    from unittest import mock

    root = build_repo(tmp_path, with_git=False)
    out, err = StringIO(), StringIO()
    with mock.patch.object(materialize.sys, "version_info", (3, 10, 6, "final", 0)):
        with redirect_stdout(out), redirect_stderr(err):
            code = materialize.main(["--root", str(root)])
    assert code == materialize.EXIT_PREREQ == 2
    assert "Python 3.11+ is required" in err.getvalue()
    assert out.getvalue() == ""


def test_b13_replacing_a_stale_link_never_touches_the_link_target(tmp_path):
    """The hazard behind non-recursive unlinking: a junction to an external
    directory is replaced, and the external directory's contents survive."""
    root = build_repo(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    (external / "precious.txt").write_bytes(b"precious\n")
    stale = root / ".claude" / "rules"
    stale.parent.mkdir(parents=True, exist_ok=True)
    materialize.make_link(external, stale)
    assert materialize.is_link(stale)

    result = materialize.apply(root)

    assert any("SYNCED" in line and ".claude/rules" in line and "stale link replaced" in line for line in result.lines)
    assert materialize.link_matches(stale, root / "harness" / "rules")
    assert (external / "precious.txt").read_bytes() == b"precious\n"
    assert sorted(p.name for p in external.iterdir()) == ["precious.txt"]


def test_b13_shell_entry_points_carry_no_recursive_removal_or_hardlinks():
    posix = (BOOTSTRAP / "bootstrap.sh").read_text(encoding="utf-8")
    windows = (BOOTSTRAP / "bootstrap.ps1").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s*rm\s+-r", posix) is None
    assert re.search(r"(?im)^\s*Remove-Item\b[^\r\n]*-Recurse\b", windows) is None
    assert "New-Item -ItemType HardLink" not in windows
    assert "ln " not in posix.replace("ln -s", "")  # no hardlink creation in the wrapper
    for text in (posix, windows):
        assert "materialize.py" in text
        assert 'import sys; sys.exit(0)' in text


def test_b13_engine_only_recursively_removes_marker_carrying_directories():
    """Every shutil.rmtree call in the engine is guarded by a marker or generator check."""
    source = (BOOTSTRAP / "materialize.py").read_text(encoding="utf-8")
    lines = source.splitlines()
    calls = [index for index, line in enumerate(lines) if "shutil.rmtree(" in line]
    assert calls, "expected the prune paths to use shutil.rmtree"
    for index in calls:
        window = "\n".join(lines[max(0, index - 14): index + 1])
        assert "MARKER" in window or "is_generated_dir" in window, lines[index]


def test_managed_copy_never_becomes_a_hardlink_or_symlink(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    src = root / "harness" / "adapters" / "claude" / "settings.base.json"
    dst = root / ".claude" / "settings.json"
    assert dst.is_file() and not dst.is_symlink()
    assert not os.path.samefile(src, dst)
    dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        return
    check = materialize.apply(root, check=True)
    assert any("hardlink" in line and ".claude/settings.json" in line for line in check.lines)
    repaired = materialize.apply(root)
    assert any("hardlink replaced" in line for line in repaired.lines)
    assert not os.path.samefile(src, dst)


bind_unittest(globals(), "MaterializeSafetyBridge")
