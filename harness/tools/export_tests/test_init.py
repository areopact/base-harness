"""E15, E16: init.py lanes and brain scaffolding."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import TempDirCase, run_cli, structure, write, write_structure, load_tool  # noqa: E402

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
