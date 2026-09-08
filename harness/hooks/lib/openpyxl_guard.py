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


def extract_xlsx_paths(text):
    quoted = re.findall(r"""['"]([^'"]*\.xlsx)['"]""", text)
    unquoted = re.findall(r"""(?<!['"=])([\w./\\-]+\.xlsx)(?!['"]\w)""", text)
    return quoted + unquoted


def extract_script_paths(text):
    quoted = re.findall(r"""['"]([^'"]+\.py)['"]""", text)
    unquoted = re.findall(r"""([\w./\\-]+\.py)\b""", text)
    seen, out = set(), []
    for path in quoted + unquoted:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out[:SCRIPT_SCAN_MAX_FILES]


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

    try:
        if ".py" in command:
            for script in resolve_existing(extract_script_paths(command), cwd):
                body = read_script(script)
                if "openpyxl" not in body or not has_write_pattern(body):
                    continue
                if resolve_existing(extract_xlsx_paths(body) + extract_xlsx_paths(command), cwd):
                    return deny(HOOK_NAME, TIER, REASON, digest, RECOVERY)
    except Exception:
        return None
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
