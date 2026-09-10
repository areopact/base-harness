"""H11: write_deny is inert until a host sets write_deny.globs, exact on the path, and honors except."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "lib"))

import dispatch  # noqa: E402
import write_deny  # noqa: E402

RESERVED = {"write_deny": {"globs": ["docs/reserved/**", "ledger.md"], "except": ["docs/reserved/records/**"]}}


def seed(temp, structure=None):
    root = Path(temp)
    registry = root / "harness" / "registry"
    registry.mkdir(parents=True)
    if structure is not None:
        (registry / "structure.json").write_text(json.dumps(structure), encoding="utf-8")
    return root


def write(path, tool="Write"):
    return {"tool_name": tool, "tool_input": {"file_path": str(path), "content": "x"}}


def patch(*paths):
    body = "".join(f"*** Update File: {path}\n+x\n" for path in paths)
    return {"tool_name": "apply_patch", "tool_input": {"patch": f"*** Begin Patch\n{body}*** End Patch\n"}}


class WriteDenyTests(unittest.TestCase):
    def test_default_structure_is_silent_for_every_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            assert write_deny.decide(write(root / "docs" / "reserved" / "page.md"), root) is None
            assert write_deny.decide(write(root / "anything.md"), root) is None

    def test_reserved_path_is_denied_and_names_the_pattern(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            out = write_deny.decide(write(root / "docs" / "reserved" / "deep" / "page.md"), root)
            assert out is not None
            payload = json.loads(out)["hookSpecificOutput"]
            assert payload["permissionDecision"] == "deny"
            assert payload["hookEventName"] == "PreToolUse"
            reason = payload["permissionDecisionReason"]
            assert reason.startswith("write-deny [host-reserved-path]: docs/reserved/deep/page.md is under docs/reserved/**")
            assert "[command-sha256:" in reason and "hand the text to the writer" in reason

    def test_exact_file_pattern_and_edit_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            for tool in ("Write", "Edit", "NotebookEdit"):
                assert write_deny.decide(write(root / "ledger.md", tool), root) is not None, tool
            assert write_deny.decide(write(root / "ledger.md", "Read"), root) is None
            assert write_deny.decide(write(root / "ledger.md", "Bash"), root) is None

    def test_outside_scope_and_except_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            assert write_deny.decide(write(root / "docs" / "elsewhere" / "page.md"), root) is None
            assert write_deny.decide(write(root / "reserved.md"), root) is None
            assert write_deny.decide(write(root / "docs" / "reserved" / "records" / "r1.md"), root) is None

    def test_patch_with_one_reserved_path_is_denied_and_all_targets_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            allowed = patch("docs/elsewhere/a.md", "docs/elsewhere/b.md")
            assert write_deny.decide(allowed, root) is None
            mixed = patch("docs/elsewhere/a.md", "docs/reserved/b.md")
            out = write_deny.decide(mixed, root)
            assert out is not None and "docs/reserved/b.md is under docs/reserved/**" in out
            deleted = {"tool_name": "apply_patch", "tool_input": {"patch": "*** Begin Patch\n*** Delete File: docs/reserved/gone.md\n*** End Patch\n"}}
            assert write_deny.decide(deleted, root) is not None

    def test_path_outside_the_repository_passes(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as other:
            root = seed(temp, RESERVED)
            assert write_deny.decide(write(Path(other) / "reserved" / "page.md"), root) is None

    def test_malformed_section_is_silent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, {"write_deny": {"globs": "docs/reserved/**"}})
            assert write_deny.decide(write(root / "docs" / "reserved" / "page.md"), root) is None
            assert write_deny.decide(write(root / "docs" / "reserved" / "page.md"), root, {"write_deny": None}) is None

    def test_no_target_and_non_dict_payloads_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            assert write_deny.decide({"tool_name": "Write", "tool_input": {}}, root) is None
            assert write_deny.decide(["not", "a", "dict"], root) is None
            assert write_deny.decide({"tool_name": "Write", "tool_input": {"file_path": ""}}, root) is None

    def test_windows_path_tails_and_case_collapse_onto_the_reserved_name(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            assert write_deny.canonical("docs/Reserved/Page.md.") == "docs/reserved/page.md"
            assert write_deny.canonical("ledger.md ") == "ledger.md"
            assert write_deny.decide(write(root / "DOCS" / "RESERVED" / "x.md"), root) is not None
            assert write_deny.decide(write(str(root / "ledger.md") + "."), root) is not None
            assert write_deny.decide(write(str(root / "ledger.md") + " "), root) is not None

    def test_bare_directory_pattern_covers_descendants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, {"write_deny": {"globs": ["docs/reserved"]}})
            assert write_deny.decide(write(root / "docs" / "reserved" / "a" / "b.md"), root) is not None
            assert write_deny.decide(write(root / "docs" / "reserved.md"), root) is None

    def test_direct_path_and_patch_targets_are_both_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            both = {"tool_name": "apply_patch", "tool_input": {"file_path": "docs/free.md", "patch": "*** Begin Patch\n*** Update File: docs/reserved/b.md\n+x\n*** End Patch\n"}}
            assert write_deny.decide(both, root) is not None

    def test_digest_is_stable_across_absolute_and_relative_targets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, RESERVED)
            absolute = write_deny.decide(write(root / "docs" / "reserved" / "p.md"), root)
            relative = write_deny.decide({"tool_name": "Write", "tool_input": {"file_path": "docs/reserved/p.md"}}, root)
            assert absolute.split("command-sha256:")[1][:64] == relative.split("command-sha256:")[1][:64]

    def test_dispatch_routes_every_edit_tool_on_pre_tool_use(self):
        for tool in ("Write", "Edit", "NotebookEdit", "apply_patch"):
            assert dispatch.modules_for("PreToolUse", {"tool_name": tool}) == [write_deny], tool


if __name__ == "__main__":
    unittest.main()
