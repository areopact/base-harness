"""Shell entry points: execute-probe (B10) and hooksPath chaining (B11)."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import bash_executable, bind_unittest, build_repo, git, powershell_executable, run_bootstrap_ps1, run_bootstrap_sh


def _githooks_snapshot(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in (root / ".githooks").iterdir() if p.is_file()}


@unittest.skipIf(bash_executable() is None, reason="no usable bash on this host")
def test_b11_bootstrap_sh_chains_a_prior_hooks_path(tmp_path):
    root = build_repo(tmp_path)
    (root / "myhooks").mkdir()
    assert git(root, "config", "--local", "core.hooksPath", "myhooks").returncode == 0
    before = _githooks_snapshot(root)

    completed = run_bootstrap_sh(root)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "chained prior hooks path" in completed.stdout
    assert git(root, "config", "--local", "harness.chainedHooksPath").stdout.strip() == "myhooks"
    assert git(root, "config", "--local", "core.hooksPath").stdout.strip() == ".githooks"
    assert _githooks_snapshot(root) == before
    assert run_bootstrap_sh(root, "--check").returncode == 0


@unittest.skipIf(bash_executable() is None, reason="no usable bash on this host")
def test_b11_bootstrap_sh_warns_outside_a_git_repository_and_stays_clean(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    completed = run_bootstrap_sh(root, "--copy")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "  WARN     not a git repository" in completed.stdout
    assert "run git init, then rerun bootstrap" in completed.stdout
    assert "DRIFT" not in completed.stdout


@unittest.skipIf(bash_executable() is None, reason="no usable bash on this host")
def test_bootstrap_sh_exit_codes_for_unknown_flag_and_missing_manifest(tmp_path):
    root = build_repo(tmp_path)
    assert run_bootstrap_sh(root, "--bogus").returncode == 2
    (root / "harness" / "bootstrap" / "junctions.json").unlink()
    assert run_bootstrap_sh(root, "--check").returncode == 3


@unittest.skipIf(bash_executable() is None, reason="no usable bash on this host")
def test_bootstrap_sh_check_detects_seeded_drift(tmp_path):
    root = build_repo(tmp_path)
    assert run_bootstrap_sh(root).returncode == 0
    assert run_bootstrap_sh(root, "--check").returncode == 0
    settings = root / ".claude" / "settings.json"
    settings.write_bytes(settings.read_bytes() + b"\n")
    completed = run_bootstrap_sh(root, "--check")
    assert completed.returncode == 1
    assert ".claude/settings.json differs" in completed.stdout


@unittest.skipIf(powershell_executable() is None, reason="no PowerShell on this host")
def test_b11_bootstrap_ps1_chains_a_prior_hooks_path_with_the_same_verdict(tmp_path):
    root = build_repo(tmp_path)
    (root / "myhooks").mkdir()
    assert git(root, "config", "--local", "core.hooksPath", "myhooks").returncode == 0

    completed = run_bootstrap_ps1(root)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "chained prior hooks path" in completed.stdout
    assert git(root, "config", "--local", "harness.chainedHooksPath").stdout.strip() == "myhooks"
    assert git(root, "config", "--local", "core.hooksPath").stdout.strip() == ".githooks"
    assert run_bootstrap_ps1(root, "-Check").returncode == 0
    settings = root / ".claude" / "settings.json"
    settings.write_bytes(settings.read_bytes() + b"\n")
    assert run_bootstrap_ps1(root, "-Check").returncode == 1


@unittest.skipIf(
    sys.platform == "win32",
    reason="Git Bash on Windows resolves python candidates through Windows PATH semantics (.exe lookup and app execution aliases); the stub-on-PATH shape is exercised on POSIX CI only",
)
def test_b10_execute_probe_skips_a_python_that_exits_nonzero(tmp_path):
    root = build_repo(tmp_path)
    shims = tmp_path / "shims"
    shims.mkdir()
    stub = shims / "python3"
    stub.write_text("#!/bin/sh\nexit 49\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    working = shims / "python"
    working.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    working.chmod(working.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = dict(os.environ)
    env["PATH"] = f"{shims}{os.pathsep}{env.get('PATH', '')}"

    completed = subprocess.run(
        [bash_executable(), (root / "harness" / "bootstrap" / "bootstrap.sh").as_posix(), "--check"],
        cwd=str(root), env=env, capture_output=True, text=True, check=False,
    )

    assert completed.returncode != 2, completed.stdout + completed.stderr
    assert f"bootstrap: python = {working}" in completed.stdout


@unittest.skipIf(
    sys.platform == "win32",
    reason="POSIX-only companion to the execute-probe test",
)
def test_b10_execute_probe_exits_2_when_every_candidate_is_broken(tmp_path):
    root = build_repo(tmp_path)
    shims = tmp_path / "shims"
    shims.mkdir()
    for name in ("python3", "python", "py"):
        stub = shims / name
        stub.write_text("#!/bin/sh\nexit 49\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    env = {"PATH": str(shims) + os.pathsep + "/usr/bin:/bin", "HOME": str(tmp_path)}
    completed = subprocess.run(
        [bash_executable(), (root / "harness" / "bootstrap" / "bootstrap.sh").as_posix(), "--check"],
        cwd=str(root), env=env, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 2
    assert "no working Python 3" in completed.stderr


bind_unittest(globals(), "BootstrapShellBridge")
