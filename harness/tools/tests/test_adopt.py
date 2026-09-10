"""adopt.py writes an adopted host's structure: adopted is true on every run, roots are the target's
own top-level directories, and contract.mode alone records a pre-existing AGENTS.md."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "harness" / "tools"))

import adopt  # noqa: E402


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _target(root: Path, *, with_agents: bool) -> Path:
    assert _git(root, "init", "-q").returncode == 0
    _git(root, "config", "user.email", "fixture@example.invalid")
    _git(root, "config", "user.name", "fixture")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "content").mkdir()
    (root / "content" / "page.md").write_text("# page\n", encoding="utf-8")
    (root / "evidence").mkdir()
    (root / "evidence" / "drop.txt").write_text("received\n", encoding="utf-8")
    if with_agents:
        (root / "AGENTS.md").write_text("# The host's own contract\n", encoding="utf-8")
    assert _git(root, "add", ".").returncode == 0
    assert _git(root, "commit", "-q", "-m", "seed").returncode == 0
    return root


@unittest.skipIf(shutil.which("git") is None, reason="no git on this host")
class AdoptStructureTests(unittest.TestCase):
    def test_a_target_without_agents_md_is_still_adopted_with_its_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _target(Path(tmp), with_agents=False)
            structure, _reason, _note = adopt.build_structure(target, [])
            assert structure["host"]["adopted"] is True
            assert structure["host"]["roots"] == ["content", "evidence"]
            assert structure["host"]["profile"] == "team"
            assert structure["contract"]["mode"] == "rendered"

    def test_a_target_with_agents_md_keeps_a_host_owned_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = _target(Path(tmp), with_agents=True)
            structure, _reason, _note = adopt.build_structure(target, [])
            assert structure["host"]["adopted"] is True
            assert structure["host"]["roots"] == ["content", "evidence"]
            assert structure["contract"]["mode"] == "host-owned"


if __name__ == "__main__":
    unittest.main()
