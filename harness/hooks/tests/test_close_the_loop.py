"""Stop hook: close-the-loop's final clause composes from git.mode and host.profile."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import close_the_loop  # noqa: E402


def seeded_git_repo(temp):
    """A git repository with one configured lane and one dirty file in it."""
    root = Path(temp)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(root), check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(root), check=True)
    docs = root / "docs"
    docs.mkdir()
    (docs / "page.md").write_text("# page\n", encoding="utf-8")
    return root


def structure_for(mode, profile=None):
    structure = {"lanes": {"docs": ["docs"]}, "git": {"mode": mode}}
    if profile is not None:
        structure["host"] = {"profile": profile}
    return structure


class ClosingClauseTests(unittest.TestCase):
    """closing_clause() itself: pure, no I/O, never raises on a partial structure."""

    def test_main_only_solo(self):
        clause = close_the_loop.closing_clause(structure_for("main-only", "solo"))
        assert clause == "commit to the default branch or park it"

    def test_branches_team(self):
        clause = close_the_loop.closing_clause(structure_for("branches", "team"))
        assert clause == "commit on a task branch (never the default branch) and open a PR only when asked"

    def test_branches_solo(self):
        clause = close_the_loop.closing_clause(structure_for("branches", "solo"))
        assert clause == "commit on a task branch (never the default branch)"

    def test_main_only_team(self):
        clause = close_the_loop.closing_clause(structure_for("main-only", "team"))
        assert clause == "commit to the default branch or park it and open a PR only when asked"

    def test_missing_host_key_does_not_raise_and_reads_as_solo(self):
        structure = {"git": {"mode": "branches"}}
        assert "host" not in structure
        clause = close_the_loop.closing_clause(structure)
        assert clause == "commit on a task branch (never the default branch)"

    def test_missing_git_key_does_not_raise_and_reads_as_main_only(self):
        structure = {"host": {"profile": "team"}}
        assert "git" not in structure
        clause = close_the_loop.closing_clause(structure)
        assert clause == "commit to the default branch or park it and open a PR only when asked"

    def test_non_dict_structure_does_not_raise_and_reads_as_solo_main_only(self):
        assert close_the_loop.closing_clause(None) == "commit to the default branch or park it"
        assert close_the_loop.closing_clause({}) == "commit to the default branch or park it"


class DecideEndToEndTests(unittest.TestCase):
    """decide() over a real dirty git tree carries the composed clause through."""

    def _run(self, mode, profile):
        with tempfile.TemporaryDirectory() as temp:
            root = seeded_git_repo(temp)
            structure = structure_for(mode, profile)
            message = close_the_loop.decide(root=root, structure=structure, today="2026-09-10")
            assert message is not None, "expected a reminder for a dirty configured lane"
            return message

    def test_main_only_solo_message_names_the_default_branch_clause(self):
        message = self._run("main-only", "solo")
        assert "commit to the default branch or park it" in message
        assert "open a PR" not in message

    def test_branches_team_message_names_the_task_branch_and_pr_clause(self):
        message = self._run("branches", "team")
        assert "commit on a task branch (never the default branch) and open a PR only when asked" in message

    def test_branches_solo_message_names_the_task_branch_clause_without_pr(self):
        message = self._run("branches", "solo")
        assert "commit on a task branch (never the default branch)" in message
        assert "open a PR" not in message

    def test_main_only_team_message_names_the_default_branch_and_pr_clause(self):
        message = self._run("main-only", "team")
        assert "commit to the default branch or park it and open a PR only when asked" in message

    def test_structure_missing_host_key_still_produces_a_message(self):
        with tempfile.TemporaryDirectory() as temp:
            root = seeded_git_repo(temp)
            structure = {"lanes": {"docs": ["docs"]}, "git": {"mode": "branches"}}
            assert "host" not in structure
            message = close_the_loop.decide(root=root, structure=structure, today="2026-09-10")
            assert message is not None
            assert "commit on a task branch (never the default branch)" in message
            assert "open a PR" not in message


if __name__ == "__main__":
    unittest.main()
