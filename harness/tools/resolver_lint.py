#!/usr/bin/env python3
"""Structural parser and validator for the generated Markdown skill resolver.

The resolver (harness/skills/RESOLVER.md) is one table with the columns
``Intent phrase | Target skill | Neighbor | Pack | Status``, written by
gen_manifest.py from every skill's ``metadata.triggers``. This module parses
that table without any YAML or catalog coupling and validates each row:

- the target skill exists;
- the neighbor (the skill named in the target's WHEN NOT clause: a routing
  boundary, not a fallback) exists or is the literal ``none``;
- no intent phrase appears twice;
- a trigger that routes to a ``stub`` skill is a warning, never an error;
- a target outside the effective selection (harness/registry/selection.json)
  is a note, never an error: the resolver lists the whole catalog, and the
  note makes a phrase with no materialized handler visible.

Usage:
    python harness/tools/resolver_lint.py [--root <repo>]

Exit 1 on any error, 0 otherwise (warnings are printed and do not fail).
"""

from __future__ import annotations

# A sibling module in this directory shares its name with the standard
# library's select module, and a script's own directory heads sys.path. Keep
# this directory at the tail of sys.path so the stdlib wins for "import select"
# while sibling modules still resolve, and pin the stdlib module before any
# later import (subprocess on POSIX needs it) can be shadowed.
import os as _os
import sys as _sys

_TOOLS_DIR = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:] = [entry for entry in _sys.path if _os.path.abspath(entry or _os.curdir) != _TOOLS_DIR]
_sys.path.append(_TOOLS_DIR)
import selectors as _selectors  # noqa: E402,F401  (imports the stdlib select module)

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = Path("harness/skills/RESOLVER.md")
SKILLS_DIR = Path("harness/skills")
SELECTION = Path("harness/registry/selection.json")


@dataclass(frozen=True)
class Route:
    line: int
    intent: str
    target: str
    target_cell: str
    neighbor: str
    neighbor_cell: str
    pack: str
    status: str


def split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in stripped[1:]:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if current:
        cells.append("".join(current).strip())
    if cells and not cells[-1]:
        cells.pop()
    return cells


def _separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def _skill_target(cell: str) -> str:
    """The skill slug named by a cell; empty when the cell names no skill."""
    if cell.lower().startswith("not this skill"):
        return ""
    match = re.match(r"(?:`|\*\*)?/?([a-z][a-z0-9-]*)(?:`|\*\*)?(?:\s|\(|$)", cell, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _neighbor_target(cell: str) -> str:
    """``none`` for an explicit no-neighbor cell, else the named skill slug."""
    bare = cell.strip().strip("`").strip().lower()
    if bare in {"", "none", "-"}:
        return "none"
    return _skill_target(cell)


def _is_header(cells: list[str]) -> bool:
    if len(cells) < 2:
        return False
    first, second = cells[0].lower(), cells[1].lower()
    return (first.startswith("intent") or first.startswith("trigger")) and (
        "skill" in second or second.startswith("target")
    )


def normalize_intent(intent: str) -> str:
    """Case-insensitive, quote-insensitive key used for duplicate detection."""
    value = intent.strip().strip("`").strip().strip("\"'").strip()
    return " ".join(value.lower().split())


def parse_routes(text: str) -> list[Route]:
    routes: list[Route] = []
    in_table = False
    for line_number, line in enumerate(text.splitlines(), 1):
        cells = split_markdown_row(line)
        if not cells:
            in_table = False
            continue
        if _separator(cells):
            continue
        if _is_header(cells):
            in_table = True
            continue
        if not in_table or len(cells) < 2:
            continue
        neighbor_cell = cells[2] if len(cells) > 2 else "none"
        routes.append(Route(
            line=line_number,
            intent=cells[0],
            target=_skill_target(cells[1]),
            target_cell=cells[1],
            neighbor=_neighbor_target(neighbor_cell),
            neighbor_cell=neighbor_cell,
            pack=cells[3] if len(cells) > 3 else "",
            status=cells[4] if len(cells) > 4 else "",
        ))
    return routes


def validate_resolver(text: str, skills: dict[str, object]) -> tuple[list[str], list[str]]:
    """Validate resolver rows against a name -> skill map (any object with .status)."""
    errors: list[str] = []
    warns: list[str] = []
    statuses = {name: str(getattr(skill, "status", "") or "") for name, skill in skills.items()}
    seen: dict[str, int] = {}
    for route in parse_routes(text):
        if not route.target:
            if route.intent.lower().startswith("note:") or route.target_cell.lower().startswith("not this skill"):
                continue
            errors.append(f"resolver line {route.line}: cannot parse skill target from '{route.target_cell}'")
            continue
        if route.target not in skills:
            errors.append(f"resolver line {route.line}: unknown skill target '{route.target}'")
        elif statuses[route.target] == "stub":
            warns.append(f"resolver line {route.line}: trigger routes to stub skill '{route.target}'")
        if route.neighbor != "none":
            if not route.neighbor:
                errors.append(f"resolver line {route.line}: cannot parse neighbor from '{route.neighbor_cell}'")
            elif route.neighbor not in skills:
                errors.append(f"resolver line {route.line}: unknown neighbor skill '{route.neighbor}'")
            elif route.neighbor == route.target:
                errors.append(f"resolver line {route.line}: neighbor names the target itself")
            elif statuses[route.neighbor] == "stub":
                warns.append(f"resolver line {route.line}: neighbor is the stub skill '{route.neighbor}'")
        key = normalize_intent(route.intent)
        if not key:
            errors.append(f"resolver line {route.line}: empty intent phrase")
        elif key in seen:
            errors.append(
                f"resolver line {route.line}: duplicate intent phrase {route.intent!r} (first at line {seen[key]})"
            )
        else:
            seen[key] = route.line
    return errors, warns


def effective_selection(root: Path, skills: dict[str, object]) -> set[str] | None:
    """Skill names in the effective selection (packs union include, minus
    exclude, mirroring the bootstrap contract), or None when the repository
    carries no readable selection file."""
    path = Path(root) / SELECTION
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    packs = set(doc.get("packs") or [])
    chosen = {name for name, skill in skills.items() if packs.intersection(getattr(skill, "packs", None) or [])}
    chosen.update(name for name in (doc.get("include") or []) if name in skills)
    chosen.difference_update(doc.get("exclude") or [])
    return chosen


def selection_notes(text: str, skills: dict[str, object], selected: set[str] | None) -> list[str]:
    """One note per target outside the effective selection: the phrases that
    route to it have no materialized handler until its pack is selected. The
    neighbor is reported for context only; it is a routing boundary, not a
    substitute."""
    if selected is None:
        return []
    outside: dict[str, list] = {}
    for route in parse_routes(text):
        if route.target and route.target in skills and route.target not in selected:
            entry = outside.setdefault(route.target, [0, route.neighbor])
            entry[0] += 1
    notes: list[str] = []
    for target, (count, neighbor) in sorted(outside.items()):
        if neighbor == "none":
            tail = "no neighbor"
        elif neighbor in selected:
            tail = f"neighbor '{neighbor}' is selected"
        else:
            tail = f"neighbor '{neighbor}' is also outside the selection"
        notes.append(
            f"{count} row(s) target '{target}', which is outside the effective selection ({tail}); "
            "select its pack or expect no handler for those phrases"
        )
    return notes


def notes(root: Path = ROOT) -> list[str]:
    """Selection notes for the repository resolver; empty when it or the
    selection file is absent or unreadable (lint() reports those cases)."""
    root = Path(root)
    path = root / RESOLVER
    if not path.is_file() or not (root / SKILLS_DIR).is_dir():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    skills = load_catalog(root)
    return selection_notes(text, skills, effective_selection(root, skills))


def load_catalog(root: Path) -> dict[str, object]:
    """Name -> skill for every catalog entry, read through gen_manifest."""
    import gen_manifest  # sibling module, resolved through the tail entry above

    return {skill.name: skill for skill in gen_manifest.scan_skills(Path(root))}


def lint(root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Parse and validate the repository resolver. Returns (errors, warnings)."""
    root = Path(root)
    path = root / RESOLVER
    if not path.is_file():
        if not (root / SKILLS_DIR).is_dir():
            return [f"{SKILLS_DIR.as_posix()} is absent; nothing to resolve"], []
        return [f"{RESOLVER.as_posix()} is missing; run: python harness/tools/gen_manifest.py"], []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [f"cannot read {RESOLVER.as_posix()}: {exc}"], []
    return validate_resolver(text, load_catalog(root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the generated skill resolver.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    args = parser.parse_args(argv)
    errors, warns = lint(args.root.resolve())
    for item in (notes(args.root.resolve()) if not errors else []):
        print(f"NOTE   {item}")
    for item in warns:
        print(f"WARN   {item}")
    for item in errors:
        print(f"ERROR  {item}")
    if not errors:
        print(f"OK     resolver: {len(warns)} warning(s), 0 error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
