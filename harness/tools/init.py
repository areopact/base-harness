#!/usr/bin/env python
"""Configure the host shape: lanes, the memory module, adoption, or the profile.

Usage:
    python harness/tools/init.py                 print the current host shape
    python harness/tools/init.py --lanes         configure the five lanes (prompted)
    python harness/tools/init.py --brain [--track-local]
                                                 scaffold the reference memory module
    python harness/tools/init.py --adopt <repo> [adopt.py flags]
                                                 delegate to adopt.py
    python harness/tools/init.py --profile [solo|team] [--yes]
                                                 configure host.profile, git.mode,
                                                 the local memory lane, and (optionally)
                                                 the five lanes, in one interview

--profile asks four questions in order: who works in the repository
(host.profile), how work lands (git.mode), where personal notes live
(brain.local_path; brain.local_tracked always stays false here), and whether
to configure the five lanes now (chains into the unchanged --lanes prompt) or
keep the profile's lane preset, which follows where the personal notes live,
not the chosen profile. A value ("solo" or "team") answers the first question
up front; --yes answers every question with that profile's defaults and asks
nothing, unless git.mode, brain.local_path, or the lanes already differ from
the shipped defaults, in which case --yes changes host.profile only and keeps
the rest exactly as configured. Bare `--profile` with no value runs the
interview against any tty or non-empty piped stdin; it exits 2 naming the
`--profile <value> --yes` form only when stdin is closed or empty.
contract.mode is asked of no one: it keeps an already-declared value, and is
derived by the same test adopt.py uses (root AGENTS.md present and not
written by the harness itself means host-owned, otherwise rendered) only when
absent. A retired `journal` key still present in lanes or tiers.lane_defaults
is removed and reported, not refused. Nothing is materialized: the run prints
the next two commands (harness/tools/selector.py --list, then bootstrap).

--lanes shows each lane's current value and accepts a comma- or
space-separated list of repository-relative paths, the literal "none" for an
unset lane, or an empty line to keep the current value. Every path is
validated (no leading slash, no drive letter, no backslash, no "." or ".."
segment) and the prompt repeats on a rejected answer. The result is written
to harness/registry/structure.json. Nothing is created on disk: lane folders
are created on first write.

--brain scaffolds brain/ from harness/tools/templates/brain/ plus the identity
shapes: the module README, the shared and local lane guides, the shared
identity file, the shared knowledge folder, and the operator file and folder
of the local lane (brain.local_path in structure.json). Every brain/ path
listed in harness/kernel-manifest.json is placed. An existing file is never
overwritten.
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

LANE_NAMES = ("identity", "knowledge", "decisions", "records", "docs")
LANE_HELP = {
    "identity": "who the agent is and who it works with (files)",
    "knowledge": "standing and working beliefs (folders)",
    "decisions": "recorded choices (folders)",
    "records": "what happened: meetings, sessions, research (folders)",
    "docs": "shared project documentation (folders)",
}
TRACK_CONSEQUENCE = (
    "Enabling tracking commits every file under the local lane to this repository's history; "
    "on a repository with a public or shared remote that publishes personal notes to everyone "
    "with read access, and reversing it later requires a history rewrite."
)

HOST_PROFILES = ("solo", "team")
PROFILE_GIT_MODE = {"solo": "main-only", "team": "branches"}
# The shared-only root every team lane entry must keep; anything else in the
# shipped identity/knowledge lists is the local half, which team drops (Q3's
# team default moves personal notes outside the repository).
TEAM_LANE_SHARED_ROOT = ("brain", "shared")


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


def _adopt_module():
    """Load adopt.py from its file without touching sys.path, so its own
    derive_host_name and EXTERNAL_LOCAL_TEMPLATE are reused, never copied."""
    path = TOOLS_DIR / "adopt.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("adopt", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a broken adopt module means "absent"
        return None
    return module


def _contract_files_module():
    """Load harness/bootstrap/contract_files.py without touching sys.path."""
    path = ROOT / "harness" / "bootstrap" / "contract_files.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("contract_files", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a broken contract module means "absent"
        return None
    return module


def derive_contract_mode(root: Path) -> str:
    """The same test adopt.py's own contract-mode detection applies,
    generalized for a host that already has a materialized AGENTS.md:
    rendered when no root AGENTS.md exists that the harness did not write
    (absent, or byte-identical to the harness's own render of
    harness/CONTRACT.md + harness/CONTRACT.host.md); host-owned otherwise."""
    agents = root / "AGENTS.md"
    if not agents.is_file():
        return "rendered"
    contract = _contract_files_module()
    if contract is not None:
        try:
            expected = contract.render(root)
            actual = agents.read_bytes()
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        else:
            if actual == expected:
                return "rendered"
    return "host-owned"


def _external_local_path(root: Path) -> tuple:
    """(path, name-source) for the external local lane; delegates to
    adopt.py's derive_host_name and EXTERNAL_LOCAL_TEMPLATE by import."""
    adopt = _adopt_module()
    if adopt is None:
        return "~/.harness-local/host", "adopt.py unavailable; falling back to 'host'"
    name, source = adopt.derive_host_name(root)
    return adopt.EXTERNAL_LOCAL_TEMPLATE.format(name=name), source


def _lanes_untouched(current: dict, shipped: dict) -> bool:
    """True when every non-null current lane is byte-equal (order-sensitive)
    to the shipped default for that lane. A host where every lane is null
    also counts as untouched. Any lane that differs from the shipped default
    and is not null means the whole set is host-configured."""
    for name in LANE_NAMES:
        value = (current or {}).get(name)
        if value is None:
            continue
        if value != shipped.get(name):
            return False
    return True


def _structure_untouched(structure: dict, shipped: dict) -> bool:
    """True when lanes, git.mode, and brain.local_path all still match the
    shipped defaults (a missing git.mode or local_path counts as matching).
    Any one of the three differing marks the whole structure as
    host-configured: --yes and question 4's 'no' answer must then leave all
    three alone rather than silently overwriting some of them."""
    if not _lanes_untouched(structure.get("lanes") or {}, shipped["lanes"]):
        return False
    git_mode = (structure.get("git") or {}).get("mode")
    if git_mode is not None and git_mode != shipped["git"]["mode"]:
        return False
    local_path = (structure.get("brain") or {}).get("local_path")
    if local_path is not None and local_path != shipped["brain"]["local_path"]:
        return False
    return True


def _is_external_local_path(local_path: str) -> bool:
    """True when a personal-notes path is not repository-relative (outside
    the repository), the same test the .gitignore step already applies."""
    try:
        normalize_lane_path(local_path)
    except ValueError:
        return True
    return False


def _lane_preset_for_local_path(local_path: str) -> dict:
    """The lane preset for one personal-notes location, not one profile: the
    shipped defaults verbatim when the local path is inside the repository;
    the same defaults with each identity/knowledge entry outside
    TEAM_LANE_SHARED_ROOT dropped when it is external (decisions, records,
    and docs are the shipped defaults verbatim either way). An external local
    path (question 3's second answer, or the team default) means the local
    halves of identity/knowledge point at files no consumer can reach."""
    shipped = _default_structure()["lanes"]
    preset = {name: (list(shipped[name]) if isinstance(shipped.get(name), list) else shipped.get(name)) for name in LANE_NAMES}
    if not _is_external_local_path(local_path):
        return preset
    for name in ("identity", "knowledge"):
        value = preset.get(name) or []
        kept = [item for item in value if tuple(item.split("/")[: len(TEAM_LANE_SHARED_ROOT)]) == TEAM_LANE_SHARED_ROOT]
        preset[name] = kept or None
    return preset


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


def _load_raw_structure(root: Path) -> dict:
    """The on-disk structure.json object, verbatim, or {} when the file is
    absent. Every write path merges only the keys it changed into this
    object; writing back the fully-merged read view (load_structure's
    return) would materialize every shipped default the host never asked
    for, which the ship-gate lint is supposed to keep reporting as absent
    until an operator repairs it on purpose."""
    path = structure_path(root)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("structure.json is not an object")
    return raw


def _merged_structure(raw: dict) -> dict:
    """The same default-merge load_structure applies on read, computed
    in-memory over a raw object that has not (yet) been written to disk.
    Raises ValueError on an unknown top-level key or a schema violation."""
    registry = _registry_module()
    if registry is None:
        default = _default_structure()
        merged = dict(default)
        for key, value in raw.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                inner = dict(merged[key])
                inner.update(value)
                merged[key] = inner
            else:
                merged[key] = value
        return merged
    default = registry.DEFAULT_STRUCTURE
    unknown = sorted(set(raw) - set(default))
    if unknown:
        raise ValueError(f"structure.json: unknown top-level keys: {', '.join(unknown)}")
    merged = registry._merge_defaults(default, raw)
    errors = registry.validate_structure(merged)
    if errors:
        raise ValueError("; ".join(errors))
    return merged


def _strip_retired_journal(raw: dict) -> tuple:
    """Return (raw-without-journal, removed). A host that pulled a
    pre-profile kernel may still carry the retired 'journal' key in lanes,
    tiers.lane_defaults, or both; --profile repairs it and reports the
    repair instead of refusing, since a fresh --profile run is exactly the
    moment a stale host needs to shed it. Every other init path keeps
    refusing on it, per the registry's own unknown-lane message."""
    removed = False
    raw = dict(raw)
    lanes = raw.get("lanes")
    if isinstance(lanes, dict) and "journal" in lanes:
        lanes = dict(lanes)
        del lanes["journal"]
        raw["lanes"] = lanes
        removed = True
    tiers = raw.get("tiers")
    if isinstance(tiers, dict):
        lane_defaults = tiers.get("lane_defaults")
        if isinstance(lane_defaults, dict) and "journal" in lane_defaults:
            lane_defaults = dict(lane_defaults)
            del lane_defaults["journal"]
            tiers = dict(tiers)
            tiers["lane_defaults"] = lane_defaults
            raw["tiers"] = tiers
            removed = True
    return raw, removed


def structure_errors(structure: dict) -> list:
    """Validate a write candidate, which may carry only the keys a write
    path changed, by simulating the same default merge load_structure
    applies on read."""
    registry = _registry_module()
    if registry is None or not hasattr(registry, "validate_structure"):
        return []
    default = getattr(registry, "DEFAULT_STRUCTURE", None)
    merge = getattr(registry, "_merge_defaults", None)
    if default is None or merge is None:
        return list(registry.validate_structure(structure))
    unknown = sorted(set(structure) - set(default))
    if unknown:
        return [f"structure.json: unknown top-level keys: {', '.join(unknown)}"]
    return list(registry.validate_structure(merge(default, structure)))


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
        raw = _load_raw_structure(root)
    except Exception as exc:  # noqa: BLE001
        print(f"init: structure.json invalid: {exc}", file=sys.stderr)
        return 1
    try:
        lanes = configure_lanes(structure, ask, out)
    except (EOFError, KeyboardInterrupt):
        print("init: prompt ended early; nothing written", file=sys.stderr)
        return 1
    new_lanes = {lane: lanes.get(lane) for lane in LANE_NAMES}
    candidate = dict(raw)
    candidate["lanes"] = new_lanes
    errors = structure_errors(candidate)
    if errors:
        print("init: refused to write an invalid structure.json:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    write_structure(root, candidate)
    print(f"wrote {structure_path(root).relative_to(root).as_posix()}", file=out)
    for lane in LANE_NAMES:
        value = new_lanes[lane]
        print(f"  {lane}: {'none' if value is None else ', '.join(value)}", file=out)
    print("no folders were created; lane folders are created on first write", file=out)
    return 0


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------


def _ask_numbered(ask, prompt: str, default: str, out) -> str:
    """Ask a 1/2 question; blank keeps default; a rejected answer repeats."""
    while True:
        answer = ask(prompt).strip()
        if not answer:
            return default
        if answer in ("1", "2"):
            return answer
        print("  rejected: answer 1 or 2, or press Enter for the default", file=out)


def _ask_yes_no(ask, prompt: str, default_yes: bool, out) -> bool:
    """Ask a Y/n question; blank keeps default; a rejected answer repeats."""
    while True:
        answer = ask(prompt).strip().lower()
        if not answer:
            return default_yes
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("  rejected: answer y or n, or press Enter for the default", file=out)


def _solo_local_path() -> str:
    """The shipped default local lane path, read from structure.default.json."""
    return _default_structure()["brain"]["local_path"]


def _profile_defaults(root: Path, structure: dict, profile: str) -> dict:
    """The full answer set for one profile with no questions asked. On an
    untouched structure (lanes, git.mode, and brain.local_path all still the
    shipped defaults) the whole preset applies, exactly as before. On any
    other structure (a configured host) --yes changes host.profile only:
    git.mode, brain.local_path, and lanes are all left exactly as they are
    on disk, never silently overwritten."""
    shipped = _default_structure()
    if not _structure_untouched(structure, shipped):
        return {"profile": profile, "configured_kept": True}

    if profile == "solo":
        brain_local_path = shipped["brain"]["local_path"]
    else:
        brain_local_path, _source = _external_local_path(root)

    return {
        "profile": profile,
        "configured_kept": False,
        "git_mode": PROFILE_GIT_MODE[profile],
        "brain_local_path": brain_local_path,
        "lanes": _lane_preset_for_local_path(brain_local_path),
    }


def run_profile_interview(root: Path, structure: dict, profile, ask, out) -> dict:
    """Ask the profile questions (Q1 only when profile is not already known)
    and return the new answer set. Raises EOFError or KeyboardInterrupt on an
    early end; the caller writes nothing in that case."""
    if profile is None:
        answer = _ask_numbered(ask, "Who works in this repository? 1) just me 2) a team [1]: ", "1", out)
        profile = "team" if answer == "2" else "solo"

    git_default = "1" if profile == "solo" else "2"
    answer = _ask_numbered(
        ask,
        "How does work land? 1) straight onto the default branch 2) on task branches, "
        "reviewed before merge [solo 1 / team 2]: ",
        git_default,
        out,
    )
    git_mode = "main-only" if answer == "1" else "branches"

    external_path, _source = _external_local_path(root)
    solo_local_path = _solo_local_path()
    local_default = "1" if profile == "solo" else "2"
    answer = _ask_numbered(
        ask,
        f"Where do personal notes live? 1) inside the repository, untracked ({solo_local_path}) "
        f"2) outside it ({external_path}) [solo 1 / team 2]: ",
        local_default,
        out,
    )
    brain_local_path = solo_local_path if answer == "1" else external_path

    # The untouched/configured test looks at the structure as it was before
    # this interview's own answers (git_mode, brain_local_path above are
    # explicit decisions and always apply, unlike --yes); it decides only
    # whether question 4's "no" falls back to the preset or keeps the
    # current lanes.
    untouched = _structure_untouched(structure, _default_structure())
    if untouched:
        question4 = "Set the five memory lanes now? [Y/n]: "
    else:
        question4 = "Set the five memory lanes now? [Y/n] (no keeps them as configured): "
    if _ask_yes_no(ask, question4, True, out):
        lanes = configure_lanes(structure, ask, out)
        lanes_kept = False
    elif untouched:
        lanes = _lane_preset_for_local_path(brain_local_path)
        lanes_kept = False
    else:
        lanes = {name: (structure.get("lanes") or {}).get(name) for name in LANE_NAMES}
        lanes_kept = True

    return {
        "profile": profile,
        "configured_kept": False,
        "git_mode": git_mode,
        "brain_local_path": brain_local_path,
        "lanes": lanes,
        "lanes_kept": lanes_kept,
    }


def run_profile(root: Path, profile, yes: bool, ask=input, out=None) -> int:
    out = out or sys.stdout
    try:
        raw = _load_raw_structure(root)
    except Exception as exc:  # noqa: BLE001
        print(f"init: structure.json invalid: {exc}", file=sys.stderr)
        return 1

    # A host that pulled a pre-profile kernel may still carry the retired
    # journal key; --profile repairs it here instead of refusing (every
    # other init path keeps refusing on it, per the registry's message).
    raw, removed_journal = _strip_retired_journal(raw)
    try:
        structure = _merged_structure(raw)
    except ValueError as exc:
        print(f"init: structure.json invalid: {exc}", file=sys.stderr)
        return 1
    if removed_journal:
        print("retired lane key removed: journal (lanes, tiers.lane_defaults)", file=out)

    if yes:
        answers = _profile_defaults(root, structure, profile or "solo")
    else:
        try:
            answers = run_profile_interview(root, structure, profile, ask, out)
        except (EOFError, KeyboardInterrupt):
            print("init: prompt ended early; nothing written", file=sys.stderr)
            return 1

    # contract.mode sits alongside host profile, git mode, brain, and lanes
    # here: this question is asked and answered on purpose every run, so it
    # is exempt from the raw-preserving rule the same way host profile is.
    # It still keeps an already-declared value rather than re-deriving it,
    # so a contract whose rendered AGENTS.md merely needs regeneration is
    # not flipped to host-owned underneath the operator.
    current_contract = raw.get("contract") or {}
    if "mode" in current_contract and current_contract["mode"] is not None:
        contract_mode = current_contract["mode"]
    else:
        contract_mode = derive_contract_mode(root)

    new_structure = dict(raw)
    new_structure["host"] = dict(raw.get("host") or {})
    new_structure["host"]["profile"] = answers["profile"]
    new_structure["contract"] = {"mode": contract_mode}
    configured_kept = answers.get("configured_kept", False)
    if not configured_kept:
        new_structure["git"] = {"mode": answers["git_mode"]}
        new_structure["brain"] = {"local_tracked": False, "local_path": answers["brain_local_path"]}
        if not answers.get("lanes_kept"):
            new_structure["lanes"] = {lane: answers["lanes"].get(lane) for lane in LANE_NAMES}
    # configured_kept: git, brain, and lanes are left exactly as they are in
    # raw (not even re-written with their own current value).

    errors = structure_errors(new_structure)
    if errors:
        print("init: refused to write an invalid structure.json:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    write_structure(root, new_structure)
    print(f"wrote {structure_path(root).relative_to(root).as_posix()}", file=out)
    print(f"  host.profile: {answers['profile']}", file=out)
    if configured_kept:
        git_mode_display = (structure.get("git") or {}).get("mode")
        local_path_display = (structure.get("brain") or {}).get("local_path")
        print(f"  git.mode: kept as configured ({git_mode_display})", file=out)
        print(f"  brain.local_path: kept as configured ({local_path_display})", file=out)
        print("  lanes: kept as configured (answer the interview to change them)", file=out)
        for lane in LANE_NAMES:
            value = (structure.get("lanes") or {}).get(lane)
            print(f"  lanes.{lane}: {'none' if value is None else ', '.join(value)}", file=out)
    else:
        print(f"  git.mode: {answers['git_mode']}", file=out)
        print(f"  brain.local_path: {answers['brain_local_path']}", file=out)
        if answers.get("lanes_kept"):
            print("  lanes: kept as configured (answer yes to question 4, or run init.py --lanes, to change them)", file=out)
        for lane in LANE_NAMES:
            value = new_structure["lanes"][lane]
            print(f"  lanes.{lane}: {'none' if value is None else ', '.join(value)}", file=out)
    print(f"  contract.mode: {new_structure['contract']['mode']}", file=out)

    effective_brain = new_structure.get("brain") or structure.get("brain") or {}
    local_path_for_gitignore = effective_brain.get("local_path")
    try:
        normalize_lane_path(local_path_for_gitignore)
    except ValueError:
        print(f"  no .gitignore entry needed: {local_path_for_gitignore} is outside the repository", file=out)
    else:
        ensure_ignored(root, local_path_for_gitignore, out)

    print("next: python harness/tools/selector.py --list", file=out)
    print(
        "then: bash harness/bootstrap/bootstrap.sh (POSIX) or "
        "powershell -NoProfile -ExecutionPolicy Bypass -File harness/bootstrap/bootstrap.ps1 (Windows)",
        file=out,
    )
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
        raw = _load_raw_structure(root)
    except Exception as exc:  # noqa: BLE001
        print(f"init: structure.json invalid: {exc}", file=sys.stderr)
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
    _place(template_root / "shared" / "README.md", root / "brain" / "shared" / "README.md", out, root)
    _place(template_root / "local" / "README.md", root / "brain" / "local" / "README.md", out, root)
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
        candidate = dict(raw)
        candidate["brain"] = {"local_tracked": True, "local_path": local_path}
        errors = structure_errors(candidate)
        if errors:
            print("init: refused to write an invalid structure.json:", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
            return 1
        write_structure(root, candidate)
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
        print(f"init: structure.json invalid: {exc}", file=sys.stderr)
        return 1
    path = structure_path(root)
    print(f"host shape ({path.relative_to(root).as_posix()}{'' if path.is_file() else ', defaults; file absent'})", file=out)
    print(f"host profile: {_host_profile_status(root, structure)}", file=out)
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
    print("  python harness/tools/init.py --profile [solo|team] [--yes]", file=out)
    return 0


def _host_profile_status(root: Path, structure: dict) -> str:
    """The status line's value: the merged profile, or an absence note when
    the on-disk structure.json (if any) carries no host.profile key."""
    profile = (structure.get("host") or {}).get("profile") or "solo"
    path = structure_path(root)
    if not path.is_file():
        return "solo (absent; set it with python harness/tools/init.py --profile)"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict) or "profile" not in (raw.get("host") or {}):
        return "solo (absent; set it with python harness/tools/init.py --profile)"
    return str(profile)


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
    mode.add_argument("--lanes", action="store_true", help="configure the five lanes (prompted)")
    mode.add_argument("--brain", action="store_true", help="scaffold the reference memory module")
    mode.add_argument("--adopt", metavar="REPO", help="install the harness into an existing repository via adopt.py")
    mode.add_argument(
        "--profile",
        nargs="?",
        const="",
        default=None,
        metavar="{solo,team}",
        help="configure host.profile, git.mode, the local lane, and (optionally) the lanes; bare flag asks interactively",
    )
    parser.add_argument("--track-local", action="store_true", help="with --brain: track the local lane in git (prints the consequence)")
    parser.add_argument("--yes", action="store_true", help="answer every question with defaults; only meaningful with --profile or --adopt (long-form only)")
    parser.add_argument("--root", default=str(ROOT), help="repository root (default: this repository)")
    args, extra = parser.parse_known_args(argv)

    if args.track_local and not args.brain:
        parser.print_usage(sys.stderr)
        print("init: --track-local is only meaningful with --brain", file=sys.stderr)
        return 2
    if args.yes and args.profile is None and not args.adopt:
        parser.print_usage(sys.stderr)
        print("init: --yes is only meaningful with --profile or --adopt", file=sys.stderr)
        return 2
    if extra and not args.adopt:
        parser.print_usage(sys.stderr)
        print(f"init: unrecognized arguments: {' '.join(extra)}", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    if args.adopt:
        forwarded = list(extra)
        if args.yes:
            # F10 guard: --yes is a global flag on this parser, so
            # parse_known_args already stripped it out of `extra` before it
            # could reach adopt.py, and adopt.py itself has no --yes flag
            # (only -y/--apply). Without this, `init.py --adopt <target>
            # --yes` would silently dry-run. Translate to the flag adopt.py
            # actually understands so it applies.
            forwarded = forwarded + ["--apply"]
        return run_adopt(args.adopt, forwarded)
    if args.profile is not None:
        value = args.profile or None
        if value is not None and value not in HOST_PROFILES:
            parser.print_usage(sys.stderr)
            print(f"init: --profile must be 'solo' or 'team', not {value!r}", file=sys.stderr)
            return 2
        ask = input
        if value is None and not args.yes and not sys.stdin.isatty():
            # A closed or empty pipe (piping nothing, or </dev/null) is the
            # only case that needs the --yes guidance: a real tty, or a
            # pipe that actually carries the four answers, must run the
            # interview. isatty() alone is not enough (a Windows redirect
            # from NUL still reports a tty), so this reads whatever is
            # already queued on the pipe instead of gating on the terminal
            # check alone.
            piped = sys.stdin.read()
            if not piped:
                print(
                    "init: --profile needs a value on a non-interactive session; use `--profile <value> --yes`",
                    file=sys.stderr,
                )
                return 2
            queue = piped.splitlines()

            def ask(_prompt: str, _queue=queue) -> str:
                if not _queue:
                    raise EOFError
                return _queue.pop(0)

        return run_profile(root, value, args.yes, ask=ask)
    if args.lanes:
        return run_lanes(root)
    if args.brain:
        return run_brain(root, args.track_local)
    return print_shape(root)


if __name__ == "__main__":
    sys.exit(main())
