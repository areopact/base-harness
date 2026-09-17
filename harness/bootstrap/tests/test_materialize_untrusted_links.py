"""Windows Redirection Guard: a junction the elevated process cannot traverse
(Win32 448) is drift in check mode and is recreated in apply mode, a blocked
registry preflight repairs the links first and runs again, and the doctors
name the remedy. The probe is mocked so every platform exercises the logic."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import BOOTSTRAP, bind_unittest, build_repo

sys.path.insert(0, str(BOOTSTRAP))
import doctor_claude  # noqa: E402
import materialize  # noqa: E402

NEEDS_TOMLLIB = sys.version_info < (3, 11)


def _blocked_only(*names: str):
    """A probe that reports a link as blocked when its last path component is one of names."""
    def probe(path) -> bool:
        return Path(path).name in names
    return probe


def _snapshot(root: Path) -> dict[str, bytes]:
    files = {}
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def _run_doctor(module, root: Path) -> tuple[int, str]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = module.main(["--offline", "--root", str(root)])
    return code, stream.getvalue()


def test_untrusted_mount_point_is_recognized_by_winerror_only():
    assert materialize.is_untrusted_mount_point(SimpleNamespace(winerror=448))
    assert not materialize.is_untrusted_mount_point(SimpleNamespace(winerror=5))
    assert not materialize.is_untrusted_mount_point(OSError(22, "no winerror attribute here"))


def test_link_blocked_is_false_for_a_traversable_link_and_a_real_directory(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    assert not materialize.link_blocked(root / ".claude" / "rules")
    assert not materialize.link_blocked(root / "harness" / "rules")


def test_blocked_link_is_drift_in_check_mode_and_nothing_changes(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    before = _snapshot(root)
    with mock.patch.object(materialize, "link_blocked", side_effect=_blocked_only("rules")):
        result = materialize.apply(root, check=True)
    assert result.drift >= 1
    assert any("DRIFT" in line and ".claude/rules" in line and "Redirection Guard" in line for line in result.lines)
    assert _snapshot(root) == before


def test_blocked_link_is_recreated_in_apply_mode_and_the_target_survives(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    target = root / "harness" / "rules" / "README.md"
    content = target.read_bytes()
    with mock.patch.object(materialize, "link_blocked", side_effect=_blocked_only("rules")):
        result = materialize.apply(root)
    assert any(
        "SYNCED" in line and ".claude/rules" in line and "untrusted junction recreated" in line
        for line in result.lines
    )
    assert materialize.is_link(root / ".claude" / "rules")
    assert materialize.link_matches(root / ".claude" / "rules", root / "harness" / "rules")
    assert target.read_bytes() == content
    assert materialize.apply(root, check=True).clean


def test_blocked_skill_link_is_drift_then_recreated_per_skill(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    with mock.patch.object(materialize, "link_blocked", side_effect=_blocked_only("alpha")):
        check = materialize.apply(root, check=True)
        assert any(
            "DRIFT" in line and ".claude/skills/alpha" in line and "Redirection Guard" in line
            for line in check.lines
        )
        result = materialize.apply(root)
    assert any(
        "SYNCED" in line and ".claude/skills/alpha" in line and "untrusted junction recreated" in line
        for line in result.lines
    )
    assert materialize.apply(root, check=True).clean


def test_blocked_preflight_repairs_links_first_then_runs_again(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    engine = materialize.Engine(root, check=False, force=False, copy=False)
    calls: list[int] = []

    def preflight():
        calls.append(1)
        if len(calls) == 1:
            engine.preflight_blocked_path = ".claude/agents"
            return "blocked"
        return True

    with mock.patch.object(engine, "registry_preflight", side_effect=preflight), \
            mock.patch.object(materialize, "link_blocked", side_effect=_blocked_only("agents")):
        result = engine.run()
    assert len(calls) == 2
    assert any("NOTE" in line and ".claude/agents" in line and "repairing the links" in line for line in result.lines)
    assert any(
        "SYNCED" in line and ".claude/agents" in line and "untrusted junction recreated" in line
        for line in result.lines
    )
    assert not any("bootstrap made no changes" in line for line in result.lines)
    # A repaired block is not an unresolved item: the apply run ends clean (exit 0).
    assert result.clean, result.lines


def test_blocked_preflight_in_check_mode_reports_and_changes_nothing(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    before = _snapshot(root)
    engine = materialize.Engine(root, check=True, force=False, copy=False)
    with mock.patch.object(engine, "registry_preflight", return_value="blocked"), \
            mock.patch.object(materialize, "link_blocked", side_effect=_blocked_only("agents")):
        result = engine.run()
    assert any("DRIFT" in line and "registry preflight" in line and "Redirection Guard" in line for line in result.lines)
    assert any("DRIFT" in line and ".claude/agents" in line and "Redirection Guard" in line for line in result.lines)
    assert any("bootstrap made no changes" in line for line in result.lines)
    assert not result.clean
    assert _snapshot(root) == before


@unittest.skipIf(NEEDS_TOMLLIB, "requires Python 3.11+ (tomllib is stdlib-only from 3.11)")
def test_doctor_reports_a_blocked_link_and_blocked_skill_links_with_the_remedy(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    with mock.patch.object(materialize, "link_blocked", side_effect=_blocked_only("rules", "alpha")):
        code, output = _run_doctor(doctor_claude, root)
    assert code == 1
    assert ".claude/rules cannot be traversed by this elevated process" in output
    assert "run bootstrap from an elevated shell" in output
    assert ".claude/skills: 1 skill link(s) cannot be traversed" in output
    assert "alpha" in output
    assert "missing alpha" not in output


def test_a_blocked_link_is_classified_before_any_stat_that_follows_it(tmp_path):
    """Path.exists() follows the link and raises under the guard, so the engine
    and the doctor must decide on is_link (an lstat) first. Here exists() is
    made to explode for the link itself; a correct ordering never calls it."""
    root = build_repo(tmp_path)
    materialize.apply(root)
    real_exists = Path.exists

    def exists(self, *args, **kwargs):
        if self.name == "rules" and self.parent.name == ".claude":
            raise RuntimeError("exists() followed the link before is_link() classified it")
        return real_exists(self, *args, **kwargs)

    with mock.patch.object(Path, "exists", exists), \
            mock.patch.object(materialize, "link_blocked", side_effect=_blocked_only("rules")):
        result = materialize.apply(root, check=True)
        code, output = _run_doctor(doctor_claude, root)
    assert any("DRIFT" in line and ".claude/rules" in line and "Redirection Guard" in line for line in result.lines)
    assert code == 1
    assert ".claude/rules cannot be traversed by this elevated process" in output


bind_unittest(globals(), "MaterializeUntrustedLinksBridge")
