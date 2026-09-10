"""E18: deidentify_lint.py structural checks, term file, and history walk.

Seeded violations are assembled from fragments at runtime so this file passes
the lint it exercises.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import TempDirCase, commit_all, init_repo, write, load_tool  # noqa: E402

lint = load_tool("deidentify_lint")

EMAIL = "someone" + "@" + "corp-mail" + ".io"
NARRATIVE = "# " + "2026" + "-01-02 the hook " + "broke" + " on this path"
FOREIGN_PATH = "private-area" + "/" + "foo" + "/" + "bar.md"
SHELL_PATH = "$" + "SCRIPT_DIR" + "/" + "lib" + "/" + "x.py"
RELATIVE_PATH = "./" + "img" + "/" + "a.png"
USER_DIR = "/" + "home" + "/someone/repo"
DRIVE_PATH = "D" + ":" + "\\Sources\\os"
ATTRIBUTION = "".join(("Areo", "pact"))
EM_DASH = chr(0x2014)
# The generic knowledge-base word the seed list denies, assembled so this
# module carries no denied term and needs no exemption from the term layer.
GENERIC_TERM = "va" + "ult"


def run(args: list) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = lint.main(args)
    return code, out.getvalue(), err.getvalue()


def checks(output: str) -> set:
    return {line.split()[0] for line in output.splitlines() if line and line[0] in "DT"}


class TestStructural(TempDirCase):
    def test_each_check_fires_on_a_seeded_violation(self):
        seeds = {
            "D1": ("docs/a.md", f"contact {EMAIL}\n"),
            "D2": ("harness/x.py", NARRATIVE + "\n"),
            "D3": ("docs/c.md", f"see {FOREIGN_PATH}\n"),
            "D4": ("docs/d.md", "clone at " + "/" + "root" + "/somewhere\n"),
            "D5": ("docs/e.md", f"made by {ATTRIBUTION}\n"),
            "D6": ("docs/f.md", f"dash {EM_DASH} here\n"),
            "D7": ("docs/g.md", f"checkout at {DRIVE_PATH}\n"),
        }
        for check, (rel, content) in seeds.items():
            repo = self.tmp / check
            write(repo / rel, content)
            code, out, _ = run([str(repo), "--structural"])
            assert code == 1, f"{check} did not fire"
            assert checks(out) == {check}, f"{check}: {out}"
            assert content.strip() not in out, "finding echoed the line"

    def test_d2_prose_line_and_d6_bytes(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "p.md", "On " + "2026" + "-03-04 there was an " + "incident" + " here\n")
        write(repo / "docs" / "crlf.md", b"line\r\nline\r\n")
        write(repo / "docs" / "bom.md", b"\xef\xbb\xbfclean text\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1
        assert "D2 docs/p.md:1" in out
        assert "D6 docs/crlf.md:1: carriage return" in out
        assert "D6 docs/bom.md:1: byte-order mark" in out

    def test_attribution_allowed_only_in_named_root_files(self):
        repo = self.tmp / "r"
        write(repo / "README.md", f"{ATTRIBUTION} wrote this\n")
        write(repo / "LICENSE", f"Copyright {ATTRIBUTION}\n")
        write(repo / "NOTICE", f"{ATTRIBUTION}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        write(repo / "docs" / "README.md", f"{ATTRIBUTION}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D5 docs/README.md:1" in out

    def test_attribution_allowed_in_harness_siblings(self):
        repo = self.tmp / "r-siblings"
        write(repo / "README.harness.md", f"{ATTRIBUTION} wrote this\n")
        write(repo / "LICENSE.harness.md", f"Copyright {ATTRIBUTION}\n")
        write(repo / "NOTICE.harness.md", f"{ATTRIBUTION}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_attribution_allowed_in_the_host_contract_notes(self):
        repo = self.tmp / "r-host-notes"
        write(repo / "harness" / "CONTRACT.host.md", f"# Host notes\n\nThe {ATTRIBUTION} lead reviews every package.\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        write(repo / "harness" / "CONTRACT.md", f"{ATTRIBUTION}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D5 harness/CONTRACT.md:1" in out

    def test_clean_tree_is_silent(self):
        repo = self.tmp / "clean"
        write(repo / "README.md", "# Title\n\nA clean file with an email at user@example.com and docs/guide.md.\n")
        write(repo / "harness" / "tool.py", "# invariant: the guard denies a read of the env file\nprint('ok')\n")
        write(repo / "docs" / "note.md", "Version 1.2.3 and a ratio like read/write are prose.\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        assert "0 finding(s)" in out

    def test_shell_expansions_and_relative_references_are_not_paths(self):
        repo = self.tmp / "r"
        write(repo / "harness" / "x.sh", f'python "{SHELL_PATH}"\n')
        write(repo / "docs" / "a.md", f"![a]({RELATIVE_PATH}) and ../{RELATIVE_PATH[2:]}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_lane_roots_from_structure_are_allowed(self):
        repo = self.tmp / "lanes"
        doc = lint._fallback_structure(repo)
        doc["lanes"]["records"] = ["notes"]
        write(repo / "harness" / "registry" / "structure.json", __import__("json").dumps(doc))
        write(repo / "docs" / "a.md", "see " + "notes" + "/" + "2026" + "/" + "meeting.md" + "\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_d3_adopted_host_roots_from_structure_are_allowed(self):
        repo = self.tmp / "hostroots"
        doc = lint._fallback_structure(repo)
        doc["host"] = {"adopted": True, "roots": ["courses", "modules"], "harness_owned": []}
        write(repo / "harness" / "registry" / "structure.json", __import__("json").dumps(doc))
        write(repo / "docs" / "a.md", "see " + "courses" + "/" + "algebra" + "/" + "lesson1.md" + "\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        assert "D3" not in checks(out)
        # The allow list still matters under --all (the whole-tree scan),
        # where docs/a.md is scanned rather than excluded by default scope.
        code, out, _ = run([str(repo), "--structural", "--all"])
        assert code == 0, out
        assert "D3" not in checks(out)

    def test_d3_non_host_root_still_flagged_even_with_adopted_host(self):
        """docs/a.md is host content: an adopted host's default scope no
        longer scans it at all (it is neither in adopted-files.json nor the
        kernel manifest), so D3 is silent by default. --all restores the
        whole-tree scan, where the token is still not allow-listable."""
        repo = self.tmp / "hostroots-negative"
        doc = lint._fallback_structure(repo)
        doc["host"] = {"adopted": True, "roots": ["courses"], "harness_owned": []}
        write(repo / "harness" / "registry" / "structure.json", __import__("json").dumps(doc))
        write(repo / "docs" / "a.md", f"see {FOREIGN_PATH}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        assert "D3" not in checks(out)
        code, out, _ = run([str(repo), "--structural", "--all"])
        assert code == 1
        assert "D3" in checks(out)


class TestTerms(TempDirCase):
    def test_terms_respect_comments_and_blank_lines(self):
        repo = self.tmp / "r"
        terms = self.tmp / "terms.txt"
        write(terms, "# comment-word is not a term\n\n   \nPrivateTerm\n")
        write(repo / "docs" / "a.md", "comment-word appears here\nand privateterm appears on line two\n")
        write(repo / "harness" / "x.py", "# a code comment naming PRIVATETERM is still a leak\n")
        code, out, _ = run([str(repo), "--terms", str(terms)])
        assert code == 1
        lines = [line for line in out.splitlines() if line.startswith("TERM")]
        assert lines == ["TERM docs/a.md:2: matched term 'privateterm'", "TERM harness/x.py:1: matched term 'privateterm'"], lines
        assert "comment-word" not in out

    def test_structural_flag_ignores_terms(self):
        repo = self.tmp / "r"
        terms = self.tmp / "terms.txt"
        write(terms, "privateterm\n")
        write(repo / "docs" / "a.md", "privateterm\n")
        code, out, _ = run([str(repo), "--terms", str(terms), "--structural"])
        assert code == 0, out


class TestDefaultTermSource(TempDirCase):
    def test_seed_file_is_used_when_terms_is_omitted(self):
        repo = self.tmp / "r"
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "# seed" + chr(10) + "privateterm" + chr(10))
        write(repo / "docs" / "a.md", "privateterm appears here" + chr(10))
        code, out, _ = run([str(repo)])
        assert code == 1
        lines = [line for line in out.splitlines() if line.startswith("TERM")]
        assert lines == ["TERM docs/a.md:1: matched term 'privateterm'"], lines
        assert "mode structural+terms" in out

    def test_seed_file_is_ignored_by_structural_and_overridden_by_terms(self):
        repo = self.tmp / "r"
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "privateterm" + chr(10))
        write(repo / "docs" / "a.md", "privateterm appears here" + chr(10))
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        other = self.tmp / "other.txt"
        write(other, "unrelated-term" + chr(10))
        code, out, _ = run([str(repo), "--terms", str(other)])
        assert code == 0, out

    def test_no_seed_file_means_structural_only(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "plain prose" + chr(10))
        code, out, _ = run([str(repo)])
        assert code == 0, out
        assert "mode structural," in out

    def test_shipped_seed_loads_and_stays_public_safe(self):
        seed = lint.ROOT / lint.DEFAULT_TERMS_RELATIVE
        assert seed.is_file(), seed
        terms = lint.load_terms(seed)
        assert terms, "seed list is empty"
        assert all(len(term) >= 5 for term in terms), terms
        assert all(term == term.lower() for term in terms), terms
        raw = seed.read_bytes()
        assert bytes([13]) not in raw
        assert not raw.startswith(lint.BOM)
        assert raw.decode("ascii")  # ASCII only
        # the seed file itself passes every structural check, since lint L14
        # scans it without a skip list
        allowed = lint.allowed_first_segments(lint.ROOT)
        findings = lint.scan_content(lint.DEFAULT_TERMS_RELATIVE, raw, [], allowed, True)
        assert findings == [], [f.render() for f in findings]

    def test_versioned_identifier_is_not_a_path(self):
        repo = self.tmp / "r"
        write(repo / "harness" / "m.json", '{"balanced": "' + "provider-x" + "/" + "model-5.3-flash" + '"}' + chr(10))
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        write(repo / "docs" / "b.md", "see " + "private-area" + "/" + "notes.md" + chr(10))
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and checks(out) == {"D3"}, out

    def test_machine_state_root_is_not_a_foreign_path(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "scratch lives under " + ".tmp" + "/" + "workflows" + "/" + "<run-id>" + "/ only" + chr(10))
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out


class TestHistory(TempDirCase):
    def test_history_finds_a_term_only_in_an_old_commit(self):
        repo = init_repo(self.tmp / "repo")
        terms = self.tmp / "terms.txt"
        write(terms, "privateterm\n")
        write(repo / "docs" / "a.md", "privateterm was here\n")
        first = commit_all(repo, "first")
        write(repo / "docs" / "a.md", "clean now\n")
        commit_all(repo, "second")
        code, out, _ = run([str(repo), "--terms", str(terms)])
        assert code == 0, out
        code, out, _ = run([str(repo), "--terms", str(terms), "--history"])
        assert code == 1
        assert f"{first[:12]} TERM docs/a.md:1: matched term 'privateterm'" in out
        assert "history on" in out

    def test_history_with_no_refs_exits_1_not_clean(self):
        """F3(b): an empty or ref-less repository must not be indistinguishable
        from a clean history. git rev-list --all returns nothing here because
        init_repo() never commits, so --history must fail loudly."""
        repo = init_repo(self.tmp / "empty-repo")
        code, out, err = run([str(repo), "--structural", "--history"])
        assert code == 1, (code, out, err)
        assert "no refs to scan" in err


class TestRequireTerms(TempDirCase):
    def test_require_terms_fails_release_on_a_thin_list(self):
        """F3(c): a release run must not pass silently against an empty or
        near-empty private term list."""
        repo = self.tmp / "r"
        terms = self.tmp / "private.txt"
        write(terms, "onlyone\n")
        write(repo / "docs" / "a.md", "clean\n")
        code, out, err = run([str(repo), "--terms", str(terms), "--require-terms", "3"])
        assert code == 2, (code, out, err)
        assert "--require-terms 3 not met" in err
        assert "1 entry" in err

    def test_require_terms_passes_when_the_floor_is_met(self):
        repo = self.tmp / "r"
        terms = self.tmp / "private.txt"
        write(terms, "one\ntwo\nthree\n")
        write(repo / "docs" / "a.md", "clean\n")
        code, out, err = run([str(repo), "--terms", str(terms), "--require-terms", "3"])
        assert code == 0, (code, out, err)

    def test_require_terms_counts_the_shipped_seed_when_terms_is_omitted(self):
        repo = self.tmp / "r"
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "# seed\none\ntwo\n")
        write(repo / "docs" / "a.md", "clean\n")
        code, out, err = run([str(repo), "--require-terms", "5"])
        assert code == 2, (code, out, err)


class TestCarriageReturnNormalization(TempDirCase):
    def test_d6_committed_clean_worktree_cr_from_checkout_normalization_is_not_flagged(self):
        repo = init_repo(self.tmp / "crlf")
        write(repo / "docs" / "a.md", "line one\nline two\n")
        commit_all(repo, "seed")
        # Simulate a Windows checkout with CRLF normalization: the worktree
        # copy carries CR even though the committed index blob is clean LF.
        write(repo / "docs" / "a.md", "line one\r\nline two\r\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        assert "D6" not in checks(out)

    def test_d6_untracked_file_with_real_cr_is_still_flagged(self):
        repo = init_repo(self.tmp / "crlf-untracked")
        write(repo / "docs" / "a.md", "line one\nline two\n")
        commit_all(repo, "seed")
        write(repo / "docs" / "b.md", "untracked new\r\nfile\r\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1
        assert "D6" in checks(out)

    def test_d6_committed_cr_in_the_blob_is_still_flagged(self):
        repo = init_repo(self.tmp / "crlf-real")
        write(repo / "docs" / "a.md", "line one\r\nline two\r\n")
        commit_all(repo, "seed")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1
        assert "D6" in checks(out)


class TestDeniedFirstSegments(TempDirCase):
    """F3(a) regression: a two-segment token under a denied private root must
    be flagged even though it has no extension, no third segment, and no
    trailing slash, the shape D3 otherwise requires."""

    def test_two_segment_denied_root_is_flagged(self):
        repo = self.tmp / "r"
        two_segment = "ventures" + "/" + "acme"
        three_segment_under_denied = two_segment + "/" + "CONTEXT.md"
        other_denied_root = "fleet" + "/" + "scripts"
        write(
            repo / "docs" / "a.md",
            f"See {two_segment} and {three_segment_under_denied}, plus {other_denied_root}.\n",
        )
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1
        assert checks(out) == {"D3"}
        assert "denied private root: first segment 'ventures'" in out
        assert "denied private root: first segment 'fleet'" in out

    def test_denied_root_synthetic_repo_from_the_review_finding(self):
        """Reproduces the reviewer's throwaway repo shape: a two-segment
        private root, a three-segment path under it, and a second two-segment
        private root, all previously invisible to D3."""
        repo = self.tmp / "review-repo"
        write(repo / ("ventures" + "/" + "acme" + "/" + "CONTEXT.md"), "context\n")
        write(
            repo / "docs" / "notes.md",
            "planning under " + "ventures" + "/" + "acme" + " and " + "fleet" + "/" + "scripts" + "\n",
        )
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1
        assert checks(out) == {"D3"}
        first_segments = {"ventures", "fleet"}
        for segment in first_segments:
            assert f"first segment '{segment}'" in out

    def test_denied_root_is_not_allow_listable_by_structure_lanes(self):
        repo = self.tmp / "r"
        doc = lint._fallback_structure(repo)
        doc["lanes"]["records"] = ["fleet"]
        write(repo / "harness" / "registry" / "structure.json", __import__("json").dumps(doc))
        write(repo / "docs" / "a.md", "see " + "fleet" + "/" + "scripts" + "\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and checks(out) == {"D3"}, out

    def test_generic_seed_term_is_shipped_and_used_by_default(self):
        """F3(d): the public seed list now carries generic private-source
        vocabulary, including the knowledge-base word, and the default
        invocation (no --terms) picks it up from inside the scanned
        repository."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        assert GENERIC_TERM in seed
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        write(repo / "docs" / "a.md", f"clone the {GENERIC_TERM} before you start\n")
        code, out, _ = run([str(repo)])
        assert code == 1
        assert f"matched term '{GENERIC_TERM}'" in out

    def test_only_the_denied_block_lines_are_exempt_from_the_term_layer(self):
        """The tool that defines the denied vocabulary necessarily contains it,
        but only inside the DENIED_FIRST_SEGMENTS literal and the default
        term-file path line. A term planted on any other line of that same
        module is still flagged, and a structural finding inside the exempt
        file is still reported."""
        assert lint.SELF_EXEMPT_FILE == "harness/tools/deidentify_lint.py"
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            f'    "{GENERIC_TERM}",\n'
            "}\n",
        )
        code, out, _ = run([str(repo)])
        assert code == 0, out
        write(repo / "docs" / "a.md", f"clone the {GENERIC_TERM} before you start\n")
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and "docs/a.md" in out, out
        write(repo / exempt, f"# {GENERIC_TERM}\n{EMAIL}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D1" in out and exempt in out, out

    def test_a_term_outside_the_denied_block_is_still_reported(self):
        """A private term written on a line of the lint module that is NOT
        inside the DENIED_FIRST_SEGMENTS block, and not the default
        term-file path line, is a real leak and must still be caught."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            '    "ventures",\n'
            "}\n"
            f"# this comment names {GENERIC_TERM} outside the block\n",
        )
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and exempt in out, out

    def test_a_term_inside_the_denied_block_does_not_report(self):
        """A term that lives inside the DENIED_FIRST_SEGMENTS block (or on the
        default term-file path line) of the lint module is exempt, since the
        module necessarily names the roots it denies."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            f'    "{GENERIC_TERM}",\n'
            "}\n"
            f'DEFAULT_TERMS_RELATIVE = "harness/tools/{GENERIC_TERM}-terms.txt"\n',
        )
        code, out, _ = run([str(repo)])
        assert code == 0, out

    def test_a_comment_mentioning_the_identifier_is_not_exempt(self):
        """The exemption is anchored to the actual DEFAULT_TERMS_RELATIVE
        assignment statement, not to any line that mentions the identifier:
        a probe term on a comment line naming DEFAULT_TERMS_RELATIVE must
        still be reported."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            '    "ventures",\n'
            "}\n"
            f"# DEFAULT_TERMS_RELATIVE discussion mentions {GENERIC_TERM} here\n"
            'DEFAULT_TERMS_RELATIVE = "harness/tools/deidentify-terms.txt"\n',
        )
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and exempt in out, out

    def test_a_second_statement_on_the_assignment_line_is_not_exempt(self):
        """A term hidden after a semicolon on the same line as the
        DEFAULT_TERMS_RELATIVE assignment is still reported: the exemption
        covers only a line that is the assignment alone."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            '    "ventures",\n'
            "}\n"
            'DEFAULT_TERMS_RELATIVE = "harness/tools/deidentify-terms.txt"; '
            f'PROBE = "{GENERIC_TERM}"\n',
        )
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and exempt in out, out

    def test_a_nested_function_assignment_is_not_exempt(self):
        """The exemption only ever applies to the module-level assignment:
        a same-named assignment inside a nested function must still be
        reported like any other line."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            '    "ventures",\n'
            "}\n"
            "def _probe():\n"
            f'    DEFAULT_TERMS_RELATIVE = "harness/tools/{GENERIC_TERM}-terms.txt"\n'
            "    return DEFAULT_TERMS_RELATIVE\n",
        )
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and exempt in out, out

    def test_a_multiline_assignments_closing_line_second_statement_is_not_exempt(self):
        """A parenthesized multiline DEFAULT_TERMS_RELATIVE value whose
        closing line carries a second statement (`); SECRET = "..."`) must
        report a term hidden in that second statement: only the value's
        own span is exempt, never the whole multiline statement's line
        range (which used to swallow the closing line entirely)."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            '    "ventures",\n'
            "}\n"
            "DEFAULT_TERMS_RELATIVE = (\n"
            '    "harness/tools/deidentify-terms.txt"\n'
            f'); PROBE = "{GENERIC_TERM}"\n',
        )
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and exempt in out, out

    def test_a_trailing_comment_on_the_assignment_line_is_not_exempt(self):
        """A term hidden in a trailing comment on the same physical line as
        a one-line DEFAULT_TERMS_RELATIVE assignment must still be
        reported: only the string value's own column span is exempt, not
        the rest of the line."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            '    "ventures",\n'
            "}\n"
            f'DEFAULT_TERMS_RELATIVE = "harness/tools/deidentify-terms.txt"  # {GENERIC_TERM}\n',
        )
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and exempt in out, out

    def test_a_fake_denied_block_inside_a_multiline_string_is_not_exempt(self):
        """The block exemption is anchored to a real module-level
        DENIED_FIRST_SEGMENTS assignment found by AST, never a regex line
        scan: a fake `DENIED_FIRST_SEGMENTS = { ... }` shape sitting inside
        an unrelated multiline string must not exempt its contents."""
        repo = self.tmp / "r"
        seed = lint.load_terms(lint.ROOT / lint.DEFAULT_TERMS_RELATIVE)
        write(repo / lint.DEFAULT_TERMS_RELATIVE, "\n".join(seed) + "\n")
        exempt = lint.SELF_EXEMPT_FILE
        write(
            repo / exempt,
            "DENIED_FIRST_SEGMENTS = {\n"
            '    "ventures",\n'
            "}\n"
            'DEFAULT_TERMS_RELATIVE = "harness/tools/deidentify-terms.txt"\n'
            "NOTES = \"\"\"\n"
            "DENIED_FIRST_SEGMENTS = {\n"
            f'    "{GENERIC_TERM}",\n'
            "}\n"
            "\"\"\"\n",
        )
        code, out, _ = run([str(repo)])
        assert code == 1 and f"matched term '{GENERIC_TERM}'" in out and exempt in out, out

    def test_the_test_module_is_covered_by_the_term_layer(self):
        """A private term planted at this test module's path is reported like
        any other file: the fixtures here are assembled from fragments, so the
        module needs no exemption, and the release gate's exit 0 covers it."""
        repo = self.tmp / "r"
        test_module = "harness/tools/export_tests/test_deidentify_lint.py"
        assert test_module != lint.SELF_EXEMPT_FILE
        private = self.tmp / "private-terms.txt"
        private.write_text("secretco\n", encoding="utf-8")
        write(repo / test_module, "# fixture mentions secretco by name\n")
        code, out, _ = run([str(repo), "--terms", str(private)])
        assert code == 1 and "matched term 'secretco'" in out and test_module in out, out


class TestD7AbsoluteHostPath(TempDirCase):
    def test_drive_letter_path_backslash_form_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", f"clone at {DRIVE_PATH}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_drive_letter_path_forward_slash_form_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "checkout at " + "C" + ":/" + "Users" + "/name/x\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_posix_home_directory_form_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "see " + "/" + "Users" + "/name/repo\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_bare_drive_root_is_not_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "run from " + "C" + ":\\ then continue\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_tilde_relative_path_is_not_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "config lives at ~/.config/tool/settings\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_generic_placeholder_path_is_not_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "clone into /abs/path/to/your/repo first\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_url_scheme_is_not_mistaken_for_a_drive_letter(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", '"$schema": "https://json-schema.org/draft-07/schema#"\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_python_source_is_never_scanned_for_d7(self):
        repo = self.tmp / "r"
        write(repo / "harness" / "x.py", f'# example: {DRIVE_PATH}\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_json_fixture_under_a_tests_directory_is_not_scanned_for_d7(self):
        repo = self.tmp / "r"
        write(repo / "harness" / "tools" / "tests" / "fixture.json", f'{{"path": "{DRIVE_PATH}"}}\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_non_fixture_json_is_scanned_for_d7(self):
        repo = self.tmp / "r"
        write(repo / "harness" / "registry" / "example.json", f'{{"path": "{DRIVE_PATH}"}}\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 harness/registry/example.json:1" in out, out

    def test_markdown_under_a_tests_directory_is_still_scanned_for_d7(self):
        """The test/fixture-directory exclusion is for a JSON fixture
        specifically, not the whole directory: a .md file under tests/
        still carries D7 coverage."""
        repo = self.tmp / "r"
        write(repo / "harness" / "tools" / "tests" / "notes.md", f"clone at {DRIVE_PATH}\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 harness/tools/tests/notes.md:1" in out, out

    def test_space_inside_a_path_segment_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "install at " + "C" + ":\\Program Files\\Acme\\x\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_one_segment_drive_root_backslash_form_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "clone at " + "D" + ":\\Sources\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_mixed_separators_are_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "see " + "C" + ":\\work/private\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_json_escaped_doubled_backslash_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "harness" / "registry" / "example.json", '{"path": "' + "C" + ':\\\\work\\\\private"}\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 harness/registry/example.json:1" in out, out

    def test_json_escaped_unc_path_is_flagged(self):
        """A UNC path's mandatory leading double-backslash, itself
        JSON-escaped, decodes to four raw backslashes; the UNC scan must
        recover the leading pair rather than losing the UNC shape."""
        repo = self.tmp / "r"
        escaped_unc = chr(92) * 4 + "server" + chr(92) * 2 + "share" + chr(92) * 2 + "private"
        write(repo / "harness" / "registry" / "example.json", '{"path": "' + escaped_unc + '"}\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 harness/registry/example.json:1" in out and "UNC" in out, out

    def test_segment_exact_test_dir_filter_still_scans_a_contest_directory(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "contest" / "x.json", f'{{"path": "{DRIVE_PATH}"}}\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/contest/x.json:1" in out, out

    def test_segment_exact_test_dir_filter_still_scans_a_latest_directory(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "latest" / "x.json", f'{{"path": "{DRIVE_PATH}"}}\n')
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/latest/x.json:1" in out, out

    def test_placeholder_drive_path_is_not_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "adapter root at " + "C" + ":/<repo>/harness\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_placeholder_posix_home_path_is_not_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "clone into " + "/" + "home/<user>/repo\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_every_match_on_a_line_is_inspected_not_only_the_first(self):
        """A placeholder in an earlier match on a line must not hide a real
        path in a later match on the same line."""
        repo = self.tmp / "r"
        write(
            repo / "docs" / "a.md",
            "Use `" + "C" + ":/<repo>/harness` then `" + "D" + ":/Acme/private`.\n",
        )
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_two_unquoted_absolute_paths_on_one_line_do_not_merge_placeholder_first(self):
        """Without a backtick boundary, two absolute paths on the same line
        must not greedily merge into a single match: a placeholder in the
        first must not hide a real path in the second."""
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "See " + "C" + ":/<repo>/x and " + "D" + ":/Acme/private\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_two_unquoted_absolute_paths_on_one_line_do_not_merge_placeholder_second(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "See " + "C" + ":/Acme/private and " + "D" + ":/<repo>/x\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_placeholder_embedded_in_a_larger_segment_does_not_exempt(self):
        """A placeholder must occupy a whole path segment; one appended
        after a real path does not exempt that real path."""
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "Use " + "C" + ":/Acme/private for <input>.\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_unc_path_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "share at " + r"\\server\share\x" + "\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out and "UNC" in out, out

    def test_unc_path_with_placeholder_share_is_not_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "share at " + r"\\server\<share>\x" + "\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_macos_volumes_path_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "mounted at " + "/" + "Vol" + "umes" + "/Acme" + "/data\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out

    def test_file_url_plain_drive_path_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "see file:///" + "C" + ":/Acme/report.md\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out and "file URL" in out, out

    def test_file_url_percent_encoded_drive_path_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "see file:///" + "C%3A%2FAcme%2Freport.md\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out and "file URL" in out, out

    def test_file_url_percent_encoded_unc_path_is_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "see file://server%2Fshare%2Fx\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out and "UNC" in out, out

    def test_https_url_drive_looking_segment_is_not_flagged(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "docs at https://example.com/" + "C" + ":/guide\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_file_url_embedded_in_an_https_query_string_is_not_flagged(self):
        """http(s) URLs are masked before file:// URLs are decoded and
        classified: a file:// value inside an https URL's query string is
        that URL's parameter text, not a real local path."""
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "see https://example.com/?next=file:///" + "C" + ":/guide\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_uppercase_url_scheme_is_masked_like_the_lowercase_form(self):
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "see HTTPS://example.com/" + "C" + ":/guide\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out

    def test_markdown_link_followed_by_a_real_path_is_not_over_masked(self):
        """A Markdown inline link's URL span must stop at its closing
        paren: without that boundary the URL match swallows a real path
        typed immediately after the link, hiding it entirely."""
        repo = self.tmp / "r"
        write(repo / "docs" / "a.md", "[a](https://example.com/y)" + "C" + ":/Acme/private/x\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 1 and "D7 docs/a.md:1" in out, out


class TestAdoptedHostScope(TempDirCase):
    """The default scan set on an adopted host is the template's own files
    (adopted-files.json + the kernel manifest + structure.json), not the
    host's content; --all restores the whole-tree scan."""

    def _adopted_repo(self, name: str) -> Path:
        repo = self.tmp / name
        write(repo / "harness" / "kernel-manifest.json", '{"version": "0.1.0", "files": [{"path": "harness/kernel-manifest.json", "state": "new", "source": null}]}\n')
        write(repo / "harness" / "registry" / "adopted-files.json", '{"template_version": "0.1.0", "paths": ["harness/rules/git-workflow.md"]}\n')
        doc = lint._fallback_structure(repo)
        doc["host"] = {"adopted": True, "roots": [], "harness_owned": []}
        write(repo / "harness" / "registry" / "structure.json", __import__("json").dumps(doc))
        return repo

    def test_default_scope_excludes_host_file_and_includes_template_file(self):
        repo = self._adopted_repo("scope-default")
        write(repo / "harness" / "rules" / "git-workflow.md", f"see {FOREIGN_PATH}\n")  # template-owned: in scope
        write(repo / "docs" / "host-only.md", f"see {FOREIGN_PATH}\n")  # host content: out of scope

        code, out, _ = run([str(repo), "--structural"])
        assert code == 1, out
        assert "harness/rules/git-workflow.md" in out
        assert "docs/host-only.md" not in out

    def test_all_flag_restores_whole_tree_scope(self):
        repo = self._adopted_repo("scope-all")
        write(repo / "harness" / "rules" / "git-workflow.md", f"see {FOREIGN_PATH}\n")
        write(repo / "docs" / "host-only.md", f"see {FOREIGN_PATH}\n")

        code, out, _ = run([str(repo), "--structural", "--all"])
        assert code == 1, out
        assert "harness/rules/git-workflow.md" in out
        assert "docs/host-only.md" in out

    def test_scope_line_prints_the_mode_and_count(self):
        repo = self._adopted_repo("scope-line")
        write(repo / "docs" / "clean.md", "clean\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        assert "deidentify_lint: scope adopted-host (" in out
        code, out, _ = run([str(repo), "--structural", "--all"])
        assert code == 0, out
        assert "deidentify_lint: scope whole tree (" in out

    def test_non_adopted_host_scope_is_unchanged(self):
        repo = self.tmp / "not-adopted"
        write(repo / "docs" / "a.md", "clean\n")
        code, out, _ = run([str(repo), "--structural"])
        assert code == 0, out
        assert "deidentify_lint: scope whole tree (" in out
