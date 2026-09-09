"""E15, E16: init.py lanes and brain scaffolding."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import TempDirCase, commit_all, init_repo, run_cli, structure, write, write_structure, load_tool  # noqa: E402

init = load_tool("init")


def scripted(answers: list):
    queue = list(answers)

    def ask(_prompt: str) -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    return ask


class TestLanes(TempDirCase):
    def test_e15_rejections(self):
        for bad in ("../x", "docs/../x", "/abs/path", "~/x", "C:/x", "C:\\x", "a\\b", "./docs", "docs//x"):
            try:
                init.parse_lane_answer(bad, None)
            except ValueError:
                continue
            raise AssertionError(f"accepted {bad!r}")
        assert init.parse_lane_answer("docs, docs/notes", None) == ["docs", "docs/notes"]
        assert init.parse_lane_answer("docs/", None) == ["docs"]
        assert init.parse_lane_answer("none", ["x"]) is None
        assert init.parse_lane_answer("", ["x"]) == ["x"]

    def test_e15_prompt_repeats_and_writes_nulls(self):
        answers = ["../evil", "docs/id", "none", "none", "none", "docs"]
        out = io.StringIO()
        code = init.run_lanes(self.tmp, ask=scripted(answers), out=out)
        assert code == 0, out.getvalue()
        assert "rejected" in out.getvalue()
        doc = json.loads((self.tmp / "harness" / "registry" / "structure.json").read_text())
        assert doc["lanes"] == {"identity": ["docs/id"], "knowledge": None, "decisions": None, "records": None, "docs": ["docs"]}
        assert not (self.tmp / "docs").exists()
        assert sorted(p.name for p in self.tmp.iterdir()) == ["harness"]

    def test_e15_early_eof_writes_nothing(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = init.run_lanes(self.tmp, ask=scripted(["docs"]), out=io.StringIO())
        assert code == 1
        assert "nothing written" in err.getvalue()
        assert not (self.tmp / "harness").exists()

    def test_e15_cli_reads_stdin(self):
        write_structure(self.tmp, structure(lanes={"docs": ["docs"]}))
        stdin = "\n".join(["none", "none", "docs/decisions", "none", ""]) + "\n"
        result = run_cli("init", "--lanes", "--root", str(self.tmp), stdin=stdin)
        assert result.returncode == 0, result.stderr + result.stdout
        doc = json.loads((self.tmp / "harness" / "registry" / "structure.json").read_text())
        assert doc["lanes"]["decisions"] == ["docs/decisions"]
        assert doc["lanes"]["docs"] == ["docs"]
        assert doc["lanes"]["identity"] is None
        assert not (self.tmp / "docs").exists()


class TestBrain(TempDirCase):
    def test_e16_scaffold_without_tracking(self):
        write(self.tmp / ".gitignore", "*.pyc\n")
        out = io.StringIO()
        code = init.run_brain(self.tmp, track_local=False, out=out)
        assert code == 0, out.getvalue()
        for rel in ("brain/README.md", "brain/shared/IDENTITY.md", "brain/shared/knowledge/.gitkeep", "brain/local/OPERATOR.md", "brain/local/.gitkeep"):
            assert (self.tmp / rel).is_file(), rel
        assert "/brain/local/" in (self.tmp / ".gitignore").read_text().split("\n")
        assert "tracking: off" in out.getvalue()
        assert "--track-local" in out.getvalue()
        assert not (self.tmp / "harness" / "registry" / "structure.json").exists()
        assert init.load_structure(self.tmp)["brain"]["local_tracked"] is False

    def test_e16_existing_files_kept(self):
        write(self.tmp / "brain" / "README.md", "mine\n")
        out = io.StringIO()
        assert init.run_brain(self.tmp, track_local=False, out=out) == 0
        assert (self.tmp / "brain" / "README.md").read_text() == "mine\n"
        assert "kept     brain/README.md" in out.getvalue()

    def test_e16_track_local_is_explicit(self):
        write(self.tmp / ".gitignore", "/brain/local/\n")
        out = io.StringIO()
        code = init.run_brain(self.tmp, track_local=True, out=out)
        assert code == 0, out.getvalue()
        assert init.TRACK_CONSEQUENCE in out.getvalue()
        doc = json.loads((self.tmp / "harness" / "registry" / "structure.json").read_text())
        assert doc["brain"] == {"local_tracked": True, "local_path": "brain/local"}
        assert "/brain/local/" not in (self.tmp / ".gitignore").read_text().split("\n")

    def test_e16_flag_without_brain_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = init.main(["--track-local", "--root", str(self.tmp)])
        assert code == 2
        assert "--track-local" in err.getvalue()
        assert not (self.tmp / "brain").exists()


class TestShape(TempDirCase):
    def test_bare_invocation_prints_shape(self):
        write_structure(self.tmp, structure(lanes={"docs": ["docs"]}, git_mode="branches"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = init.main(["--root", str(self.tmp)])
        assert code == 0
        text = out.getvalue()
        assert "lanes:" in text and "git mode:        branches" in text
        assert "init.py --lanes" in text and "init.py --brain" in text and "init.py --adopt" in text


class TestProfile(TempDirCase):
    def _repo(self, name="host-repo"):
        target = init_repo(self.tmp / name)
        write(target / "README.md", "x\n")
        commit_all(target, "seed")
        return target

    def test_team_yes_writes_team_defaults(self):
        target = self._repo()
        out = io.StringIO()
        code = init.run_profile(target, "team", True, out=out)
        assert code == 0, out.getvalue()
        doc = json.loads((target / "harness" / "registry" / "structure.json").read_text())
        assert doc["host"]["profile"] == "team"
        assert doc["git"]["mode"] == "branches"
        assert doc["brain"] == {"local_tracked": False, "local_path": f"~/.harness-local/{target.name}"}
        assert doc["lanes"] == {
            "identity": ["brain/shared/IDENTITY.md"],
            "knowledge": ["brain/shared/knowledge"],
            "decisions": ["docs/decisions"],
            "records": None,
            "docs": ["docs"],
        }
        assert doc["contract"]["mode"] == "rendered"

    def test_solo_yes_writes_solo_defaults(self):
        target = self._repo("solo-repo")
        out = io.StringIO()
        code = init.run_profile(target, "solo", True, out=out)
        assert code == 0, out.getvalue()
        doc = json.loads((target / "harness" / "registry" / "structure.json").read_text())
        assert doc["host"]["profile"] == "solo"
        assert doc["git"]["mode"] == "main-only"
        assert doc["brain"] == {"local_tracked": False, "local_path": "brain/local"}
        shipped = json.loads((init.TEMPLATES / "structure.default.json").read_text())
        assert doc["lanes"] == shipped["lanes"]

    def test_scripted_four_answers_match_flags(self):
        """A bare-profile interview answered 2/2/2/n equals `--profile team --yes`."""
        flagged = self._repo("flagged-repo")
        init.run_profile(flagged, "team", True, out=io.StringIO())
        flagged_doc = json.loads((flagged / "harness" / "registry" / "structure.json").read_text())

        scripted_target = self._repo("scripted-repo")
        out = io.StringIO()
        answers = ["2", "2", "2", "n"]
        asked = []

        def counting_ask(prompt):
            asked.append(prompt)
            if not answers:
                raise EOFError
            return answers.pop(0)

        code = init.run_profile(scripted_target, None, False, ask=counting_ask, out=out)
        assert code == 0, out.getvalue()
        assert len(asked) == 4, asked
        scripted_doc = json.loads((scripted_target / "harness" / "registry" / "structure.json").read_text())
        for key in ("git", "lanes", "contract"):
            assert scripted_doc[key] == flagged_doc[key], key
        assert scripted_doc["host"]["profile"] == flagged_doc["host"]["profile"]

    def test_eof_at_question_three_writes_nothing(self):
        target = self._repo("eof-repo")
        seed = json.loads((init.TEMPLATES / "structure.default.json").read_text())
        write_structure(target, seed)
        before = (target / "harness" / "registry" / "structure.json").read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = init.run_profile(target, None, False, ask=scripted(["2", "2"]), out=io.StringIO())
        assert code == 1
        assert "nothing written" in err.getvalue()
        after = (target / "harness" / "registry" / "structure.json").read_bytes()
        assert before == after

    def test_f10_adopt_yes_still_applies(self):
        """`--adopt <target> --yes` applies: --yes is a global flag consumed
        by init's own parser, so it never reaches adopt.py's argv unless
        main() re-forwards it as the flag adopt.py understands (-y/--apply)."""
        target = init_repo(self.tmp / "adopt-target")
        write(target / "README.md", "x\n")
        commit_all(target, "seed")

        dry_run = run_cli("init", "--adopt", str(target))
        assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
        assert "adopt: applied" not in dry_run.stdout
        assert "adopt: dry run" in dry_run.stdout

        applied = run_cli("init", "--adopt", str(target), "--yes")
        assert applied.returncode == 0, applied.stdout + applied.stderr
        assert "adopt: applied" in applied.stdout

    def test_bare_status_line_present_and_absent(self):
        target = self._repo("status-repo")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            init.main(["--root", str(target)])
        assert "host profile: solo (absent; set it with python harness/tools/init.py --profile)" in out.getvalue()

        init.run_profile(target, "team", True, out=io.StringIO())
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            init.main(["--root", str(target)])
        assert "host profile: team" in out2.getvalue()

    def test_idempotent_team_yes_run_twice(self):
        target = self._repo("idem-repo")
        init.run_profile(target, "team", True, out=io.StringIO())
        first = (target / "harness" / "registry" / "structure.json").read_bytes()
        gitignore_first = (target / ".gitignore").read_text() if (target / ".gitignore").is_file() else ""
        init.run_profile(target, "team", True, out=io.StringIO())
        second = (target / "harness" / "registry" / "structure.json").read_bytes()
        gitignore_second = (target / ".gitignore").read_text() if (target / ".gitignore").is_file() else ""
        assert first == second
        assert gitignore_first == gitignore_second

    def test_profile_bare_requires_value_on_non_tty(self):
        target = self._repo("nontty-repo")
        result = run_cli("init", "--profile", "--root", str(target), stdin="")
        assert result.returncode == 2
        assert "--profile <value> --yes" in result.stderr
