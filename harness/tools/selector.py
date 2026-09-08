#!/usr/bin/env python
"""Skill selection: edit selection.json and re-run materialization.

Usage:
    python harness/tools/selector.py --pack X [--pack Y] [--skill Z] [--without W]
                                   [--scope repo|user] [--dry-run] [--no-materialize]
    python harness/tools/selector.py            (interactive on a terminal)
    python harness/tools/selector.py --list     (show packs, skills, and the effective set)

Effective set = union(skills whose metadata.packs intersects packs, include)
minus exclude. The file written is harness/registry/selection.json for the
repository scope or harness/registry/selection.local.json for the user scope;
the default scope comes from structure.json selection_scope.

After a write the tool re-invokes bootstrap's materialization (bootstrap.sh on
POSIX, bootstrap.ps1 on Windows) and reports its prune lines, unless
--no-materialize is given. --dry-run prints the diff and writes nothing.

A selection naming a skill that does not exist is refused (exit 1, valid slugs
listed). A pack no shipped skill declares is a warning, not a refusal, so the
selection can be prepared before the skills land.

Skill discovery mirrors the bootstrap catalog: harness/skills/<name>/SKILL.md,
skipping directories whose name starts with "_" or ".".
"""

from __future__ import annotations

import os
import sys

# This file shares its name with the standard library's select module. When
# it runs as a script its own directory heads sys.path, so a later
# "import select" (subprocess needs the real one on POSIX) would find this
# file instead. Drop that entry before importing anything that may need it.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [entry for entry in sys.path if os.path.abspath(entry or os.curdir) != _HERE]

import argparse  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]

SELECTION_DEFAULT = {"schema_version": 1, "packs": ["core", "maintain"], "include": [], "exclude": []}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# --------------------------------------------------------------------------
# host facts
# --------------------------------------------------------------------------


def _registry_module():
    """Load harness_registry from its file without touching sys.path."""
    path = TOOLS_DIR / "harness_registry.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("harness_registry", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a broken registry module means "absent"
        return None
    return module


def _fallback_structure(root: Path) -> dict:
    """Same defaults contract as harness_registry.load_structure, used only
    when that module is absent."""
    default_path = TOOLS_DIR / "templates" / "structure.default.json"
    default = json.loads(default_path.read_text(encoding="utf-8"))
    host_path = root / "harness" / "registry" / "structure.json"
    if not host_path.is_file():
        return default
    host = json.loads(host_path.read_text(encoding="utf-8"))
    if not isinstance(host, dict):
        raise ValueError("structure.json is not an object")
    merged = dict(default)
    for key, value in host.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            inner = dict(merged[key])
            inner.update(value)
            merged[key] = inner
        else:
            merged[key] = value
    return merged


def load_structure(root: Path) -> dict:
    registry = _registry_module()
    if registry is None:
        return _fallback_structure(root)
    return registry.load_structure(root)


# --------------------------------------------------------------------------
# skill discovery (frontmatter subset: scalars, inline lists, dash lists, nested blocks)
# --------------------------------------------------------------------------


def _parse_scalar(raw: str):
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip("\"'") for item in inner.split(",")]
    if value in ("null", "~", ""):
        return None
    return value.strip("\"'")


KEY_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:(.*)$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _skip_blank(lines: list, index: int) -> int:
    while index < len(lines) and (not lines[index].strip() or lines[index].strip().startswith("#")):
        index += 1
    return index


def _parse_block(lines: list, start: int, indent: int):
    """Parse a mapping or a dash list at one indent level. Returns (value, next index)."""
    result = None
    i = start
    while i < len(lines):
        i = _skip_blank(lines, i)
        if i >= len(lines):
            break
        line = lines[i]
        current = _indent(line)
        if current < indent:
            break
        if current > indent:
            i += 1
            continue
        stripped = line.strip()
        if stripped.startswith("- ") or stripped == "-":
            if result is None:
                result = []
            if not isinstance(result, list):
                break
            result.append(_parse_scalar(stripped[1:]))
            i += 1
            continue
        match = KEY_RE.match(stripped)
        if not match:
            i += 1
            continue
        if result is None:
            result = {}
        if not isinstance(result, dict):
            break
        key, raw = match.group(1), match.group(2).strip()
        if raw in ("", ">", "|", ">-", "|-"):
            j = _skip_blank(lines, i + 1)
            if j < len(lines):
                child_indent = _indent(lines[j])
                child_is_list = lines[j].strip().startswith("- ")
                if child_indent > indent or (child_indent == indent and child_is_list):
                    if raw in (">", "|", ">-", "|-"):
                        texts = []
                        k = j
                        while k < len(lines) and (not lines[k].strip() or _indent(lines[k]) > indent):
                            texts.append(lines[k].strip())
                            k += 1
                        result[key] = " ".join(t for t in texts if t)
                        i = k
                        continue
                    value, i = _parse_block(lines, j, child_indent)
                    result[key] = value
                    continue
            result[key] = None if raw == "" else ""
            i += 1
            continue
        result[key] = _parse_scalar(raw)
        i += 1
    return (result if result is not None else {}), i


def parse_frontmatter(text: str) -> dict:
    """Frontmatter subset: scalars, inline lists, dash lists, nested blocks, and
    folded scalars. Enough for name, description, and the metadata block."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    body = []
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        body.append(line.rstrip("\r"))
    value, _ = _parse_block(body, 0, 0)
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v is not None]
    if isinstance(value, dict):
        return []
    return [str(value)]


def discover_skills(root: Path) -> dict:
    """name -> {"packs": [...], "status": str, "path": Path}."""
    skills = {}
    base = root / "harness" / "skills"
    if not base.is_dir():
        return skills
    for skill_md in sorted(base.glob("*/SKILL.md")):
        if skill_md.parent.name.startswith(("_", ".")):
            continue
        try:
            fm = parse_frontmatter(skill_md.read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            continue
        name = fm.get("name") or skill_md.parent.name
        meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
        skills[str(name)] = {
            "packs": _as_list(meta.get("packs")),
            "status": str(meta.get("status") or "unknown"),
            "path": skill_md,
        }
    return skills


def effective_set(selection: dict, skills: dict) -> list:
    packs = set(selection.get("packs") or [])
    chosen = {name for name, info in skills.items() if packs.intersection(info["packs"])}
    chosen.update(selection.get("include") or [])
    chosen.difference_update(selection.get("exclude") or [])
    return sorted(chosen)


# --------------------------------------------------------------------------
# selection file
# --------------------------------------------------------------------------


def selection_path(root: Path, scope: str) -> Path:
    name = "selection.local.json" if scope == "user" else "selection.json"
    return root / "harness" / "registry" / name


def load_selection(path: Path) -> dict:
    if not path.is_file():
        return dict(SELECTION_DEFAULT)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(SELECTION_DEFAULT)
    if not isinstance(data, dict):
        return dict(SELECTION_DEFAULT)
    out = dict(SELECTION_DEFAULT)
    for key in ("packs", "include", "exclude"):
        if isinstance(data.get(key), list):
            out[key] = [str(v) for v in data[key]]
    return out


def write_selection(path: Path, selection: dict) -> None:
    ordered = {
        "schema_version": 1,
        "packs": list(selection["packs"]),
        "include": list(selection["include"]),
        "exclude": list(selection["exclude"]),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------
# materialization
# --------------------------------------------------------------------------


def materialize(root: Path) -> int:
    bootstrap_dir = root / "harness" / "bootstrap"
    if os.name == "nt":
        script = bootstrap_dir / "bootstrap.ps1"
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    else:
        script = bootstrap_dir / "bootstrap.sh"
        command = ["bash", str(script)]
    if not script.is_file():
        print(f"materialize: bootstrap entry not found ({script.relative_to(root).as_posix()}); run bootstrap by hand")
        return 0
    try:
        result = subprocess.run(command, cwd=str(root), capture_output=True, text=True, check=False)
    except OSError as exc:
        print(f"materialize: could not start bootstrap: {exc}")
        return 1
    output = (result.stdout or "") + (result.stderr or "")
    prune_lines = [line for line in output.splitlines() if "prune" in line.lower()]
    print(f"materialize: bootstrap exit {result.returncode}; {len(prune_lines)} prune line(s)")
    for line in prune_lines:
        print(f"  {line}")
    if result.returncode != 0:
        tail = output.strip().splitlines()[-5:]
        for line in tail:
            print(f"  {line}")
    return result.returncode


# --------------------------------------------------------------------------
# presentation
# --------------------------------------------------------------------------


def print_catalog(skills: dict, selection: dict) -> None:
    packs = sorted({p for info in skills.values() for p in info["packs"]})
    chosen = set(effective_set(selection, skills))
    print("packs:")
    for index, pack in enumerate(packs, start=1):
        members = sorted(n for n, i in skills.items() if pack in i["packs"])
        marker = "*" if pack in (selection.get("packs") or []) else " "
        print(f"  {index:>2}. [{marker}] {pack}: {', '.join(members) or '(no skills yet)'}")
    if not packs:
        print("  (no skills declare a pack yet)")
    print("skills:")
    for index, name in enumerate(sorted(skills), start=1):
        info = skills[name]
        marker = "*" if name in chosen else " "
        print(f"  {index:>2}. [{marker}] {name} ({info['status']}; packs: {', '.join(info['packs']) or 'none'})")
    if not skills:
        print("  (no skills found under harness/skills)")


def print_diff(old: dict, new: dict, skills: dict) -> None:
    print("selection diff:")
    for key in ("packs", "include", "exclude"):
        before, after = list(old.get(key) or []), list(new.get(key) or [])
        flag = " " if before == after else "*"
        print(f"  {flag} {key}: {before} -> {after}")
    old_set, new_set = set(effective_set(old, skills)), set(effective_set(new, skills))
    added, removed = sorted(new_set - old_set), sorted(old_set - new_set)
    print(f"  effective skills: {len(old_set)} -> {len(new_set)}")
    for name in added:
        print(f"    + {name}")
    for name in removed:
        print(f"    - {name}")
    if not added and not removed:
        print("    (no change in the effective set)")


# --------------------------------------------------------------------------
# interactive
# --------------------------------------------------------------------------


def _pick(raw: str, options: list) -> list:
    chosen = []
    for token in re.split(r"[,\s]+", raw.strip()):
        if not token:
            continue
        if token.isdigit():
            index = int(token) - 1
            if 0 <= index < len(options):
                chosen.append(options[index])
            else:
                raise ValueError(f"no item numbered {token}")
        else:
            chosen.append(token)
    return chosen


def interactive(skills: dict, current: dict, ask=input) -> dict:
    """Numbered prose prompt. `ask` is input-compatible so tests can script it."""
    print_catalog(skills, current)
    packs = sorted({p for info in skills.values() for p in info["packs"]})
    names = sorted(skills)
    new = {"packs": list(current["packs"]), "include": list(current["include"]), "exclude": list(current["exclude"])}
    answer = ask("Packs to select (numbers or slugs; Enter keeps current): ")
    if answer.strip():
        new["packs"] = _pick(answer, packs)
    answer = ask("Extra skills to include (numbers or slugs; Enter for none): ")
    new["include"] = _pick(answer, names) if answer.strip() else []
    answer = ask("Skills to exclude (numbers or slugs; Enter for none): ")
    new["exclude"] = _pick(answer, names) if answer.strip() else []
    print("resulting selection:", json.dumps(new))
    print("effective skills:", ", ".join(effective_set(new, skills)) or "(none)")
    confirm = ask("Write this selection? [y/N]: ")
    if confirm.strip().lower() not in ("y", "yes"):
        raise SystemExit("select: aborted, nothing written")
    return new


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Edit skill selection and re-run materialization.")
    parser.add_argument("--pack", action="append", default=[], help="pack to select (repeatable; replaces the current packs)")
    parser.add_argument("--skill", action="append", default=[], help="skill to include explicitly (repeatable)")
    parser.add_argument("--without", action="append", default=[], help="skill to exclude (repeatable)")
    parser.add_argument("--scope", choices=("repo", "user"), default=None, help="selection file scope (default: structure.json selection_scope)")
    parser.add_argument("--dry-run", action="store_true", help="print the diff and write nothing")
    parser.add_argument("--no-materialize", action="store_true", help="do not re-run bootstrap after writing")
    parser.add_argument("--list", action="store_true", help="print packs, skills, and the effective set")
    parser.add_argument("--root", default=str(ROOT), help="repository root (default: this repository)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    try:
        structure = load_structure(root)
    except Exception as exc:  # noqa: BLE001
        print(f"select: structure.json unreadable: {exc}", file=sys.stderr)
        return 2
    scope = args.scope or structure.get("selection_scope") or "repo"
    if scope not in ("repo", "user"):
        scope = "repo"
    path = selection_path(root, scope)
    skills = discover_skills(root)
    current = load_selection(path)

    if args.list:
        print(f"selection file: {path.relative_to(root).as_posix()} (scope {scope})")
        print_catalog(skills, current)
        print("effective skills:", ", ".join(effective_set(current, skills)) or "(none)")
        return 0

    flags_given = bool(args.pack or args.skill or args.without)
    if not flags_given:
        if sys.stdin.isatty() and sys.stdout.isatty():
            try:
                new = interactive(skills, current)
            except (ValueError, EOFError, KeyboardInterrupt) as exc:
                print(f"select: {exc or 'aborted'}", file=sys.stderr)
                return 1
        else:
            print(f"selection file: {path.relative_to(root).as_posix()} (scope {scope})")
            print("current selection:", json.dumps(current))
            print("effective skills:", ", ".join(effective_set(current, skills)) or "(none)")
            print("pass --pack, --skill, or --without to change it, or run on a terminal for the interactive prompt")
            return 0
    else:
        new = {"packs": list(current["packs"]), "include": list(current["include"]), "exclude": list(current["exclude"])}
        if args.pack:
            new["packs"] = list(dict.fromkeys(args.pack))
        for name in args.skill:
            if name not in new["include"]:
                new["include"].append(name)
            if name in new["exclude"]:
                new["exclude"].remove(name)
        for name in args.without:
            if name not in new["exclude"]:
                new["exclude"].append(name)
            if name in new["include"]:
                new["include"].remove(name)

    bad_slugs = [s for s in new["packs"] + new["include"] + new["exclude"] if not SLUG_RE.match(s)]
    if bad_slugs:
        print(f"select: refused: not kebab-case slugs: {', '.join(bad_slugs)}", file=sys.stderr)
        return 1
    unknown = sorted(set(new["include"] + new["exclude"]) - set(skills))
    if unknown:
        print(f"select: refused: unknown skill(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"select: valid skills: {', '.join(sorted(skills)) or '(none found under harness/skills)'}", file=sys.stderr)
        return 1
    known_packs = {p for info in skills.values() for p in info["packs"]}
    for pack in new["packs"]:
        if pack not in known_packs:
            print(f"select: warning: no skill declares pack '{pack}' yet")

    print(f"selection file: {path.relative_to(root).as_posix()} (scope {scope})")
    print_diff(current, new, skills)
    if args.dry_run:
        print("dry run: nothing written, nothing materialized")
        return 0
    write_selection(path, new)
    print(f"wrote {path.relative_to(root).as_posix()}")
    if scope == "user":
        gitignore = root / ".gitignore"
        try:
            ignored = "selection.local.json" in gitignore.read_text(encoding="utf-8", errors="replace")
        except OSError:
            ignored = False
        if not ignored:
            print("note: add harness/registry/selection.local.json to .gitignore; the user scope is local by design")
    if args.no_materialize:
        print("materialization skipped (--no-materialize)")
        return 0
    return 1 if materialize(root) != 0 else 0


if __name__ == "__main__":
    sys.exit(main())
