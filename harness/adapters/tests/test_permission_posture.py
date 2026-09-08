"""P5-1: the shipped permission posture is minimal.

This is the CI assertion for the permission posture. The test name is stable
so the workflow can invoke it directly:

    python -m pytest harness/adapters/tests/test_permission_posture.py -q
"""

from __future__ import annotations

import re
import unittest

try:
    import tomllib
except ImportError:  # Python 3.10: TOML parsing unavailable in the stdlib
    tomllib = None  # type: ignore[assignment]

from ._paths import ADAPTERS, bind_unittest, read_json, read_text

CLAUDE_SETTINGS = ADAPTERS / "claude" / "settings.base.json"
CODEX_CONFIG = ADAPTERS / "codex" / "config.toml"

# Keys that switch off the runtime's own prompting. Forbidden at the top level
# and inside "permissions" of the generated Claude settings file.
FORBIDDEN_CLAUDE_KEYS = (
    "defaultMode",
    "bypassPermissions",
    "skipDangerousModePermissionPrompt",
    "autoMode",
    "dangerouslySkipPermissions",
)

# Tool names that must never appear in permissions.allow, with or without a
# wildcard argument. Read-shaped tools are the only allowed entries.
NON_READ_TOOLS = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Task", "Workflow")
READ_ONLY_TOOLS = ("Read", "Glob", "Grep")

# Operator-owned Codex permission controls that the repository config never sets.
FORBIDDEN_CODEX_KEYS = (
    "approval_policy",
    "approvals_reviewer",
    "sandbox_mode",
    "sandbox_workspace_write",
    "default_permissions",
    "permissions",
)


def _walk_keys(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            yield path, key
            yield from _walk_keys(child, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, f"{prefix}[{index}]")


def test_claude_settings_has_no_forbidden_keys_anywhere():
    data = read_json(CLAUDE_SETTINGS)
    found = [path for path, key in _walk_keys(data) if key in FORBIDDEN_CLAUDE_KEYS]
    assert found == [], f"forbidden permission keys present: {found}"


def test_claude_settings_raw_text_has_no_bypass_tokens():
    text = read_text(CLAUDE_SETTINGS)
    for token in FORBIDDEN_CLAUDE_KEYS:
        assert token not in text, f"{token} appears in settings.base.json"


def test_claude_allow_list_is_read_only():
    data = read_json(CLAUDE_SETTINGS)
    allow = data["permissions"]["allow"]
    assert isinstance(allow, list) and allow, "permissions.allow must be a non-empty list"
    pattern = re.compile(r"^(%s)(\(.*\))?$" % "|".join(NON_READ_TOOLS))
    widened = [entry for entry in allow if pattern.match(entry)]
    assert widened == [], f"non-read tools in permissions.allow: {widened}"
    read_pattern = re.compile(r"^(%s)(\(\*\))?$" % "|".join(READ_ONLY_TOOLS))
    unexpected = [entry for entry in allow if not read_pattern.match(entry)]
    assert unexpected == [], f"permissions.allow carries entries outside the read-shaped set: {unexpected}"


def test_claude_deny_list_covers_credential_shapes():
    data = read_json(CLAUDE_SETTINGS)
    deny = data["permissions"]["deny"]
    assert isinstance(deny, list) and deny, "permissions.deny must be a non-empty list"
    # One pattern per credential shape the repository's .gitignore block enumerates:
    # environment files (including dotted variants), plus the pem, key, p12, and
    # pfx extensions. Deny outranks allow in Claude Code, so Read(*) in
    # permissions.allow is only safe while this list actually covers these
    # shapes; a shape missing here silently widens Read(*) to that credential.
    required_patterns = (
        re.compile(r"\.env(\.\*)?\)$"),
        re.compile(r"\.envrc\)$"),
        re.compile(r"\*\.pem\)$"),
        re.compile(r"\*\.key\)$"),
        re.compile(r"\*\.p12\)$"),
        re.compile(r"\*\.pfx\)$"),
    )
    missing = [pattern.pattern for pattern in required_patterns if not any(pattern.search(entry) for entry in deny)]
    assert missing == [], f"permissions.deny is missing coverage for: {missing}"


def test_claude_settings_declares_no_model_and_no_plugins_widening():
    data = read_json(CLAUDE_SETTINGS)
    assert "model" not in data, "the runtime's own model choice is left to the operator"
    assert set(data) <= {"$schema", "permissions", "hooks", "enabledPlugins", "env"}


@unittest.skipIf(tomllib is None, "requires Python 3.11+ (tomllib is stdlib-only from 3.11)")
def test_codex_config_has_no_operator_permission_controls():
    text = read_text(CODEX_CONFIG)
    data = tomllib.loads(text)
    found = [path for path, key in _walk_keys(data) if key in FORBIDDEN_CODEX_KEYS]
    assert found == [], f"operator permission controls present in config.toml: {found}"
    # Also check the raw text so a commented-out or profile-nested key is visible to a reviewer.
    for key in FORBIDDEN_CODEX_KEYS:
        assert re.search(rf"^\s*{re.escape(key)}\s*=", text, re.M) is None, f"{key} assigned in config.toml"


@unittest.skipIf(tomllib is None, "requires Python 3.11+ (tomllib is stdlib-only from 3.11)")
def test_codex_config_declares_only_environment_hooks_and_agents():
    data = tomllib.loads(read_text(CODEX_CONFIG))
    assert set(data) <= {"allow_login_shell", "developer_instructions", "shell_environment_policy", "features", "agents"}
    assert data["features"]["hooks"] is True
    assert "model" not in data
    assert "projects" not in data, "trust is granted by the operator, never by the repository"


bind_unittest(globals(), "PermissionPostureBridge")
