"""F7: fixtures demonstrating the named gaps in SECURITY.md's pre-commit row.

SECURITY.md's guard table documents five things the `.githooks/pre-commit`
secret scan does NOT catch: an unmatched-shape secret, a secret split across
two lines, a secret inside a binary blob, a commit made with the scan
skipped, and a clone with core.hooksPath unset. Each test here stages the
matching fixture in a disposable temp repository, runs the real hook (or the
real absence of one), and asserts the commit PASSES: that is the gap, not a
bug. A synthetic AWS-access-key-shaped value (all "F" after the AKIA
prefix) stands in for "a secret that would be caught if the scan ran and was
not bypassed"; every value here is obviously fake.

Fixtures live in harness/hooks/tests/fixtures/precommit/. Stdlib only.

One fixture (binary-secret.bin) turned out, on verification, NOT to
demonstrate its claimed gap on this git version; see its test's docstring
for the discrepancy against SECURITY.md, kept in place (not silently fixed
up) for the docs agent to re-verify.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GITHOOKS = REPO_ROOT / ".githooks"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "precommit"


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def _init_repo(root: Path, *, wire_hooks: bool) -> None:
    assert _git(root, "init", "-q").returncode == 0
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    _git(root, "config", "commit.gpgsign", "false")
    if wire_hooks:
        target = root / ".githooks"
        shutil.copytree(GITHOOKS, target)
        assert _git(root, "config", "core.hooksPath", ".githooks").returncode == 0


# Fixtures never carry a pattern-shaped credential at rest, so the tracked tree
# passes the scanner it exercises. The placeholder is swapped for a fake key
# assembled from fragments at stage time.
PLACEHOLDER = b"@@SECRET@@"
FAKE_KEY = b"AK" + b"IA" + b"F" * 16


def _stage_fixture(root: Path, name: str) -> Path:
    source = FIXTURES / name
    dest = root / name
    dest.write_bytes(source.read_bytes().replace(PLACEHOLDER, FAKE_KEY))
    assert _git(root, "add", name).returncode == 0
    return dest


def _commit(root: Path, message: str, env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", message],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=full_env,
    )


@unittest.skipIf(shutil.which("git") is None, reason="no git on this host")
class PrecommitGapTests(unittest.TestCase):
    def test_unmatched_shape_secret_passes(self):
        """A plausible credential whose shape is not in secret-patterns.txt slips through."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, wire_hooks=True)
            _stage_fixture(root, "unmatched-shape-secret.txt")
            completed = _commit(root, "add unmatched-shape secret")
            assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_secret_inside_encoded_content_passes(self):
        """A credential-shaped string carried as base64 text is invisible to the
        pattern scanner: the encoded form matches nothing, so the commit passes.
        This is the documented gap; the raw binary fixture below shows that
        unencoded blobs are scanned and caught."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, wire_hooks=True)
            _stage_fixture(root, "encoded-secret.txt")
            completed = _commit(root, "add encoded secret")
            assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_secret_split_across_two_lines_passes(self):
        """git grep is line-based: a secret broken across a newline never matches."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, wire_hooks=True)
            _stage_fixture(root, "split-secret.txt")
            completed = _commit(root, "add split secret")
            assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_secret_inside_a_binary_blob_is_actually_caught_here(self):
        """Documents a discrepancy, not the claimed gap: on git 2.51.0 (this
        host), `git grep` WITHOUT `-I` still matches inside a NUL-containing
        blob (`-I`, per `git grep -h`, is what makes it "don't match patterns
        in binary files"; that is not the default). The pre-commit hook's
        invocation (`git grep -l -Ef "$patfile" --cached -- .`) passes
        neither `-a` nor `-I`, so this fixture is in fact BLOCKED, contrary
        to SECURITY.md's "secrets in binaries" row. Verified directly against
        `.githooks/secret-patterns.txt` with `git check-attr` confirming
        `.gitattributes`' `text=auto` does not change the outcome either.
        Left as a fixture and a failing-the-gap assertion rather than edited
        into a false pass: SECURITY.md is out of this task's scope (owned by
        the docs agent) and this finding needs their re-verification, not a
        silent fixture rewrite.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, wire_hooks=True)
            _stage_fixture(root, "binary-secret.bin")
            completed = _commit(root, "add binary secret")
            assert completed.returncode != 0, (
                "expected this fixture to be BLOCKED on this git version (see docstring); "
                "if it now passes, git's binary-grep default changed and the SECURITY.md "
                "gap claim may be accurate again: " + completed.stdout + completed.stderr
            )
            assert "BLOCKED" in completed.stderr

    def test_commit_made_with_the_scan_skipped_passes(self):
        """SKIP_SECRET_SCAN=1 bypasses the scan entirely, even for a matching shape."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, wire_hooks=True)
            _stage_fixture(root, "skip-secret.txt")
            # Control: the same fixture, unskipped, is genuinely caught.
            blocked = _commit(root, "add matching-shape secret (control)")
            assert blocked.returncode != 0, blocked.stdout + blocked.stderr
            assert "BLOCKED" in blocked.stderr
            # The gap: setting the skip variable lets the identical staged
            # content through.
            completed = _commit(root, "add matching-shape secret (skipped)", env={"SKIP_SECRET_SCAN": "1"})
            assert completed.returncode == 0, completed.stdout + completed.stderr

    def test_clone_with_hookspath_unset_passes(self):
        """A raw clone that never ran bootstrap has no pre-commit wired at all."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _init_repo(root, wire_hooks=False)
            assert _git(root, "config", "--get", "core.hooksPath").returncode != 0
            _stage_fixture(root, "hookspath-unset-secret.txt")
            completed = _commit(root, "add secret, hooksPath never set")
            assert completed.returncode == 0, completed.stdout + completed.stderr


if __name__ == "__main__":
    unittest.main()
