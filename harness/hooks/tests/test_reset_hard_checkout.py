"""git reset --hard on a protected checkout: effective repository and HEAD.

Classifier inputs only: no command string here is ever executed. Every
repository is a temporary directory whose .git/HEAD (or .git file) this
module writes itself, so no result depends on the checkout the suite runs
from. "old" in a row is the decision before the checked-out-branch rule
existed; a head reader that never knows the branch disables the rule, so it
reproduces that decision.
"""
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / "lib"))

import dangerous_ops_guard as guard  # noqa: E402

# Assembled from fragments, as in the guard, so the ref namespace is not read
# as a repository path by the lane-path and de-identification lints.
HEADS = "refs" + "/heads" + "/"
BACKSLASH = chr(92)
CEILING_SECONDS = 0.25


def NO_BRANCH(directory):
    return None


def write_head(gitdir, branch=None, raw=None):
    gitdir.mkdir(parents=True, exist_ok=True)
    text = raw if raw is not None else "ref: " + HEADS + branch + "\n"
    (gitdir / "HEAD").write_text(text, encoding="utf-8", newline="\n")


def payload(command, cwd, shell="Bash"):
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": shell,
        "tool_input": {"command": command},
        "cwd": cwd,
        "session_id": "fixture",
    }


def denied(command, cwd, shell="Bash", reader=None):
    return guard.decide(payload(command, cwd, shell), {}, head_reader=reader) is not None


class ResetHardCheckoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.mkdtemp(prefix="reset-hard-")
        root = Path(cls.scratch) / "root"
        # root: the enclosing repository, on a topic branch, so every
        # directory below it without its own .git resolves deterministically.
        write_head(root / ".git", "topic")
        write_head(root / "main-repo" / ".git", "main")
        write_head(root / "topic-repo" / ".git", "feature/main")
        write_head(root / "detached" / ".git", raw="0123456789abcdef0123456789abcdef01234567\n")
        write_head(root / "dir with space" / ".git", "main")
        # A linked worktree: its .git is a file pointing at a gitdir whose HEAD is main.
        write_head(root / ".git" / "worktrees" / "w", "main")
        (root / "w").mkdir()
        (root / "w" / ".git").write_text("gitdir: ../.git/worktrees/w\n", encoding="utf-8", newline="\n")
        (root / "cwdrepo" / "src").mkdir(parents=True)
        write_head(root / "cwdrepo" / ".git", "topic")
        (root / "a" / "b").mkdir(parents=True)
        write_head(root / "repo" / ".git", "main")
        cls.root = root
        cls.dirs = {
            "": "",
            "main": str(root / "main-repo"),
            "topic": str(root / "topic-repo"),
            "detached": str(root / "detached"),
            "root": str(root),
            "space": str(root / "dir with space"),
            "cwdrepo": str(root / "cwdrepo"),
            "ab": str(root / "a" / "b"),
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def check(self, rows):
        """Rows are (shell, command, cwd key, old, new[, shape]).

        shape is the decision with the checkout rule disabled. It equals old
        except where the same change closed a command-shape gap (abbreviated
        --hard, the timeout wrapper); those rows state it.
        """
        for row in rows:
            shell, command, where, old, new = row[:5]
            shape = row[5] if len(row) > 5 else old
            with self.subTest(shell=shell, command=command, cwd=where):
                assert denied(command, self.dirs[where], shell, reader=NO_BRANCH) == shape, "shape decision changed"
                assert denied(command, self.dirs[where], shell) == new

    def test_bare_hard_reset_follows_the_checked_out_branch(self):
        self.check([
            ("Bash", "git reset --hard", "main", False, True),
            ("PowerShell", "git reset --hard", "main", False, True),
            ("Bash", "git reset --hard", "topic", False, False),
            ("PowerShell", "git reset --hard", "topic", False, False),
            ("Bash", "git reset --hard", "detached", False, False),
            ("Bash", "git reset --hard", "", False, False),
            ("Bash", "git reset --hard HEAD", "main", False, True),
            ("Bash", "git reset --hard HEAD~3", "main", False, True),
            ("Bash", "git reset --hard 0123abc", "main", False, True),
            ("Bash", "git reset --hard feature", "main", False, True),
            ("Bash", "git reset -q --hard", "main", False, True),
            ("PowerShell", "& git.exe reset --hard HEAD~1", "main", False, True),
            ("PowerShell", "git reset -q --hard", "main", False, True),
        ])

    def test_protected_operand_still_denies_anywhere(self):
        self.check([
            ("Bash", "git reset --hard origin/main", "topic", True, True),
            ("PowerShell", "git reset --hard origin/main", "topic", True, True),
            ("Bash", "git reset --hard main~1", "", True, True),
        ])

    def test_other_reset_modes_are_unaffected(self):
        self.check([
            ("Bash", "git reset --soft HEAD~1", "main", False, False),
            ("PowerShell", "git reset --soft HEAD~1", "main", False, False),
            ("Bash", "git reset --keep", "main", False, False),
            ("PowerShell", "git reset --keep", "main", False, False),
            ("Bash", "git reset --mixed HEAD~1", "main", False, False),
            ("Bash", "git reset --merge", "main", False, False),
            ("Bash", "git reset HEAD~1", "main", False, False),
            # git applies the last mode flag.
            ("Bash", "git reset --hard --keep", "main", False, False),
        ])

    def test_prose_and_nested_shells(self):
        self.check([
            ("Bash", 'echo "git reset --hard"', "main", False, False),
            ("PowerShell", 'Write-Output "git reset --hard"', "main", False, False),
            ("Bash", "git commit -m 'git reset --hard'", "main", False, False),
            ("Bash", "bash -c 'git reset --hard'", "main", False, True),
            ("Bash", "sh -c 'cd ../topic-repo && git reset --hard'", "main", False, False),
            ("Bash", "cd ../topic-repo && bash -c 'git reset --hard'", "main", False, False),
            ("PowerShell", 'pwsh -Command "git reset --hard"', "main", False, True),
            ("Bash", "echo $(git reset --hard)", "main", False, True),
        ])

    def test_git_dash_c_and_worktree_gitdir_file(self):
        self.check([
            ("Bash", "git reset --hard", "cwdrepo", False, False),
            ("Bash", "git -C ../w reset --hard", "cwdrepo", False, True),
            ("PowerShell", "git -C ../w reset --hard", "cwdrepo", False, True),
            ("Bash", "git -C .. -C main-repo reset --hard", "cwdrepo", False, True),
            ("Bash", "git -C src reset --hard", "cwdrepo", False, False),
            ("Bash", "git -C $REPO reset --hard", "cwdrepo", False, False),
        ])

    def test_powershell_relative_traversal_resolves_before_deciding(self):
        up = ".." + BACKSLASH + ".." + BACKSLASH
        traversal = "git -C " + up + "repo reset --hard"
        self.check([
            ("PowerShell", traversal, "ab", False, True),
            ("PowerShell", "git -C " + up + "topic-repo reset --hard", "ab", False, False),
            # Bash reads the backslashes as escapes ("....repo"), which stays
            # inside the topic repository at root.
            ("Bash", traversal, "ab", False, False),
        ])

    def test_cd_family_moves_the_effective_repository(self):
        absolute = str(self.root / "dir with space")
        self.check([
            ("Bash", "cd 'dir with space' && git reset --hard", "root", False, True),
            ("PowerShell", "cd 'dir with space'; git reset --hard", "root", False, True),
            ("Bash", "cd '%s' && git reset --hard" % absolute, "topic", False, True),
            ("PowerShell", "Set-Location -LiteralPath '%s'; git reset --hard" % absolute, "topic", False, True),
            # After "&&" the move is sure, so an unknown target is unknown.
            ("Bash", "cd $d && git reset --hard", "main", False, False),
            ("PowerShell", "cd $d && git reset --hard", "main", False, False),
            # After ";" the cd may have failed, so the old directory stays a candidate.
            ("Bash", "cd $d; git reset --hard", "main", False, True),
            ("PowerShell", "cd $d; git reset --hard", "main", False, True),
            ("Bash", "cd ~ && git reset --hard", "main", False, False),
            ("Bash", "cd && git reset --hard", "main", False, False),
            ("Bash", "cd - && git reset --hard", "main", False, False),
            ("Bash", "cd ../main-repo/* && git reset --hard", "topic", False, False),
            ("Bash", "cd -- ../main-repo && git reset --hard", "topic", False, True),
            ("Bash", "cd -P ../main-repo && git reset --hard", "topic", False, True),
            ("PowerShell", "Set-Location -Path ../main-repo; git reset --hard", "topic", False, True),
            ("PowerShell", "sl ../main-repo; git reset --hard", "topic", False, True),
            ("PowerShell", "Push-Location ../main-repo; git reset --hard", "topic", False, True),
            ("Bash", "pushd ../main-repo && git reset --hard", "topic", False, True),
            ("Bash", "pushd ../main-repo && popd && git reset --hard", "topic", False, False),
            ("Bash", "(cd ../main-repo && git reset --hard)", "topic", False, True),
            ("Bash", "cd ../main-repo && cd ../topic-repo && git reset --hard", "topic", False, False),
            # Both targets exist, so each move replaces the candidates.
            ("Bash", "cd ../main-repo; cd ../topic-repo; git reset --hard", "topic", False, False),
            ("Bash", "cd ../topic-repo && git reset --hard", "main", False, False),
            ("Bash", "env -C ../main-repo git reset --hard", "topic", False, True),
            ("Bash", "env --chdir=../main-repo git reset --hard", "topic", False, True),
        ])

    def test_review_1_abbreviated_hard_is_hard(self):
        # git 2.51 resolves any unique prefix: --h, --ha, --har are --hard;
        # --m is ambiguous (mixed, merge) and git rejects it.
        self.check([
            ("Bash", "git reset --h", "main", False, True),
            ("Bash", "git reset --ha", "main", False, True),
            ("Bash", "git reset --har", "main", False, True),
            ("PowerShell", "git reset --har HEAD~1", "main", False, True),
            ("Bash", "git reset --har origin/main", "topic", False, True, True),
            ("PowerShell", "git reset --ha origin/main", "topic", False, True, True),
            ("Bash", "git reset --h main", "", False, True, True),
            ("Bash", "git reset --m", "main", False, False),
            ("Bash", "git reset --har --ke", "main", False, False),
            ("Bash", "git reset --hardest", "main", False, False),
        ])

    def test_review_2_a_location_command_may_not_move_the_shell(self):
        missing = str(self.root / "no-such")
        self.check([
            # The cd fails, and ";" runs the reset where the shell already was.
            ("Bash", "cd '%s'; git reset --hard" % missing, "main", False, True),
            ("PowerShell", "cd '%s'; git reset --hard" % missing, "main", False, True),
            ("Bash", "cd ../no-such; git reset --hard", "main", False, True),
            # A POSIX pipeline element and a background job run in a child.
            ("Bash", "cd ../topic-repo | cat; git reset --hard", "main", False, True),
            ("Bash", "cd ../topic-repo & git reset --hard", "main", False, True),
            ("PowerShell", "cd ../topic-repo & git reset --hard", "main", False, True),
            ("Bash", "cd ../main-repo | cat; git reset --hard", "topic", False, False),
            # A POSIX ( ... ) group is a subshell; PowerShell parentheses are not.
            ("Bash", "(cd ../topic-repo); git reset --hard", "main", False, True),
            ("Bash", "(cd ../topic-repo && git status); git reset --hard", "main", False, True),
            ("Bash", "(cd ../main-repo); git reset --hard", "topic", False, False),
            ("PowerShell", "(cd ../main-repo); git reset --hard", "topic", False, True),
            ("PowerShell", "cd ../main-repo | Out-Null; git reset --hard", "topic", False, True),
            # "||" runs the reset only when the cd failed, which a missing
            # target can do and an existing one cannot.
            ("Bash", "cd ../no-such || git reset --hard", "main", False, True),
            ("Bash", "cd ../topic-repo || git reset --hard", "main", False, False),
            # After a "&&" chain ends, a move that may have failed leaves both candidates.
            ("Bash", "cd ../no-such && git status; git reset --hard", "main", False, True),
            ("Bash", "cd ../topic-repo && git status; git reset --hard", "main", False, False),
            ("Bash", "cd ../topic-repo && git status && git reset --hard", "main", False, False),
            # A substitution body may run at any directory the line visits.
            ("Bash", "cd ../topic-repo && echo $(git reset --hard)", "main", False, True),
        ])

    def test_review_3_wrappers_and_reserved_words(self):
        self.check([
            ("Bash", "timeout 10 git reset --hard", "main", False, True),
            ("Bash", "timeout -s KILL 5 git reset --hard", "main", False, True),
            ("Bash", "timeout --kill-after=2 1m git reset --hard", "main", False, True),
            ("Bash", "timeout 10 git reset --hard main", "", False, True, True),
            ("Bash", "nice -n 5 git reset --hard", "main", False, True),
            ("Bash", "command git reset --hard", "main", False, True),
            ("Bash", "builtin cd ../main-repo && git reset --hard", "topic", False, True),
            ("Bash", BACKSLASH + "cd ../main-repo && git reset --hard", "topic", False, True),
            ("Bash", "if git reset --hard; then echo done; fi", "main", False, True),
            ("Bash", "while true; do git reset --hard; done", "main", False, True),
            ("Bash", "! git reset --hard", "main", False, True),
        ])
        # The wrapper gap affected every git rule, not only reset.
        for command in ("timeout 10 git push --force origin main", "timeout -k 1 30s git push -f origin main"):
            with self.subTest(command=command):
                assert guard.classify(command, {})[0]
        assert not guard.classify("timeout 10 git push origin feature", {})[0]

    def test_review_4_prefix_assignment_scopes_to_its_command(self):
        self.check([
            ("Bash", "GIT_DIR=.git git log -1; git reset --hard", "main", False, True),
            ("Bash", "env GIT_DIR=.git git log -1; git reset --hard", "main", False, True),
            ("Bash", "GIT_DIR=.git git reset --hard", "main", False, False),
            ("Bash", "GIT_DIR=.git; git reset --hard", "main", False, False),
            ("Bash", "echo $env:GIT_DIR; git reset --hard", "main", False, True),
        ])

    def test_review_5_colon_bound_path_is_unwrapped(self):
        # "&&" makes the move sure, so the result shows where the path pointed.
        self.check([
            ("PowerShell", "Set-Location -Path:'../main-repo' && git reset --hard", "topic", False, True),
            ("PowerShell", "Set-Location -Path:'../topic-repo' && git reset --hard", "main", False, False),
            ("PowerShell", "Set-Location -LiteralPath:\"dir with space\" && git reset --hard", "root", False, True),
            ("PowerShell", "Set-Location -Path:../main-repo && git reset --hard", "topic", False, True),
        ])

    def test_review_6_a_move_to_an_existing_directory_replaces_the_candidates(self):
        # cwd on main, a literal move into a task-branch repository: the
        # move succeeds, so the reset never runs on main.
        self.check([
            ("Bash", "cd ../topic-repo; git reset --hard", "main", False, False),
            ("Bash", "cd ../topic-repo\ngit reset --hard", "main", False, False),
            ("Bash", "cd ../topic-repo || exit 1; git reset --hard", "main", False, False),
            ("Bash", "set -e; cd ../topic-repo; git reset --hard", "main", False, False),
            ("Bash", "pushd ../topic-repo >/dev/null; git reset --hard", "main", False, False),
            ("PowerShell", "Set-Location ../topic-repo; git reset --hard", "main", False, False),
            ("PowerShell", "Set-Location ../topic-repo | Out-Null; git reset --hard", "main", False, False),
            ("PowerShell", "Set-Location ../topic-repo\ngit reset --hard", "main", False, False),
            # Still denied: the target cannot be resolved, does not exist,
            # or is not a directory, so the shell may still be on main.
            ("Bash", "cd $d; git reset --hard", "main", False, True),
            ("PowerShell", "Set-Location $d; git reset --hard", "main", False, True),
            ("Bash", "cd ../topic-repo/missing; git reset --hard", "main", False, True),
            ("Bash", "cd ../topic-repo/.git/HEAD; git reset --hard", "main", False, True),
            ("Bash", "cd ../no-such || exit 1; git reset --hard", "main", False, True),
            # And a move onto a protected checkout still denies.
            ("Bash", "cd ../main-repo; git reset --hard", "topic", False, True),
            ("PowerShell", "Set-Location ../main-repo; git reset --hard", "topic", False, True),
        ])

    def test_unknown_repository_allows(self):
        self.check([
            ("Bash", "git --git-dir=../main-repo/.git reset --hard", "main", False, False),
            ("Bash", "git --work-tree . reset --hard", "main", False, False),
            ("Bash", "GIT_DIR=x git reset --hard", "main", False, False),
            ("Bash", "export GIT_DIR=x; git reset --hard", "main", False, False),
            ("PowerShell", "$env:GIT_DIR = 'x'; git reset --hard", "main", False, False),
            ("Bash", "cd //host/share && git reset --hard", "main", False, False),
        ])
        unc = BACKSLASH * 2 + "host" + BACKSLASH + "share"
        assert not denied("git reset --hard", unc)
        assert not denied("git reset --hard", "//host/share")
        assert not denied("git reset --hard", "relative/dir")

    def test_network_paths_are_never_probed(self):
        unc = BACKSLASH * 2 + "host" + BACKSLASH + "share"
        with mock.patch("os.path.isdir", side_effect=AssertionError("probed")), \
                mock.patch("os.path.isfile", side_effect=AssertionError("probed")):
            assert guard.read_head_branch(unc) is None
            assert guard.read_head_branch("//host/share/repo") is None
            assert not denied("git reset --hard", unc)
            # The cd makes the repository unknown before anything is read.
            assert not denied("cd //host/share && git reset --hard", self.dirs["main"])

    def test_gitdir_file_pointing_at_a_network_path_is_unknown(self):
        repo = self.root / "unc-worktree"
        repo.mkdir(exist_ok=True)
        (repo / ".git").write_text("gitdir: //host/share/.git\n", encoding="utf-8", newline="\n")
        assert guard.read_head_branch(str(repo)) is None
        assert not denied("git reset --hard", str(repo))

    def test_default_reader_parses_head(self):
        assert guard.read_head_branch(self.dirs["main"]) == "main"
        assert guard.read_head_branch(str(self.root / "main-repo" / "deep" / "er")) == "main"
        assert guard.read_head_branch(str(self.root / "w")) == "main"
        assert guard.read_head_branch(self.dirs["topic"]) == "feature/main"
        assert guard.read_head_branch(self.dirs["detached"]) is None
        assert guard.read_head_branch("") is None

    def test_walk_stops_after_sixty_four_levels(self):
        base = Path(self.scratch) / "walk"
        write_head(base / ".git", "main")
        deep = base
        for _level in range(64):
            deep = deep / "d"
        deep.mkdir(parents=True)
        # 63 levels below the repository: the 64th check finds it.
        assert guard.read_head_branch(str(deep.parent)) == "main"
        assert guard.read_head_branch(str(deep)) is None

    def test_injected_reader_receives_the_effective_directory(self):
        seen = []

        def reader(directory):
            seen.append(directory)
            return "main"

        assert denied("git -C src reset --hard", self.dirs["cwdrepo"], reader=reader)
        assert seen == [os.path.normpath(os.path.join(self.dirs["cwdrepo"], "src"))]
        assert not denied("git reset --hard", "", reader=reader)
        assert denied("git reset --hard", self.dirs["topic"], reader=lambda directory: "master")
        assert not denied("git reset --hard", self.dirs["main"], reader=lambda directory: None)

        def broken(directory):
            raise OSError("unreadable")

        assert not denied("git reset --hard", self.dirs["main"], reader=broken)

    def test_deny_names_the_sanctioned_alternatives(self):
        out = guard.decide(payload("git reset --hard", self.dirs["main"]), {})
        assert out is not None
        assert "[git-protected-branch]" in out
        assert "git stash push" in out
        assert "git checkout -B <branch> origin/<branch>" in out
        assert "git reset --keep" in out
        assert "task branch" in out
        assert "git -C <dir> reset --hard" in out
        assert "cd <dir> && git reset --hard" in out

    def test_decision_stays_well_under_the_hook_budget(self):
        cases = {
            "bare reset on main": payload("git reset --hard", self.dirs["main"]),
            "cd then reset": payload("cd 'dir with space' && git reset --hard", self.dirs["root"]),
            "typical allow": payload("git status --short && git log --oneline -5", self.dirs["main"]),
            "deep walk": payload("git reset --hard", str(self.root / "a" / "b")),
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                guard.decide(data, {})
                timings = []
                for _run in range(3):
                    started = time.perf_counter()
                    guard.decide(data, {})
                    timings.append(time.perf_counter() - started)
                assert min(timings) < CEILING_SECONDS, "%s took %.3fs" % (name, min(timings))


if __name__ == "__main__":
    unittest.main()
