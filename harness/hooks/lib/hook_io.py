"""Shared normalization for Claude, Codex, and OpenCode hook payloads.

This module is the only place a hook learns about the repository layout. It
reads harness/registry/structure.json through load_structure() and fails
open: a missing or malformed file yields the shipped defaults plus one stderr
note, never an exception and never a deny. It imports nothing from
harness/tools so a hook stays runnable with the standard library alone.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STRUCTURE_RELATIVE = ("harness", "registry", "structure.json")
PATCH_PATH_RE = re.compile(
    r"^\*\*\* (Add File|Update File|Delete File|Move to):\s+(.+?)\s*$"
)

LANE_NAMES = ("identity", "knowledge", "journal", "decisions", "records", "docs")
TIER_LABELS = ("public", "internal", "confidential", "restricted", "secret")

# The defaults contract: a missing structure.json yields exactly this object.
# harness/tools/harness_registry.py carries the same object and both loaders
# must agree; the hook side never validates beyond what fail-open needs.
DEFAULT_STRUCTURE = {
    "schema_version": 1,
    "lanes": {
        "identity": ["brain/shared/IDENTITY.md", "brain/local/OPERATOR.md"],
        "knowledge": ["brain/shared/knowledge", "brain/local/knowledge"],
        "journal": ["brain/local/journal"],
        "decisions": ["docs/decisions"],
        "records": None,
        "docs": ["docs"],
    },
    "git": {"mode": "main-only"},
    "outbound_globs": [],
    "brain": {"local_tracked": False, "local_path": "brain/local"},
    "tiers": {
        "lane_defaults": {
            "identity": "internal",
            "knowledge": "internal",
            "journal": "internal",
            "decisions": "internal",
            "records": "internal",
            "docs": "public",
        },
        "unlisted_path": "internal",
    },
    "delegation": {"mandatory": False},
    "selection_scope": "repo",
    "contract": {"mode": "rendered"},
    "host": {"adopted": False, "roots": [], "harness_owned": []},
}


def _note(message: str) -> None:
    try:
        print(f"hook-io: {message}", file=sys.stderr)
    except Exception:
        pass


def _merge(default, value):
    """Merge a loaded value over a default, key by key for nested objects."""
    if isinstance(default, dict) and isinstance(value, dict):
        merged = {key: copy.deepcopy(item) for key, item in default.items()}
        for key, item in value.items():
            merged[key] = _merge(default.get(key), item) if key in default else copy.deepcopy(item)
        return merged
    return copy.deepcopy(value)


def _valid_lane(value) -> bool:
    if value is None:
        return True
    if not isinstance(value, list) or not value:
        return False
    for item in value:
        if not isinstance(item, str) or not item:
            return False
        if item.startswith("/") or ".." in item.split("/") or (len(item) > 1 and item[1] == ":"):
            return False
    return True


def load_structure(root: str | Path | None = None) -> dict:
    """Return the host structure, merged over the defaults; never raises."""
    base = Path(root) if root is not None else REPO_ROOT
    path = base.joinpath(*STRUCTURE_RELATIVE)
    defaults = copy.deepcopy(DEFAULT_STRUCTURE)
    try:
        if not path.is_file():
            return defaults
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        _note(f"structure.json unreadable, using defaults ({exc.__class__.__name__})")
        return defaults
    if not isinstance(loaded, dict):
        _note("structure.json is not an object, using defaults")
        return defaults
    merged = _merge(defaults, loaded)
    lanes = merged.get("lanes")
    if not isinstance(lanes, dict):
        _note("structure.json lanes is not an object, using default lanes")
        merged["lanes"] = copy.deepcopy(DEFAULT_STRUCTURE["lanes"])
        return merged
    for name in LANE_NAMES:
        if name not in lanes:
            lanes[name] = copy.deepcopy(DEFAULT_STRUCTURE["lanes"][name])
        elif not _valid_lane(lanes[name]):
            _note(f"structure.json lane {name} is malformed, treating it as not configured")
            lanes[name] = None
    return merged


def lane_paths(name: str, root: str | Path | None = None) -> list[str]:
    """Repo-relative POSIX paths for a lane; an empty list when it is null."""
    lanes = load_structure(root).get("lanes", {})
    value = lanes.get(name) if isinstance(lanes, dict) else None
    if not isinstance(value, list):
        return []
    return [item.strip("/") for item in value if isinstance(item, str) and item]


def tool_input(data: dict) -> dict:
    value = data.get("tool_input") or data.get("input") or {}
    return value if isinstance(value, dict) else {}


def canonical_tool_name(data: dict) -> str:
    """Return the shared canonical tool name for known runtime aliases.

    Bash and Agent are the canonical names the hook logic keys on. The alias
    map stays deliberately small; every added alias needs an exact payload
    fixture before it is trusted.
    """
    value = data.get("tool_name", "")
    if not isinstance(value, str):
        return ""
    return {
        "shell_command": "Bash",
        "exec_command": "Bash",
        "agent": "Agent",
        "Task": "Agent",
        "spawn_agent": "Agent",
    }.get(value, value)


def _quoted_element(item: str) -> str:
    """Quote an argv element that carries a separator.

    Only the classifier asks for this. It re-parses the joined text, and
    without the quotes an element such as a whole command string would be
    indistinguishable from separate arguments.
    """
    if item and not any(char in item for char in " \t\n\"'\\"):
        return item
    return "'" + item.replace("'", "'\\''") + "'"


def _command_field_text(value, quote: bool = False) -> str:
    """Return the classifiable text for one command-shaped field value.

    A list-valued command (argv form) is joined with spaces. The join adds
    no quoting by default, which is what the command digest hashes; a
    caller that re-parses the text passes quote=True so an element that
    contains a separator stays one argument. An invalid element
    (non-string) yields "" for the whole field rather than a partial join.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if not isinstance(item, str):
                return ""
            parts.append(_quoted_element(item) if quote else item)
        return " ".join(parts)
    return ""


def shell_command_text(data: dict, quote: bool = False) -> str:
    """Extract a shell command from the canonical Bash payload.

    Codex unified exec (exec_command) carries the command under "cmd" rather
    than "command". Both fields are read: an empty or missing "command"
    falls through to "cmd" rather than short-circuiting on the empty string,
    and when both fields carry non-empty text, both are classified (joined
    with "; " so each stays its own scan segment) rather than only the first.

    quote=True keeps the argv boundary of a list-valued field for a caller
    that re-parses the joined text.
    """
    if canonical_tool_name(data) != "Bash":
        return ""
    input_data = tool_input(data)
    parts = []
    for key in ("command", "cmd"):
        text = _command_field_text(input_data.get(key), quote)
        if text and text not in parts:
            parts.append(text)
    return "; ".join(parts)


def patch_texts(data: dict) -> list[str]:
    values: list[str] = []
    raw_input = data.get("tool_input") or data.get("input") or {}
    if isinstance(raw_input, str):
        values.append(raw_input)
    elif isinstance(raw_input, dict):
        for key in ("command", "patch", "input", "content", "text"):
            value = raw_input.get(key)
            if isinstance(value, str):
                values.append(value)
    for key in ("command", "patch", "input", "content", "text"):
        value = data.get(key)
        if isinstance(value, str):
            values.append(value)
    return values


def changed_paths(data: dict, include_deleted: bool = False) -> list[str]:
    """Return unique target paths for Write, Edit, NotebookEdit, and apply_patch."""
    direct = tool_input(data).get("file_path") or tool_input(data).get("notebook_path")
    if direct:
        return [str(direct)]

    paths: list[str] = []
    for text in patch_texts(data):
        for line in text.splitlines():
            match = PATCH_PATH_RE.match(line.strip())
            if not match:
                continue
            action, path = match.groups()
            if action == "Delete File" and not include_deleted:
                continue
            if path not in paths:
                paths.append(path)
    return paths


def absolute_path(path: str, root: str | Path | None = None) -> Path:
    base = Path(root) if root is not None else REPO_ROOT
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def relative_path(path: str, root: str | Path | None = None) -> str | None:
    """Repo-relative POSIX path, or None when the path is outside the root."""
    base = Path(root).resolve() if root is not None else REPO_ROOT
    try:
        return absolute_path(path, base).relative_to(base).as_posix()
    except (OSError, ValueError):
        return None


def parse_frontmatter(text: str, max_lines: int = 500) -> tuple[dict | None, bool]:
    """Return (fields, closed) for a leading YAML-style frontmatter block.

    fields is None when the text carries no block. Only top-level scalar keys
    and simple lists (inline or dash lists) are read; nothing else is parsed,
    which keeps the hook free of a YAML dependency.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, True
    end = None
    for index in range(1, min(len(lines), max_lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, False
    fields: dict = {}
    current = None
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in (" ", "\t"):
            stripped = line.strip()
            if current is not None and stripped.startswith("- ") and isinstance(fields.get(current), list):
                fields[current].append(_scalar(stripped[2:]))
            continue
        if line.startswith("- "):
            if current is not None and isinstance(fields.get(current), list):
                fields[current].append(_scalar(line[2:]))
            continue
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        if not key or not (key[0].isalpha() or key[0] == "_") or any(c in key for c in " \t\"'"):
            continue
        rest = rest.strip()
        current = key
        if rest == "":
            fields[key] = []
        elif rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            fields[key] = [_scalar(item) for item in inner.split(",") if item.strip()] if inner else []
        else:
            fields[key] = _scalar(rest)
    return fields, True


def _scalar(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    return value


def advisory(event: str, message: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": message,
            }
        },
        ensure_ascii=False,
    )


def advisory_for(data: dict, event: str, message: str) -> str:
    """Emit a model-visible advisory in the active runtime's accepted shape.

    Turn-scoped payloads (turn_id present) and apply_patch or web tools take
    the hookSpecificOutput shape. Claude Write/Edit payloads take a top-level
    systemMessage, the shape Claude accepts for edit-tool advisories.
    """
    tool_name = canonical_tool_name(data)
    if "turn_id" in data or tool_name in {"apply_patch", "web__run", "web.run"}:
        return advisory(event, message)
    return json.dumps({"systemMessage": message}, ensure_ascii=False)


def deny(hook_name: str, tier: str, reason: str, command_sha256: str, recovery: str) -> str:
    """Emit the PreToolUse deny envelope in the shared reason format."""
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"{hook_name} [{tier}]: {reason}. "
                    f"[command-sha256:{command_sha256}] {recovery}"
                ),
            }
        }
    )
