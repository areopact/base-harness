#!/usr/bin/env python3
"""PostToolUse(Write|Edit|apply_patch) advisory: mechanical writing tells.

Enforcement rung: advisory. Never blocks; always exits 0.

Scope: Markdown files whose repo-relative path matches a glob in
structure.json outbound_globs, the material that leaves the repository
under the operator's name. The shipped list is empty, so the hook is silent
until a host names its outbound paths.

Added lines only: the written content is diffed against HEAD and only the
lines this write introduced are scanned. A hook that shouts about history
nobody is editing gets muted, and then the whole layer loses trust.

Cluster gate: one tell is noise. The hook reports when an em or en dash is
present (that one is law on its own, harness/rules/output-quality.md
section 2) or when at least three pattern families fire in the same write.
Quotations, code fences, frontmatter, inline code, URLs, and wikilink targets
are never scanned.
"""
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

from _debug import debug
from hook_io import (
    REPO_ROOT,
    absolute_path,
    advisory_for,
    canonical_tool_name,
    changed_paths,
    load_structure,
    relative_path,
)

HOOK_NAME = "prose-lint"

FAMILIES = {
    "em/en dash": [r"[\u2014\u2013]"],
    "filler": [
        r"\bin order to\b",
        r"\bdue to the fact that\b",
        r"\bat this point in time\b",
        r"\bhas the ability to\b",
        r"\bit is important to note\b",
    ],
    "copula avoidance": [
        r"\bserves as\b",
        r"\bstands as a testament\b",
        r"\bboasts a\b",
    ],
    "signposting": [
        r"\blet's dive in\b",
        r"\bhere's what you need to know\b",
        r"\bwithout further ado\b",
        r"\bin this section,? we will\b",
    ],
    "negative parallelism": [r"\bnot only\b[^.!?\n]{0,80}\bbut also\b"],
    "AI vocabulary": [
        r"\bdelve\b",
        r"\btapestry\b",
        r"\btestament to\b",
        r"\binterplay\b",
        r"\bpivotal moment\b",
        r"\bcutting-edge\b",
    ],
    "sycophancy": [r"\bgreat question\b", r"\bexcellent point\b"],
    "chatbot artifacts": [
        r"\bi hope this helps\b",
        r"\blet me know if you\b",
        r"\bfeel free to reach out\b",
        r"\bas of my last update\b",
    ],
    "generic conclusion": [
        r"\bthe future looks bright\b",
        r"\bpossibilities are endless\b",
        r"\bexciting chapter\b",
    ],
}

COMPILED = {
    name: [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for name, patterns in FAMILIES.items()
}


def outbound_globs(structure=None):
    structure = structure if structure is not None else load_structure()
    value = structure.get("outbound_globs") if isinstance(structure, dict) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def in_scope(rel_path, globs):
    for pattern in globs:
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if pattern.endswith("/**") and rel_path.startswith(pattern[:-3] + "/"):
            return True
        if pattern.endswith("/") and rel_path.startswith(pattern):
            return True
    return False


def read_target_content(tool_name, tool_input, file_path):
    if tool_name == "Write":
        content = tool_input.get("content")
        if content is not None:
            return content
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def strip_uncheckable(content):
    """Blank out regions where a tell is not the author's prose."""
    out = []
    in_fence = False
    in_frontmatter = False
    for index, line in enumerate(content.split("\n")):
        stripped = line.strip()
        if index == 0 and stripped == "---":
            in_frontmatter = True
            out.append("")
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            out.append("")
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence or stripped.startswith(">"):
            out.append("")
            continue
        line = re.sub(r"`[^`]*`", "", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"\[\[[^\]]*\]\]", "", line)
        out.append(line)
    return out


def git_baseline(rel_path, root=None):
    """Committed content of the file, or None when it is new or untracked."""
    base = Path(root) if root is not None else REPO_ROOT
    try:
        proc = subprocess.run(
            ["git", "-C", str(base), "show", "HEAD:" + rel_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def added_lines(content, baseline):
    """[(lineno, text)] for lines this write introduced (multiset difference)."""
    lines = strip_uncheckable(content)
    if baseline is None:
        return [(index, line) for index, line in enumerate(lines, start=1) if line.strip()]
    counts = {}
    for line in strip_uncheckable(baseline):
        key = line.strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    out = []
    for index, line in enumerate(lines, start=1):
        key = line.strip()
        if not key:
            continue
        if counts.get(key):
            counts[key] -= 1
        else:
            out.append((index, line))
    return out


def scan(numbered):
    """Return {family: (count, first_line_no, sample)}."""
    hits = {}
    for name, patterns in COMPILED.items():
        count = 0
        first = None
        for lineno, line in numbered:
            for pattern in patterns:
                found = pattern.findall(line)
                if found:
                    count += len(found)
                    if first is None:
                        match = pattern.search(line)
                        first = (lineno, match.group(0).strip())
        if count:
            hits[name] = (count, first[0], first[1])
    return hits


def should_report(hits):
    if "em/en dash" in hits:
        return True
    return len(hits) >= 3


def format_message(rel_path, hits):
    total = sum(value[0] for value in hits.values())
    lines = [
        "[prose-lint] this write ADDED %d writing tell(s) across %d pattern famil%s in %s"
        % (total, len(hits), "y" if len(hits) == 1 else "ies", rel_path),
        "That file is outbound (it goes out under the operator's name).",
    ]
    for name in sorted(hits, key=lambda key: -hits[key][0]):
        count, lineno, sample = hits[name]
        lines.append("  - %s x%d (line %d: \"%s\")" % (name, count, lineno, sample))
    lines.append("Advisory only. Run the humanize skill on this file to fix, or ignore.")
    return "\n".join(lines)


def decide(data, root=None, structure=None):
    """Return the advisory JSON string, or None when silent."""
    if not isinstance(data, dict):
        return None
    base = Path(root) if root is not None else REPO_ROOT
    globs = outbound_globs(structure if structure is not None else load_structure(base))
    if not globs:
        return None
    tool_name = canonical_tool_name(data)
    if tool_name not in ("Write", "Edit", "apply_patch"):
        return None
    tool_input = data.get("tool_input") or data.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    messages = []
    for file_path in changed_paths(data):
        if not file_path.lower().endswith(".md"):
            continue
        rel_path = relative_path(file_path, base)
        if rel_path is None or not in_scope(rel_path, globs):
            continue
        content = read_target_content(tool_name, tool_input, str(absolute_path(file_path, base)))
        if content is None:
            continue
        if re.search(r"^type:\s*record\b", content[:800], re.MULTILINE):
            continue
        numbered = added_lines(content, git_baseline(rel_path, base))
        if not numbered:
            continue
        hits = scan(numbered)
        if hits and should_report(hits):
            messages.append(format_message(rel_path, hits))
    if not messages:
        return None
    return advisory_for(data, "PostToolUse", "\n".join(messages))


def main():
    debug.start()
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        debug.end(HOOK_NAME, out_bytes=0, extra="bad-json")
        sys.exit(0)
    out = decide(data)
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="clean-or-out-of-scope")
        sys.exit(0)
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="advisory")
    sys.exit(0)


if __name__ == "__main__":
    main()
