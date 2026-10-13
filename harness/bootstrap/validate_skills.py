#!/usr/bin/env python3
"""Validate canonical skill frontmatter and, on request, the exact Codex catalog.

Reads every ``harness/skills/<name>/SKILL.md`` (and vendored
``_vendor/<source>/<name>/SKILL.md``) through the shared frontmatter reader,
which enforces: ``name`` matches the directory, ``description`` is present
and carries ``WHEN:``, ``metadata.status`` is one of the closed values,
``metadata.distribution`` and ``metadata.license`` are valid, and every pack
slug is kebab-case.

The v0.2 contract adds three optional parts, all additive. ``metadata.form``
(``procedure``, ``criteria``, ``reference``) and ``metadata.dependencies`` (a
list drawn from ``code``, ``system``, ``agents``) are checked against their
closed vocabularies. When a skill has an ``evals/`` folder, its three files
(``triggers.tsv``, ``cases.md``, ``ledger.tsv``) are shape-checked; a skill
without ``evals/`` is simply ``spec-only``. The sections a declared form
expects are advisory: they print as WARN lines and never change the exit
status. A v0.1 skill passes unchanged.

With ``--catalog <dir>`` (or when ``.agents/skills`` exists) the generated
Codex catalog must match the render byte for byte. Zero skills is legal and
reports ``0 checked``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_codex_adapter  # noqa: E402
from skill_catalog import (  # noqa: E402
    SLUG,
    VALID_LICENSES,
    SkillError,
    load_selection,
    read_skills,
    select_skills,
)

ROOT = Path(__file__).resolve().parents[2]

VALID_FORMS = ("procedure", "criteria", "reference")
VALID_DEPENDENCIES = ("code", "system", "agents")
TRIGGER_COLUMNS = ("prompt", "expect", "competitor")
LEDGER_COLUMNS = (
    "date", "harness", "harness_version", "model",
    "description_rev", "triggers_rev", "package_rev", "cases_rev",
    "trigger_result", "outcome_result", "notes",
)
REVISION_COLUMNS = ("description_rev", "triggers_rev", "package_rev", "cases_rev")
VALID_RESULTS = ("pass", "fail", "unknown")
# A numbered list item, or a numbered heading such as "### 1. Check".
ORDERED_STEP_RE = re.compile(r"^(?:[ \t]*|#{2,6}[ \t]+)\d+[.)][ \t]+\S")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


def split_body(text: str) -> str:
    """Return the Markdown after the closing frontmatter delimiter line."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1:])
    return ""


def prose_lines(body: str) -> list[str]:
    """Body lines outside fenced code blocks."""
    kept: list[str] = []
    fence = ""
    for line in body.splitlines():
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and line.strip() == marker:
                fence = ""
            continue
        if not fence:
            kept.append(line)
    return kept


def has_heading(lines: list[str], prefix: str) -> bool:
    """True when a level-2 heading starts with prefix, ignoring case."""
    pattern = re.compile(r"^##[ \t]+" + re.escape(prefix), re.IGNORECASE)
    return any(pattern.match(line) for line in lines)


def contract_metadata_errors(rel: str, metadata: dict) -> list[str]:
    errors: list[str] = []
    if "form" in metadata and metadata["form"] not in VALID_FORMS:
        errors.append(f"{rel}: metadata.form {metadata['form']!r} is not one of {', '.join(VALID_FORMS)}")
    if "dependencies" in metadata:
        deps = metadata["dependencies"]
        if not isinstance(deps, list) or not all(isinstance(item, str) for item in deps):
            errors.append(f"{rel}: metadata.dependencies must be a list drawn from {', '.join(VALID_DEPENDENCIES)}")
        else:
            for item in deps:
                if item not in VALID_DEPENDENCIES:
                    errors.append(f"{rel}: metadata.dependencies entry {item!r} is not one of {', '.join(VALID_DEPENDENCIES)}")
    return errors


def form_section_warnings(rel: str, form: object, body: str) -> list[str]:
    """Advisory section checks for a declared form. Never errors."""
    lines = prose_lines(body)
    has_steps = any(ORDERED_STEP_RE.match(line) for line in lines)
    warnings: list[str] = []
    if form == "procedure":
        if not has_steps:
            warnings.append(f"{rel}: [form] procedure skill has no ordered steps; use a numbered list or numbered headings outside fenced code")
        if not has_heading(lines, "Done when"):
            warnings.append(f"{rel}: [form] procedure skill has no '## Done when' section; state the observable end condition")
    elif form == "criteria":
        for heading in ("Floors", "Ceilings"):
            if not has_heading(lines, heading):
                warnings.append(f"{rel}: [form] criteria skill has no '## {heading}' section; add it or declare another form")
    elif form == "reference" and has_steps:
        warnings.append(f"{rel}: [form] reference skill carries ordered steps; declare procedure, or move the steps out")
    return warnings


def read_tsv(path: Path, columns: tuple[str, ...]) -> tuple[list[dict[str, str]], list[str]]:
    """Read a tab-separated file with an exact header; return (rows, problems)."""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t", strict=True)
            if reader.fieldnames != list(columns):
                return [], [f"header must be exactly {' | '.join(columns)}"]
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        return [], [f"cannot parse TSV ({exc})"]
    problems = [
        f"row {number} does not have exactly {len(columns)} fields"
        for number, row in enumerate(rows, 2)
        if None in row or any(row.get(column) is None for column in columns)
    ]
    return rows, problems


def eval_errors(rel_dir: str, evals: Path) -> list[str]:
    """Shape checks for a skill's evals/ trio. Absent evals are not checked."""
    errors: list[str] = []

    def add(name: str, problem: str) -> None:
        errors.append(f"{rel_dir}/evals/{name}: {problem}")

    triggers = evals / "triggers.tsv"
    if not triggers.is_file():
        add("triggers.tsv", "missing; an evals/ folder carries triggers.tsv, cases.md, and ledger.tsv")
    else:
        rows, problems = read_tsv(triggers, TRIGGER_COLUMNS)
        for problem in problems:
            add("triggers.tsv", problem)
        if not problems:
            for number, row in enumerate(rows, 2):
                if not row["prompt"].strip():
                    add("triggers.tsv", f"row {number} has an empty prompt")
                if row["expect"] not in ("select", "skip"):
                    add("triggers.tsv", f"row {number} expect must be select or skip")

    cases = evals / "cases.md"
    if not cases.is_file():
        add("cases.md", "missing; an evals/ folder carries triggers.tsv, cases.md, and ledger.tsv")
    else:
        try:
            text = cases.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            add("cases.md", f"cannot read ({exc})")
        else:
            missing = [
                label
                for label, pattern in (
                    ("input", r"\binput\b"),
                    ("acceptance checks", r"\baccept(?:ance)?\b"),
                    ("without-skill note", r"\bwithout\b[^\n]{0,40}\bskill\b"),
                )
                if not re.search(pattern, text, re.IGNORECASE)
            ]
            if missing:
                add("cases.md", "outcome case is missing " + ", ".join(missing))

    ledger = evals / "ledger.tsv"
    if not ledger.is_file():
        add("ledger.tsv", "missing; an evals/ folder carries triggers.tsv, cases.md, and ledger.tsv")
    else:
        rows, problems = read_tsv(ledger, LEDGER_COLUMNS)
        for problem in problems:
            add("ledger.tsv", problem)
        if not problems:
            for number, row in enumerate(rows, 2):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]):
                    add("ledger.tsv", f"row {number} date must be YYYY-MM-DD")
                for column in REVISION_COLUMNS:
                    if row[column] and not re.fullmatch(r"[0-9a-f]{64}", row[column]):
                        add("ledger.tsv", f"row {number} {column} must be empty or a SHA-256 hex digest")
                for column in ("trigger_result", "outcome_result"):
                    if row[column] not in VALID_RESULTS:
                        add("ledger.tsv", f"row {number} {column} must be pass, fail, or unknown")
    return errors


def validate_contract(root: Path, skills: dict) -> tuple[list[str], list[str]]:
    """The v0.2 additions: (errors, warnings). Every check is a no-op on a v0.1 skill."""
    errors: list[str] = []
    warnings: list[str] = []
    for _, skill in sorted(skills.items()):
        rel = f"{skill.relative}/SKILL.md"
        metadata = skill.raw.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        errors.extend(contract_metadata_errors(rel, metadata))
        form = metadata.get("form")
        if form in VALID_FORMS:
            try:
                text = (root / skill.relative / "SKILL.md").read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                text = ""
            warnings.extend(form_section_warnings(rel, form, split_body(text)))
        evals = root / skill.relative / "evals"
        if evals.is_dir():
            errors.extend(eval_errors(skill.relative, evals))
    return errors, warnings


def collect(root: Path) -> tuple[int, list[str], list[str]]:
    """Return (skills checked, error lines, warning lines) for the canonical skill tree."""
    errors: list[str] = []
    try:
        skills = read_skills(root / "harness" / "skills")
    except SkillError as exc:
        return 0, [line for line in str(exc).splitlines() if line.strip()], []
    for name, skill in sorted(skills.items()):
        rel = f"{skill.relative}/SKILL.md"
        if "WHEN:" not in skill.description:
            errors.append(f"{rel}: description must contain 'WHEN:'")
        for pack in skill.packs:
            if not SLUG.fullmatch(pack):
                errors.append(f"{rel}: pack slug {pack!r} is not kebab-case")
        if not skill.packs:
            errors.append(f"{rel}: metadata.packs is empty (a skill belongs to at least one pack)")
        if skill.license not in VALID_LICENSES:
            errors.append(f"{rel}: metadata.license {skill.license!r} is not one of {', '.join(VALID_LICENSES)}")
        if skill.distribution == "runtime-provided" and not [
            entry for entry in skill.requires if not (entry.startswith("lane:") or entry.startswith("fact:"))
        ]:
            errors.append(f"{rel}: runtime-provided skills must name a capability id in metadata.requires")
        if skill.distribution == "vendored" and not skill.notice and skill.license != "MIT":
            errors.append(f"{rel}: vendored skills carry metadata.notice unless the license needs none")
    try:
        _, selection_warnings = select_skills(skills, load_selection(root))
    except (SkillError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"selection.json: {exc}")
    else:
        errors.extend(f"selection.json: {warning}" for warning in selection_warnings)
    contract_errors, contract_warnings = validate_contract(root, skills)
    errors.extend(contract_errors)
    return len(skills), errors, contract_warnings


def validate_source(root: Path) -> tuple[int, list[str]]:
    """Return (skills checked, error lines) for the canonical skill tree."""
    checked, errors, _ = collect(root)
    return checked, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-codex-catalog", action="store_true", help="fail when the catalog is missing or drifted")
    parser.add_argument("--catalog", type=Path, help="catalog path to validate instead of .agents/skills")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    checked, errors, warnings = collect(root)
    catalog = (args.catalog.absolute() if args.catalog else root / ".agents" / "skills")
    catalog_requested = args.require_codex_catalog or args.catalog is not None or catalog.exists()
    if catalog_requested and not errors:
        try:
            expected, _ = build_codex_adapter.render_catalog(root)
        except (OSError, SkillError, json.JSONDecodeError) as exc:
            errors.append(f"catalog render failed: {exc}")
        else:
            problems, _ = build_codex_adapter.diff_catalog(catalog, expected)
            errors.extend(f"{catalog.as_posix()}: {problem}" for problem in problems)
    if errors:
        print(f"Skill frontmatter/catalog: {checked} checked, {len(errors)} error(s)")
        for error in errors:
            print(f"  ERROR: {error}")
        for warning in warnings:
            print(f"  WARN: {warning}")
        return 1
    note = "; exact Codex catalog OK" if catalog_requested else ""
    print(f"Skill frontmatter: {checked} checked, 0 error(s), {len(warnings)} warning(s){note}")
    for warning in warnings:
        print(f"  WARN: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
