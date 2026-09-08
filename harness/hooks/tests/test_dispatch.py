"""H2: routing, deny short-circuit, SessionStart budgeting, registry limits."""
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parents[2]
LIB = TESTS.parent / "lib"
sys.path.insert(0, str(LIB))

import close_the_loop  # noqa: E402
import dangerous_ops_guard  # noqa: E402
import delegation_guard  # noqa: E402
import dispatch  # noqa: E402
import frontmatter_guard  # noqa: E402
import load_identity  # noqa: E402
import memory_first  # noqa: E402
import openpyxl_guard  # noqa: E402
import pre_bootstrap_detector  # noqa: E402
import prose_lint  # noqa: E402
import read_deny  # noqa: E402

DENY_FIXTURE = TESTS / "fixtures" / "guard" / "bypass-force-push-main.json"

# See test_guard_regressions.py: pin structure lookups to the template's
# shipped default for this module's lifetime, so dispatch routing through
# dangerous_ops_guard and frontmatter_guard stays deterministic on any host.
_STRUCTURE_OVERRIDE = str((ROOT / "harness" / "tools" / "templates" / "structure.default.json").resolve())
_PRIOR_STRUCTURE_ENV = None


def setUpModule():
    global _PRIOR_STRUCTURE_ENV
    _PRIOR_STRUCTURE_ENV = os.environ.get("HARNESS_STRUCTURE_FILE")
    os.environ["HARNESS_STRUCTURE_FILE"] = _STRUCTURE_OVERRIDE


def tearDownModule():
    if _PRIOR_STRUCTURE_ENV is None:
        os.environ.pop("HARNESS_STRUCTURE_FILE", None)
    else:
        os.environ["HARNESS_STRUCTURE_FILE"] = _PRIOR_STRUCTURE_ENV


def deny_raw(tool_name="Bash"):
    data = json.loads(DENY_FIXTURE.read_text(encoding="utf-8"))
    data["tool_name"] = tool_name
    return json.dumps(data)


def write_registry(root, structure, runtimes):
    registry = Path(root) / "harness" / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "structure.json").write_text(json.dumps(structure), encoding="utf-8")
    (registry / "runtimes.json").write_text(json.dumps(runtimes), encoding="utf-8")


class RoutingTests(unittest.TestCase):
    def test_modules_for_matches_the_package_table(self):
        env_off = {}
        env_on = {"HARNESS_READ_DENY": "1"}
        assert dispatch.modules_for("SessionStart", {}) == [load_identity, pre_bootstrap_detector]
        assert dispatch.modules_for("PreToolUse", {"tool_name": "Bash"}) == [dangerous_ops_guard, openpyxl_guard]
        assert dispatch.modules_for("PreToolUse", {"tool_name": "shell_command"}) == [dangerous_ops_guard, openpyxl_guard]
        assert dispatch.modules_for("PreToolUse", {"tool_name": "exec_command"}) == [dangerous_ops_guard, openpyxl_guard]
        assert dispatch.modules_for("PreToolUse", {"tool_name": "write_stdin"}) == []
        for web in ("WebSearch", "WebFetch", "web_search", "web__run", "web.run"):
            assert dispatch.modules_for("PreToolUse", {"tool_name": web}) == [memory_first]
        assert dispatch.modules_for("PreToolUse", {"tool_name": "Read"}, env_off) == []
        assert dispatch.modules_for("PreToolUse", {"tool_name": "Read"}, env_on) == [read_deny]
        for agent in ("Agent", "agent", "Task", "spawn_agent", "Workflow"):
            assert dispatch.modules_for("PreToolUse", {"tool_name": agent}) == [delegation_guard]
            assert dispatch.modules_for("PostToolUse", {"tool_name": agent}) == [delegation_guard]
        for edit in ("Edit", "Write", "NotebookEdit", "apply_patch"):
            assert dispatch.modules_for("PostToolUse", {"tool_name": edit}) == [frontmatter_guard, prose_lint]
        assert dispatch.modules_for("Stop", {}) == [close_the_loop]
        assert dispatch.modules_for("UserPromptSubmit", {"prompt": "x"}) == []
        assert dispatch.modules_for("PreToolUse", {"tool_name": "Glob"}) == []

    def test_shell_command_alias_is_denied_through_dispatch(self):
        result = dispatch.dispatch("PreToolUse", deny_raw("shell_command"), runtime="codex")
        specific = result["hookSpecificOutput"]
        assert specific["permissionDecision"] == "deny"
        assert "dangerous-ops-guard" in specific["permissionDecisionReason"]
        assert set(specific) == {"hookEventName", "permissionDecision", "permissionDecisionReason"}

    def test_deny_short_circuits_later_modules(self):
        calls = []
        sentinel = types.SimpleNamespace(__name__="sentinel", main=lambda: calls.append("ran"))
        with patch.object(dispatch, "modules_for", return_value=[dangerous_ops_guard, sentinel]):
            result = dispatch.dispatch("PreToolUse", deny_raw(), runtime="codex")
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert calls == []

    def test_later_modules_run_when_no_deny(self):
        calls = []
        sentinel = types.SimpleNamespace(__name__="sentinel", main=lambda: calls.append("ran"))
        raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": "echo ok"}})
        with patch.object(dispatch, "modules_for", return_value=[dangerous_ops_guard, sentinel]):
            assert dispatch.dispatch("PreToolUse", raw, runtime="codex") is None
        assert calls == ["ran"]

    def test_module_exception_is_a_malfunction_not_a_decision(self):
        def boom():
            raise RuntimeError("fixture")
        broken = types.SimpleNamespace(__name__="broken", main=boom)
        with patch.object(dispatch, "modules_for", return_value=[broken]):
            assert dispatch.dispatch("PreToolUse", deny_raw(), runtime="codex") is None

    def test_bad_json_and_non_object_fail_open(self):
        assert dispatch.dispatch("PreToolUse", "not json") is None
        assert dispatch.dispatch("PreToolUse", "[1,2]") is None
        assert dispatch.dispatch("PreToolUse", "") is None


class CombineTests(unittest.TestCase):
    def test_deny_wins_over_advisories(self):
        deny = {"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "stop"}}
        advisory = {"hookSpecificOutput": {"additionalContext": "later"}}
        result = dispatch.combine("PreToolUse", [advisory, deny])
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "additionalContext" not in result["hookSpecificOutput"]

    def test_context_combination_is_deterministic(self):
        first = {"hookSpecificOutput": {"additionalContext": "first"}}
        second = {"systemMessage": "second"}
        result = dispatch.combine("PostToolUse", [first, second])
        assert result["hookSpecificOutput"]["additionalContext"] == "first\n\nsecond"

    def test_stop_uses_system_message(self):
        result = dispatch.combine("Stop", [{"systemMessage": "remember"}])
        assert result == {"systemMessage": "remember"}
        assert dispatch.combine("Stop", []) is None

    def test_cap_context_appends_the_cap_suffix(self):
        value = "\n".join("line %d" % index for index in range(400))
        capped = dispatch.cap_context(value, 300)
        assert len(capped) <= 300
        assert capped.endswith(dispatch.CAP_SUFFIX)
        assert dispatch.cap_context(value, None) == value


class RegistryLimitTests(unittest.TestCase):
    def test_context_limit_reads_runtimes_json(self):
        registry = json.loads((ROOT / "harness" / "registry" / "runtimes.json").read_text(encoding="utf-8-sig"))
        for runtime in ("codex", "opencode"):
            for event in ("SessionStart", "PreToolUse", "PostToolUse", "Stop"):
                declared = registry["hook_events"][event]["runtimes"][runtime]["context_limit"]
                expected = declared if isinstance(declared, int) and declared > 0 else None
                assert dispatch.context_limit(runtime, event) == expected

    def test_unknown_runtime_or_event_falls_back_to_no_cap(self):
        assert dispatch.context_limit("nonexistent", "SessionStart") is None
        assert dispatch.context_limit("codex", "NoSuchEvent") is None

    def test_missing_registry_falls_back_to_no_cap(self):
        with patch.object(dispatch, "REGISTRY", Path("/nonexistent/runtimes.json")):
            assert dispatch.context_limit("codex", "SessionStart") is None


class SessionStartBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write_registry(
            self.root,
            {"lanes": {"identity": ["examples/IDENTITY.md"], "knowledge": ["examples/knowledge"], "journal": ["examples/journal"]}},
            {"runtimes": {}},
        )

    def tearDown(self):
        self.temp.cleanup()

    def lanes(self):
        identity = "=== IDENTITY (examples/IDENTITY.md) ===\n## Voice\n" + ("identity words " * 300) + "\n## Values\n" + ("value words " * 300)
        knowledge = "=== notes (examples/knowledge/notes.md) ===\n" + ("knowledge words " * 200)
        other = "pre-bootstrap-detector: " + ("other words " * 100)
        return [identity, knowledge, other]

    def test_under_limit_is_untouched(self):
        values = ["short one", "short two"]
        assert dispatch.budget_session_context(values, 10_000, self.root) == "short one\n\nshort two"

    def test_over_limit_never_tail_truncates_and_names_sources(self):
        limit = 2000
        result = dispatch.budget_session_context(self.lanes(), limit, self.root)
        assert len(result) <= limit
        last_line = result.rstrip().splitlines()[-1]
        assert last_line.startswith("[boot context budget; trimmed sources (read on demand): ")
        assert "; omitted sources: " in last_line
        assert dispatch.CAP_SUFFIX.strip() not in result
        assert "examples/IDENTITY.md" in last_line
        # identity lane is delivered first, ahead of knowledge and unclassified output
        assert result.index("=== IDENTITY") < result.index("=== notes")

    def test_budget_is_deterministic(self):
        first = dispatch.budget_session_context(self.lanes(), 1500, self.root)
        second = dispatch.budget_session_context(self.lanes(), 1500, self.root)
        assert first == second

    def test_identity_lane_uses_load_identity_truncation(self):
        result = dispatch.budget_session_context(self.lanes(), 1800, self.root)
        assert "[identity truncated at " in result
        assert "read examples/IDENTITY.md on demand]" in result

    def test_tiny_budget_omits_lanes_and_says_so(self):
        result = dispatch.budget_session_context(self.lanes(), 900, self.root)
        assert len(result) <= 900
        assert "omitted sources: " in result
        assert "omitted sources: none" not in result


class MainEntryTests(unittest.TestCase):
    def test_main_accepts_both_runtimes_and_exits_zero(self):
        for runtime in ("codex", "opencode"):
            with patch.object(sys, "stdin", new=_Stdin(deny_raw())):
                assert dispatch.main(["--event", "PreToolUse", "--runtime", runtime]) == 0

    def test_read_deny_flag_is_read_from_the_environment(self):
        with patch.dict(os.environ, {"HARNESS_READ_DENY": "1"}):
            assert dispatch.read_deny_enabled()
        with patch.dict(os.environ, {}, clear=True):
            assert not dispatch.read_deny_enabled()


class _Stdin:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text


if __name__ == "__main__":
    unittest.main()
