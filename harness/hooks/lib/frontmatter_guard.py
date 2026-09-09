#!/usr/bin/env python3
"""PostToolUse(Write|Edit|apply_patch) advisory: frontmatter classification.

Enforcement rung: advisory. Never blocks; always exits 0.

Scope: Markdown files under any lane path configured in structure.json. A
file outside every lane, or any file when no lane is configured, is ignored.

Checks:

  a. a frontmatter block opened on line 1 is closed by a matching "---";
  b. access:, when present, is one of the five tier labels;
  c. allowed_collaborators is present exactly when access is restricted, is
     non-empty, and every id exists in harness/registry/collaborators.yaml;
  d. created, updated, date, last_assessed, and archived are ISO dates.

Content source: for Write the exact bytes in tool_input.content; for Edit
and apply_patch the post-edit file on disk. Pure text parsing, no YAML
dependency, no network.
"""
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from _debug import debug
from hook_io import (
    REPO_ROOT,
    TIER_LABELS,
    absolute_path,
    advisory_for,
    canonical_tool_name,
    changed_paths,
    lane_paths,
    parse_frontmatter,
    relative_path,
)

HOOK_NAME = "frontmatter-guard"
LANE_NAMES = ("identity", "knowledge", "decisions", "records", "docs")
DATE_KEYS = ("created", "updated", "date", "last_assessed", "archived")
COLLABORATORS_RELATIVE = ("harness", "registry", "collaborators.yaml")
MAX_FILE_BYTES = 5_000_000
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def scope_paths(root=None):
    seen, out = set(), []
    for lane in LANE_NAMES:
        for path in lane_paths(lane, root):
            if path not in seen:
                seen.add(path)
                out.append(path)
    return out


def in_scope(rel_path, root=None):
    for lane_path in scope_paths(root):
        if rel_path == lane_path or rel_path.startswith(lane_path + "/"):
            return True
    return False


def collaborator_ids(root=None):
    """Return (ids, present) from the collaborator registry; ids empty when absent."""
    base = Path(root) if root is not None else REPO_ROOT
    target = base.joinpath(*COLLABORATORS_RELATIVE)
    try:
        text = target.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return set(), False
    return set(re.findall(r"(?m)^\s*-\s*id:\s*['\"]?([A-Za-z0-9_.-]+)", text)), True


def check_frontmatter(text, root=None):
    """Return a list of violation dicts (possibly empty)."""
    fields, closed = parse_frontmatter(text)
    if fields is None:
        return []
    if not closed:
        return [{
            "rule": "unclosed-frontmatter",
            "level": "ERROR",
            "message": "frontmatter opened at line 1 but no closing '---' was found",
        }]
    violations = []
    access = fields.get("access")
    access_value = access.strip().lower() if isinstance(access, str) else None
    if access is not None and access_value not in TIER_LABELS:
        violations.append({
            "rule": "invalid-access-value",
            "level": "ERROR",
            "message": f"access: {access!r} is not one of {{{','.join(TIER_LABELS)}}}",
        })
    restricted = access_value == "restricted"
    collaborators = fields.get("allowed_collaborators")
    if restricted and collaborators is None:
        violations.append({
            "rule": "missing-allowed-collaborators",
            "level": "ERROR",
            "message": "access: restricted requires a non-empty allowed_collaborators list",
        })
    elif collaborators is not None and not restricted:
        violations.append({
            "rule": "unexpected-allowed-collaborators",
            "level": "ERROR",
            "message": f"allowed_collaborators is present but access is not restricted (access: {access!r})",
        })
    elif restricted:
        ids = collaborators if isinstance(collaborators, list) else [collaborators]
        ids = [item for item in ids if isinstance(item, str) and item]
        if not ids:
            violations.append({
                "rule": "empty-allowed-collaborators",
                "level": "ERROR",
                "message": "access: restricted requires at least one collaborator id",
            })
        else:
            known, present = collaborator_ids(root)
            if not present:
                violations.append({
                    "rule": "collaborator-registry-missing",
                    "level": "WARN",
                    "message": "harness/registry/collaborators.yaml not found; collaborator ids were not validated",
                })
            else:
                unknown = [item for item in ids if item not in known]
                if unknown:
                    violations.append({
                        "rule": "unknown-collaborator",
                        "level": "ERROR",
                        "message": f"allowed_collaborators id(s) not in the registry: {', '.join(unknown)}",
                    })
    for key in DATE_KEYS:
        value = fields.get(key)
        if value is None or isinstance(value, list):
            continue
        text_value = str(value).strip()
        valid = bool(ISO_DATE.match(text_value))
        if valid:
            try:
                date.fromisoformat(text_value)
            except ValueError:
                valid = False
        if not valid:
            violations.append({
                "rule": "invalid-iso-date",
                "level": "ERROR",
                "message": f"{key}: {text_value!r} is not an ISO date (YYYY-MM-DD)",
            })
    return violations


def format_message(rel_path, violations):
    parts = [f"[{item['level']} {item['rule']}] {item['message']}" for item in violations]
    return f"frontmatter-guard: {rel_path}: " + " ".join(parts)


def read_target_content(tool_name, tool_input, file_path):
    if tool_name == "Write":
        content = tool_input.get("content")
        if content is not None:
            return content
    try:
        if os.path.getsize(file_path) > MAX_FILE_BYTES:
            return None
        with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def decide(data, root=None):
    """Return the advisory JSON string, or None when silent."""
    if not isinstance(data, dict):
        return None
    tool_name = canonical_tool_name(data)
    if tool_name not in ("Write", "Edit", "apply_patch"):
        return None
    tool_input = data.get("tool_input") or data.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    base = Path(root) if root is not None else REPO_ROOT
    messages = []
    for file_path in changed_paths(data):
        if not file_path.lower().endswith(".md"):
            continue
        rel_path = relative_path(file_path, base)
        if rel_path is None or not in_scope(rel_path, base):
            continue
        content = read_target_content(tool_name, tool_input, str(absolute_path(file_path, base)))
        if content is None:
            continue
        violations = check_frontmatter(content, base)
        if violations:
            messages.append(format_message(rel_path, violations))
    if not messages:
        return None
    return advisory_for(data, "PostToolUse", "\n".join(messages))


def main():
    debug.start()
    try:
        data = json.load(sys.stdin)
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
