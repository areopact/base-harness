"""openpyxl-guard: path extraction parity with the reference regexes, drive-qualified candidates, linear cost."""
from __future__ import annotations

import itertools
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
LIB = ROOT / "harness" / "hooks" / "lib"
sys.path.insert(0, str(LIB))

import openpyxl_guard as og  # noqa: E402

REF_QUOTED_XLSX = r"""['"]([^'"]*\.xlsx)['"]"""
REF_UNQUOTED_XLSX = r"""(?<!['"=])([\w./\\-]+\.xlsx)(?!['"]\w)"""
REF_QUOTED_PY = r"""['"]([^'"]+\.py)['"]"""
REF_UNQUOTED_PY = r"""([\w./\\-]+\.py)\b"""


# Reference implementations: the quadratic originals, kept verbatim as the
# arbiter. Parity is whole-function (quoted part, unquoted part, dedupe, and
# the file cap), so a change to any of them shows up here.
def ref_extract_xlsx_paths(command):
    quoted = re.findall(REF_QUOTED_XLSX, command)
    unquoted = re.findall(REF_UNQUOTED_XLSX, command)
    return quoted + unquoted


def ref_extract_script_paths(command):
    quoted = re.findall(REF_QUOTED_PY, command)
    unquoted = re.findall(REF_UNQUOTED_PY, command)
    seen, out = set(), []
    for p in quoted + unquoted:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:og.SCRIPT_SCAN_MAX_FILES]


def assert_parity(text):
    assert og.extract_xlsx_paths(text) == ref_extract_xlsx_paths(text), f"xlsx mismatch for {text!r}"
    assert og.extract_script_paths(text) == ref_extract_script_paths(text), f"py mismatch for {text!r}"


BACKSLASH = chr(92)

# (input, kind, expected extraction, expected drive-qualified candidates). A backslash is
# spelled "|" here and converted below: no hook file may spell a drive letter, a colon and a
# backslash in a row.
_ROWS = [
    ("python C:|work|x.py", "py", ["|work|x.py"], ["C:|work|x.py"]),
    ("python C:/work/x.py", "py", ["/work/x.py"], ["C:/work/x.py"]),
    ("--out=C:|a.xlsx", "xlsx", ["|a.xlsx"], ["C:|a.xlsx"]),
    ("x=C:/a.xlsx", "xlsx", ["/a.xlsx"], ["C:/a.xlsx"]),
    ('"C:|a.xlsx"', "xlsx", ["C:|a.xlsx", "|a.xlsx"], ["C:|a.xlsx"]),
    ('python "C:/w/x.py"', "py", ["C:/w/x.py", "/w/x.py"], ["C:/w/x.py"]),
    ("http://host/a.xlsx", "xlsx", ["//host/a.xlsx"], []),
    ("abc:/x.py", "py", ["/x.py"], []),
    ("python C:|w|x.py D:|w|x.py", "py", ["|w|x.py"], ["C:|w|x.py", "D:|w|x.py"]),
    ("C:|w|a.xlsx D:|w|a.xlsx", "xlsx", ["|w|a.xlsx", "|w|a.xlsx"], ["C:|w|a.xlsx", "D:|w|a.xlsx"]),
    ("python c:/w/x.py", "py", ["/w/x.py"], ["c:/w/x.py"]),
    ("(C:|w|x.py)", "py", ["|w|x.py"], ["C:|w|x.py"]),
    ("C:x.py", "py", ["x.py"], []),
    ("||?|C:|x.py", "py", ["|x.py"], []),
    ('C:|a.xlsx"b', "xlsx", [], []),
    ('C:|a.xlsx.xlsx"b', "xlsx", ["|a.xlsx"], ["C:|a.xlsx"]),
    ('C:|x.py"b', "py", ["|x.py"], ["C:|x.py"]),
    ("\u00e9:|a.xlsx", "xlsx", ["|a.xlsx"], []),
    ("-oC:/a.xlsx", "xlsx", ["/a.xlsx"], []),
    (":C:/a.xlsx", "xlsx", ["/a.xlsx"], []),
    ("file:///C:/a.xlsx", "xlsx", ["/a.xlsx"], []),
    ("C:/a.xlsx", "xlsx", ["/a.xlsx"], ["C:/a.xlsx"]),
    ("sed 's:/old/a.py:/new/b.py:'", "py", ["/old/a.py", "/new/b.py"], ["s:/old/a.py"]),
]
TABLE = [(text.replace("|", BACKSLASH), kind,
          [p.replace("|", BACKSLASH) for p in extracted],
          [p.replace("|", BACKSLASH) for p in candidates])
         for text, kind, extracted, candidates in _ROWS]


class ParityTests(unittest.TestCase):
    def test_exhaustive_short_token_strings(self):
        tokens = ["a", ".xlsx", ".py", ".", "-", '"', "=", " "]
        for n in range(0, 7):
            for combo in itertools.product(tokens, repeat=n):
                assert_parity("".join(combo))

    def test_seeded_fuzz(self):
        tokens = ["a", ".xlsx", ".py", ".", "-", '"', "=", " ", "'", "/", "\\",
                  "_", "\u00e9", "\u0663", "x", "\n", "(", "xlsx", "py"]
        rng = random.Random(7)
        for _ in range(20000):
            text = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 40)))
            assert_parity(text)

    def test_quirk_cases(self):
        quirks = {
            "=a.xlsx": ([], None),
            "=ab.xlsx": (["b.xlsx"], None),
            ".xlsx": ([], None),
            ".py": (None, []),
            'a.xlsx.xlsx"b': (["a.xlsx"], None),
            "a.py-b.pyc": (None, ["a.py"]),
            ".py.py": (None, [".py.py"]),
        }
        for text, (xlsx, py) in quirks.items():
            assert_parity(text)
            if xlsx is not None:
                assert og.extract_xlsx_paths(text) == xlsx, text
            if py is not None:
                assert og.extract_script_paths(text) == py, text

    def test_long_shapes_match_reference_at_small_size(self):
        for text in shapes(2000):
            assert_parity(text)

    def test_script_cap_and_dedupe(self):
        text = " ".join(f"s{i}.py" for i in range(9)) + " s0.py"
        assert og.extract_script_paths(text) == [f"s{i}.py" for i in range(5)]
        assert_parity(text)


class DriveCandidateTests(unittest.TestCase):
    def test_table_rows(self):
        for text, kind, extracted, candidates in TABLE:
            if kind == "xlsx":
                got, got_candidates = og.extract_xlsx_paths(text), og.xlsx_drive_candidates(text)
                reference = ref_extract_xlsx_paths(text)
            else:
                got, got_candidates = og.extract_script_paths(text), og.script_drive_candidates(text)
                reference = ref_extract_script_paths(text)
            assert got == reference, f"parity {text!r}: {got} != {reference}"
            assert got == extracted, f"extraction {text!r}: {got} != {extracted}"
            assert got_candidates == candidates, f"candidates {text!r}: {got_candidates} != {candidates}"

    def test_candidates_are_uncapped_and_deduped(self):
        text = " ".join(f"C:/s{i}.py" for i in range(9)) + " C:/s0.py"
        assert og.script_drive_candidates(text) == [f"C:/s{i}.py" for i in range(9)]
        assert og.extract_script_paths(text) == [f"/s{i}.py" for i in range(5)]

    def test_seeded_fuzz_invariants(self):
        tokens = ["a", "C", "s", ".xlsx", ".py", ".", "-", '"', "'", "=", " ", ":", "/", "\\", "(", "\u00e9", "x", "\n"]
        rng = random.Random(11)
        for _ in range(20000):
            text = "".join(rng.choice(tokens) for _ in range(rng.randint(0, 30)))
            assert_parity(text)
            unquoted_x = re.findall(REF_UNQUOTED_XLSX, text)
            unquoted_s = re.findall(REF_UNQUOTED_PY, text)
            for candidates, unquoted in ((og.xlsx_drive_candidates(text), unquoted_x),
                                         (og.script_drive_candidates(text), unquoted_s)):
                for cand in candidates:
                    assert cand[0] in og._ASCII_LETTERS and cand[1] == ":" and cand[2] in "/\\", (text, cand)
                    assert cand[2:] in unquoted, (text, cand)
                if ":" not in text:
                    assert candidates == [], (text, candidates)


def shapes(n):
    return [
        "a" * n,
        "a/" * (n // 2),
        "a.pyx" * (n // 5),
        "aaaaaa.xlsx" * (n // 11),
        "=" + "a" * n,
        "a.xlsx " * (n // 7),
        "C:/a.xlsx " * (n // 10),
        "C:/a.py " * (n // 8),
    ]


class TimingTests(unittest.TestCase):
    CEILING = 0.5

    def best_of_three(self, fn, text):
        best = None
        for _ in range(3):
            t0 = time.perf_counter()
            fn(text)
            dt = time.perf_counter() - t0
            best = dt if best is None else min(best, dt)
        return best

    def test_linear_on_long_inputs(self):
        functions = (og.extract_xlsx_paths, og.extract_script_paths,
                     og.xlsx_drive_candidates, og.script_drive_candidates)
        for text in shapes(50000):
            for fn in functions:
                dt = self.best_of_three(fn, text)
                assert dt < self.CEILING, f"{fn.__name__} took {dt:.3f}s on shape {text[:12]!r} len={len(text)}"


SCRIPT_BODY = "import openpyxl\nwb = openpyxl.load_workbook('book.xlsx')\nwb.save('book.xlsx')\n"
ARGV_BODY = "import openpyxl, sys\nwb = openpyxl.load_workbook(sys.argv[1])\nwb.save(sys.argv[1])\n"
READ_ONLY_BODY = "import openpyxl, sys\nwb = openpyxl.load_workbook(sys.argv[1])\n"


class DrivePhaseDecisionTests(unittest.TestCase):
    """Host-independent: the filesystem is replaced, so a drive layout is not required."""

    def run_phase(self, command, existing, bodies=None, flagged=()):
        bodies = bodies or {}

        def fake_resolve(paths, cwd):
            return [p for p in paths if p in existing]

        with mock.patch.object(og, "resolve_existing", fake_resolve), \
                mock.patch.object(og, "read_script", lambda path: bodies.get(path, "")):
            return og.drive_phase_targets(command, "", list(flagged))

    def test_script_with_unquoted_drive_path_is_found(self):
        for sep in ("\\", "/"):
            script = f"C:{sep}work{sep}writer.py"
            existing = {script, "book.xlsx"}
            targets = self.run_phase(f"python {script}", existing, {script: SCRIPT_BODY})
            assert targets and set(targets) == {"book.xlsx"}, (sep, targets)

    def test_inline_save_with_unquoted_drive_workbook_is_found(self):
        for sep in ("\\", "/"):
            workbook = f"C:{sep}work{sep}data.xlsx"
            command = 'python -c "import openpyxl; wb = openpyxl.Workbook(); wb.save(sys.argv[1])" ' + workbook
            assert self.run_phase(command, {workbook}) == [workbook], sep

    def test_non_drive_paths_alone_allow(self):
        stripped = BACKSLASH + "work" + BACKSLASH + "writer.py"
        script = "C:" + stripped
        assert self.run_phase(f"python {script}", {stripped, "book.xlsx"}, {stripped: SCRIPT_BODY}) == []
        workbook = "C:/work/data.xlsx"
        command = 'python -c "import openpyxl; wb.save(sys.argv[1])" ' + workbook
        assert self.run_phase(command, {"/work/data.xlsx"}) == []

    def test_resolve_failure_allows(self):
        command = 'python -c "import openpyxl; wb.save(sys.argv[1])" C:/work/data.xlsx'
        with mock.patch.object(og, "resolve_existing", side_effect=OSError("unreachable drive")):
            assert og.drive_phase_targets(command, "", []) == []

    def test_drive_workbook_alone_allows(self):
        workbook = "C:/work/data.xlsx"
        assert self.run_phase(f"cat {workbook}", {workbook}) == []

    def test_inline_read_only_use_allows(self):
        workbook = "C:/work/data.xlsx"
        command = 'python -c "import openpyxl; openpyxl.load_workbook(sys.argv[1])" ' + workbook
        assert self.run_phase(command, {workbook}) == []

    def test_flagged_script_arms_drive_workbook_on_command_line(self):
        workbook = "C:/work/data.xlsx"
        command = f"python s.py {workbook}"
        assert self.run_phase(command, {workbook}, flagged=[ARGV_BODY]) == [workbook]
        assert self.run_phase(command, {workbook}) == []

    def test_flagged_body_with_drive_workbook_is_found(self):
        workbook = "C:/work/data.xlsx"
        body = ARGV_BODY + f"# target: {workbook}\n"
        assert self.run_phase("python s.py", {workbook}, flagged=[body]) == [workbook]

    def test_script_pool_takes_drive_workbooks_from_command_and_body(self):
        script, workbook = "C:/work/writer.py", "C:/work/data.xlsx"
        existing = {script, workbook}
        assert self.run_phase(f"python {script} {workbook}", existing, {script: ARGV_BODY}) == [workbook]
        body = ARGV_BODY + f"# target: {workbook}\n"
        assert self.run_phase(f"python {script}", existing, {script: body}) == [workbook]

    def test_script_pool_takes_relative_workbook_from_command(self):
        script = "C:/work/writer.py"
        targets = self.run_phase(f"python {script} other.xlsx", {script, "other.xlsx"}, {script: ARGV_BODY})
        assert targets == ["other.xlsx"]

    def test_script_without_write_pattern_allows(self):
        script, workbook = "C:/work/reader.py", "C:/work/data.xlsx"
        assert self.run_phase(f"python {script} {workbook}", {script, workbook}, {script: READ_ONLY_BODY}) == []

    def test_script_cap_applies_after_dropping_first_phase_scripts(self):
        quoted = " ".join(f'"C:/s{i}.py"' for i in range(5))
        script = "C:/work/writer.py"
        targets = self.run_phase(f"python {quoted} {script}", {script, "book.xlsx"}, {script: SCRIPT_BODY})
        assert targets and set(targets) == {"book.xlsx"}, targets

    def test_second_phase_reads_at_most_five_scripts(self):
        scripts = [f"C:/s{i}.py" for i in range(9)]
        reads = []

        def fake_read(path):
            reads.append(path)
            return ""

        with mock.patch.object(og, "resolve_existing", lambda paths, cwd: list(paths)), \
                mock.patch.object(og, "read_script", fake_read):
            assert og.drive_phase_targets("python " + " ".join(scripts), "", []) == []
        assert reads == scripts[:og.SCRIPT_SCAN_MAX_FILES]


class DecideWiringTests(unittest.TestCase):
    """decide() with the filesystem replaced: how the two phases are joined, on every host."""

    def decision(self, command, existing, bodies=None, read=None, phase_two=None):
        bodies = bodies or {}
        data = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": ""}
        patches = [
            mock.patch.object(og, "resolve_existing", lambda paths, cwd: [p for p in paths if p in existing]),
            mock.patch.object(og, "read_script", read or (lambda path: bodies.get(path, ""))),
        ]
        if phase_two is not None:
            patches.append(mock.patch.object(og, "drive_phase_targets", phase_two))
        for patch in patches:
            patch.start()
        try:
            out = og.decide(data)
        finally:
            for patch in reversed(patches):
                patch.stop()
        return "allow" if out is None else json.loads(out)["hookSpecificOutput"]["permissionDecision"]

    def test_phase_one_error_does_not_skip_phase_two(self):
        first, second = "x.py", "C:/work/writer.py"

        def fake_read(path):
            if path == first:
                raise RuntimeError("unreadable")
            return SCRIPT_BODY

        assert self.decision(f"python {first} {second}", {first, second, "book.xlsx"}, read=fake_read) == "deny"

    def test_first_phase_script_arms_drive_workbook_on_command_line(self):
        script, workbook = "C:/work/writer.py", "C:/work/data.xlsx"
        command = f'python "{script}" {workbook}'
        assert self.decision(command, {script, workbook}, {script: ARGV_BODY}) == "deny"

    def test_script_without_the_write_shape_arms_nothing(self):
        script, workbook = "C:/work/reader.py", "C:/work/data.xlsx"
        command = f'python "{script}" {workbook}'
        for body in ("print('hello')\n", READ_ONLY_BODY):
            assert self.decision(command, {script, workbook}, {script: body}) == "allow", body

    def test_first_phase_deny_does_not_wait_for_second_phase(self):
        def unreachable(command, cwd, flagged):
            raise AssertionError("the second phase ran before the first phase decided")

        inline = "python -c 'import openpyxl; wb.save(\"book.xlsx\")'"
        assert self.decision(inline, {"book.xlsx"}, phase_two=unreachable) == "deny"
        assert self.decision("python w.py", {"w.py", "book.xlsx"}, {"w.py": SCRIPT_BODY},
                             phase_two=unreachable) == "deny"


class EndToEndTests(unittest.TestCase):
    GUARD = LIB / "openpyxl_guard.py"

    def run_guard(self, command, cwd, process_cwd=None):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        t0 = time.perf_counter()
        proc = subprocess.run([sys.executable, str(self.GUARD)], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=10, env=env, cwd=process_cwd)
        return proc, time.perf_counter() - t0

    def assert_deny(self, proc):
        assert proc.returncode == 0, proc.stderr
        hook_output = json.loads(proc.stdout)["hookSpecificOutput"]
        assert hook_output["permissionDecision"] == "deny"
        assert hook_output["permissionDecisionReason"].startswith("openpyxl-guard [styled-workbook]: ")

    def test_inline_save_with_160kb_padding_is_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "book.xlsx"
            xlsx.write_bytes(b"PK")
            command = (f"python -c 'import openpyxl; wb=openpyxl.load_workbook(\"{xlsx}\"); "
                       f"wb.save(\"{xlsx}\")' " + "a" * 160000)
            proc, dt = self.run_guard(command, tmp)
            self.assert_deny(proc)
            assert dt < 10, dt

    def test_script_reference_with_160kb_padding_is_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            xlsx = Path(tmp) / "book.xlsx"
            xlsx.write_bytes(b"PK")
            script = Path(tmp) / "writer.py"
            script.write_text(f"import openpyxl\nwb = openpyxl.load_workbook(r'{xlsx}')\n"
                              f"wb.save(r'{xlsx}')\n", encoding="utf-8")
            # A relative name resolves against the payload cwd on every host.
            proc, dt = self.run_guard(f"python {script.name} " + "a" * 160000, tmp)
            self.assert_deny(proc)
            assert dt < 10, dt

    @unittest.skipUnless(os.name == "nt", "drive letters exist only on Windows")
    def test_unquoted_drive_paths_on_another_drive_are_denied(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = os.path.realpath(raw)
            drive, tail = os.path.splitdrive(tmp)
            if not re.fullmatch(r"[A-Za-z]:[\w./\\-]+", tmp):
                self.skipTest("fixture path has characters that end an unquoted path")
            if os.path.splitdrive(str(og.REPO_ROOT))[0].upper() == drive.upper():
                self.skipTest("the repository-root probe already reaches a fixture on its drive")
            others = [f"{letter}:" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      if f"{letter}:".upper() != drive.upper() and os.path.isdir(f"{letter}:\\")]
            if not others:
                self.skipTest("no second drive is mounted")
            other = others[0]
            xlsx = os.path.join(tmp, "book.xlsx")
            script = os.path.join(tmp, "writer.py")
            Path(xlsx).write_bytes(b"PK")
            Path(script).write_text(f"import openpyxl\nwb = openpyxl.load_workbook(r'{xlsx}')\n"
                                    f"wb.save(r'{xlsx}')\n", encoding="utf-8")
            argv_script = os.path.join(tmp, "argv_writer.py")
            Path(argv_script).write_text(ARGV_BODY, encoding="utf-8")
            for name in ("book.xlsx", "writer.py"):
                stripped = other + os.path.join(tail, name)
                assert not os.path.isfile(stripped), stripped
            inline = 'python -c "import openpyxl; wb = openpyxl.Workbook(); wb.save(sys.argv[1])" '
            commands = [
                f"python {script}",
                f"python {script.replace(chr(92), '/')}",
                inline + xlsx,
                inline + xlsx.replace(chr(92), "/"),
                f'python "{argv_script}" {xlsx}',
                f'python "{argv_script}" {xlsx}'.replace(chr(92), "/"),
            ]
            for command in commands:
                proc, _ = self.run_guard(command, other + "\\", process_cwd=other + "\\")
                self.assert_deny(proc)


if __name__ == "__main__":
    unittest.main()
