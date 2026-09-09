#!/usr/bin/env python
"""De-identification lint for a repository that must carry no private vocabulary.

Usage:
    python harness/tools/deidentify_lint.py <repo> [--terms <file>] [--history] [--structural]
    python harness/tools/deidentify_lint.py <repo> --terms <private-list> --require-terms <N>
        # release gate: exit 2 unless the resolved term list has at least N entries

Structural checks run without a term file and are what lint check L14 calls
with --structural:

    D1  email address in a scanned file (reserved example domains are allowed)
    D2  incident narrative: a comment or prose line that carries an ISO date and
        a past-tense incident verb; the fix is to state the invariant instead
    D3  path-shaped token whose first segment is not an allowed repository root.
        A token whose first segment is in DENIED_FIRST_SEGMENTS (private-source
        folder roots; see DENIED_FIRST_SEGMENTS) is flagged at ANY segment
        count, including a bare two-segment token; every other first segment
        still needs the shape below. (A shell expansion
        such as $DIR/x and a relative reference such as ./x or ../x are not
        repository paths and are not flagged.)
    D4  absolute path that names a user directory
    D5  attribution strings outside README.md, LICENSE, and NOTICE
    D6  em-dash, en-dash, smart quote, byte-order mark, or carriage return
    D7  absolute host path in prose or config: a drive-letter path (drive
        colon then one or more segments; a segment may carry internal
        spaces, e.g. C:\\Program Files\\Acme\\x), backslash-, slash-,
        mixed-, or JSON-escaped-doubled-backslash separated, or a /Users/<name>/,
        /home/<name>/, /Volumes/<name>/ (macOS), or drive-colon Users form.
        A UNC path (\\\\server\\share\\x) and a file:// URL (plain or
        percent-encoded, decoded before classification) are also flagged
        when they name a drive-letter or UNC path. An http(s) URL span
        (case-insensitive scheme; the span excludes a trailing ")" so a
        Markdown link followed immediately by a real path is not
        over-masked) is masked out before the drive-letter check runs, so a
        URL path segment that merely looks like a drive letter
        (https://example.com/C:/guide) is never mistaken for one. A real
        path deliberately hidden inside a URL's own query string
        (https://example.com/?next=C:/Acme/private) stays masked and
        unflagged either way: that text is the URL's parameter value, an
        accepted scope limit, not a miss to fix. Checked only in Markdown,
        JSON, YAML, TOML, and plain-text files; never in .py, .sh, .ps1, .js source, and
        never in a .json file under a test or fixture directory
        (segment-exact match against D7_TEST_DIR_NAMES, never substring, so
        "docs/contest/x.json" and a "latest/" directory are still scanned).
        A .md, .yaml, .toml, or .txt file under the same test or fixture
        directory keeps D7 coverage; the exclusion is for a JSON fixture
        specifically, not the whole directory.
        A bare drive root (no segment after the colon), a tilde-relative
        path, and a placeholder such as /abs/path/to/your/repo or a whole
        "<...>" path segment (C:/<repo>/harness, /home/<user>/repo) are not
        flagged. Every match on a line is inspected independently: a
        placeholder segment in one match never exempts a real path in
        another match on the same line, and a placeholder must be a whole
        segment, not text embedded inside a larger segment
        (`C:/Acme/private for <input>.` still flags the real path).

The term check (--terms) matches each term as a case-insensitive substring of
every scanned line, including comment lines: a private term hidden in a code
comment is still a leak. The term file itself may hold comment lines starting
with "#" and blank lines; both are ignored, so a word used in a term-file
comment never becomes a term. Findings name the file, the line number, and the
matched term. The surrounding line is never printed, so a finding cannot echo
a secret into a log.

Term sources. The repository ships a public seed list at
harness/tools/deidentify-terms.txt; it holds only terms that are safe to
publish, because a list of private vocabulary is itself private vocabulary.
When --terms is omitted and that file exists inside the scanned repository it
is used, so the default invocation always has a term source. A host that
publishes from a private source keeps its own list outside the published tree
and passes it with --terms; that list should carry the seed entries as well,
since only one term file is read per run. The term file in use is excluded
from the scan so its own entries never report against themselves.

--history walks every commit reachable from any ref and runs the content checks
over each (path, blob) pair once. It prints the first offending commit per
finding. It is slow by design and never part of the default lint. An empty
or ref-less repository (git rev-list --all returns nothing) exits 1 with a
"no refs to scan" message rather than silently reporting a clean history.

--require-terms N is the release-only floor on the term list itself: it
exits 2 when the resolved term list (the file named by --terms, or the
shipped seed when --terms is omitted) has fewer than N entries, so a release
run built against an empty or missing private list cannot pass.

Exit 0 when clean, 1 on any finding (including "no refs to scan" under
--history), 2 on a usage error (including --require-terms not met).

Scope note for D3: a token counts as path-shaped when it has three or more
slash-separated segments, or any segment contains a dot followed by a letter
(an extension), or it is followed by a slash. Two bare words joined by a slash
("read/write") are prose, not paths, and a version number inside a segment
("provider/model-5.3") is an identifier, not a file; both are left to the term
check.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]

ALLOWED_FIRST_SEGMENTS = {
    "harness",
    "docs",
    "brain",
    ".github",
    ".githooks",
    ".claude",
    ".codex",
    ".opencode",
    ".agents",
    "tests",
    "examples",
    # Home dot-directories that credential shapes name (the AWS credentials
    # file, SSH private keys, gcloud ADC); ignore lists, deny lists, and the
    # guard's own tests spell them out and they identify no private source.
    ".aws",
    ".ssh",
    ".config",
    # ".git" is the repository's own metadata directory; hook and worktree
    # documentation names it legitimately.
    ".git",
    # ".tmp" is the machine-state root: ignored by git, and the delegation
    # policy names it as the only scratch write scope for orchestration.
    ".tmp",
}

# A path-shaped token whose first segment is one of these is flagged at ANY
# segment count, including a bare two-segment token (root plus one child),
# because these are private-source roots that must never appear as a shipped
# default: a two-segment hit is exactly as identifying as a three-segment one.
# This set overrides ALLOWED_FIRST_SEGMENTS and the shipped structure.json
# (a host misconfiguring a lane under one of these names is still a leak).
DENIED_FIRST_SEGMENTS = {
    "ventures",
    "embryos",
    "rolodex",
    "fleet",
    # assembled from fragments so this module carries no private term at rest
    "all" + "ies",
    "vault",
}

# Public seed term list, resolved inside the scanned repository when --terms
# is omitted. It is skipped from the scan like any explicit term file.
DEFAULT_TERMS_RELATIVE = "harness/tools/deidentify-terms.txt"

# Built from fragments so this file passes its own D5 check.
ATTRIBUTION_TERMS = ("".join(("Areo", "pact")), "".join(("Claw", "ford")))
ATTRIBUTION_FILES = {
    "README.md", "LICENSE", "NOTICE",
    "README.harness.md", "LICENSE.harness.md", "NOTICE.harness.md",
}

RESERVED_EMAIL_DOMAINS = ("example.com", "example.org", "example.net", "localhost", "invalid")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
INCIDENT_VERB_RE = re.compile(
    r"\b(happened|broke|corrupted|leaked|wiped|hung|failed on|bit us|incident|postmortem)\b",
    re.IGNORECASE,
)
# A token preceded by "$" is a shell expansion ($SCRIPT_DIR/..), never a
# repository path; the lookbehind excludes it along with mid-path positions.
PATH_TOKEN_RE = re.compile(r"(?<![\w/:.~\\$-])([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)(/?)")
# A dot followed by a letter marks a file extension; a dot inside a version
# number ("model-5.3") does not make an identifier a path.
EXTENSION_RE = re.compile(r"\.[A-Za-z]")
# Assembled from fragments so this file passes its own D4 check.
USER_DIR_RE = re.compile(
    "(?:/" + "home/|/" + "Users/|[A-Za-z]:" + r"\\+" + "Users" + r"\\+" + ")[A-Za-z0-9._-]+|/" + "root" + r"(?=/|\b)"
)
# D7: a drive-letter path, matched against a backslash-normalized view of
# the line (see _d7_normalize) so backslash, forward-slash, mixed, and
# JSON-escaped doubled-backslash separators all resolve to one shape. A
# bare drive root (no segment after the colon) is not flagged. The
# lookbehind keeps a scheme's last letter ("https:") from reading as a
# drive letter, and a doubled slash after the colon ("http://") is excluded
# so a URL is never mistaken for a drive path. A segment may carry internal
# spaces (C:\Program Files\Acme\x) but may not begin with one, so a bare
# drive root followed by a space never matches.
# A segment may carry internal spaces (C:\Program Files\Acme\x), but must
# stop before a space that introduces a SECOND absolute path on the same
# line: a drive letter and separator, or a UNC start. Without this, two
# unquoted absolute paths on one line greedily merge into a single match,
# and a placeholder in either one hides a real path in the other
# ("C:/<repo>/x and D:/Acme/private" produced no finding).
D7_NEW_PATH_START = r"[A-Za-z]:[\\/]|\\\\"
D7_SEGMENT = r"[^/\s\"'`](?:(?!\s(?:" + D7_NEW_PATH_START + r"))[^/\"'`])*"
D7_DRIVE_PATH_RE = re.compile(
    # The "/" separator itself must not be preceded by a space either: that
    # is the same merge, one segment later (a leading-slash root after a
    # word and a space must not be read as a continuation of the path
    # named just before it).
    r"(?<![A-Za-z0-9_])[A-Za-z]:/(?!/)" + D7_SEGMENT + r"(?:(?<!\s)/" + D7_SEGMENT + r")*"
)
# D7: a POSIX home-directory or macOS volume form naming a specific segment.
D7_POSIX_HOME_RE = re.compile("(?:/" + "Users/|/" + "home/|/" + "Volumes/)[^/\\s\"'`]+/")
# D7: a UNC path (two leading backslashes, a host, then share/path
# segments), matched on the raw (pre-normalize) line: normalization would
# collapse the doubled leading backslash and destroy the shape.
D7_UNC_RE = re.compile(r"\\\\[^\\\s\"'`]+\\[^\\\s\"'`]+(?:\\[^\\\s\"'`]+)*")
# D7: an http(s) URL span, masked out before the drive-letter/POSIX checks
# run so a URL path segment that merely looks like a drive letter
# (https://example.com/C:/guide) is never mistaken for one. Case-insensitive
# (HTTPS://... is still a URL scheme), and a trailing ")" is excluded from
# the span so a Markdown link followed immediately by a real path
# ([a](https://ex.com/y)C:/Acme/private/x) does not over-mask into the real
# path: the URL is read as ending at the closing paren, the common shape for
# an inline link, at the cost of never matching a URL containing a literal
# unescaped ")" in its own path. A real path deliberately hidden inside a
# URL's own query string (https://ex.com/?next=C:/Acme/private) stays
# masked either way: that text is the URL's parameter value, not a path
# typed on this host, and is out of scope for D7.
D7_HTTP_URL_RE = re.compile(r"https?://[^\s\"'`)]+", re.IGNORECASE)
# D7: a file:// URL, decoded and classified on its own (percent-encoding
# hides a drive-letter or UNC shape from the plain-text regexes above).
# Same case-insensitivity and trailing-")" exclusion as the http(s) regex.
D7_FILE_URL_RE = re.compile(r"file://[^\s\"'`)]+", re.IGNORECASE)
# D7: a "<placeholder>" segment (C:/<repo>/harness, /home/<user>/repo)
# documents an example shape rather than a real host path. Exemption
# requires a WHOLE separator-delimited segment to be the placeholder token;
# a placeholder embedded inside a larger segment does not exempt a real
# path sharing the same match.
D7_PLACEHOLDER_RE = re.compile(r"<[^<>/\\]+>")
# File suffixes D7 scans: prose and config, never code.
D7_SCANNED_SUFFIXES = {".md", ".markdown", ".json", ".yml", ".yaml", ".toml", ".txt", ""}
D7_EXCLUDED_SUFFIXES = {".py", ".sh", ".ps1", ".js"}
# Test/fixture directories are excluded segment-exact, never by substring,
# so "docs/contest/x.json" and a "latest/" directory are still scanned.
D7_TEST_DIR_NAMES = {"tests", "test", "fixtures", "export_tests", "expected"}


def _d7_normalize(line: str) -> str:
    """Undo JSON-escaped doubled backslashes, then fold backslash separators
    to forward slashes so one regex catches every separator style."""
    normalized = line
    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")
    return normalized.replace("\\", "/")


def _d7_decode_json_backslash_pairs(line: str) -> str:
    """One JSON-string level of backslash unescaping: every doubled pair
    becomes one backslash, left to right, non-overlapping (str.replace, not
    a loop-to-fixpoint). This recovers a UNC path's mandatory leading pair
    from a JSON-escaped form (`{"path": "\\\\server\\share\\private"}`,
    four raw backslashes decoding to the real two-backslash UNC start) that
    the UNC scan on the raw line cannot see. Applying the same fixpoint
    collapse _d7_normalize uses would over-collapse that leading pair down
    to one backslash and destroy the UNC shape, so this is a distinct,
    single-pass decode used only for the UNC check, in addition to (never
    instead of) scanning the raw line for an already-single-escaped UNC
    path."""
    return line.replace("\\\\", "\\")


def _is_d7_placeholder(matched: str, sep: str = "/") -> bool:
    """True only when a whole sep-separated segment of the matched text is
    an exact bracketed placeholder token: a placeholder embedded inside a
    larger segment ("private for <input>.") never exempts the match."""
    return any(D7_PLACEHOLDER_RE.fullmatch(part) for part in matched.split(sep))


def _d7_mask(line: str, match) -> str:
    """Replace a matched span with same-length filler so a later D7 regex
    never re-scans it (used to remove http(s) and file:// URL spans before
    the drive-letter/POSIX checks run)."""
    start, end = match.span()
    return line[:start] + ("#" * (end - start)) + line[end:]


def _d7_classify_file_url(url: str):
    """Percent-decode a file:// URL and classify its path as a drive-letter
    path or a UNC path. Returns (message, matched_text) or None when the
    decoded path names neither shape, or is entirely a placeholder."""
    decoded = urllib.parse.unquote(url)
    remainder = decoded[len("file://"):]
    if len(remainder) >= 3 and remainder[0] == "/" and remainder[1].isalpha() and remainder[2] == ":":
        # file:///C:/x -> remainder "/C:/x" -> drive path "C:/x"
        drive_path = remainder[1:]
        if D7_DRIVE_PATH_RE.match(drive_path) and not _is_d7_placeholder(drive_path):
            return ("absolute host path (file URL, drive-letter path)", drive_path)
        return None
    if "/" in remainder.strip("/"):
        unc_path = "\\\\" + remainder.strip("/").replace("/", "\\")
        if not _is_d7_placeholder(unc_path, sep="\\"):
            return ("absolute host path (file URL, UNC path)", unc_path)
    return None

# Escaped so this file carries none of the characters it rejects.
NON_ASCII_PUNCT = {
    chr(0x2014): "em-dash",
    chr(0x2013): "en-dash",
    chr(0x2018): "smart quote",
    chr(0x2019): "smart quote",
    chr(0x201C): "smart quote",
    chr(0x201D): "smart quote",
}
BOM = b"\xef\xbb\xbf"

COMMENT_PREFIX_BY_SUFFIX = {
    ".py": "#",
    ".sh": "#",
    ".ps1": "#",
    ".toml": "#",
    ".yml": "#",
    ".yaml": "#",
    ".txt": "#",
    ".cfg": "#",
    ".ini": "#",
    ".js": "//",
    ".ts": "//",
    ".mjs": "//",
}
PROSE_SUFFIXES = {".md", ".markdown", ".rst", ""}


class Finding:
    __slots__ = ("check", "path", "line", "message", "commit")

    def __init__(self, check, path, line, message, commit=None):
        self.check = check
        self.path = path
        self.line = line
        self.message = message
        self.commit = commit

    def key(self):
        return (self.check, self.path, self.message)

    def render(self):
        where = f"{self.path}:{self.line}" if self.line else self.path
        prefix = f"{self.commit[:12]} " if self.commit else ""
        return f"{prefix}{self.check} {where}: {self.message}"


# --------------------------------------------------------------------------
# host facts
# --------------------------------------------------------------------------


def _fallback_structure(root: Path) -> dict:
    """Same defaults contract as harness_registry.load_structure, used only
    when that module is absent: the shipped default object merged key by key
    with the host file. A malformed host file yields the default here because
    a lint must not crash on the file it is meant to help fix."""
    default_path = TOOLS_DIR / "templates" / "structure.default.json"
    try:
        default = json.loads(default_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        default = {
            "schema_version": 1,
            "lanes": {k: None for k in ("identity", "knowledge", "decisions", "records", "docs")},
        }
    host_path = root / "harness" / "registry" / "structure.json"
    try:
        host = json.loads(host_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    if not isinstance(host, dict):
        return default
    merged = dict(default)
    for key, value in host.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            inner = dict(merged[key])
            inner.update(value)
            merged[key] = inner
        else:
            merged[key] = value
    return merged


def _registry_module():
    """Load harness_registry from its file without touching sys.path."""
    path = TOOLS_DIR / "harness_registry.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("harness_registry", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a broken registry module means "absent"
        return None
    return module


def load_structure(root: Path) -> dict:
    registry = _registry_module()
    if registry is None:
        return _fallback_structure(root)
    try:
        return registry.load_structure(root)
    except Exception:  # noqa: BLE001 - a lint never crashes on the file it helps fix
        return _fallback_structure(root)


def allowed_first_segments(root: Path) -> set:
    allowed = set(ALLOWED_FIRST_SEGMENTS)
    structure = load_structure(root)
    lanes = structure.get("lanes") or {}
    for value in lanes.values():
        if not isinstance(value, list):
            continue
        for lane_path in value:
            if isinstance(lane_path, str) and lane_path:
                allowed.add(lane_path.strip("/").split("/")[0])
    # An adopted host's own top-level directories (recorded at adoption time
    # in structure.json's host.roots) are its content, not orphaned template
    # path tokens.
    for root_name in (structure.get("host") or {}).get("roots") or []:
        if isinstance(root_name, str) and root_name:
            allowed.add(root_name.strip("/").split("/")[0])
    return allowed


# --------------------------------------------------------------------------
# adopted-host scope
# --------------------------------------------------------------------------

ADOPTED_FILES_REGISTRY = "harness/registry/adopted-files.json"
KERNEL_MANIFEST = "harness/kernel-manifest.json"


def _load_json_lenient(path: Path):
    """Parsed JSON, or None on a missing/malformed file: a lint must not
    crash on the file it is scoping itself by."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def adopted_scope_paths(root: Path) -> set:
    """The default scan set on an adopted host: the union of
    harness/registry/adopted-files.json's recorded paths, every path listed
    in harness/kernel-manifest.json (the files the template owns on this
    host), and harness/registry/structure.json itself. The host's own
    content, wherever it lives, is out of scope by default: the template's
    tools judge the template's files."""
    scope = {"harness/registry/structure.json"}
    adopted_doc = _load_json_lenient(root / ADOPTED_FILES_REGISTRY)
    if isinstance(adopted_doc, dict):
        scope.update(p for p in (adopted_doc.get("paths") or []) if isinstance(p, str))
    manifest_doc = _load_json_lenient(root / KERNEL_MANIFEST)
    if isinstance(manifest_doc, dict):
        for entry in manifest_doc.get("files") or []:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                scope.add(entry["path"])
    return scope


def scan_scope(root: Path, structure: dict, all_scope: bool) -> tuple:
    """Return (files, label): the file list this run scans, and a one-word
    label naming the mode. On a non-adopted host, or with --all, the scope
    is the whole tree and nothing about the default behavior changes."""
    files = list_files(root)
    adopted = bool((structure.get("host") or {}).get("adopted"))
    if all_scope or not adopted:
        return files, "whole tree"
    scope = adopted_scope_paths(root)
    return [rel for rel in files if rel in scope], "adopted-host"


# --------------------------------------------------------------------------
# term file
# --------------------------------------------------------------------------


def load_terms(path: Path) -> list:
    terms = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line.lower())
    return terms


# --------------------------------------------------------------------------
# content checks
# --------------------------------------------------------------------------


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8000]


def comment_prefix(path: str):
    suffix = Path(path).suffix.lower()
    if suffix in PROSE_SUFFIXES:
        return ""  # every line is prose
    return COMMENT_PREFIX_BY_SUFFIX.get(suffix)


def _is_d7_scanned_file(rel: str) -> bool:
    """D7 checks Markdown, JSON, YAML, TOML, and plain-text files. Source
    (.py, .sh, .ps1, .js) is never scanned. Only a .json file under a test
    or fixture directory (segment-exact match, never substring, so
    "docs/contest/x.json" and a "latest/" directory are still scanned) is
    excluded, as a fixture; a .md, .yaml, .toml, or .txt file under the same
    directory carries prose or config that is still worth scanning, so it
    keeps D7 coverage."""
    suffix = Path(rel).suffix.lower()
    if suffix in D7_EXCLUDED_SUFFIXES:
        return False
    if suffix not in D7_SCANNED_SUFFIXES:
        return False
    if suffix == ".json" and any(part.lower() in D7_TEST_DIR_NAMES for part in Path(rel).parts[:-1]):
        return False
    return True


def scan_content(rel: str, data: bytes, terms: list, allowed: set, structural_only: bool, commit=None, term_exempt_masks: dict | None = None) -> list:
    findings = []
    if is_binary(data):
        return findings
    if data.startswith(BOM):
        findings.append(Finding("D6", rel, 1, "byte-order mark", commit))
        data = data[len(BOM):]
    if b"\r" in data:
        first = data.index(b"\r")
        line_no = data[:first].count(b"\n") + 1
        findings.append(Finding("D6", rel, line_no, "carriage return", commit))
    text = data.decode("utf-8", errors="replace")
    prefix = comment_prefix(rel)
    basename = Path(rel).name
    attribution_allowed = basename in ATTRIBUTION_FILES and "/" not in rel
    d7_scanned = _is_d7_scanned_file(rel)
    for index, line in enumerate(text.split("\n"), start=1):
        if d7_scanned:
            # http(s) URLs are masked FIRST: a file:// URL embedded as a
            # query-string value inside an http(s) URL
            # (https://example.com/?next=file:///C:/guide) is that URL's
            # parameter text, not a real local path typed on this host, and
            # must not be separately decoded and classified as one.
            working_line = line
            for http_url_match in D7_HTTP_URL_RE.finditer(line):
                working_line = _d7_mask(working_line, http_url_match)
            for file_url_match in D7_FILE_URL_RE.finditer(working_line):
                classified = _d7_classify_file_url(file_url_match.group(0))
                if classified is not None:
                    message, _matched = classified
                    findings.append(Finding("D7", rel, index, message, commit))
                working_line = _d7_mask(working_line, file_url_match)
            unc_flagged = False
            for unc_candidate in (working_line, _d7_decode_json_backslash_pairs(working_line)):
                for unc_match in D7_UNC_RE.finditer(unc_candidate):
                    if not _is_d7_placeholder(unc_match.group(0), sep="\\"):
                        unc_flagged = True
                        break
                if unc_flagged:
                    break
            if unc_flagged:
                findings.append(Finding("D7", rel, index, "absolute host path (UNC path)", commit))
            normalized_line = _d7_normalize(working_line)
            drive_flagged = False
            for drive_match in D7_DRIVE_PATH_RE.finditer(normalized_line):
                if not _is_d7_placeholder(drive_match.group(0)):
                    drive_flagged = True
                    break
            if drive_flagged:
                findings.append(Finding("D7", rel, index, "absolute host path (drive-letter path)", commit))
            else:
                for home_match in D7_POSIX_HOME_RE.finditer(normalized_line):
                    if not _is_d7_placeholder(home_match.group(0)):
                        findings.append(Finding("D7", rel, index, "absolute host path (POSIX home directory or macOS volume)", commit))
                        break
        for match in EMAIL_RE.finditer(line):
            domain = match.group(0).rsplit("@", 1)[1].lower()
            if not any(domain == d or domain.endswith("." + d) for d in RESERVED_EMAIL_DOMAINS):
                findings.append(Finding("D1", rel, index, "email address", commit))
                break
        stripped = line.strip()
        is_narrative_line = prefix == "" or (prefix is not None and stripped.startswith(prefix))
        if is_narrative_line and ISO_DATE_RE.search(line):
            verb = INCIDENT_VERB_RE.search(line)
            if verb:
                findings.append(
                    Finding("D2", rel, index, f"incident narrative ({verb.group(1).lower()} with a date); state the invariant", commit)
                )
        for match in PATH_TOKEN_RE.finditer(line):
            token, trailing = match.group(1), match.group(2)
            segments = token.split("/")
            first = segments[0]
            if first.isdigit() or first in (".", ".."):
                # numeric ratios and relative references say nothing about roots
                continue
            if first in DENIED_FIRST_SEGMENTS:
                # a denied private root is path-shaped at any segment count,
                # even a bare two-segment token, and is never allow-listable
                findings.append(Finding("D3", rel, index, f"path token under denied private root: first segment '{first}'", commit))
                continue
            shaped = len(segments) >= 3 or any(EXTENSION_RE.search(s) for s in segments) or trailing == "/"
            if not shaped:
                continue
            if first in allowed:
                continue
            findings.append(Finding("D3", rel, index, f"path token outside allowed roots: first segment '{first}'", commit))
        if USER_DIR_RE.search(line):
            findings.append(Finding("D4", rel, index, "absolute path naming a user directory", commit))
        if not attribution_allowed:
            for term in ATTRIBUTION_TERMS:
                if term in line:
                    findings.append(Finding("D5", rel, index, f"attribution string '{term}' outside README.md, LICENSE, NOTICE", commit))
        for char in line:
            if char in NON_ASCII_PUNCT:
                findings.append(Finding("D6", rel, index, NON_ASCII_PUNCT[char], commit))
                break
        if terms and not structural_only:
            scanned_line = line
            spans = (term_exempt_masks or {}).get(index)
            if spans:
                scanned_line = _mask_spans(scanned_line, spans)
            lowered = scanned_line.lower()
            for term in terms:
                if term in lowered:
                    findings.append(Finding("TERM", rel, index, f"matched term '{term}'", commit))
    return findings


# --------------------------------------------------------------------------
# file enumeration
# --------------------------------------------------------------------------


def git(repo: Path, *args, binary=False):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "git failed")
    return result.stdout if binary else result.stdout.decode("utf-8", "replace")


def list_files(repo: Path) -> list:
    """Tracked plus untracked-not-ignored files, the set a commit would see.
    Falls back to a filesystem walk when git is unavailable or the directory
    is not a repository."""
    try:
        out = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
        rels = [p for p in out.split("\0") if p]
        return sorted(set(r for r in rels if (repo / r).is_file()))
    except (RuntimeError, OSError):
        rels = []
        for dirpath, dirnames, filenames in os.walk(repo):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                full = Path(dirpath) / name
                rels.append(full.relative_to(repo).as_posix())
        return sorted(rels)


# The tool that defines the denied vocabulary necessarily contains it, but
# only inside two spots: the DENIED_FIRST_SEGMENTS literal and the default
# term-file path. Only the exact VALUE of each of those two module-level
# assignments is exempt from the TERM layer; every other line of this file,
# every structural check (D1..D7), and every other file (its test module
# assembles every denied string from fragments at runtime) stay fully
# scanned. A private term hidden anywhere else in this file is reported.
SELF_EXEMPT_FILE = "harness/tools/deidentify_lint.py"
SELF_EXEMPT_NAMES = ("DENIED_FIRST_SEGMENTS", "DEFAULT_TERMS_RELATIVE")


def _module_level_value_span(tree: ast.Module, name: str):
    """(start_lineno, start_col, end_lineno, end_col) of the VALUE of the
    real module-level `name = ...` assignment, found by AST position among
    tree.body only (never a nested scope, so a same-named assignment inside
    a function is never exempted, and never a regex line-scan, so a fake
    assignment inside a multiline string is never exempted). Exempting the
    value's own span rather than the whole statement or the whole line
    means a second statement sharing the line (`); SECRET = "x"` after a
    multiline value, or `# probeprivate` trailing a one-line value) is
    never swept in: only the exact characters of the value itself are
    masked. Returns None when no such assignment exists at module level."""
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        value = node.value
        if value is None or not hasattr(value, "end_lineno") or not hasattr(value, "end_col_offset"):
            continue
        return (value.lineno, value.col_offset, value.end_lineno, value.end_col_offset)
    return None


def _value_span_masks(span) -> dict:
    """A value span expanded to per-line (start_col, end_col_or_None) mask
    ranges: end_col_or_None means "to end of line" (used for every line of
    a multiline value except its last)."""
    if span is None:
        return {}
    start_line, start_col, end_line, end_col = span
    masks: dict = {}
    if start_line == end_line:
        masks.setdefault(start_line, []).append((start_col, end_col))
        return masks
    masks.setdefault(start_line, []).append((start_col, None))
    for mid in range(start_line + 1, end_line):
        masks.setdefault(mid, []).append((0, None))
    masks.setdefault(end_line, []).append((0, end_col))
    return masks


def _self_exempt_masks(data: bytes) -> dict:
    """Per-line column-range masks (1-indexed line -> list of
    (start_col, end_col_or_None)) covering exactly the VALUE of each real
    module-level DENIED_FIRST_SEGMENTS and DEFAULT_TERMS_RELATIVE
    assignment. A parse failure (e.g. probe text a test writes is not
    valid Python) yields no masks rather than raising."""
    text = data.decode("utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    combined: dict = {}
    for name in SELF_EXEMPT_NAMES:
        for line, spans in _value_span_masks(_module_level_value_span(tree, name)).items():
            combined.setdefault(line, []).extend(spans)
    return combined


def _mask_spans(line: str, spans: list) -> str:
    """line with each (start, end_or_None) column range replaced by
    same-length filler, so a term hidden in that exact span is invisible
    while the rest of the line (a second statement, a trailing comment)
    stays fully scanned."""
    masked = line
    for start, end in spans:
        stop = len(masked) if end is None else min(end, len(masked))
        begin = min(start, len(masked))
        if begin < stop:
            masked = masked[:begin] + ("#" * (stop - begin)) + masked[stop:]
    return masked


def _committed_blob(repo: Path, rel: str):
    """The git index's bytes for a tracked path, or None (untracked, or git failed)."""
    try:
        return git(repo, "show", f":{rel}", binary=True)
    except (RuntimeError, OSError):
        return None


def _worktree_cr_is_normalization_noise(repo: Path, rel: str, data: bytes) -> bool:
    """True when the worktree's CR bytes are a checkout-time normalization
    (core.autocrlf or a text attribute) of a committed blob that carries no
    CR: the committed history is clean, so D6 must not flag the checkout."""
    if b"\r" not in data:
        return False
    blob = _committed_blob(repo, rel)
    if blob is None:
        return False  # untracked: the worktree bytes are the real content
    return b"\r" not in blob


def scan_worktree(repo: Path, terms: list, allowed: set, structural_only: bool, skip: set, files: list | None = None) -> list:
    """Scan files=list_files(repo) by default, or the given file list (an
    adopted-host scope, an --only subset, ...) when files is passed."""
    findings = []
    for rel in (files if files is not None else list_files(repo)):
        if rel in skip:
            continue
        try:
            data = (repo / rel).read_bytes()
        except OSError:
            continue
        if _worktree_cr_is_normalization_noise(repo, rel, data):
            data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        exempt_masks = _self_exempt_masks(data) if rel == SELF_EXEMPT_FILE else None
        findings.extend(scan_content(rel, data, terms, allowed, structural_only, term_exempt_masks=exempt_masks))
    return findings


class NoRefsError(RuntimeError):
    """git rev-list --all returned nothing: an empty or ref-less repository.
    A distinct type so main() can exit 1 (a real finding: history was never
    scanned) instead of 2 (a usage error), and never let this look like a
    clean history."""


def scan_history(repo: Path, terms: list, allowed: set, structural_only: bool, skip: set) -> list:
    shas = [s for s in git(repo, "rev-list", "--all", "--reverse").split("\n") if s]
    if not shas:
        raise NoRefsError("no refs to scan: git rev-list --all returned nothing")
    seen = set()
    first_by_key = {}
    for sha in shas:
        tree = git(repo, "ls-tree", "-r", "-z", sha)
        for entry in tree.split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t", 1)
            mode, kind, blob = meta.split()
            if kind != "blob" or mode == "120000":
                continue
            if path in skip or (path, blob) in seen:
                continue
            seen.add((path, blob))
            data = git(repo, "cat-file", "-p", blob, binary=True)
            exempt_masks = _self_exempt_masks(data) if path == SELF_EXEMPT_FILE else None
            for finding in scan_content(path, data, terms, allowed, structural_only, commit=sha, term_exempt_masks=exempt_masks):
                first_by_key.setdefault(finding.key(), finding)
    return list(first_by_key.values())


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="De-identification lint (structural checks plus optional term list).")
    parser.add_argument("repo", help="repository to scan")
    parser.add_argument(
        "--terms",
        help="term file: one term per line, # comments and blank lines ignored (default: harness/tools/deidentify-terms.txt inside the repository when present)",
    )
    parser.add_argument("--history", action="store_true", help="also scan every commit reachable from any ref")
    parser.add_argument("--structural", action="store_true", help="run D1..D7 only (ignores --terms)")
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "on an adopted host, scan the whole tree instead of the default adopted scope "
            "(harness/registry/adopted-files.json + the kernel manifest paths + structure.json); "
            "no effect on a non-adopted host"
        ),
    )
    parser.add_argument(
        "--require-terms",
        type=int,
        default=None,
        metavar="N",
        help=(
            "release gate: exit 2 unless the resolved term list has at least N entries, so a release "
            "run cannot pass silently against an empty or missing private list "
            "(release command shape: --terms <private-list> --require-terms N)"
        ),
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"deidentify_lint: not a directory: {repo}", file=sys.stderr)
        return 2
    terms = []
    skip = set()
    terms_path = None
    if args.terms and not args.structural:
        terms_path = Path(args.terms).resolve()
        if not terms_path.is_file():
            print(f"deidentify_lint: term file not found: {terms_path}", file=sys.stderr)
            return 2
    elif not args.structural and (repo / DEFAULT_TERMS_RELATIVE).is_file():
        terms_path = repo / DEFAULT_TERMS_RELATIVE
    if terms_path is not None:
        terms = load_terms(terms_path)
        try:
            skip.add(terms_path.relative_to(repo).as_posix())
        except ValueError:
            pass
    if args.require_terms is not None and len(terms) < args.require_terms:
        print(
            f"deidentify_lint: --require-terms {args.require_terms} not met: resolved term list has {len(terms)} entr"
            f"{'y' if len(terms) == 1 else 'ies'} (terms path: {terms_path if terms_path else 'none resolved'})",
            file=sys.stderr,
        )
        return 2
    structure = load_structure(repo)
    allowed = allowed_first_segments(repo)
    scope_files, scope_label = scan_scope(repo, structure, args.all)
    if terms_path is not None:
        scope_files = [rel for rel in scope_files if rel not in skip]
    print(f"deidentify_lint: scope {scope_label} ({len(scope_files)} file(s) scanned)")

    findings = scan_worktree(repo, terms, allowed, args.structural, skip, files=scope_files)
    if args.history:
        try:
            findings.extend(scan_history(repo, terms, allowed, args.structural, skip))
        except NoRefsError as exc:
            print(f"deidentify_lint: {exc}", file=sys.stderr)
            return 1
        except RuntimeError as exc:
            print(f"deidentify_lint: --history needs a git repository with commits: {exc}", file=sys.stderr)
            return 2

    for finding in findings:
        print(finding.render())
    mode = "structural" if args.structural else ("structural+terms" if terms else "structural")
    print(f"deidentify_lint: {len(findings)} finding(s), mode {mode}, history {'on' if args.history else 'off'}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
