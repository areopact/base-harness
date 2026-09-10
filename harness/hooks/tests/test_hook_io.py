"""H1: payload normalization and the structure.json defaults contract."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import hook_io  # noqa: E402
from hook_io import (  # noqa: E402
    canonical_tool_name,
    changed_paths,
    lane_paths,
    load_structure,
    relative_path,
    shell_command_text,
)

# The defaults contract from the shared interfaces, restated verbatim so a
# drift in hook_io.DEFAULT_STRUCTURE is caught against the interface text and
# not against itself.
INTERFACE_DEFAULTS = {
    "schema_version": 1,
    "lanes": {
        "identity": ["brain/shared/IDENTITY.md", "brain/local/OPERATOR.md"],
        "knowledge": ["brain/shared/knowledge", "brain/local/knowledge"],
        "decisions": ["docs/decisions"],
        "records": None,
        "docs": ["docs"],
    },
    "git": {"mode": "main-only"},
    "outbound_globs": [],
    "write_deny": {"globs": [], "except": []},
    "brain": {"local_tracked": False, "local_path": "brain/local"},
    "tiers": {
        "lane_defaults": {
            "identity": "internal",
            "knowledge": "internal",
            "decisions": "internal",
            "records": "internal",
            "docs": "public",
        },
        "unlisted_path": "internal",
    },
    "delegation": {"mandatory": False},
    "selection_scope": "repo",
    "contract": {"mode": "rendered"},
    "host": {"adopted": False, "roots": [], "harness_owned": [], "profile": "solo", "verify_command": None},
}


def write_structure(root, text):
    target = Path(root) / "harness" / "registry" / "structure.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


class StructureDefaultsTests(unittest.TestCase):
    def test_missing_file_yields_the_interface_object_verbatim(self):
        with tempfile.TemporaryDirectory() as temp:
            assert load_structure(temp) == INTERFACE_DEFAULTS
        assert hook_io.DEFAULT_STRUCTURE == INTERFACE_DEFAULTS

    def test_malformed_file_fails_open_with_one_stderr_line(self):
        with tempfile.TemporaryDirectory() as temp:
            write_structure(temp, "{not json")
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                result = load_structure(temp)
            assert result == INTERFACE_DEFAULTS
            lines = [line for line in captured.getvalue().splitlines() if line.strip()]
            assert len(lines) == 1 and lines[0].startswith("hook-io:")

    def test_non_object_file_fails_open(self):
        with tempfile.TemporaryDirectory() as temp:
            write_structure(temp, "[1, 2, 3]")
            with contextlib.redirect_stderr(io.StringIO()):
                assert load_structure(temp) == INTERFACE_DEFAULTS

    def test_present_file_merges_key_by_key_and_keeps_null_lanes(self):
        with tempfile.TemporaryDirectory() as temp:
            write_structure(temp, json.dumps({
                "lanes": {"records": ["notes"], "identity": None},
                "delegation": {"mandatory": True},
            }))
            result = load_structure(temp)
            assert result["lanes"]["records"] == ["notes"]
            assert result["lanes"]["identity"] is None
            assert result["lanes"]["docs"] == ["docs"]
            assert result["delegation"] == {"mandatory": True}
            assert result["git"] == {"mode": "main-only"}
            assert lane_paths("identity", temp) == []
            assert lane_paths("records", temp) == ["notes"]

    def test_malformed_lane_value_is_treated_as_not_configured(self):
        with tempfile.TemporaryDirectory() as temp:
            write_structure(temp, json.dumps({"lanes": {"docs": ["/absolute"], "records": "string"}}))
            with contextlib.redirect_stderr(io.StringIO()):
                result = load_structure(temp)
            assert result["lanes"]["docs"] is None
            assert result["lanes"]["records"] is None
            assert lane_paths("docs", temp) == []

    def test_loader_never_raises_on_unreadable_root(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "does-not-exist"
            assert load_structure(missing) == INTERFACE_DEFAULTS


class PayloadNormalizationTests(unittest.TestCase):
    def test_alias_map_is_exactly_the_interface_set(self):
        assert canonical_tool_name({"tool_name": "Bash"}) == "Bash"
        assert canonical_tool_name({"tool_name": "shell_command"}) == "Bash"
        assert canonical_tool_name({"tool_name": "Agent"}) == "Agent"
        assert canonical_tool_name({"tool_name": "agent"}) == "Agent"
        assert canonical_tool_name({"tool_name": "Task"}) == "Agent"
        assert canonical_tool_name({"tool_name": "spawn_agent"}) == "Agent"
        assert canonical_tool_name({"tool_name": "exec_command"}) == "Bash"
        assert canonical_tool_name({"tool_name": "write_stdin"}) == "write_stdin"
        assert canonical_tool_name({"tool_name": 12}) == ""
        assert canonical_tool_name({}) == ""

    def test_input_alias_is_accepted(self):
        payload = {"tool_name": "shell_command", "input": {"command": "echo ok"}}
        assert shell_command_text(payload) == "echo ok"

    def test_shell_command_requires_string_or_list_command(self):
        payload = {"tool_name": "shell_command", "tool_input": {"command": "echo ok"}}
        assert shell_command_text(payload) == "echo ok"
        payload["tool_input"]["command"] = 12
        assert shell_command_text(payload) == ""
        assert shell_command_text({"tool_name": "Read", "tool_input": {"command": "x"}}) == ""

    def test_shell_command_accepts_list_valued_command(self):
        payload = {"tool_name": "shell_command", "tool_input": {"command": ["git", "push", "--force", "origin main"]}}
        assert shell_command_text(payload) == "git push --force origin main"
        payload["tool_input"]["command"] = ["echo", 12]
        assert shell_command_text(payload) == ""

    def test_exec_command_reads_the_cmd_field(self):
        payload = {"tool_name": "exec_command", "tool_input": {"cmd": "git push --force origin main"}}
        assert canonical_tool_name(payload) == "Bash"
        assert shell_command_text(payload) == "git push --force origin main"

    def test_empty_command_falls_through_to_cmd(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "", "cmd": ["rm", "-rf", "/"]}}
        assert shell_command_text(payload) == "rm -rf /"

    def test_command_and_cmd_both_present_are_both_classified(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "echo hi", "cmd": "git push -f origin main"}}
        assert shell_command_text(payload) == "echo hi; git push -f origin main"

    def test_write_stdin_stays_silent(self):
        payload = {"tool_name": "write_stdin", "tool_input": {"input": "y\n"}}
        assert canonical_tool_name(payload) == "write_stdin"
        assert shell_command_text(payload) == ""

    def test_apply_patch_text_extracts_non_deleted_paths(self):
        patch = "*** Begin Patch\n*** Update File: docs/a.md\n*** Delete File: docs/b.md\n*** Add File: docs/c.md\n*** End Patch"
        raw = {"tool_name": "apply_patch", "tool_input": patch}
        assert changed_paths(raw) == ["docs/a.md", "docs/c.md"]
        assert changed_paths(raw, include_deleted=True) == ["docs/a.md", "docs/b.md", "docs/c.md"]
        nested = {"tool_name": "apply_patch", "tool_input": {"patch": patch}}
        assert changed_paths(nested) == ["docs/a.md", "docs/c.md"]

    def test_direct_file_path_wins_over_patch_text(self):
        payload = {"tool_name": "Write", "tool_input": {"file_path": "docs/x.md", "content": "*** Update File: y.md"}}
        assert changed_paths(payload) == ["docs/x.md"]

    def test_relative_path_is_posix_and_none_outside_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inside = root / "docs" / "page.md"
            assert relative_path(str(inside), root) == "docs/page.md"
            assert relative_path("docs/page.md", root) == "docs/page.md"
            assert relative_path(str(root.parent / "elsewhere.md"), root) is None

    def test_deny_envelope_has_the_exact_key_set(self):
        text = hook_io.deny("hook", "tier", "reason", "0" * 64, "recover")
        payload = json.loads(text)
        assert set(payload) == {"hookSpecificOutput"}
        specific = payload["hookSpecificOutput"]
        assert set(specific) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
        assert specific["hookEventName"] == "PreToolUse"
        assert specific["permissionDecision"] == "deny"
        assert specific["permissionDecisionReason"].startswith("hook [tier]: reason. [command-sha256:")

    def test_advisory_shape_follows_the_payload(self):
        claude_write = {"tool_name": "Write", "tool_input": {"file_path": "x.md"}}
        assert set(json.loads(hook_io.advisory_for(claude_write, "PostToolUse", "m"))) == {"systemMessage"}
        turn_scoped = dict(claude_write, turn_id="t")
        payload = json.loads(hook_io.advisory_for(turn_scoped, "PostToolUse", "m"))
        assert payload["hookSpecificOutput"] == {"hookEventName": "PostToolUse", "additionalContext": "m"}


if __name__ == "__main__":
    unittest.main()
