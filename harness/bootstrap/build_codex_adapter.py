#!/usr/bin/env python3
"""Build or exactly check the generated Codex skill catalog (.agents/skills).

One directory per SELECTED, non-stub skill: a compact SKILL.md wrapper that
points Codex at the canonical harness/skills/<name>/SKILL.md, plus the
interface metadata (an openai.yaml file under agents) Codex reads for
implicit invocation.
Every generated directory carries a ``.generated-by`` marker so the prune
step can tell a harness-managed entry from a user's own skill directory.
Zero skills is legal: the catalog then holds only its root marker and stats.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_catalog import (  # noqa: E402
    Skill,
    SkillError,
    display_name,
    selected_skills,
    short_description,
    yaml_string,
)

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = "harness/bootstrap/build_codex_adapter.py"
MARKER = ".generated-by"
MARKER_BYTES = (GENERATOR + "\n").encode("utf-8")
DEFAULT_DESTINATION = Path(".agents/skills")
CATALOG_POLICY = {"implemented": "implicit", "spec-only": "explicit-only", "stub": "omitted"}


def catalog_policy(skill: Skill) -> str:
    return CATALOG_POLICY[skill.status]


def _wrapper(skill: Skill) -> str:
    return f"""---
name: {skill.name}
description: {yaml_string(short_description(skill.description))}
---

# Codex adapter for `{skill.name}`

Read `{skill.relative}/SKILL.md` completely, then follow that canonical
procedure. Translate any `/skill` examples or `$ARGUMENTS` placeholders to the
Codex `${skill.name}` invocation and the user's supplied arguments. This wrapper only
keeps Codex discovery metadata compact.

Invoke explicitly as `${skill.name}`. Canonical status: `{skill.status}`.
"""


def _metadata(skill: Skill, policy: str) -> str:
    implicit = policy == "implicit"
    return f"""interface:
  display_name: {yaml_string(display_name(skill.name))}
  short_description: {yaml_string(short_description(skill.description))}
policy:
  allow_implicit_invocation: {str(implicit).lower()}
"""


def render_catalog(root: Path) -> tuple[dict[str, bytes], list[str]]:
    """Return ({relative path: bytes}, warnings) for the selected skills."""
    skills, selected, warnings = selected_skills(Path(root))
    enabled = [skills[name] for name in selected if catalog_policy(skills[name]) != "omitted"]
    files: dict[str, bytes] = {MARKER: MARKER_BYTES}
    for skill in enabled:
        policy = catalog_policy(skill)
        files[f"{skill.name}/SKILL.md"] = _wrapper(skill).encode("utf-8")
        files[f"{skill.name}/agents/openai.yaml"] = _metadata(skill, policy).encode("utf-8")
        files[f"{skill.name}/{MARKER}"] = MARKER_BYTES
    digest = hashlib.sha256(
        json.dumps(
            {"skills": [skills[name].public_dict() for name in selected], "selected": selected},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    stats = {
        "schema_version": 1,
        "generator": GENERATOR,
        "skills": len(enabled),
        "selected": len(selected),
        "available": len(skills),
        "implemented": sum(skill.status == "implemented" for skill in enabled),
        "spec_only": sum(skill.status == "spec-only" for skill in enabled),
        "implicit": sum(catalog_policy(skill) == "implicit" for skill in enabled),
        "explicit_only": sum(catalog_policy(skill) == "explicit-only" for skill in enabled),
        "source_sha256": digest,
    }
    files[".catalog.json"] = (json.dumps(stats, indent=2) + "\n").encode("utf-8")
    return files, warnings


def is_generated_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and (path / MARKER).is_file()


def diff_catalog(destination: Path, expected: dict[str, bytes]) -> tuple[list[str], list[str]]:
    """Return (drift problems, unmanaged notes). Read-only."""
    destination = Path(destination)
    if not destination.is_dir():
        return [f"{destination.as_posix()}: catalog missing"], []
    problems: list[str] = []
    notes: list[str] = []
    expected_dirs = {relative.split("/", 1)[0] for relative in expected if "/" in relative}
    for relative, content in sorted(expected.items()):
        path = destination / relative
        if not path.is_file():
            problems.append(f"{relative}: missing")
        elif path.read_bytes() != content:
            problems.append(f"{relative}: byte drift")
    for entry in sorted(destination.iterdir()):
        if entry.name in {MARKER, ".catalog.json"}:
            continue
        if entry.name in expected_dirs:
            extra = {
                p.relative_to(destination).as_posix()
                for p in entry.rglob("*")
                if p.is_file()
            } - set(expected)
            problems.extend(f"{relative}: unexpected" for relative in sorted(extra))
            continue
        if is_generated_dir(entry):
            problems.append(f"{entry.name}: stale generated directory (not selected); run bootstrap")
        else:
            notes.append(f"{entry.relative_to(destination).as_posix()}: unmanaged, left in place")
    return problems, notes


def _write_atomic(destination: Path, relative: str, content: bytes) -> None:
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", dir=target.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _remove_managed_entry(entry: Path) -> bool:
    """Remove one harness-managed entry; never a real unmanaged directory."""
    if entry.is_symlink() or _is_junction(entry):
        try:
            os.rmdir(entry)
        except OSError:
            entry.unlink()
        return True
    if is_generated_dir(entry):
        shutil.rmtree(entry)
        return True
    return False


def _is_junction(path: Path) -> bool:
    checker = getattr(os.path, "isjunction", None)
    return bool(checker(path)) if checker else False


def write_catalog(root: Path, destination: Path) -> tuple[dict, list[str]]:
    """Write the catalog for root into destination; return (stats, notes)."""
    files, warnings = render_catalog(root)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    expected_dirs = {relative.split("/", 1)[0] for relative in files if "/" in relative}
    notes = list(warnings)
    for name in sorted(expected_dirs):
        entry = destination / name
        if entry.exists() or entry.is_symlink():
            if not _remove_managed_entry(entry):
                raise RuntimeError(f"refusing to replace unmanaged entry {entry.as_posix()}; move it aside first")
        staging = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=destination))
        try:
            for relative, content in files.items():
                if relative.startswith(name + "/"):
                    _write_atomic(staging, relative.split("/", 1)[1], content)
            os.replace(staging, entry)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    for relative, content in files.items():
        if "/" not in relative:
            _write_atomic(destination, relative, content)
    for entry in sorted(destination.iterdir()):
        if entry.name in expected_dirs or entry.name in {MARKER, ".catalog.json"}:
            continue
        if is_generated_dir(entry) or entry.is_symlink() or _is_junction(entry):
            _remove_managed_entry(entry)
            notes.append(f"pruned {entry.relative_to(destination).as_posix()}")
        else:
            notes.append(f"{entry.relative_to(destination).as_posix()}: unmanaged, left in place")
    return json.loads(files[".catalog.json"]), notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--output", type=Path, help="catalog directory (default .agents/skills)")
    parser.add_argument("--check", action="store_true", help="compare exact bytes and file set; write nothing")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    destination = (args.output or (root / DEFAULT_DESTINATION)).absolute()
    try:
        if args.check:
            files, warnings = render_catalog(root)
            problems, notes = diff_catalog(destination, files)
            for note in warnings + notes:
                print(f"  NOTE {note}")
            if problems:
                print(f"Codex skill catalog: {len(problems)} drift item(s)", file=sys.stderr)
                for problem in problems:
                    print(f"  DRIFT {problem}", file=sys.stderr)
                return 1
            stats = json.loads(files[".catalog.json"])
            print(
                f"Codex skill catalog: exact ({stats['skills']} wrappers; "
                f"{stats['selected']} selected of {stats['available']} available)"
            )
            return 0
        stats, notes = write_catalog(root, destination)
    except (KeyError, json.JSONDecodeError, OSError, RuntimeError, SkillError) as exc:
        print(f"ERROR: Codex skill catalog: {exc}", file=sys.stderr)
        return 1
    for note in notes:
        print(f"  NOTE {note}")
    print(
        f"Codex skill catalog: {stats['skills']} wrappers written to {destination.as_posix()} "
        f"({stats['implicit']} implicit, {stats['explicit_only']} explicit-only; "
        f"{stats['selected']} selected of {stats['available']} available)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
