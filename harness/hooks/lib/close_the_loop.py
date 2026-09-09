#!/usr/bin/env python3
"""Stop hook: close-the-loop reminder over the configured lanes.

Enforcement rung: advisory. Never blocks; always exits 0.

One `git status --porcelain` (read-only, optional locks disabled) lists the
staged, modified, and untracked files. Each path is attributed to the lane
in structure.json that contains it. The reminder names the lanes that hold
changes but have no companion entry in the decisions lane, and
lists Markdown files whose `updated:` frontmatter is not today's date.

Silent when the tree is clean or when no lane is configured at all.
"""
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

from _debug import debug
from hook_io import REPO_ROOT, load_structure

HOOK_NAME = "close-the-loop"
LANE_NAMES = ("identity", "knowledge", "decisions", "records", "docs")
EVIDENCE_LANES = ("decisions",)


def dirty_paths(root):
    """Repo-relative paths with index or working-tree changes."""
    try:
        environment = os.environ.copy()
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
            env=environment,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    paths = []
    for line in result.stdout.splitlines():
        if len(line) < 4 or not line[:2].strip():
            continue
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        paths.append(path.replace("\\", "/"))
    return paths


def frontmatter_updated(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            content = handle.read(4000)
    except OSError:
        return None
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    match = re.search(r"(?m)^updated:\s*(.+)$", content[3:end])
    return match.group(1).strip().strip("'\"") if match else None


def lane_map(structure):
    lanes = structure.get("lanes") if isinstance(structure, dict) else None
    out = {}
    if not isinstance(lanes, dict):
        return out
    for name in LANE_NAMES:
        value = lanes.get(name)
        if isinstance(value, list) and value:
            out[name] = [item.strip("/") for item in value if isinstance(item, str) and item]
    return out


def lane_of(path, lanes):
    for name, prefixes in lanes.items():
        for prefix in prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                return name
    return None


def closing_clause(structure):
    """The final clause's advice, composed from git.mode and host.profile.

    Both reads use .get chains so an injected structure missing the host key,
    or missing git.mode entirely, cannot raise; a missing host.profile reads
    as solo, the shipped default.
    """
    structure = structure if isinstance(structure, dict) else {}
    mode = (structure.get("git") or {}).get("mode")
    if mode == "branches":
        branch_part = "commit on a task branch (never the default branch)"
    else:
        branch_part = "commit to the default branch or park it"
    profile = (structure.get("host") or {}).get("profile", "solo")
    social_part = " and open a PR only when asked" if profile == "team" else ""
    return branch_part + social_part


def build_message(paths, lanes, root, today, structure=None):
    if not paths or not lanes:
        return None
    touched = {}
    for path in paths:
        lane = lane_of(path, lanes)
        if lane:
            touched.setdefault(lane, []).append(path)
    parts = [f"close-the-loop: {len(paths)} uncommitted change(s)"]
    if touched:
        described = ", ".join(f"{lane} ({len(items)})" for lane, items in sorted(touched.items()))
        parts.append(f"lanes touched: {described}")
    evidence_configured = [lane for lane in EVIDENCE_LANES if lane in lanes]
    evidence_touched = [lane for lane in EVIDENCE_LANES if lane in touched]
    content_lanes = sorted(lane for lane in touched if lane not in EVIDENCE_LANES)
    if content_lanes and not evidence_touched:
        if evidence_configured:
            parts.append(
                "no matching entry in " + " or ".join(evidence_configured)
                + f" for changes in {', '.join(content_lanes)}"
            )
        else:
            parts.append("no decisions lane is configured to record why these changed")
    stale = []
    for path in paths:
        if not path.endswith(".md") or lane_of(path, lanes) is None:
            continue
        value = frontmatter_updated(Path(root) / path)
        if value and value != today:
            stale.append(os.path.basename(path))
    if stale:
        shown = ", ".join(stale[:3]) + (f" +{len(stale) - 3} more" if len(stale) > 3 else "")
        parts.append(f"{len(stale)} file(s) carry a stale updated: date ({shown})")
    parts.append(f"verify the change ran, then {closing_clause(structure)}, then see harness/rules/close-the-loop.md")
    return "; ".join(parts) + "."


def decide(root=None, structure=None, today=None):
    """Return the systemMessage JSON string, or None when silent."""
    base = Path(root) if root is not None else REPO_ROOT
    structure = structure if structure is not None else load_structure(base)
    lanes = lane_map(structure)
    if not lanes:
        return None
    message = build_message(dirty_paths(base), lanes, base, today or date.today().isoformat(), structure)
    if message is None:
        return None
    return json.dumps({"systemMessage": message})


def main():
    debug.start()
    try:
        sys.stdin.read()
    except Exception:
        pass
    out = decide()
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="silent")
        sys.exit(0)
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="reminder")
    sys.exit(0)


if __name__ == "__main__":
    main()
