"""The eight tool modules carry no private vocabulary.

Two layers. The structural layer runs deidentify_lint's content checks for
email addresses, user-directory paths, attribution strings, and non-ASCII
punctuation over every tool file. The term layer runs only when the
maintainer points HARNESS_DEIDENTIFY_TERMS at a private term file that lives
outside this repository; the list itself is never shipped, so the public test
cannot leak it. Without the variable the term layer is skipped and says so.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ._repo import ROOT, TOOLS, install_bridge  # noqa: F401

import deidentify_lint as dl

TOOL_FILES = (
    "routing_policy.py",
    "native_routing.py",
    "workflow.py",
    "workflow_state.py",
    "gen_manifest.py",
    "lint.py",
    "resolver_lint.py",
    "skill_usage.py",
)
STRUCTURAL_CHECKS = {"D1", "D4", "D5", "D6"}
# Shapes that betray a private origin regardless of the term list.
PRIVATE_SHAPES = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"[A-Za-z]:\\+Users\\+|/Users/|/home/[a-z]"),
    re.compile(r"\b(?!(?:SHA|MD|RSA|AES|UTF|ISO|RFC|CVE|HMAC|BSD)-)[A-Z]{2,4}-\d{1,5}\b(?![.\d-])"),
)


def _findings(relative: str) -> list:
    data = (TOOLS / relative).read_bytes()
    allowed = dl.allowed_first_segments(ROOT)
    return [
        item for item in dl.scan_content(f"harness/tools/{relative}", data, [], allowed, True)
        if item.check in STRUCTURAL_CHECKS
    ]


def test_structural_checks_are_clean():
    for relative in TOOL_FILES:
        found = _findings(relative)
        assert found == [], [item.render() for item in found]


def test_private_shapes_are_absent():
    for relative in TOOL_FILES:
        text = (TOOLS / relative).read_text(encoding="utf-8")
        for pattern in PRIVATE_SHAPES:
            hit = pattern.search(text)
            assert hit is None, f"{relative}: {hit.group(0)!r}"


def test_term_list_when_supplied_has_zero_hits():
    location = os.environ.get("HARNESS_DEIDENTIFY_TERMS")
    if not location:
        return
    terms_path = Path(location)
    assert terms_path.is_file(), f"HARNESS_DEIDENTIFY_TERMS does not name a file: {location}"
    terms = dl.load_terms(terms_path)
    assert terms, "the supplied term file is empty"
    allowed = dl.allowed_first_segments(ROOT)
    hits = []
    for relative in TOOL_FILES:
        data = (TOOLS / relative).read_bytes()
        hits.extend(
            item.render() for item in dl.scan_content(f"harness/tools/{relative}", data, terms, allowed, False)
            if item.check == "TERM"
        )
    assert hits == [], hits


def test_ascii_only_and_lf_only():
    for relative in TOOL_FILES:
        raw = (TOOLS / relative).read_bytes()
        assert b"\r" not in raw, relative
        assert not raw.startswith(b"\xef\xbb\xbf"), relative
        assert all(byte < 128 for byte in raw), f"{relative}: non-ASCII byte"


install_bridge(globals(), "NoPrivateVocabularyBridge")
