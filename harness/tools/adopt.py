#!/usr/bin/env python
"""Install the harness into an existing repository.

Usage:
    python harness/tools/adopt.py <target-repo> [--dry-run | -y/--apply]

Default is a dry run that prints every action and writes nothing; -y/--apply
performs them. The source is the repository this file lives in.

Refusals (exit 2): the target is not a git repository, has uncommitted
changes, is this repository, or already carries a harness kernel.

Actions:
  * harness/ is copied file by file. A target file that already exists is
    never overwritten: under harness/rules/ the incoming file lands as
    <slug>.harness.md (reserved-name merge, reported); elsewhere it lands as
    <name>.harness<suffix>, reported.
  * The scaffold-owned root files (README.md, AGENTS.md, CLAUDE.md,
    CONTRIBUTING.md, SECURITY.md, LICENSE, NOTICE, THIRD-PARTY.md, .gitignore,
    .gitattributes, .githooks/, the conformance workflow, docs/) are copied
    only when absent; an existing one is kept and the harness version lands as
    <name>.harness.md.
  * harness/registry/structure.json is written for the target, never copied:
    every lane is null except docs (when docs/ exists) and decisions (when
    the default decisions lane folder from the structure defaults, or a
    top-level decisions/ folder, exists); git.mode is "branches" when the
    target has more than one remote branch or a branch protection marker
    (CODEOWNERS, .github/rulesets/), otherwise "main-only". In branches mode
    the local memory lane is placed outside the repository when the structure
    validator admits an external path; until it does, the lane stays
    repository-relative and untracked, and the checklist says so.
  * harness/registry/adopted-files.json records the exact repository-relative
    paths this run created or wrote (copies, the structure.json write, every
    landed .harness sibling). An apply merges (unions) into a file left by an
    earlier adoption rather than overwriting it. lint.py and
    deidentify_lint.py read this file to scope their default scan to the
    template's own files on an adopted host (--all restores the whole tree).
  * An apply stages the executable bit (git update-index --add --chmod=+x)
    for every landed harness/*.sh file and .githooks/pre-commit, the same
    scope lint check L18 and materialize.py's _ensure_scripts_executable
    use. On POSIX the file is also chmod'd on disk. This is the only way
    the bit reaches history on Windows, where core.filemode is false and
    the working-tree copy carries no executable bit for git to read at
    commit time: the adopter's own commit stages these paths' modes along
    with everything else.

The run ends with a numbered checklist that closes with the bootstrap and
doctor commands.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
TEMPLATES = TOOLS_DIR / "templates"
ROOT = Path(__file__).resolve().parents[2]

ROOT_FILES = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "LICENSE",
    "NOTICE",
    "THIRD-PARTY.md",
    ".gitignore",
    ".gitattributes",
]
ROOT_TREES = [".githooks", "docs"]
ROOT_EXTRA = [".github/workflows/offline-conformance.yml"]
HARNESS_SKIP_DIRS = {".selected", "__pycache__", ".pytest_cache"}
HARNESS_SKIP_FILES = {"harness/registry/structure.json", "harness/registry/selection.local.json"}
PROTECTION_MARKERS = ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS", ".github/rulesets"]
LANE_NAMES = ("identity", "knowledge", "journal", "decisions", "records", "docs")
EXTERNAL_LOCAL_TEMPLATE = "~/.harness-local/{name}"
HOST_NAME_SANITIZE_RE = re.compile(r"[^A-Za-z0-9._-]+")
URL_SEGMENT_SPLIT_RE = re.compile(r"[:/\\]")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def git(repo: Path, *args) -> tuple:
    try:
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    except OSError as exc:
        return 127, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def sanitize_host_name(raw: str) -> str:
    """Collapse everything outside [A-Za-z0-9._-] to '-' and trim stray edges."""
    cleaned = HOST_NAME_SANITIZE_RE.sub("-", raw).strip("-")
    return cleaned or "host"


def derive_host_name(target: Path) -> tuple:
    """(name, source) for EXTERNAL_LOCAL_TEMPLATE: the basename of the
    target repository's origin remote (https, ssh, or local-path form),
    trailing .git stripped, sanitized to [A-Za-z0-9._-]. Falls back to the
    target folder's own name when there is no git, no origin, or the origin
    URL yields no usable segment."""
    code, out, _ = git(target, "remote", "get-url", "origin")
    url = out.strip() if code == 0 else ""
    if url:
        stripped = url.rstrip("/")
        if stripped.lower().endswith(".git"):
            stripped = stripped[: -len(".git")]
        segments = [seg for seg in URL_SEGMENT_SPLIT_RE.split(stripped) if seg]
        if segments:
            return sanitize_host_name(segments[-1]), f"origin remote ({url})"
    return sanitize_host_name(target.name), "folder name (no usable origin remote)"


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


def harness_name(rel: str) -> str:
    """Sibling name for a file that must not overwrite an existing one."""
    path = Path(rel)
    if path.suffix == ".md":
        return path.with_name(path.stem + ".harness.md").as_posix()
    if path.suffix == "":
        return path.with_name(path.name + ".harness.md").as_posix()
    return path.with_name(path.stem + ".harness" + path.suffix).as_posix()


def default_structure() -> dict:
    return json.loads((TOOLS_DIR / "templates" / "structure.default.json").read_text(encoding="utf-8"))


def detect_git_mode(target: Path) -> tuple:
    code, out, _ = git(target, "branch", "-r", "--format=%(refname:short)")
    remote_branches = [line for line in out.splitlines() if line.strip() and not line.strip().endswith("/HEAD")] if code == 0 else []
    markers = [m for m in PROTECTION_MARKERS if (target / m).exists()]
    if len(remote_branches) > 1:
        return "branches", f"{len(remote_branches)} remote branches"
    if markers:
        return "branches", f"branch protection marker: {markers[0]}"
    return "main-only", "one remote branch or none, no protection marker"


def _default_lane(name: str) -> list:
    """The shipped default for one lane: the registry's defaults contract, else the template copy."""
    registry = _registry_module()
    default = getattr(registry, "DEFAULT_STRUCTURE", None) if registry is not None else None
    if not isinstance(default, dict):
        default = json.loads((TEMPLATES / "structure.default.json").read_text(encoding="utf-8"))
    value = (default.get("lanes") or {}).get(name)
    return [item for item in (value or []) if isinstance(item, str) and item]


def detect_lanes(target: Path) -> dict:
    lanes = {name: None for name in LANE_NAMES}
    if (target / "docs").is_dir():
        lanes["docs"] = ["docs"]
    present_defaults = [path for path in _default_lane("decisions") if (target / path).is_dir()]
    if present_defaults:
        lanes["decisions"] = present_defaults
    elif (target / "decisions").is_dir():
        lanes["decisions"] = ["decisions"]
    return lanes


def structure_errors(structure: dict) -> list:
    """Run the registry validator when it is available; [] otherwise."""
    registry = _registry_module()
    if registry is None or not hasattr(registry, "validate_structure"):
        return []
    try:
        return list(registry.validate_structure(structure))
    except Exception as exc:  # noqa: BLE001
        return [f"validator raised: {exc}"]


def detect_host_roots(target: Path) -> list:
    """Top-level tracked directories the host already had before adoption (harness/ excluded)."""
    code, out, _ = git(target, "ls-files")
    if code != 0:
        return []
    dirs = set()
    for line in out.splitlines():
        line = line.strip()
        if not line or "/" not in line:
            continue
        top = line.split("/", 1)[0]
        if top and top != "harness":
            dirs.add(top)
    return sorted(dirs)


def detect_harness_owned(target: Path, actions: list) -> list:
    """Paths under harness/ that already existed in the target before adoption.

    Most of a host's pre-existing harness/ tree has no template counterpart
    (its own scripts, schemas, or workflows) and adopt's file-by-file copy
    never visits those paths at all, so the collision list from `actions`
    (paths the template also ships, landed as a `.harness.md` sibling)
    covers only the overlap. The target's own tracked harness/ tree, listed
    before any file is copied in, is the complete and accurate record.
    """
    owned = {
        rel
        for verb, rel, _dst in actions
        if verb.startswith("land-as") and rel.startswith("harness/")
    }
    code, out, _ = git(target, "ls-files", "harness")
    if code == 0:
        owned.update(line.strip() for line in out.splitlines() if line.strip())
    return sorted(owned)


def build_structure(target: Path, actions: list | None = None) -> tuple:
    """Return (structure, git-mode reason, local-lane note)."""
    actions = actions if actions is not None else []
    structure = default_structure()
    structure["lanes"] = detect_lanes(target)
    mode, reason = detect_git_mode(target)
    structure["git"] = {"mode": mode}
    adopted_agents = (target / "AGENTS.md").is_file()
    structure["contract"] = {"mode": "host-owned" if adopted_agents else "rendered"}
    structure["host"] = {
        "adopted": adopted_agents,
        "roots": detect_host_roots(target) if adopted_agents else [],
        "harness_owned": detect_harness_owned(target, actions) if adopted_agents else [],
    }
    local_note = f"brain.local_path {structure['brain']['local_path']} (repository-relative, untracked)"
    if mode == "branches":
        name, name_source = derive_host_name(target)
        external = EXTERNAL_LOCAL_TEMPLATE.format(name=name)
        candidate = dict(structure)
        candidate["brain"] = {"local_tracked": False, "local_path": external}
        errors = structure_errors(candidate)
        if errors:
            local_note = (
                f"brain.local_path stays {structure['brain']['local_path']} (repository-relative, untracked): "
                f"the structure validator rejects the external path {external} ({errors[0]})"
            )
        else:
            structure = candidate
            local_note = f"brain.local_path {external} (outside the repository; branches mode; name from {name_source})"
    return structure, reason, local_note


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------


def plan_actions(source: Path, target: Path) -> list:
    """List of (verb, source_rel, target_rel). verbs: copy, land-as, write."""
    actions = []

    def consider(rel: str, rules_merge: bool):
        dst = target / rel
        if dst.exists():
            alt = harness_name(rel)
            verb = "land-as (reserved-name merge)" if rules_merge else "land-as (existing kept)"
            actions.append((verb, rel, alt))
        else:
            actions.append(("copy", rel, rel))

    harness_root = source / "harness"
    for dirpath, dirnames, filenames in os.walk(harness_root):
        dirnames[:] = sorted(d for d in dirnames if d not in HARNESS_SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".pyc"):
                continue
            rel = (Path(dirpath) / name).relative_to(source).as_posix()
            if rel in HARNESS_SKIP_FILES:
                continue
            consider(rel, rules_merge=rel.startswith("harness/rules/") and rel.endswith(".md"))

    for rel in ROOT_FILES + ROOT_EXTRA:
        if (source / rel).is_file():
            consider(rel, rules_merge=False)
    for tree in ROOT_TREES:
        base = source / tree
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in HARNESS_SKIP_DIRS)
            for name in sorted(filenames):
                rel = (Path(dirpath) / name).relative_to(source).as_posix()
                consider(rel, rules_merge=False)

    actions.append(("write", "(generated)", "harness/registry/structure.json"))
    return actions


def apply_actions(source: Path, target: Path, actions: list, structure: dict) -> None:
    for verb, src_rel, dst_rel in actions:
        dst = target / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if verb == "write":
            dst.write_text(json.dumps(structure, indent=2) + "\n", encoding="utf-8", newline="\n")
            continue
        if dst.exists():
            # A sibling from an earlier adoption is also never overwritten.
            continue
        shutil.copyfile(source / src_rel, dst)


# --------------------------------------------------------------------------
# executable bit
# --------------------------------------------------------------------------


def is_script_path(rel: str) -> bool:
    """The exact predicate lint check L18 and materialize.py's
    _ensure_scripts_executable use: every harness/*.sh file, plus the
    pre-commit hook. A landed sibling (a .harness suffix) is in scope too
    when its own landing path still matches, since it is a real file on
    disk that core.hooksPath or a sourcing script will execute."""
    return (rel.startswith("harness/") and rel.endswith(".sh")) or rel == ".githooks/pre-commit"


def landed_script_paths(actions: list) -> list:
    """Repository-relative paths this run lands (copy or land-as) that are
    shell entry points in L18's scope."""
    return sorted(
        {
            dst_rel
            for verb, _src_rel, dst_rel in actions
            if (verb == "copy" or verb.startswith("land-as")) and is_script_path(dst_rel)
        }
    )


def manual_chmod_command(paths: list) -> str:
    return "git update-index --add --chmod=+x -- " + " ".join(paths)


def set_executable_bits(target: Path, paths: list) -> tuple:
    """Stage the executable bit for every landed script in the target's git
    index: on POSIX this also chmods the file on disk, but the index write
    is what carries the bit forward on every platform, since Windows has no
    on-disk executable bit for git to read at commit time (proven live: a
    Windows adopter's commit landed harness/**/*.sh at mode 100644, and the
    template's own lint L18 then failed on the adopter's POSIX CI).

    Returns (staged_paths, warning). warning is None on success; it is a
    manual-command string when git is absent or the target is not a git
    work tree, so the caller can print one WARN and continue rather than
    crash. An empty paths list is a no-op: ([], None)."""
    if not paths:
        return [], None
    if shutil.which("git") is None:
        return [], manual_chmod_command(paths)
    code, out, _ = git(target, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return [], manual_chmod_command(paths)
    if os.name != "nt":
        for rel in paths:
            path = target / rel
            if not path.is_file():
                continue
            try:
                mode = path.stat().st_mode
                path.chmod(mode | 0o111)
            except OSError:
                continue
    code, _out, err = git(target, "update-index", "--add", "--chmod=+x", "--", *paths)
    if code != 0:
        return [], manual_chmod_command(paths) + f" (git update-index failed: {err.strip()})"
    return paths, None


# --------------------------------------------------------------------------
# adopted-files.json
# --------------------------------------------------------------------------

ADOPTED_FILES_REL = "harness/registry/adopted-files.json"


def adopted_file_paths(actions: list) -> list:
    """Repository-relative paths adopt created or wrote this run: every
    copy, the structure.json write, and every landed .harness sibling
    (including AGENTS.harness.md when the host contract is host-owned)."""
    paths = {dst_rel for verb, _src_rel, dst_rel in actions if verb == "copy" or verb == "write" or verb.startswith("land-as")}
    return sorted(paths)


def kernel_template_version(source: Path) -> str:
    """The template version this adoption was cut from, from the source's
    own kernel-manifest.json. 'unknown' when the manifest is absent or
    unreadable, never a crash."""
    manifest_path = source / "harness" / "kernel-manifest.json"
    try:
        doc = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "unknown"
    version = doc.get("version") if isinstance(doc, dict) else None
    return version if isinstance(version, str) and version else "unknown"


def write_adopted_files(target: Path, new_paths: list, template_version: str) -> tuple:
    """Write or merge harness/registry/adopted-files.json.

    A file from an earlier adoption is merged (union of paths, template_version
    updated to this run's), never overwritten. Returns (merged, total_count,
    added_count)."""
    dst = target / ADOPTED_FILES_REL
    existing: set = set()
    merged = False
    if dst.is_file():
        try:
            doc = json.loads(dst.read_text(encoding="utf-8-sig"))
            if isinstance(doc, dict):
                existing = {p for p in (doc.get("paths") or []) if isinstance(p, str)}
            merged = True
        except (OSError, ValueError):
            existing = set()
    combined = sorted(existing | set(new_paths))
    added = len(set(new_paths) - existing)
    doc = {"template_version": template_version, "paths": combined}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    return merged, len(combined), added


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------


def refusal(source: Path, target: Path) -> str:
    if not target.is_dir():
        return f"target is not a directory: {target}"
    if target.resolve() == source.resolve():
        return "target is this repository (the source)"
    if (target / "harness" / "kernel-manifest.json").is_file() or (target / "harness" / "tools" / "adopt.py").is_file():
        return "target already carries a harness kernel (harness/kernel-manifest.json or harness/tools/adopt.py present)"
    code, out, err = git(target, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return "target is not a git repository (git rev-parse --is-inside-work-tree failed)"
    code, top, _ = git(target, "rev-parse", "--show-toplevel")
    if code == 0 and Path(top.strip()).resolve() != target.resolve():
        return f"target is not the repository root (root is {top.strip()})"
    code, status, _ = git(target, "status", "--porcelain")
    if code != 0:
        return "git status failed on the target"
    if status.strip():
        return "target has uncommitted changes; commit or stash them first"
    return ""


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def checklist(target: Path, structure: dict, local_note: str) -> list:
    mode = structure["git"]["mode"]
    items = [
        "Review the diff: adopt is additive; delete what it added to reverse it.",
        "Read every *.harness.md sibling and merge it into the file it sits beside, or delete it.",
        "Edit harness/CONTRACT.host.md with the host facts (what this repository is, where things live).",
        "Check harness/registry/structure.json: lanes detected from the tree, the rest null; set the ones you use.",
    ]
    if mode == "branches":
        items.append(f"Branches mode detected: {local_note}. Keep personal notes out of pull requests: the local lane is untracked and, once the validator admits it, lives outside the repository.")
    if structure["host"]["adopted"]:
        items.append(
            "Contract is host-owned (harness/registry/structure.json contract.mode=host-owned): AGENTS.md "
            "stays yours; add a line pointing at AGENTS.harness.md so runtimes load the harness block, or "
            "merge its content in directly."
        )
    items.append("After merging any *.gitignore.harness.md sibling, run git check-ignore -v on every bootstrap-managed copy (.claude/settings.json, .codex/config.toml, .codex/hooks.json, opencode.json, ...): a pre-existing host rule can hide one. The doctors run this check automatically after bootstrap.")
    items.append("Bootstrap: bash harness/bootstrap/bootstrap.sh (POSIX) or powershell -NoProfile -ExecutionPolicy Bypass -File harness/bootstrap/bootstrap.ps1 (Windows).")
    items.append("Doctor: bash harness/bootstrap/doctor.sh, python harness/bootstrap/doctor_codex.py --offline, python harness/bootstrap/doctor_opencode.py --offline.")
    return items


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install the harness into an existing repository (dry run by default).")
    parser.add_argument("target", help="path to the target repository root")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="print every action and write nothing (default)")
    group.add_argument("-y", "--apply", action="store_true", help="perform the actions")
    parser.add_argument("--source", default=str(ROOT), help="harness repository to install from (default: this repository)")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    why = refusal(source, target)
    if why:
        print(f"adopt: refused: {why}", file=sys.stderr)
        return 2

    actions = plan_actions(source, target)
    structure, mode_reason, local_note = build_structure(target, actions)
    mode = structure["git"]["mode"]
    label = "apply" if args.apply else "dry run"
    print(f"adopt ({label}): {source} -> {target}")
    print(f"  git mode: {mode} ({mode_reason})")
    lanes = ", ".join(f"{k}={v}" for k, v in structure["lanes"].items())
    print(f"  lanes: {lanes}")
    print(f"  local lane: {local_note}")
    if structure["host"]["adopted"]:
        print(
            f"  contract: host-owned (target already has AGENTS.md; the template contract lands as "
            f"AGENTS.harness.md, {len(structure['host']['harness_owned'])} pre-existing harness/ path(s) "
            f"recorded as host-owned)"
        )
    else:
        print("  contract: rendered (no pre-existing AGENTS.md; bootstrap renders the root file)")
    for verb, src_rel, dst_rel in actions:
        if verb == "copy":
            print(f"  copy      {dst_rel}")
        elif verb == "write":
            print(f"  write     {dst_rel}")
        else:
            print(f"  {verb}: {src_rel} -> {dst_rel}")
    landed = [a for a in actions if a[0].startswith("land-as")]
    print(f"  {len(actions)} action(s); {len(landed)} existing file(s) kept with a .harness sibling")

    script_paths = landed_script_paths(actions)
    new_adopted_paths = adopted_file_paths(actions)
    template_version = kernel_template_version(source)
    print(f"  adopted-files.json: {len(new_adopted_paths)} path(s) would be recorded (template_version {template_version})")

    if args.apply:
        apply_actions(source, target, actions, structure)
        staged, warning = set_executable_bits(target, script_paths)
        if warning:
            print(f"adopt: WARN: could not stage the executable bit; run manually: {warning}", file=sys.stderr)
        elif staged:
            print(f"adopt: staged {len(staged)} script(s) with the executable bit; Windows records the bit only through the index")
        merged, total, added = write_adopted_files(target, new_adopted_paths, template_version)
        if merged:
            print(f"adopt: harness/registry/adopted-files.json merged ({added} new path(s), {total} total)")
        else:
            print(f"adopt: harness/registry/adopted-files.json written ({total} path(s))")
        print("adopt: applied")
    else:
        if script_paths:
            print(f"adopt: dry run would stage {len(script_paths)} script(s) with the executable bit (harness/*.sh, .githooks/pre-commit)")
        print("adopt: dry run, nothing written; pass -y/--apply to perform these actions")

    print("post-adoption checklist:")
    for index, item in enumerate(checklist(target, structure, local_note), start=1):
        print(f"  {index}. {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
