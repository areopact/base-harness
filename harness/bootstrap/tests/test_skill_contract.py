"""The v0.2 skill contract: form, dependencies, evals shape, advisory sections.

Every fixture is written into a throwaway repository under tmp_path. The v0.1
fixtures prove the change is additive: a skill with none of the new keys must
pass the v0.2 validator with no error and no warning.
"""

from __future__ import annotations

import io
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import BOOTSTRAP, REAL_ROOT, bind_unittest, build_repo, write_selection, write_skill

sys.path.insert(0, str(BOOTSTRAP))
import validate_skills  # noqa: E402

TEMPLATES = REAL_ROOT / "harness" / "tools" / "templates" / "skills"
HASH = "a" * 64

PROCEDURE_BODY = (
    "# demo\n\n## Steps\n\n1. Read the input.\n2. Write the result.\n\n"
    "## Done when\n\nThe result file exists.\n"
)
CRITERIA_BODY = "# demo\n\n## Floors\n\n- Two sources.\n\n## Ceilings\n\n- No more than one page.\n"
REFERENCE_BODY = "# demo\n\n## Facts\n\n| Item | Truth |\n|---|---|\n| A | B |\n"

TRIGGERS = (
    "prompt\texpect\tcompetitor\n"
    "Please do the demo thing for me.\tselect\t\n"
    "Do the neighbor thing instead.\tskip\tbeta\n"
)
CASES = (
    "# Outcome cases\n\n## Case 1: demo\n\n**Input:** run the demo skill on the fixture.\n\n"
    "**Acceptance checks:**\n\n1. The result file exists.\n\n"
    "**Without the skill:** the run produces no result file.\n"
)
LEDGER_HEADER = (
    "date\tharness\tharness_version\tmodel\tdescription_rev\ttriggers_rev\tpackage_rev\t"
    "cases_rev\ttrigger_result\toutcome_result\tnotes\n"
)
LEDGER_ROW = (
    f"2026-10-05\tclaude-code\t2.0.0\tmodel-x\t{HASH}\t{HASH}\t{HASH}\t{HASH}\tpass\tpass\t\"first run\"\n"
)


def write_contract_skill(root: Path, name: str, metadata_lines: list[str], body: str, description: str | None = None) -> Path:
    directory = root / "harness" / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    description = description or f"Fixture skill {name}. WHEN: the user asks for {name}. WHEN NOT: anything else."
    meta = "".join(f"  {line}\n" for line in metadata_lines)
    text = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "metadata:\n"
        "  packs: [core]\n"
        "  triggers:\n"
        f'    - "{name} please"\n'
        "  distribution: native\n"
        "  status: spec-only\n"
        "  license: MIT\n"
        "  notice: null\n"
        f"{meta}"
        "---\n\n"
        f"{body}"
    )
    (directory / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")
    return directory


def write_evals(directory: Path, triggers: str | None = TRIGGERS, cases: str | None = CASES, ledger: str | None = LEDGER_HEADER) -> Path:
    evals = directory / "evals"
    evals.mkdir(exist_ok=True)
    for name, content in (("triggers.tsv", triggers), ("cases.md", cases), ("ledger.tsv", ledger)):
        if content is not None:
            (evals / name).write_text(content, encoding="utf-8", newline="")
    return evals


def empty_repo(tmp_path: Path) -> Path:
    root = build_repo(tmp_path, skills=(), with_git=False)
    write_selection(root, ["core"])
    return root


def run(root: Path) -> tuple[int, list[str], list[str]]:
    return validate_skills.collect(root)


# ---- v0.1 stays valid --------------------------------------------------

def test_v01_skill_passes_unchanged_with_no_error_and_no_warning(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    checked, errors, warnings = run(root)
    assert checked == 3 and errors == [] and warnings == []


def test_this_repository_skills_pass_with_no_error_and_no_warning():
    checked, errors, warnings = run(REAL_ROOT)
    assert checked > 0
    assert errors == [] and warnings == []


def test_validate_source_keeps_its_two_value_contract(tmp_path):
    root = build_repo(tmp_path, with_git=False)
    assert validate_skills.validate_source(root) == (3, [])


def test_v01_requirements_still_apply_when_form_is_declared(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "demo", ["form: procedure"], PROCEDURE_BODY, description="No trigger clause here.")
    _, errors, _ = run(root)
    assert any("must contain 'WHEN:'" in e for e in errors)


# ---- form --------------------------------------------------------------

def test_each_form_fixture_passes_cleanly(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "proc", ["form: procedure"], PROCEDURE_BODY)
    write_contract_skill(root, "crit", ["form: criteria"], CRITERIA_BODY)
    write_contract_skill(root, "refe", ["form: reference"], REFERENCE_BODY)
    checked, errors, warnings = run(root)
    assert checked == 3 and errors == [] and warnings == []


def test_invalid_form_value_fails(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "demo", ["form: playbook"], PROCEDURE_BODY)
    _, errors, _ = run(root)
    assert any("metadata.form 'playbook'" in e for e in errors)


def test_form_is_case_sensitive(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "demo", ["form: Procedure"], PROCEDURE_BODY)
    _, errors, _ = run(root)
    assert any("metadata.form" in e for e in errors)


# ---- dependencies ------------------------------------------------------

def test_dependencies_accept_the_closed_vocabulary_and_empty_list(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "full", ["dependencies: [code, system, agents]"], "# full\n")
    write_contract_skill(root, "none", ["dependencies: []"], "# none\n")
    _, errors, _ = run(root)
    assert errors == []


def test_dash_list_dependencies_are_accepted(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "demo", ["dependencies:", "  - code"], "# demo\n")
    # the nested dash list sits at the metadata indent plus two
    _, errors, _ = run(root)
    assert errors == []


def test_unknown_dependency_value_fails(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "demo", ["dependencies: [code, network]"], "# demo\n")
    _, errors, _ = run(root)
    assert any("entry 'network'" in e for e in errors)


def test_scalar_dependencies_value_fails(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "demo", ["dependencies: code"], "# demo\n")
    _, errors, _ = run(root)
    assert any("must be a list" in e for e in errors)


# ---- advisory section checks -------------------------------------------

def test_section_gaps_warn_and_never_fail(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "proc", ["form: procedure"], "# proc\n\nJust prose.\n")
    write_contract_skill(root, "crit", ["form: criteria"], "# crit\n\n## Floors\n\n- one\n")
    write_contract_skill(root, "refe", ["form: reference"], "# refe\n\n1. Do this.\n2. Do that.\n")
    checked, errors, warnings = run(root)
    assert checked == 3 and errors == []
    text = "\n".join(warnings)
    assert "no ordered steps" in text and "'## Done when'" in text
    assert "'## Ceilings'" in text and "'## Floors'" not in text
    assert "reference skill carries ordered steps" in text
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = validate_skills.main(["--root", str(root)])
    assert code == 0
    assert "WARN:" in stream.getvalue() and "4 warning(s)" in stream.getvalue()


def test_numbered_headings_count_as_ordered_steps(tmp_path):
    root = empty_repo(tmp_path)
    body = "# demo\n\n### 1. Read\n\nRead it.\n\n### 2) Write\n\nWrite it.\n\n## Done when\n\nDone.\n"
    write_contract_skill(root, "demo", ["form: procedure"], body)
    _, errors, warnings = run(root)
    assert errors == [] and warnings == []


def test_list_inside_a_fence_is_not_a_step(tmp_path):
    root = empty_repo(tmp_path)
    body = "# demo\n\n```text\n1. not a step\n2. not a step\n```\n\n~~~\n1. also not\n~~~\n\n## Done when\n\nDone.\n"
    write_contract_skill(root, "demo", ["form: procedure"], body)
    _, _, warnings = run(root)
    assert len(warnings) == 1 and "no ordered steps" in warnings[0]


def test_reference_with_only_fenced_steps_is_clean(tmp_path):
    root = empty_repo(tmp_path)
    body = "# demo\n\n```sh\n1. example output line\n```\n"
    write_contract_skill(root, "demo", ["form: reference"], body)
    _, _, warnings = run(root)
    assert warnings == []


def test_longer_fence_is_not_closed_by_a_shorter_one(tmp_path):
    root = empty_repo(tmp_path)
    body = "# demo\n\n````md\n```\n1. inner\n```\n````\n"
    write_contract_skill(root, "demo", ["form: reference"], body)
    _, _, warnings = run(root)
    assert warnings == []


def test_headings_match_by_prefix_and_case(tmp_path):
    root = empty_repo(tmp_path)
    body = "# demo\n\n1. Do it.\n\n## Done When (observable)\n\nDone.\n"
    write_contract_skill(root, "demo", ["form: procedure"], body)
    write_contract_skill(root, "crit", ["form: criteria"], "# crit\n\n## Floors (what good looks like)\n\n- a\n\n## Ceilings and limits\n\n- b\n")
    _, errors, warnings = run(root)
    assert errors == [] and warnings == []


def test_no_form_means_no_section_checks(tmp_path):
    root = empty_repo(tmp_path)
    write_contract_skill(root, "demo", [], "# demo\n\nNothing structured.\n")
    _, errors, warnings = run(root)
    assert errors == [] and warnings == []


# ---- evals -------------------------------------------------------------

def test_valid_evals_trio_passes_and_missing_evals_is_fine(tmp_path):
    root = empty_repo(tmp_path)
    with_evals = write_contract_skill(root, "withe", ["form: procedure"], PROCEDURE_BODY)
    write_evals(with_evals, ledger=LEDGER_HEADER + LEDGER_ROW)
    write_contract_skill(root, "nonee", ["form: procedure"], PROCEDURE_BODY)
    _, errors, warnings = run(root)
    assert errors == [] and warnings == []


def test_header_only_evals_trio_passes(tmp_path):
    root = empty_repo(tmp_path)
    directory = write_contract_skill(root, "demo", [], "# demo\n")
    write_evals(directory, triggers="prompt\texpect\tcompetitor\n")
    _, errors, _ = run(root)
    assert errors == []


def test_crlf_evals_files_pass(tmp_path):
    root = empty_repo(tmp_path)
    directory = write_contract_skill(root, "demo", [], "# demo\n")
    write_evals(
        directory,
        triggers=TRIGGERS.replace("\n", "\r\n"),
        cases=CASES.replace("\n", "\r\n"),
        ledger=(LEDGER_HEADER + LEDGER_ROW).replace("\n", "\r\n"),
    )
    _, errors, _ = run(root)
    assert errors == []


def test_missing_eval_file_is_an_error_when_the_folder_exists(tmp_path):
    root = empty_repo(tmp_path)
    directory = write_contract_skill(root, "demo", [], "# demo\n")
    write_evals(directory, cases=None)
    _, errors, _ = run(root)
    assert errors == ["harness/skills/demo/evals/cases.md: missing; an evals/ folder carries triggers.tsv, cases.md, and ledger.tsv"]


def test_trigger_header_expect_and_field_count_are_checked(tmp_path):
    root = empty_repo(tmp_path)
    one = write_contract_skill(root, "one", [], "# one\n")
    write_evals(one, triggers="prompt\tverdict\tcompetitor\n")
    two = write_contract_skill(root, "two", [], "# two\n")
    write_evals(two, triggers="prompt\texpect\tcompetitor\nDo it.\tmaybe\t\n")
    three = write_contract_skill(root, "three", [], "# three\n")
    write_evals(three, triggers="prompt\texpect\tcompetitor\nDo it.\tselect\n")
    four = write_contract_skill(root, "four", [], "# four\n")
    write_evals(four, triggers="prompt\texpect\tcompetitor\n\tselect\t\n")
    _, errors, _ = run(root)
    text = "\n".join(errors)
    assert "harness/skills/one/evals/triggers.tsv: header must be exactly prompt | expect | competitor" in text
    assert "harness/skills/two/evals/triggers.tsv: row 2 expect must be select or skip" in text
    assert "harness/skills/three/evals/triggers.tsv: row 2 does not have exactly 3 fields" in text
    assert "harness/skills/four/evals/triggers.tsv: row 2 has an empty prompt" in text


def test_cases_need_input_acceptance_and_a_without_skill_note(tmp_path):
    root = empty_repo(tmp_path)
    directory = write_contract_skill(root, "demo", [], "# demo\n")
    write_evals(directory, cases="# Cases\n\nOnly an input line.\n")
    _, errors, _ = run(root)
    assert len(errors) == 1
    assert "acceptance checks, without-skill note" in errors[0] and "input" not in errors[0].split("missing")[1]


def test_ledger_header_results_dates_and_revisions_are_checked(tmp_path):
    root = empty_repo(tmp_path)
    bad_header = write_contract_skill(root, "hdr", [], "# hdr\n")
    write_evals(bad_header, ledger=LEDGER_HEADER.replace("notes", "note"))
    bad_row = write_contract_skill(root, "row", [], "# row\n")
    write_evals(
        bad_row,
        ledger=LEDGER_HEADER + "10/05/2026\th\t1\tm\tnot-a-hash\t\t\t\tpassed\tpass\tn\n",
    )
    short = write_contract_skill(root, "short", [], "# short\n")
    write_evals(short, ledger=LEDGER_HEADER + "2026-10-05\th\t1\n")
    _, errors, _ = run(root)
    text = "\n".join(errors)
    assert "harness/skills/hdr/evals/ledger.tsv: header must be exactly date | harness" in text
    assert "row 2 date must be YYYY-MM-DD" in text
    assert "row 2 description_rev must be empty or a SHA-256 hex digest" in text
    assert "row 2 trigger_result must be pass, fail, or unknown" in text
    assert "harness/skills/short/evals/ledger.tsv: row 2 does not have exactly 11 fields" in text


def test_ledger_allows_an_empty_cases_revision(tmp_path):
    root = empty_repo(tmp_path)
    directory = write_contract_skill(root, "demo", [], "# demo\n")
    row = f"2026-10-05\th\t1\tm\t{HASH}\t{HASH}\t{HASH}\t\tpass\tunknown\tn\n"
    write_evals(directory, ledger=LEDGER_HEADER + row)
    _, errors, _ = run(root)
    assert errors == []


def test_eval_errors_fail_the_command(tmp_path):
    root = empty_repo(tmp_path)
    directory = write_contract_skill(root, "demo", [], "# demo\n")
    write_evals(directory, ledger=None)
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = validate_skills.main(["--root", str(root)])
    assert code == 1 and "ledger.tsv: missing" in stream.getvalue()


# ---- shipped skeletons -------------------------------------------------

def install_template(tmp_path: Path, form: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = empty_repo(tmp_path)
    target = root / "harness" / "skills" / f"demo-{form}"
    shutil.copytree(TEMPLATES / form, target)
    skill_md = target / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8").replace("name: new-skill\n", f"name: demo-{form}\n", 1),
        encoding="utf-8",
        newline="\n",
    )
    return root


def test_shipped_skeletons_validate_with_no_error_and_no_warning(tmp_path):
    for form in ("procedure", "criteria", "reference"):
        root = install_template(tmp_path / form, form)
        checked, errors, warnings = run(root)
        assert checked == 1, form
        assert errors == [] and warnings == [], (form, errors, warnings)


def test_shipped_skeletons_declare_their_own_form_and_carry_the_evals_trio():
    for form in ("procedure", "criteria", "reference"):
        text = (TEMPLATES / form / "SKILL.md").read_text(encoding="utf-8")
        assert f"  form: {form}\n" in text
        assert "  status: spec-only\n" in text
        for name in ("triggers.tsv", "cases.md", "ledger.tsv"):
            assert (TEMPLATES / form / "evals" / name).is_file(), (form, name)
        assert b"\r" not in (TEMPLATES / form / "SKILL.md").read_bytes()


def test_skeleton_with_the_wrong_form_warns(tmp_path):
    root = install_template(tmp_path, "reference")
    skill_md = root / "harness" / "skills" / "demo-reference" / "SKILL.md"
    skill_md.write_text(skill_md.read_text(encoding="utf-8").replace("form: reference", "form: procedure"), encoding="utf-8", newline="\n")
    _, errors, warnings = run(root)
    assert errors == [] and any("'## Done when'" in w for w in warnings)


bind_unittest(globals(), "SkillContractBridge")
