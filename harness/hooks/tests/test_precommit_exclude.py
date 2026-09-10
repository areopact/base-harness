"""F8: .githooks/secret-scan-exclude.txt removes a host's declared evidence tree from the pre-commit
scans and nothing else. Stdlib only; each test runs the real hook in a disposable repository."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GITHOOKS = REPO_ROOT / ".githooks"

# Assembled from fragments so this file never carries a pattern-shaped credential at rest.
FAKE_KEY = "AK" + "IA" + "F" * 16


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _init_repo(root: Path) -> None:
    assert _git(root, "init", "-q").returncode == 0
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    _git(root, "config", "commit.gpgsign", "false")
    shutil.copytree(GITHOOKS, root / ".githooks")
    assert _git(root, "config", "core.hooksPath", ".githooks").returncode == 0


def _stage(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    assert _git(root, "add", rel).returncode == 0


def _commit(root: Path, message: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("SKIP_SECRET_SCAN", None)
    return subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", check=False, env=env)


@unittest.skipIf(shutil.which("git") is None, reason="no git on this host")
class PrecommitExcludeTests(unittest.TestCase):
    def test_declared_evidence_tree_leaves_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _stage(root, "docs/evidence/config.txt", f"token = {FAKE_KEY}\n")
            blocked = _commit(root, "evidence without an exclusion")
            assert blocked.returncode != 0 and "BLOCKED" in blocked.stderr, blocked.stderr
            (root / ".githooks" / "secret-scan-exclude.txt").write_text(
                "# received material, never edited\n\ndocs/evidence/\n", encoding="utf-8", newline="\n")
            passed = _commit(root, "evidence with the exclusion")
            assert passed.returncode == 0, passed.stdout + passed.stderr

    def test_exclusion_never_covers_the_hosts_own_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            (root / ".githooks" / "secret-scan-exclude.txt").write_text("docs/evidence/\n", encoding="utf-8", newline="\n")
            _stage(root, "docs/evidence/keep.txt", "plain\n")
            _stage(root, "docs/mine.txt", f"token = {FAKE_KEY}\n")
            blocked = _commit(root, "a secret outside the excluded tree")
            assert blocked.returncode != 0 and "docs/mine.txt" in blocked.stderr, blocked.stderr
            assert "docs/evidence/keep.txt" not in blocked.stderr

    def test_exclusion_applies_to_the_filename_scan_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root)
            _stage(root, "docs/evidence/.env", "SETTING=value\n")
            blocked = _commit(root, "a secret-bearing filename in evidence")
            assert blocked.returncode != 0 and "BLOCKED" in blocked.stderr, blocked.stderr
            (root / ".githooks" / "secret-scan-exclude.txt").write_text("docs/evidence/\r\n", encoding="utf-8", newline="")
            passed = _commit(root, "the same name, excluded, with a CRLF line")
            assert passed.returncode == 0, passed.stdout + passed.stderr


if __name__ == "__main__":
    unittest.main()
