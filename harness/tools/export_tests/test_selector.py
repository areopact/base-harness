"""E14: selector.py pack expansion, refusal, dry run, and user scope."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import TempDirCase, write, load_tool  # noqa: E402

select = load_tool("selector")

SKILL = "---\nname: {name}\ndescription: {name} skill. WHEN: asked.\nmetadata:\n  packs:\n    - {pack}\n  status: spec-only\n---\n# {name}\n"


def seed(root: Path) -> None:
    for name, pack in (("alpha", "core"), ("beta", "maintain"), ("gamma", "decks")):
        write(root / "harness" / "skills" / name / "SKILL.md", SKILL.format(name=name, pack=pack))
    write(root / "harness" / "skills" / "_vendor" / "x" / "SKILL.md", SKILL.format(name="x", pack="core"))


def run(args: list) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = select.main(args)
    return code, out.getvalue(), err.getvalue()


class TestSelect(TempDirCase):
    def setUp(self):
        super().setUp()
        seed(self.tmp)
        self.selection = self.tmp / "harness" / "registry" / "selection.json"
        self.local = self.tmp / "harness" / "registry" / "selection.local.json"

    def base(self, *extra) -> list:
        return ["--root", str(self.tmp), "--no-materialize", *extra]

    def test_discovery_skips_underscore_dirs(self):
        skills = select.discover_skills(self.tmp)
        assert sorted(skills) == ["alpha", "beta", "gamma"]
        assert skills["alpha"]["packs"] == ["core"]

    def test_pack_expansion(self):
        code, out, _ = run(self.base("--pack", "core", "--pack", "decks"))
        assert code == 0, out
        data = json.loads(self.selection.read_text())
        assert data == {"schema_version": 1, "packs": ["core", "decks"], "include": [], "exclude": []}
        assert select.effective_set(data, select.discover_skills(self.tmp)) == ["alpha", "gamma"]
        assert "+ gamma" in out and "- beta" in out

    def test_include_and_exclude(self):
        code, _, _ = run(self.base("--pack", "core", "--skill", "gamma", "--without", "alpha"))
        assert code == 0
        data = json.loads(self.selection.read_text())
        assert data["include"] == ["gamma"] and data["exclude"] == ["alpha"]
        assert select.effective_set(data, select.discover_skills(self.tmp)) == ["gamma"]

    def test_unknown_skill_refused(self):
        code, _, err = run(self.base("--skill", "nope"))
        assert code == 1
        assert "unknown skill(s): nope" in err
        assert "valid skills: alpha, beta, gamma" in err
        assert not self.selection.exists()

    def test_dry_run_writes_nothing(self):
        code, out, _ = run(self.base("--pack", "core", "--dry-run"))
        assert code == 0
        assert "selection diff:" in out and "dry run" in out
        assert not self.selection.exists() and not self.local.exists()

    def test_scope_user_writes_local_file(self):
        code, out, _ = run(self.base("--pack", "maintain", "--scope", "user"))
        assert code == 0
        assert self.local.is_file() and not self.selection.exists()
        assert json.loads(self.local.read_text())["packs"] == ["maintain"]
        assert "selection.local.json" in out

    def test_interactive_prompt_is_prose_and_confirms(self):
        skills = select.discover_skills(self.tmp)
        answers = iter(["1", "3", "", "y"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            new = select.interactive(skills, dict(select.SELECTION_DEFAULT), ask=lambda _prompt: next(answers))
        assert new == {"packs": ["core"], "include": ["gamma"], "exclude": []}
        assert "1. [" in out.getvalue()
        answers = iter(["", "", "", "n"])
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                select.interactive(skills, dict(select.SELECTION_DEFAULT), ask=lambda _prompt: next(answers))
            except SystemExit as exc:
                assert "nothing written" in str(exc)
            else:
                raise AssertionError("declined confirmation did not abort")

    def test_missing_bootstrap_entry_is_reported_not_fatal(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = select.materialize(self.tmp)
        assert code == 0
        assert "bootstrap entry not found" in out.getvalue()
