"""No persistent output is staged in a tempfile.mkdtemp directory.

Since Python 3.13 on Windows, mkdtemp's 0o700 becomes a protected owner-only
ACL, and under an elevated token the owner is the Administrators group. A
directory (or a file created inside it and moved out) produced from an
elevated shell is then unreadable and undeletable once the shell runs at
medium integrity again. Generated catalogs, skill links, and vendored files
therefore stage with a plain mkdir that inherits the parent's ACL. Tests may
still use mkdtemp for throwaway fixtures."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# mkdtemp and TemporaryDirectory (which calls it) and any explicit 0o700 mkdir:
# Python 3.13 applies the owner-only ACL to os.mkdir with mode 0o700.
PATTERN = re.compile(
    r"\btempfile\.mkdtemp\(|\bTemporaryDirectory\(|\bfrom tempfile import[^\n]*\b(mkdtemp|TemporaryDirectory)\b"
    r"|\bmkdir\([^)\n]*\b0o700\b|\bmode\s*=\s*0o700\b"
)


def _production_sources():
    for path in sorted((ROOT / "harness").rglob("*.py")):
        parts = path.relative_to(ROOT).parts
        if any(part in {"tests", "export_tests", "__pycache__"} or part.startswith("test_") for part in parts):
            continue
        yield path


def test_no_production_module_stages_in_mkdtemp():
    offenders = [
        f"{path.relative_to(ROOT).as_posix()}:{number}"
        for path in _production_sources()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if PATTERN.search(line) and not line.lstrip().startswith("#")
    ]
    assert offenders == [], "stage with a plain mkdir instead of tempfile.mkdtemp: " + ", ".join(offenders)


def test_the_scan_sees_the_catalog_writer():
    names = {path.name for path in _production_sources()}
    assert "build_codex_adapter.py" in names and "links.py" in names
