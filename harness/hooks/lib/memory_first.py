#!/usr/bin/env python3
"""PreToolUse advisory for web tools: name local files that match the query.

Enforcement rung: advisory. Before WebSearch, WebFetch, or the Codex web
function runs, the query is tokenized and compared against filename stems
under the configured memory zones: the knowledge, decisions, docs, and
records lanes from structure.json. Content is never read; only names are
matched, so a silent hook does not mean the lanes hold nothing.

Silent when every zone lane is null, when the tool carries no query text,
or when nothing matches. Never blocks; always exits 0.
"""
import json
import os
import re
import sys
from pathlib import Path

from _debug import debug
from hook_io import REPO_ROOT, advisory_for, lane_paths

HOOK_NAME = "memory-first"
ZONE_LANES = ("knowledge", "decisions", "docs", "records")
MIN_TOKEN_LEN = 4
MAX_DEPTH = 3
MAX_ENTRIES = 4000
MAX_SHOWN = 10


def tokenize(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {word for word in words if len(word) >= MIN_TOKEN_LEN}


def search_texts(tool_name, tool_input):
    if tool_name in {"WebSearch", "web_search"}:
        return [tool_input.get("query", "") or ""]
    if tool_name == "WebFetch":
        return [tool_input.get("url", "") or ""]
    if tool_name in {"web__run", "web.run"}:
        values = []
        for key in ("search_query", "image_query"):
            for item in tool_input.get(key, []) or []:
                if isinstance(item, dict):
                    values.append(item.get("q", "") or "")
        return values
    return []


def zones(root=None):
    """Repo-relative zone paths in lane order, deduplicated."""
    seen, out = set(), []
    for lane in ZONE_LANES:
        for path in lane_paths(lane, root):
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def iter_stems(root, zone):
    """Yield (stem, display_path) for Markdown files and directories in a zone."""
    base = Path(root) / zone
    if base.is_file():
        yield base.stem, zone
        return
    if not base.is_dir():
        return
    count = 0
    for current, dirs, files in os.walk(base):
        relative = os.path.relpath(current, base)
        depth = 0 if relative == "." else relative.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "_")))
        if depth >= MAX_DEPTH:
            dirs[:] = []
        prefix = zone if relative == "." else zone + "/" + relative.replace(os.sep, "/")
        for name in dirs:
            count += 1
            yield name, f"{prefix}/{name}"
        for name in sorted(files):
            if not name.endswith(".md") or name.startswith(("_", ".")):
                continue
            count += 1
            if count > MAX_ENTRIES:
                return
            yield name[:-3], f"{prefix}/{name}"


def matches(tokens, root=None):
    root = Path(root) if root is not None else REPO_ROOT
    found = []
    for zone in zones(root):
        for stem, display in iter_stems(root, zone):
            if tokens & tokenize(stem) and display not in found:
                found.append(display)
    return found


def decide(data, root=None):
    """Return the advisory JSON string, or None when silent."""
    if not isinstance(data, dict):
        return None
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    if not isinstance(tool_input, dict):
        return None
    texts = [value for value in search_texts(tool_name, tool_input) if value]
    if not texts:
        return None
    tokens = set().union(*(tokenize(value) for value in texts))
    if not tokens or not zones(root):
        return None
    found = matches(tokens, root)
    if not found:
        return None
    shown = ", ".join(found[:MAX_SHOWN])
    more = f" (+{len(found) - MAX_SHOWN} more)" if len(found) > MAX_SHOWN else ""
    message = (
        f"memory-first: local files match these search terms: {shown}{more}. "
        "Check the configured lanes before the external lookup."
    )
    return advisory_for(data, "PreToolUse", message)


def main():
    debug.start()
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        debug.end(HOOK_NAME, out_bytes=0, extra="bad-json")
        sys.exit(0)
    out = decide(data)
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="silent")
        sys.exit(0)
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="advisory")
    sys.exit(0)


if __name__ == "__main__":
    main()
