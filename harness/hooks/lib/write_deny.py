#!/usr/bin/env python3
"""PreToolUse(Write|Edit|NotebookEdit|apply_patch) guard: host-reserved paths.

Denies an agent write to any repository path matched by structure.json
``write_deny.globs`` unless the path also matches ``write_deny.except``.
Shipped OFF: the default globs are empty, so the guard is silent until a host
names the paths it reserves for human authors (a specification the team
writes by hand, a signed record folder, a ledger a tool owns). A path outside
the repository, a payload without a target path, and a tool that is not an
edit tool all pass.

Activation is the host fact itself, never an environment variable: a host
that sets ``write_deny.globs`` has made the decision in its own registry, and
every runtime that routes edit tools through the dispatcher honors it. On
Claude Code the wrapper is registered under ``Write|Edit|NotebookEdit``; Codex
and OpenCode reach this module through ``dispatch.py``.

Matching semantics, identical on every platform:

- the target is resolved to a repository-relative POSIX path, then each
  segment loses trailing dots and spaces and the final segment loses any
  ``:`` stream suffix, because Windows opens ``ledger.md.``, ``ledger.md `` and
  ``ledger.md::$DATA`` as ``ledger.md``;
- path and pattern are compared case-insensitively with ``fnmatchcase`` on
  their casefolded forms, so a verdict never depends on whether the host's
  disk folds case;
- ``fnmatch`` wildcards apply, and ``*`` DOES cross ``/`` (``docs/*.md`` also
  matches ``docs/a/b.md``), so an ``except`` pattern is broader than it looks;
  ``dir/**``, ``dir/`` and a wildcard-free ``dir`` all cover every descendant.

Globs name the real repository-relative path: a target is resolved through
symlinks and junctions before matching, so a link into the repository is
matched by what it points at, and a link out of the repository is outside
the root and passes (a known gap).

Outside this hook entirely: any shell path to the same file. ``cat >``,
``tee``, ``sed -i``, ``python - <<'EOF'``, ``git apply``, ``mv`` and ``cp``
into a reserved path are denied by nothing; ``dangerous_ops_guard`` models
credential reads, git and destructive shapes, not writes, and
``.githooks/pre-commit`` does not read ``write_deny``. The backstop for those
is the human review of the pull request. Runtime tools outside the four
matched names (an MCP file tool, for one) are also outside.

Rung: hard-block by host declaration. The template ships it inert; the host
that fills ``write_deny.globs`` makes the hard-block decision. The deny names
the pattern, the path, and the recovery: read, quote, check, and hand the
text to the writer.
"""
import fnmatch
import hashlib
import json
import os
import sys

from _debug import debug
from hook_io import (
    PATCH_PATH_RE,
    _note,
    canonical_tool_name,
    changed_paths,
    deny,
    load_structure,
    patch_texts,
    relative_path,
)

HOOK_NAME = "write-deny"
TIER = "host-reserved-path"
EDIT_TOOLS = ("Write", "Edit", "NotebookEdit", "apply_patch")
WILDCARDS = ("*", "?", "[")


def _patterns(structure, key):
    section = structure.get("write_deny") if isinstance(structure, dict) else None
    if section is None:
        return []
    if not isinstance(section, dict):
        _note("structure.json write_deny is not an object; the write guard is off")
        return []
    value = section.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        _note(f"structure.json write_deny.{key} is not a list; the write guard treats it as empty")
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item:
            out.append(item.casefold())
        else:
            _note(f"structure.json write_deny.{key} carries a non-string entry, ignored")
    return out


def canonical(rel_path):
    """Casefolded repository path with the tails Windows strips at open time removed."""
    parts = []
    segments = rel_path.split("/")
    for index, segment in enumerate(segments):
        segment = segment.rstrip(". ")
        if index == len(segments) - 1 and os.name == "nt" and ":" in segment:
            segment = segment.split(":", 1)[0].rstrip(". ")
        parts.append(segment)
    return "/".join(parts).casefold()


def matching_pattern(rel_path, patterns):
    """The first pattern that covers the canonical rel_path, or None."""
    for pattern in patterns:
        if fnmatch.fnmatchcase(rel_path, pattern):
            return pattern
        if pattern.endswith("/**") and rel_path.startswith(pattern[:-3] + "/"):
            return pattern
        if pattern.endswith("/") and rel_path.startswith(pattern):
            return pattern
        if not any(char in pattern for char in WILDCARDS) and rel_path.startswith(pattern.rstrip("/") + "/"):
            return pattern
    return None


def targets_of(data):
    """Every write target the payload names: the direct path and every patch path, deletions included."""
    targets = list(changed_paths(data, include_deleted=True))
    if canonical_tool_name(data) == "apply_patch":
        for text in patch_texts(data):
            for line in text.splitlines():
                match = PATCH_PATH_RE.match(line.strip())
                if match and match.group(2) not in targets:
                    targets.append(match.group(2))
    return targets


def decide(data, root=None, structure=None):
    """Return the deny JSON string, or None to allow."""
    if not isinstance(data, dict) or canonical_tool_name(data) not in EDIT_TOOLS:
        return None
    structure = structure if structure is not None else load_structure(root)
    globs = _patterns(structure, "globs")
    if not globs:
        return None
    excepted = _patterns(structure, "except")
    inside = []
    for target in targets_of(data):
        if not isinstance(target, str) or not target:
            continue
        rel_path = relative_path(target, root)
        if rel_path is None:
            continue
        inside.append(canonical(rel_path))
    for rel_path in inside:
        if matching_pattern(rel_path, excepted):
            continue
        pattern = matching_pattern(rel_path, globs)
        if pattern is None:
            continue
        digest = hashlib.sha256("\n".join(sorted(inside)).encode("utf-8")).hexdigest()
        return deny(
            HOOK_NAME,
            TIER,
            f"{rel_path} is under {pattern}, a path this repository reserves for its human authors "
            "(structure.json write_deny.globs)",
            digest,
            "Read, quote and check the file, then hand the text to the writer to type; "
            "ask the operator to change write_deny in harness/registry/structure.json if the path is wrong.",
        )
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
