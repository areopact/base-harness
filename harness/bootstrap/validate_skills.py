#!/usr/bin/env python3
"""Validate canonical skill frontmatter and, on request, the exact Codex catalog.

Reads every ``harness/skills/<name>/SKILL.md`` (and vendored
``_vendor/<source>/<name>/SKILL.md``) through the shared frontmatter reader,
which enforces: ``name`` matches the directory, ``description`` is present
and carries ``WHEN:``, ``metadata.status`` is one of the closed values,
``metadata.distribution`` and ``metadata.license`` are valid, and every pack
slug is kebab-case. With ``--catalog <dir>`` (or when ``.agents/skills``
exists) the generated Codex catalog must match the render byte for byte.
Zero skills is legal and reports ``0 checked``.
"""

from __future__ import annotations

import argparse
import json
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


def validate_source(root: Path) -> tuple[int, list[str]]:
    """Return (skills checked, error lines) for the canonical skill tree."""
    errors: list[str] = []
    try:
        skills = read_skills(root / "harness" / "skills")
    except SkillError as exc:
        return 0, [line for line in str(exc).splitlines() if line.strip()]
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
        if skill.distribution == "runtime-provided" and not [entry for entry in skill.requires if not entry.startswith("lane:")]:
            errors.append(f"{rel}: runtime-provided skills must name a capability id in metadata.requires")
        if skill.distribution == "vendored" and not skill.notice and skill.license != "MIT":
            errors.append(f"{rel}: vendored skills carry metadata.notice unless the license needs none")
    try:
        _, warnings = select_skills(skills, load_selection(root))
    except (SkillError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"selection.json: {exc}")
    else:
        errors.extend(f"selection.json: {warning}" for warning in warnings)
    return len(skills), errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-codex-catalog", action="store_true", help="fail when the catalog is missing or drifted")
    parser.add_argument("--catalog", type=Path, help="catalog path to validate instead of .agents/skills")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    checked, errors = validate_source(root)
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
        return 1
    note = "; exact Codex catalog OK" if catalog_requested else ""
    print(f"Skill frontmatter: {checked} checked, 0 error(s){note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
