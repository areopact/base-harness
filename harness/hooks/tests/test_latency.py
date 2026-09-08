"""H9: each PreToolUse lib classifies a payload well inside its budget.

The 250 ms ceiling is deliberately generous; it catches a gross regression
(an accidental tree walk or a subprocess on the decision path), not a small
one. Import cost is excluded by a warm-up call.
"""
import sys
import time
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "lib"))

import dangerous_ops_guard  # noqa: E402
import delegation_guard  # noqa: E402
import dispatch  # noqa: E402
import memory_first  # noqa: E402
import openpyxl_guard  # noqa: E402
import read_deny  # noqa: E402

CEILING_SECONDS = 0.25
BASH = {"tool_name": "Bash", "tool_input": {"command": "echo ok && git status --short"}}
DANGEROUS = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
WEB = {"tool_name": "WebSearch", "tool_input": {"query": "harness hooks latency budget"}}
AGENT = {"tool_name": "Agent", "tool_input": {"description": "fixture"}}
READ = {"tool_name": "Read", "tool_input": {"file_path": str(TESTS / "fixtures" / "read-deny" / "secret-page.md")}}


def fastest(callable_, runs=3):
    callable_()
    timings = []
    for _ in range(runs):
        started = time.perf_counter()
        callable_()
        timings.append(time.perf_counter() - started)
    return min(timings)


class LatencyTests(unittest.TestCase):
    def test_pre_tool_use_libs_classify_under_the_ceiling(self):
        cases = {
            "dangerous_ops_guard allow": lambda: dangerous_ops_guard.decide(BASH),
            "dangerous_ops_guard deny": lambda: dangerous_ops_guard.decide(DANGEROUS),
            "openpyxl_guard": lambda: openpyxl_guard.decide(BASH),
            "memory_first": lambda: memory_first.decide(WEB),
            "delegation_guard": lambda: delegation_guard.decide(AGENT, "PreToolUse"),
            "read_deny": lambda: read_deny.decide(READ, {"HARNESS_READ_DENY": "1"}),
        }
        for name, call in cases.items():
            with self.subTest(name=name):
                elapsed = fastest(call)
                assert elapsed < CEILING_SECONDS, "%s took %.3fs" % (name, elapsed)

    def test_in_process_dispatch_of_pre_tool_use_under_the_ceiling(self):
        import json
        raw = json.dumps(BASH)
        elapsed = fastest(lambda: dispatch.dispatch("PreToolUse", raw, runtime="codex"))
        assert elapsed < CEILING_SECONDS, "dispatch took %.3fs" % elapsed


if __name__ == "__main__":
    unittest.main()
