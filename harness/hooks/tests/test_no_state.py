"""H4: no hook writes a file when HARNESS_HOOK_DEBUG_DIR is unset.

Every lib's decision path runs with the write side of builtins.open and
pathlib patched to raise; a single attempted write fails the test. The
positive control proves the tracer does write when the variable names a
directory, so the negative case is meaningful.
"""
import builtins
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
HOOKS = TESTS.parent
LIB = HOOKS / "lib"
sys.path.insert(0, str(LIB))

import _debug  # noqa: E402
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

REAL_OPEN = builtins.open
WRITE_MODES = ("w", "a", "x", "+")


def guarded_open(file, mode="r", *args, **kwargs):
    if any(flag in mode for flag in WRITE_MODES):
        raise AssertionError("hook attempted to write %r" % (file,))
    return REAL_OPEN(file, mode, *args, **kwargs)


def forbid_write(*args, **kwargs):
    raise AssertionError("hook attempted a pathlib write")


class NoWriteHarness:
    def __enter__(self):
        self.patches = [
            patch.object(builtins, "open", guarded_open),
            patch.object(Path, "write_text", forbid_write),
            patch.object(Path, "write_bytes", forbid_write),
            patch.object(os, "makedirs", forbid_write),
            patch.object(os, "mkdir", forbid_write),
            patch.object(os, "rename", forbid_write),
            patch.object(os, "replace", forbid_write),
            patch.object(os, "remove", forbid_write),
            patch.object(os, "unlink", forbid_write),
            patch.dict(os.environ, {}, clear=False),
        ]
        for item in self.patches:
            item.start()
        os.environ.pop("HARNESS_HOOK_DEBUG_DIR", None)
        return self

    def __exit__(self, *exc):
        for item in reversed(self.patches):
            item.stop()
        return False


def seeded_root(temp):
    root = Path(temp)
    registry = root / "harness" / "registry"
    registry.mkdir(parents=True)
    (registry / "structure.json").write_text(json.dumps({
        "lanes": {"identity": ["examples/IDENTITY.md"], "knowledge": ["examples/knowledge"], "docs": ["docs"]},
        "outbound_globs": ["docs/**"],
        "delegation": {"mandatory": True},
    }), encoding="utf-8")
    (registry / "runtimes.json").write_text(json.dumps({"runtimes": {"claude": {"tier": "tier-1", "identity_context_limit": 9000}}}), encoding="utf-8")
    (root / "examples" / "knowledge").mkdir(parents=True)
    (root / "examples" / "IDENTITY.md").write_text("---\naccess: internal\n---\n## Voice\nplain.\n", encoding="utf-8")
    (root / "examples" / "knowledge" / "guard-notes.md").write_text("# notes\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "page.md").write_text("---\naccess: internal\n---\n\nGreat question, let's dive in. It serves as a testament to the tapestry.\n", encoding="utf-8")
    (root / "harness" / "bootstrap").mkdir()
    (root / "harness" / "bootstrap" / "junctions.json").write_text(json.dumps({"junctions": [{"src": "harness/x", "dst": ".claude/x", "mode": "link", "runtime": "claude"}]}), encoding="utf-8")
    return root


class NoStateTests(unittest.TestCase):
    def test_every_decision_path_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seeded_root(temp)
            structure = json.loads((root / "harness" / "registry" / "structure.json").read_text(encoding="utf-8"))
            bash = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
            write = {"tool_name": "Write", "tool_input": {"file_path": str(root / "docs" / "page.md"), "content": (root / "docs" / "page.md").read_text(encoding="utf-8")}}
            with NoWriteHarness():
                assert dangerous_ops_guard.decide(bash) is not None
                assert openpyxl_guard.decide(bash) is None
                assert frontmatter_guard.decide(write, root) is None
                prose_lint.decide(write, root, structure)
                memory_first.decide({"tool_name": "WebSearch", "tool_input": {"query": "guard notes"}}, root)
                assert read_deny.decide({"tool_name": "Read", "tool_input": {"file_path": str(root / "docs" / "page.md")}}, {"HARNESS_READ_DENY": "1"}, root) is None
                assert delegation_guard.decide({"tool_name": "Agent", "tool_input": {}}, "PreToolUse", structure) is not None
                close_the_loop.decide(root, structure)
                assert load_identity.render(root, "claude") is not None
                assert pre_bootstrap_detector.decide(root, "claude") is not None
                dispatch.dispatch("PreToolUse", json.dumps(bash), runtime="codex")
                dispatch.dispatch("Stop", "{}", runtime="codex")

    def test_debug_tracer_is_off_without_the_variable(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HARNESS_HOOK_DEBUG_DIR", None)
            tracer = _debug._Debug()
            assert not tracer.enabled
            with NoWriteHarness():
                tracer.start()
                tracer.end("fixture", exit_code=0, out_bytes=0)

    def test_debug_tracer_writes_only_into_the_named_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"HARNESS_HOOK_DEBUG_DIR": temp}):
                tracer = _debug._Debug()
                assert tracer.enabled
                tracer.start()
                tracer.end("fixture", exit_code=0, out_bytes=3, extra="positive-control")
            log = Path(temp) / "hooks-debug.log"
            assert log.is_file()
            line = log.read_text(encoding="utf-8").strip().split("\t")
            assert line[1] == "fixture" and line[-1] == "positive-control"

    @unittest.skipIf(shutil.which("sh") is None, reason="no POSIX sh on this host")
    def test_dispatcher_run_leaves_no_pycache(self):
        """harness/hooks/README.md calls the wrappers stateless; a __pycache__
        directory left behind by the first run contradicts that. The wrapper
        scripts export PYTHONDONTWRITEBYTECODE=1 to the Python subprocess
        precisely so this holds true on a fresh run, and this test proves the
        wrapper itself sets it (the ambient variable is stripped from the
        child's environment before the subprocess starts). Existing
        __pycache__ entries under harness/hooks/lib and .../tests, written by
        pytest's own in-process imports of the same modules for the other
        tests in this file, are cleared first so they cannot mask a
        regression; those entries are pytest's own artifact, not the
        wrapper's, and are unaffected by this test since the already-imported
        modules stay resident in sys.modules without recompiling to disk."""
        for cache_dir in HOOKS.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)
        fixture = TESTS / "fixtures" / "guard" / "bypass-force-push-main.json"
        wrapper = HOOKS / "pre-tool-use" / "dangerous-ops-guard.sh"
        env = dict(os.environ)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        result = subprocess.run(
            ["sh", str(wrapper)],
            input=fixture.read_text(encoding="utf-8"),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(HOOKS.parents[1]), env=env, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        after = {path for path in HOOKS.rglob("__pycache__")}
        assert after == set(), f"__pycache__ written by the run: {after}"

    def test_lib_sources_carry_no_network_or_default_log_path(self):
        for path in sorted(LIB.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.name):
                for token in ("urllib", "socket", "http.client", "requests", "ftplib", "smtplib"):
                    assert token not in text, token
                assert ".tmp/" not in text
        debug = (LIB / "_debug.py").read_text(encoding="utf-8")
        assert "HARNESS_HOOK_DEBUG_DIR" in debug
        assert "harness-debug.log" not in debug
        close = (LIB / "close_the_loop.py").read_text(encoding="utf-8")
        assert 'environment["GIT_OPTIONAL_LOCKS"] = "0"' in close

    def test_git_subprocesses_are_read_only(self):
        for name in ("close_the_loop.py", "prose_lint.py"):
            text = (LIB / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                for verb in ("git add", "git commit", "git push", "git fetch", "git pull", '"add"', '"commit"', '"push"', '"fetch"', '"pull"'):
                    assert verb not in text, verb


if __name__ == "__main__":
    unittest.main()
