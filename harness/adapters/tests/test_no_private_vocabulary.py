"""Nothing under harness/adapters or harness/agents/README.md carries private
vocabulary, non-ASCII punctuation, carriage returns, or a byte-order mark.

Two layers, the same shape as the tool-module guard under harness/tools/tests.
The structural layer runs deidentify_lint's content checks (D1 to D6) over
every text file in the scan roots; those checks need no term list. The term
layer runs only when the maintainer points HARNESS_DEIDENTIFY_TERMS at a
private term file kept outside this repository; the list itself is never
shipped, so this test cannot leak it. Without the variable the term layer is
skipped and says so.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from ._paths import ADAPTERS, ROOT, bind_unittest

TOOLS = ROOT / "harness" / "tools"
# The tools directory holds a module named selector.py; keep it at the tail of
# sys.path so the stdlib select module wins, and pin that module now.
sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != TOOLS]
sys.path.append(str(TOOLS))
import selectors  # noqa: E402,F401  (imports the stdlib select module)

import deidentify_lint as dl  # noqa: E402

SCAN_ROOTS = [ADAPTERS, ROOT / "harness" / "agents" / "README.md"]
TEXT_SUFFIXES = {".md", ".py", ".sh", ".ps1", ".json", ".toml", ".js", ".rules", ".gitkeep", ""}
STRUCTURAL_CHECKS = {"D1", "D2", "D3", "D4", "D5", "D6"}
# Issue-tracker identifiers betray a private origin regardless of the term
# list; well-known standard prefixes are not tickets.
TICKET_SHAPE = re.compile(r"\b(?!(?:SHA|MD|RSA|AES|UTF|ISO|RFC|CVE|HMAC|BSD)-)[A-Z]{2,4}-\d{1,5}\b(?![.\d-])")


def _files():
    for root in SCAN_ROOTS:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in TEXT_SUFFIXES:
                yield path


def _findings(path: Path, terms: list, structural_only: bool) -> list:
    rel = path.relative_to(ROOT).as_posix()
    allowed = dl.allowed_first_segments(ROOT)
    return dl.scan_content(rel, path.read_bytes(), terms, allowed, structural_only)


def test_scan_covers_the_adapter_tree():
    files = list(_files())
    names = {p.name for p in files}
    assert "settings.base.json" in names and "harness-bridge.js" in names and "README.md" in names
    assert len(files) >= 20, "the scan found too few files; is the tree in place?"


def test_structural_checks_are_clean():
    problems = {}
    for path in _files():
        found = [item.render() for item in _findings(path, [], True) if item.check in STRUCTURAL_CHECKS]
        if found:
            problems[path.relative_to(ROOT).as_posix()] = found
    assert problems == {}, problems


def test_ticket_shapes_are_absent():
    problems = {}
    for path in _files():
        hit = TICKET_SHAPE.search(path.read_text(encoding="utf-8", errors="replace"))
        if hit:
            problems[path.relative_to(ROOT).as_posix()] = hit.group(0)
    assert problems == {}, problems


def test_term_list_when_supplied_has_zero_hits():
    location = os.environ.get("HARNESS_DEIDENTIFY_TERMS")
    if not location:
        return
    terms_path = Path(location)
    assert terms_path.is_file(), f"HARNESS_DEIDENTIFY_TERMS does not name a file: {location}"
    terms = dl.load_terms(terms_path)
    assert terms, "the supplied term file is empty"
    hits = []
    for path in _files():
        hits.extend(item.render() for item in _findings(path, terms, False) if item.check == "TERM")
    assert hits == [], hits


bind_unittest(globals(), "PrivateVocabularyBridge")
