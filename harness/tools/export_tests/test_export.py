"""E1..E12: export.py behavior on seeded trees."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import TempDirCase, make_link, structure, walk_files, write, write_structure, load_tool  # noqa: E402

export = load_tool("export")

FM = "---\naccess: {label}\n---\nbody\n"


def md(label: str) -> str:
    return FM.format(label=label)


class ExportCase(TempDirCase):
    def setUp(self):
        super().setUp()
        self.src = self.tmp / "src"
        self.src.mkdir()
        self.out = self.tmp / "out"
        self.collab = self.tmp / "collaborators.yaml"
        write(self.collab, "collaborators:\n  - id: alpha\n    name: Alpha\n    tier_max: restricted\n")
        write_structure(self.src, structure())

    def run_export(self, tier: str, out: Path | None = None) -> dict:
        return export.export_tree(self.src, out or self.out, tier, self.collab)

    def refused(self, tier: str, out: Path | None = None) -> str:
        try:
            export.export_tree(self.src, out or self.out, tier, self.collab)
        except export.Refused as exc:
            return str(exc)
        raise AssertionError("export was not refused")


class TestSymlinks(ExportCase):
    def test_e1_symlink_inside_source_is_skipped(self):
        write(self.src / "docs" / "t.md", md("public"))
        if not make_link(self.src / "docs" / "t.md", self.src / "docs" / "link.md"):
            self.skipTest("host cannot create links")
        result = self.run_export("internal")
        assert (self.out / "docs" / "t.md").is_file()
        assert not (self.out / "docs" / "link.md").exists()
        assert result["symlinks"] == ["docs/link.md"]
        assert result["input_files"] == 3  # structure.json, t.md, link.md

    def test_e1_symlink_component_in_out_refuses(self):
        write(self.src / "docs" / "t.md", md("public"))
        real = self.tmp / "real"
        real.mkdir()
        if not make_link(real, self.tmp / "linkdir"):
            self.skipTest("host cannot create links")
        message = self.refused("internal", self.tmp / "linkdir" / "out")
        assert "symlink component" in message
        assert not (real / "out").exists()


class TestBinaries(ExportCase):
    def test_e2_binaries_copy_byte_exact(self):
        small = b"\x00\x01\x02"
        big = random.Random(7).randbytes(1024 * 1024)
        write(self.src / "docs" / "a.bin", small)
        write(self.src / "docs" / "b.bin", big)
        self.run_export("internal")
        for name, data in (("a.bin", small), ("b.bin", big)):
            copied = (self.out / "docs" / name).read_bytes()
            assert hashlib.sha256(copied).hexdigest() == hashlib.sha256(data).hexdigest()
            assert len(copied) == len(data)


class TestNoFrontmatter(ExportCase):
    def test_e3_lane_default_then_unlisted(self):
        write_structure(self.src, structure(lanes={"docs": ["docs"]}, lane_defaults={"docs": "public"}, unlisted="internal"))
        write(self.src / "docs" / "plain.md", "no frontmatter\n")
        write(self.src / "loose.md", "no frontmatter\n")
        result = self.run_export("public")
        assert (self.out / "docs" / "plain.md").is_file()
        assert not (self.out / "loose.md").exists()
        assert ("loose.md", "tier internal above public") in result["excluded"]
        out2 = self.tmp / "out2"
        result = self.run_export("internal", out2)
        assert (out2 / "loose.md").is_file()
        assert (out2 / "docs" / "plain.md").is_file()

    def test_e3_unlisted_exclude_drops_lane_less_file(self):
        write_structure(self.src, structure(lanes={"docs": ["docs"]}, unlisted="exclude"))
        write(self.src / "docs" / "plain.md", "no frontmatter\n")
        write(self.src / "loose.md", "no frontmatter\n")
        result = self.run_export("secret")
        assert (self.out / "docs" / "plain.md").is_file()
        assert not (self.out / "loose.md").exists()
        assert ("loose.md", "unlisted path (policy exclude)") in result["excluded"]


class TestDotfiles(ExportCase):
    def test_e4_dotfiles_follow_the_same_rule(self):
        write(self.src / ".gitignore", "x\n")
        write(self.src / ".hidden", "y\n")
        result = self.run_export("internal")
        assert (self.out / ".gitignore").is_file()
        assert (self.out / ".hidden").is_file()
        assert result["input_files"] == 3
        out2 = self.tmp / "out2"
        result = self.run_export("public", out2)
        assert not (out2 / ".gitignore").exists()
        assert not (out2 / ".hidden").exists()
        names = {rel for rel, _ in result["excluded"]}
        assert {".gitignore", ".hidden"} <= names


class TestGitAbsence(ExportCase):
    def test_e5_git_never_copied_or_counted(self):
        write(self.src / ".git" / "HEAD", "ref: main\n")
        write(self.src / ".git" / "objects" / "x", "blob\n")
        write(self.src / "docs" / ".git", "gitdir: elsewhere\n")
        write(self.src / "docs" / "t.md", md("public"))
        result = self.run_export("secret")
        assert not (self.out / ".git").exists()
        assert not (self.out / "docs" / ".git").exists()
        assert all(".git" not in Path(rel).parts for rel in walk_files(self.out))
        assert result["input_files"] == 2  # structure.json and t.md


class TestAttachments(ExportCase):
    def test_e6_referenced_attachment_copied_or_reported(self):
        write_structure(
            self.src,
            structure(lanes={"docs": ["docs"], "records": ["brain"]}, lane_defaults={"docs": "public", "records": "confidential"}),
        )
        write(self.src / "docs" / "doc.md", md("public") + "![a](./img/a.png) ![b](../brain/img/b.png)\n")
        write(self.src / "docs" / "img" / "a.png", b"\x89PNG-a")
        write(self.src / "brain" / "img" / "b.png", b"\x89PNG-b")
        result = self.run_export("public")
        assert (self.out / "docs" / "img" / "a.png").read_bytes() == b"\x89PNG-a"
        assert not (self.out / "brain" / "img" / "b.png").exists()
        assert [(a, r) for a, r, _ in result["blocked"]] == [("brain/img/b.png", "docs/doc.md")]
        stream = io.StringIO()
        export.print_summary(result, stream)
        assert "blocked-attachment  1" in stream.getvalue()
        assert "brain/img/b.png (from docs/doc.md)" in stream.getvalue()


class TestUnparseable(ExportCase):
    def test_e7_each_shape_is_excluded_and_counted(self):
        write(self.src / "docs" / "dup.md", "---\naccess: public\naccess: public\n---\n")
        write(self.src / "docs" / "bom.md", b"\xef\xbb\xbf" + md("public").encode())
        write(self.src / "docs" / "cr.md", b"---\r\naccess: public\r\n---\r\nbody\n")
        write(self.src / "docs" / "unknown.md", "---\naccess: top-secret\n---\n")
        write(self.src / "docs" / "ok.md", md("public"))
        stream = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()):
            code = export.run_export(self.src, self.out, "secret", self.collab, stream)
        assert code == 1
        text = stream.getvalue()
        assert "unparseable         4" in text
        for name, why in (("dup.md", "duplicate access key"), ("bom.md", "byte-order mark"), ("cr.md", "carriage return"), ("unknown.md", "unknown tier value")):
            assert not (self.out / "docs" / name).exists()
            assert f"docs/{name}: {why}" in text
        assert (self.out / "docs" / "ok.md").is_file()


class TestSecret(ExportCase):
    def test_e8_secret_absent_from_secret_export(self):
        write(self.src / "docs" / "s.md", md("secret"))
        write(self.src / "docs" / "r.md", md("restricted"))
        result = self.run_export("secret")
        assert not (self.out / "docs" / "s.md").exists()
        assert (self.out / "docs" / "r.md").is_file()
        assert ("docs/s.md", "secret is excluded from every export") in result["excluded"]


class TestRestrictedGate(ExportCase):
    def test_e9_restricted_needs_collaborators(self):
        write(self.collab, "collaborators: []\n")
        write(self.src / "docs" / "r.md", md("restricted"))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            code = export.run_export(self.src, self.out, "restricted", self.collab)
        assert code == 2
        assert "collaborators" in err.getvalue()
        assert not self.out.exists()
        code = export.run_export(self.src, self.out, "confidential", self.collab, io.StringIO())
        assert code == 0


class TestUnlistedPath(ExportCase):
    def test_e10_policies(self):
        write(self.src / "loose.txt", "x\n")
        write_structure(self.src, structure(unlisted="exclude"))
        result = self.run_export("secret")
        assert not (self.out / "loose.txt").exists()
        assert ("loose.txt", "unlisted path (policy exclude)") in result["excluded"]
        write_structure(self.src, structure(unlisted="internal"))
        out2 = self.tmp / "out2"
        self.run_export("internal", out2)
        assert (out2 / "loose.txt").is_file()
        out3 = self.tmp / "out3"
        result = self.run_export("public", out3)
        assert not (out3 / "loose.txt").exists()
        assert ("loose.txt", "tier internal above public") in result["excluded"]


class TestDestinationRefusals(ExportCase):
    def test_e11_non_empty_out_refused_and_untouched(self):
        self.out.mkdir()
        keep = write(self.out / "keep.txt", "keep\n")
        write(self.src / "docs" / "t.md", md("public"))
        message = self.refused("internal")
        assert "not empty" in message
        assert keep.read_text() == "keep\n"
        assert os.listdir(self.out) == ["keep.txt"]

    def test_e12_out_inside_source_refused(self):
        write(self.src / "docs" / "t.md", md("public"))
        message = self.refused("internal", self.src / "export")
        assert "inside the source repository" in message
        assert not (self.src / "export").exists()

    def test_out_with_git_refused(self):
        self.out.mkdir()
        (self.out / ".git").mkdir()
        message = self.refused("internal")
        assert ".git" in message

    def test_cli_summary_reconciles(self):
        write(self.src / "docs" / "t.md", md("public"))
        write(self.src / "docs" / "c.md", md("confidential"))
        stream = io.StringIO()
        code = export.run_export(self.src, self.out, "internal", self.collab, stream)
        assert code == 0
        text = stream.getvalue()
        assert "export summary (requested tier: internal)" in text
        assert "copied              2" in text
        assert "excluded-by-tier    1" in text
        assert "input files         3 (copied + excluded-by-tier + unparseable + skipped-symlink = 3)" in text
