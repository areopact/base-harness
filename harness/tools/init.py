#!/usr/bin/env python
"""Configure the host shape: lanes, the memory module, or adoption.

Usage:
    python harness/tools/init.py                 print the current host shape
    python harness/tools/init.py --lanes         configure the six lanes (prompted)
    python harness/tools/init.py --brain [--track-local]
                                                 scaffold the reference memory module
    python harness/tools/init.py --adopt <repo> [adopt.py flags]
                                                 delegate to adopt.py

--lanes shows each lane's current value and accepts a comma- or
space-separated list of repository-relative paths, the literal "none" for an
unset lane, or an empty line to keep the current value. Every path is
validated (no leading slash, no drive letter, no backslash, no "." or ".."
segment) and the prompt repeats on a rejected answer. The result is written
to harness/registry/structure.json. Nothing is created on disk: lane folders
are created on first write.

--brain scaffolds brain/ from harness/tools/templates/brain/ plus the identity
shapes: the module README, the shared identity file, the shared knowledge
folder, and the operator file and folder of the local lane (brain.local_path
in structure.json). An existing file is never overwritten.
When structure.json brain.local_tracked is false the local lane is added to
.gitignore. Tracking is enabled only by the explicit --track-local flag; the
tool prints the consequence before writing it.

Exit 0 on success, 1 on an aborted prompt or a refused write, 2 on usage.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = TOOLS_DIR / "templates"

LANE_NAMES = ("identity", "knowledge", "journal", "decisions", "records", "docs")
LANE_HELP = {
    "identity": "who the agent is and who it works with (files)",
    "knowledge": "standing and working beliefs (folders)",
    "journal": "dated personal notes (folders)",
    "decisions": "recorded choices (folders)",
    "records": "what happened: meetings, sessions, research (folders)",
    "docs": "shared project documentation (folders)",
}
TRACK_CONSEQUENCE = (
    "Enabling tracking commits every file under the local lane to this repository's history; "
    "on a repository with a public or shared remote that publishes personal notes to everyone "
    "with read access, and reversing it later requires a history rewrite."
)


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


def _default_structure() -> dict:
    """The shipped defaults contract, read from the template it lives in."""
    return json.loads((TEMPLATES / "structure.default.json").read_text(encoding="utf-8"))


def _fallback_structure(root: Path) -> dict:
    default = _default_structure()
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


def structure_errors(structure: dict) -> list:
    registry = _registry_module()
    if registry is None or not hasattr(registry, "validate_structure"):
        return []
    return list(registry.validate_structure(structure))


def structure_path(root: Path) -> Path:
    return root / "harness" / "registry" / "structure.json"


def write_structure(root: Path, structure: dict) -> None:
    path = structure_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(structure, indent=2) + "\n", encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------
# lanes
# --------------------------------------------------------------------------


def normalize_lane_path(raw: str) -> str:
    """Return the repository-relative POSIX form or raise ValueError."""
    value = raw.strip()
    if not value:
        raise ValueError("empty path")
    if "\\" in value:
        raise ValueError(f"backslash in path {value!r}; use forward slashes")
    if value.startswith("/") or value.startswith("~"):
        raise ValueError(f"absolute or home-relative path {value!r}; lanes are repository-relative")
    if re.match(r"^[A-Za-z]:", value):
        raise ValueError(f"drive letter in path {value!r}; lanes are repository-relative")
    stripped = value.strip("/")
    segments = stripped.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError(f"path {value!r} contains an empty, '.', or '..' segment")
    if posixpath.normpath(stripped) != stripped:
        raise ValueError(f"path {value!r} is not in normal form")
    return stripped


def parse_lane_answer(answer: str, current):
    """Return the new lane value: None for "none", current for an empty line,
    else a validated list. Raises ValueError on a rejected path."""
    text = answer.strip()
    if not text:
        return current
    if text.lower() in ("none", "null", "unset"):
        return None
    paths = []
    for token in re.split(r"[,\s]+", text):
        if not token:
            continue
        normalized = normalize_lane_path(token)
        if normalized not in paths:
            paths.append(normalized)
    if not paths:
        raise ValueError("no path given")
    return paths


def configure_lanes(structure: dict, ask=input, out=None) -> dict:
    """Prompt for each lane and return the new lanes mapping. Raises EOFError
    when the prompt ends early; the caller writes nothing in that case."""
    out = out or sys.stdout
    lanes = dict(structure.get("lanes") or {})
    print("Lanes are repository-relative paths; answer with a list, 'none', or Enter to keep the current value.", file=out)
    for lane in LANE_NAMES:
        current = lanes.get(lane)
        shown = "none" if current is None else ", ".join(current)
        while True:
            answer = ask(f"{lane} ({LANE_HELP[lane]}) [{shown}]: ")
            try:
                lanes[lane] = parse_lane_answer(answer, current)
                break
            except ValueError as exc:
                print(f"  rejected: {exc}", file=out)
    return lanes


def run_lanes(root: Path, ask=input, out=None) -> int:
    out = out or sys.stdout
    try:
        structure = load_structure(root)
    except Exception as exc:  # noqa: BLE001
        print(f"init: structure.json unreadable: {exc}", file=sys.stderr)
        return 1
    try:
        lanes = configure_lanes(structure, ask, out)
    except (EOFError, KeyboardInterrupt):
        print("init: prompt ended early; nothing written", file=sys.stderr)
        return 1
    structure["lanes"] = {lane: lanes.get(lane) for lane in LANE_NAMES}
    errors = structure_errors(structure)
    if errors:
        print("init: refused to write an invalid structure.json:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    write_structure(root, structure)
    print(f"wrote {structure_path(root).relative_to(root).as_posix()}", file=out)
    for lane in LANE_NAMES:
        value = structure["lanes"][lane]
        print(f"  {lane}: {'none' if value is None else ', '.join(value)}", file=out)
    print("no folders were created; lane folders are created on first write", file=out)
    return 0


# --------------------------------------------------------------------------
# brain
# --------------------------------------------------------------------------


def _gitignore_lines(root: Path) -> list:
    path = root / ".gitignore"
    if not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").split("\n")


def _ignore_matches(line: str, local_path: str) -> bool:
    return line.strip().strip("/") == local_path.strip("/")


def ensure_ignored(root: Path, local_path: str, out) -> None:
    lines = _gitignore_lines(root)
    if any(_ignore_matches(line, local_path) for line in lines):
        print(f"  .gitignore already ignores /{local_path}/", file=out)
        return
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    existing += f"/{local_path}/\n"
    path.write_text(existing, encoding="utf-8", newline="\n")
    print(f"  .gitignore: added /{local_path}/", file=out)


def ensure_not_ignored(root: Path, local_path: str, out) -> None:
    lines = _gitignore_lines(root)
    kept = [line for line in lines if not _ignore_matches(line, local_path)]
    if len(kept) == len(lines):
        return
    (root / ".gitignore").write_text("\n".join(kept), encoding="utf-8", newline="\n")
    print(f"  .gitignore: removed /{local_path}/ (local lane is now tracked)", file=out)


def _place(src: Path, dst: Path, out, root: Path) -> None:
    rel = dst.relative_to(root).as_posix()
    if dst.exists():
        print(f"  kept     {rel} (already present, not overwritten)", file=out)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    print(f"  created  {rel}", file=out)


def run_brain(root: Path, track_local: bool, out=None) -> int:
    out = out or sys.stdout
    try:
        structure = load_structure(root)
    except Exception as exc:  # noqa: BLE001
        print(f"init: structure.json unreadable: {exc}", file=sys.stderr)
        return 1
    brain = structure.get("brain") or {}
    local_path = str(brain.get("local_path") or _default_structure()["brain"]["local_path"]).strip("/")
    tracked = bool(brain.get("local_tracked"))
    template_root = TEMPLATES / "brain"
    if not template_root.is_dir():
        print(f"init: template tree missing: {template_root}", file=sys.stderr)
        return 1

    print(f"scaffolding the memory module under {root}", file=out)
    _place(template_root / "README.md", root / "brain" / "README.md", out, root)
    _place(TEMPLATES / "IDENTITY.md", root / "brain" / "shared" / "IDENTITY.md", out, root)
    _place(template_root / "shared" / "knowledge" / ".gitkeep", root / "brain" / "shared" / "knowledge" / ".gitkeep", out, root)
    try:
        local_dir = root / normalize_lane_path(local_path)
    except ValueError as exc:
        print(f"  local lane {local_path} is not repository-relative ({exc}); it is created on first write", file=out)
        local_dir = None
    if local_dir is not None:
        _place(TEMPLATES / "OPERATOR.md", local_dir / "OPERATOR.md", out, root)
        _place(template_root / "local" / ".gitkeep", local_dir / ".gitkeep", out, root)

    if track_local and not tracked:
        print(f"  consequence: {TRACK_CONSEQUENCE}", file=out)
        structure["brain"] = {"local_tracked": True, "local_path": local_path}
        errors = structure_errors(structure)
        if errors:
            print("init: refused to write an invalid structure.json:", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
            return 1
        write_structure(root, structure)
        print("  structure.json: brain.local_tracked = true", file=out)
        if local_dir is not None:
            ensure_not_ignored(root, local_path, out)
        return 0

    if tracked:
        print("  tracking: on (structure.json brain.local_tracked is already true)", file=out)
        if local_dir is not None:
            ensure_not_ignored(root, local_path, out)
        return 0

    if local_dir is not None:
        ensure_ignored(root, local_path, out)
    print(f"  tracking: off. To enable it run: python harness/tools/init.py --brain --track-local", file=out)
    print(f"  consequence of enabling: {TRACK_CONSEQUENCE}", file=out)
    return 0


# --------------------------------------------------------------------------
# status and adoption
# --------------------------------------------------------------------------


def print_shape(root: Path, out=None) -> int:
    out = out or sys.stdout
    try:
        structure = load_structure(root)
    except Exception as exc:  # noqa: BLE001
        print(f"init: structure.json unreadable: {exc}", file=sys.stderr)
        return 1
    path = structure_path(root)
    print(f"host shape ({path.relative_to(root).as_posix()}{'' if path.is_file() else ', defaults; file absent'})", file=out)
    print("lanes:", file=out)
    for lane in LANE_NAMES:
        value = (structure.get("lanes") or {}).get(lane)
        print(f"  {lane:<10} {'none' if value is None else ', '.join(value)}", file=out)
    print(f"git mode:        {(structure.get('git') or {}).get('mode')}", file=out)
    tiers = structure.get("tiers") or {}
    defaults = ", ".join(f"{k}={v}" for k, v in (tiers.get("lane_defaults") or {}).items())
    print(f"tiers:           {defaults}; unlisted paths: {tiers.get('unlisted_path')}", file=out)
    print(f"selection scope: {structure.get('selection_scope')}", file=out)
    brain = structure.get("brain") or {}
    print(f"brain:           local lane {brain.get('local_path')}, tracked {str(bool(brain.get('local_tracked'))).lower()}", file=out)
    print(f"delegation:      mandatory {str(bool((structure.get('delegation') or {}).get('mandatory'))).lower()}", file=out)
    print("change it with:", file=out)
    print("  python harness/tools/init.py --lanes", file=out)
    print("  python harness/tools/init.py --brain [--track-local]", file=out)
    print("  python harness/tools/init.py --adopt <repo> [-y]", file=out)
    return 0


def run_adopt(target: str, extra: list) -> int:
    script = TOOLS_DIR / "adopt.py"
    if not script.is_file():
        print(f"init: adopt.py missing beside this file: {script}", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, str(script), target, *extra], check=False)
    return result.returncode


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print or change the host shape.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--lanes", action="store_true", help="configure the six lanes (prompted)")
    mode.add_argument("--brain", action="store_true", help="scaffold the reference memory module")
    mode.add_argument("--adopt", metavar="REPO", help="install the harness into an existing repository via adopt.py")
    parser.add_argument("--track-local", action="store_true", help="with --brain: track the local lane in git (prints the consequence)")
    parser.add_argument("--root", default=str(ROOT), help="repository root (default: this repository)")
    args, extra = parser.parse_known_args(argv)

    if args.track_local and not args.brain:
        parser.print_usage(sys.stderr)
        print("init: --track-local is only meaningful with --brain", file=sys.stderr)
        return 2
    if extra and not args.adopt:
        parser.print_usage(sys.stderr)
        print(f"init: unrecognized arguments: {' '.join(extra)}", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    if args.adopt:
        return run_adopt(args.adopt, extra)
    if args.lanes:
        return run_lanes(root)
    if args.brain:
        return run_brain(root, args.track_local)
    return print_shape(root)


if __name__ == "__main__":
    sys.exit(main())
