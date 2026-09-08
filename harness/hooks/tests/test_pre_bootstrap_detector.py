"""H8: the pre-bootstrap detector names the platform command or stays silent."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "lib"))

import pre_bootstrap_detector as detector  # noqa: E402
from hook_io import REPO_ROOT  # noqa: E402


def _host_adopted() -> bool:
    """True when this checkout's own structure.json declares host.adopted.

    Read directly (not through hook_io.load_structure) so this check never
    interacts with another test module's HARNESS_STRUCTURE_FILE override.
    """
    try:
        data = json.loads((REPO_ROOT / "harness" / "registry" / "structure.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(data, dict) and (data.get("host") or {}).get("adopted"))

JUNCTIONS = {
    "schema_version": 1,
    "junctions": [
        {"src": "harness/adapters/claude/settings.base.json", "dst": ".claude/settings.json", "mode": "managed-copy", "runtime": "claude"},
        {"src": "harness/rules", "dst": ".claude/rules", "mode": "link", "runtime": "claude"},
        {"src": "harness/CONTRACT.md", "dst": "AGENTS.md", "mode": "contract-render", "runtime": "all"},
        {"src": "harness/adapters/codex/config.toml", "dst": ".codex/config.toml", "mode": "managed-copy", "runtime": "codex"},
    ],
}


def seed(temp, manifest=JUNCTIONS, text=None):
    root = Path(temp)
    target = root / "harness" / "bootstrap" / "junctions.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text is not None else json.dumps(manifest), encoding="utf-8")
    (root / "harness" / "rules").mkdir(parents=True, exist_ok=True)
    return root


def materialize(root, *destinations):
    for dst in destinations:
        target = root / dst
        if dst.endswith((".json", ".md", ".toml")):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)


class PreBootstrapDetectorTests(unittest.TestCase):
    def test_missing_destination_yields_one_advisory_naming_the_platform_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            out = detector.decide(root, "claude", platform="linux")
            value = json.loads(out)
            context = value["hookSpecificOutput"]["additionalContext"]
            assert value["hookSpecificOutput"]["hookEventName"] == "SessionStart"
            assert "permissionDecision" not in out
            assert context.startswith("pre-bootstrap-detector: this clone is not bootstrapped for claude")
            assert ".claude/settings.json" in context and ".claude/rules" in context and "AGENTS.md" in context
            assert ".codex/config.toml" not in context
            assert context.endswith("Run: bash harness/bootstrap/bootstrap.sh")
            windows = json.loads(detector.decide(root, "claude", platform="win32"))["hookSpecificOutput"]["additionalContext"]
            assert windows.endswith("Run: powershell -NoProfile -ExecutionPolicy Bypass -File harness\\bootstrap\\bootstrap.ps1")

    def test_all_present_is_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            materialize(root, ".claude/settings.json", ".claude/rules", "AGENTS.md")
            assert detector.decide(root, "claude", platform="linux") is None
            # copy mode: a plain directory at a link destination counts as materialized
            assert detector.missing_destinations(root, "claude") == []

    @unittest.skipIf(_host_adopted(), "asserts this template checkout's own bootstrapped tree; not valid on an adopted host")
    def test_this_repositorys_bootstrapped_tree_is_silence_for_every_runtime(self):
        """F1: a correctly bootstrapped clone must never trip the detector.
        This repository's own junctions.json is the manifest under test, on
        the actual bootstrapped tree, for all three runtimes at once. Two
        rows are never materialized by design (the secondary contract-render
        row at .claude/CLAUDE.md; the .claude/skills per-skill row when the
        effective selection is empty) and must not be reported as missing.
        """
        for rt in ("claude", "codex", "opencode"):
            assert detector.missing_destinations(REPO_ROOT, rt) == []

    def test_runtime_scoping_only_counts_the_active_runtime_and_all(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            materialize(root, "AGENTS.md")
            assert detector.missing_destinations(root, "codex") == [".codex/config.toml"]
            materialize(root, ".codex/config.toml")
            assert detector.decide(root, "codex") is None

    def test_absent_manifest_is_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            assert detector.decide(temp, "claude") is None

    def test_malformed_manifest_is_silence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp, text="{broken")
            assert detector.decide(root, "claude") is None
            root = seed(temp, text=json.dumps({"junctions": "not a list"}))
            assert detector.decide(root, "claude") is None
            root = seed(temp, text=json.dumps({"junctions": [{"dst": 5}, "x", {"mode": "link"}]}))
            assert detector.decide(root, "claude") is None

    def test_link_pointing_outside_harness_counts_as_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seed(temp)
            materialize(root, ".claude/settings.json", "AGENTS.md")
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            link = root / ".claude" / "rules"
            try:
                os.symlink(str(elsewhere), str(link), target_is_directory=True)
            except (OSError, NotImplementedError, AttributeError):
                self.skipTest("symlink creation not permitted on this host")
            assert detector.missing_destinations(root, "claude") == [".claude/rules"]
            link.unlink()
            os.symlink(str(root / "harness" / "rules"), str(link), target_is_directory=True)
            assert detector.missing_destinations(root, "claude") == []

    def test_bootstrap_command_per_platform(self):
        assert detector.bootstrap_command("linux") == "bash harness/bootstrap/bootstrap.sh"
        assert detector.bootstrap_command("darwin") == "bash harness/bootstrap/bootstrap.sh"
        assert detector.bootstrap_command("win32").endswith("bootstrap.ps1")

    def test_runtime_from_argv_then_environment_then_claude(self):
        assert detector.runtime_from(["--runtime", "codex"], {}) == "codex"
        assert detector.runtime_from(["--runtime=opencode"], {}) == "opencode"
        assert detector.runtime_from([], {"HARNESS_RUNTIME": "codex"}) == "codex"
        assert detector.runtime_from([], {}) == "claude"


if __name__ == "__main__":
    unittest.main()
