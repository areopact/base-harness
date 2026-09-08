"""H7: read_deny is inert without HARNESS_READ_DENY=1 and exact on the label."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "lib"))

import dispatch  # noqa: E402
import read_deny  # noqa: E402

ON = {"HARNESS_READ_DENY": "1"}
OFF = {}


def seed(temp):
    root = Path(temp)
    (root / "secret.md").write_text("---\ntitle: s\naccess: secret\n---\nbody\n", encoding="utf-8")
    (root / "internal.md").write_text("---\ntitle: i\naccess: internal\n---\nbody\n", encoding="utf-8")
    (root / "secretish.md").write_text("---\ntitle: s\naccess: secrets\n---\nbody\n", encoding="utf-8")
    (root / "nolabel.md").write_text("---\ntitle: n\n---\nbody\n", encoding="utf-8")
    (root / "plain.md").write_text("no frontmatter at all\n", encoding="utf-8")
    (root / "unclosed.md").write_text("---\naccess: secret\nnever closed\n", encoding="utf-8")
    return root


def read(path):
    return {"tool_name": "Read", "tool_input": {"file_path": str(path)}}


class ReadDenyTests(unittest.TestCase):
    def test_flag_unset_returns_nothing_even_for_a_secret_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            assert read_deny.decide(read(root / "secret.md"), OFF) is None
            assert read_deny.decide(read(root / "secret.md"), {"HARNESS_READ_DENY": "true"}) is None
            assert read_deny.decide(read(root / "secret.md"), {"HARNESS_READ_DENY": "0"}) is None

    def test_flag_set_returns_the_deny_envelope_for_a_secret_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            out = read_deny.decide(read(root / "secret.md"), ON)
            assert out is not None
            value = json.loads(out)
            assert set(value) == {"hookSpecificOutput"}
            specific = value["hookSpecificOutput"]
            assert set(specific) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}
            assert specific["hookEventName"] == "PreToolUse"
            assert specific["permissionDecision"] == "deny"
            assert specific["permissionDecisionReason"].startswith("read-deny [secret-label]: ")
            assert "[command-sha256:" in specific["permissionDecisionReason"]

    def test_non_secret_labels_always_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            for name in ("internal.md", "secretish.md", "nolabel.md", "plain.md", "unclosed.md"):
                with self.subTest(name=name):
                    assert read_deny.decide(read(root / name), ON) is None

    def test_missing_file_and_other_tools_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            assert read_deny.decide(read(root / "absent.md"), ON) is None
            assert read_deny.decide({"tool_name": "Bash", "tool_input": {"command": "cat secret.md"}}, ON) is None
            assert read_deny.decide({"tool_name": "Read", "tool_input": {}}, ON) is None
            assert read_deny.decide("not a dict", ON) is None

    def test_relative_target_resolves_against_the_given_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            out = read_deny.decide({"tool_name": "Read", "tool_input": {"file_path": "secret.md"}}, ON, root)
            assert out is not None and "secret.md is labeled access: secret" in out

    def test_dispatch_routes_read_only_when_the_flag_is_set(self):
        assert dispatch.modules_for("PreToolUse", {"tool_name": "Read"}, OFF) == []
        assert dispatch.modules_for("PreToolUse", {"tool_name": "Read"}, ON) == [read_deny]

    def test_module_docstring_states_the_codex_and_opencode_position(self):
        doc = read_deny.__doc__
        assert "Codex" in doc and "OpenCode" in doc
        assert "documentation" in doc
        assert "not registered" in doc


if __name__ == "__main__":
    unittest.main()
