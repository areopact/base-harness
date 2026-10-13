#!/usr/bin/env python3
"""PreToolUse(Bash) guard: deny openpyxl writes against an existing workbook.

Enforcement rung: hard-block. openpyxl rewrites every style definition on
save, so a formatted .xlsx that goes through it loses conditional formats,
table styles, and theme colors. Creating a new workbook is fine; overwriting
one that already exists on disk is not (harness/rules/openpyxl-hands-off.md).

Two evaluation units:

  1. The command string itself: deny when it contains "openpyxl", a save or
     write pattern, and a parsed .xlsx path that already exists on disk.
  2. Each .py file the command references: the same test against the script
     body, with .xlsx path evidence pooled from the script and the command
     line (argv-passed paths). Bounded to the first 5 scripts and 256 KB
     each; any read error falls through to allow.

Residual gaps, accepted as first-order heuristics: paths built at runtime
(f-strings, variables), a save nested behind a second interpreter hop, and
entry points that are not .py files.

The path character class has no colon, so an unquoted drive-qualified path
yields only the part after the drive. A second phase runs only when the
first allowed: it rebuilds the drive-qualified form of each unquoted path
(a single ASCII letter, a colon, then a path starting with a slash, not
glued to a longer word) and repeats both units against those candidates,
reading at most 5 further scripts. It runs after the first phase has
decided, so a probe that stalls on an unreachable drive cannot cost a deny
the first phase would have issued, and any error inside it falls through
to allow. Both phases walk each maximal run of path characters once, so
extraction stays linear in the command; every extracted path is still
probed on disk.
Still without a candidate: drive-relative paths (C:x.py), extended-length
paths, an option glued to the drive (-oC:/a.xlsx), file:/// URLs, and paths
with spaces or a tilde. On Windows, a Git Bash drive path (/c/work/x.py) is
not mapped to its drive, quoted or unquoted.

Relative paths resolve against the payload cwd first, then the repository
root, so a fixture with a repo-relative path behaves the same from any
working directory.

Called by harness/hooks/pre-tool-use/openpyxl-guard.{sh,ps1} and by
harness/hooks/lib/dispatch.py.
"""
import hashlib
import json
import os
import re
import sys

from _debug import debug
from hook_io import REPO_ROOT, canonical_tool_name, deny, shell_command_text

HOOK_NAME = "openpyxl-guard"
TIER = "styled-workbook"
REASON = (
    "writing to an existing .xlsx with openpyxl rewrites its styling "
    "(see harness/rules/openpyxl-hands-off.md)"
)
RECOVERY = (
    "Create a new file instead, use a library that preserves styles, "
    "or hand the exact cells and formulas to the operator as text."
)

WRITE_PATTERNS = [
    r"\.save\(",
    r"\bwb\.save\b",
    r"\bworkbook\.save\b",
    r"\bwrite_xlsx\b",
    r"\bto_excel\b",
]

SCRIPT_SCAN_MAX_FILES = 5
SCRIPT_SCAN_MAX_BYTES = 256 * 1024


def has_write_pattern(text):
    return any(re.search(pattern, text) for pattern in WRITE_PATTERNS)


_PATH_RUN = re.compile(r"[\w./\\-]+")
_QUOTE_WORD = re.compile(r"""['"]\w""")
_PY_SUFFIX = re.compile(r"\.py(?!\w)")
_DRIVE_GUARD = re.compile(r"[\w./\\:-]")
_ASCII_LETTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _unquoted_xlsx(text):
    """Yield (path, index of its first character) for each unquoted .xlsx path."""
    for m in _PATH_RUN.finditer(text):
        run, start = m.group(), m.start()
        skip = 1 if start and text[start - 1] in "'\"=" else 0
        k = run.rfind(".xlsx", skip + 1)
        if k != -1 and k + 5 == len(run) and _QUOTE_WORD.match(text, m.end()):
            k = run.rfind(".xlsx", skip + 1, len(run) - 1)
        if k != -1:
            yield run[skip:k + 5], start + skip


def _unquoted_scripts(text):
    """Yield (path, index of its first character) for each unquoted .py path."""
    for m in _PATH_RUN.finditer(text):
        last = None
        for last in _PY_SUFFIX.finditer(m.group(), 1):
            pass
        if last:
            yield m.group()[:last.end()], m.start()


def extract_xlsx_paths(text):
    quoted = re.findall(r"""['"]([^'"]*\.xlsx)['"]""", text)
    return quoted + [path for path, _ in _unquoted_xlsx(text)]


def extract_script_paths(text):
    quoted = re.findall(r"""['"]([^'"]+\.py)['"]""", text)
    seen, out = set(), []
    for path in quoted + [path for path, _ in _unquoted_scripts(text)]:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out[:SCRIPT_SCAN_MAX_FILES]


def _drive_prefix(text, i):
    """Return 'X:' when text[i] opens a rooted path directly after a drive letter, else ''."""
    if i < 2 or text[i] not in "/\\" or text[i - 1] != ":" or text[i - 2] not in _ASCII_LETTERS:
        return ""
    if i >= 3 and _DRIVE_GUARD.match(text[i - 3]):
        return ""
    return text[i - 2:i]


def _drive_candidates(text, pairs):
    seen, out = set(), []
    for path, i in pairs:
        prefix = _drive_prefix(text, i)
        if prefix and prefix + path not in seen:
            seen.add(prefix + path)
            out.append(prefix + path)
    return out


def xlsx_drive_candidates(text):
    """Drive-qualified forms of the unquoted .xlsx paths, in first-occurrence order, no cap."""
    return _drive_candidates(text, _unquoted_xlsx(text)) if ":" in text else []


def script_drive_candidates(text):
    """Drive-qualified forms of the unquoted .py paths, in first-occurrence order, no cap."""
    return _drive_candidates(text, _unquoted_scripts(text)) if ":" in text else []


def resolve_existing(paths, cwd):
    """Return the paths that exist as files: as given, under cwd, under the root."""
    found = []
    for path in paths:
        candidates = [path]
        if not os.path.isabs(path):
            if cwd:
                candidates.append(os.path.join(cwd, path))
            candidates.append(os.path.join(str(REPO_ROOT), path))
        for candidate in candidates:
            if os.path.isfile(candidate):
                found.append(candidate)
                break
    return found


def read_script(path):
    try:
        if os.path.getsize(path) > SCRIPT_SCAN_MAX_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except OSError:
        return ""


def drive_phase_targets(command, cwd, flagged):
    """Second phase, run only after the first phase allowed.

    flagged holds the bodies of the scripts the first phase read that had openpyxl and a write
    pattern but no existing workbook. Returns the existing targets; [] means allow. Never raises.
    """
    try:
        cmd_x = xlsx_drive_candidates(command)
        inline = "openpyxl" in command and ".xlsx" in command and has_write_pattern(command)
        if cmd_x and (inline or flagged):
            hit = resolve_existing(cmd_x, cwd)
            if hit:
                return hit
        for body in flagged:
            hit = resolve_existing(xlsx_drive_candidates(body), cwd)
            if hit:
                return hit
        if ".py" in command:
            old = set(extract_script_paths(command))
            fresh = [p for p in script_drive_candidates(command) if p not in old][:SCRIPT_SCAN_MAX_FILES]
            for spath in resolve_existing(fresh, cwd):
                body = read_script(spath)
                if "openpyxl" not in body or not has_write_pattern(body):
                    continue
                hit = resolve_existing(
                    extract_xlsx_paths(body) + extract_xlsx_paths(command)
                    + xlsx_drive_candidates(body) + cmd_x, cwd)
                if hit:
                    return hit
    except Exception:  # fail-open by design
        pass
    return []


def decide(data):
    """Return the deny JSON string, or None to allow."""
    if not isinstance(data, dict) or canonical_tool_name(data) != "Bash":
        return None
    command = shell_command_text(data)
    if not command:
        return None
    cwd = data.get("cwd") if isinstance(data.get("cwd"), str) else ""
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()

    if "openpyxl" in command and ".xlsx" in command and has_write_pattern(command):
        if resolve_existing(extract_xlsx_paths(command), cwd):
            return deny(HOOK_NAME, TIER, REASON, digest, RECOVERY)

    flagged = []
    try:
        if ".py" in command:
            for script in resolve_existing(extract_script_paths(command), cwd):
                body = read_script(script)
                if "openpyxl" not in body or not has_write_pattern(body):
                    continue
                if resolve_existing(extract_xlsx_paths(body) + extract_xlsx_paths(command), cwd):
                    return deny(HOOK_NAME, TIER, REASON, digest, RECOVERY)
                flagged.append(body)
    except Exception:
        pass
    if drive_phase_targets(command, cwd, flagged):
        return deny(HOOK_NAME, TIER, REASON, digest, RECOVERY)
    return None


def main():
    debug.start()
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        debug.end(HOOK_NAME, out_bytes=0, extra="bad-json")
        sys.exit(0)
    out = decide(data)
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="allow")
        sys.exit(0)
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="deny")
    sys.exit(0)


if __name__ == "__main__":
    main()
