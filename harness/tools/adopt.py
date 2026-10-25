#!/usr/bin/env python
"""Install the harness into an existing repository.

Usage:
    python harness/tools/adopt.py <target-repo> [--dry-run | -y/--apply]
    python harness/tools/adopt.py --upgrade <target-repo> [--dry-run | -y/--apply]
        [--source SRC_OR_URL] [--ref REF] [--skip GLOB ...]

Default is a dry run that prints every action and writes nothing; -y/--apply
performs them. The source is the repository this file lives in.

Refusals (exit 2): the target is not a git repository, has uncommitted
changes, is this repository, or already carries a harness kernel.

--upgrade refreshes an already-adopted host from a newer copy of the
template, instead of installing into a fresh target. It reads the source's
committed HEAD, or the commit --ref names (never its working tree); a URL
--source is bare-cloned to a temporary directory and removed afterwards.
Each file is compared three ways (host, source, and the base the host last
received, from adopted-files.json `hashes` or the release tag): `update`
when the host is unmodified, `kept` when only the host changed, `conflict`
when both did (the source version lands as a sibling, never over the host
file). It refuses on a dirty or incompletely
checked-out target, never deletes a file, and never touches a host-owned
path (structure.json, selection.json, adopted-files.json, CONTRACT.host.md,
AGENTS.md, CLAUDE.md, any `*.harness` sibling, or any path the target's
structure.json lists under `host.harness_owned`). See `upgrade_main` below.

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
    repository-relative and untracked, and the checklist says so. host.profile
    is always written as "team", regardless of the detected git mode: an
    adopted repository is by definition someone else's shared repository.
    host.adopted is always true and host.roots lists the target's own top-level
    directories, so lint.py and deidentify_lint.py scope themselves to the
    template's files on every adopted host; contract.mode alone records whether
    the target already had an AGENTS.md.
    host.verify_command stays null; the commit skill discovers the host's
    verify command at run time. The checklist tells a solo adopter how to
    switch the profile back with init.py.
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
import fnmatch
import importlib.util
import json
import os
import re
import hashlib
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
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
LANE_NAMES = ("identity", "knowledge", "decisions", "records", "docs")
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
    host_owned_contract = (target / "AGENTS.md").is_file()
    structure["contract"] = {"mode": "host-owned" if host_owned_contract else "rendered"}
    # Every adoption is an adoption: host.adopted scopes the lint and the
    # de-identification check to the template's own files, whether or not
    # the target already had an AGENTS.md (that is contract.mode's job).
    structure["host"] = {
        "adopted": True,
        "roots": detect_host_roots(target),
        "harness_owned": detect_harness_owned(target, actions),
        "profile": "team",
        "verify_command": None,
    }
    local_note = f"brain.local_path {structure['brain']['local_path']} (repository-relative, untracked)"
    if mode == "branches":
        name, name_source = derive_host_name(target)
        external = EXTERNAL_LOCAL_TEMPLATE.format(name=name)
        structure["brain"] = {"local_tracked": False, "local_path": external}
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


def content_hash(data: bytes) -> str:
    """sha256 hex of the bytes with CRLF folded to LF, the form recorded in
    adopted-files.json `hashes` and compared by --upgrade."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def write_adopted_files(target: Path, new_paths: list, template_version: str, hashes: dict | None = None) -> tuple:
    """Write or merge harness/registry/adopted-files.json.

    A file from an earlier adoption is merged (union of paths, template_version
    updated to this run's), never overwritten. `hashes` maps a path to the
    sha256 of its CRLF-normalized source content; entries are merged over any
    existing ones and an existing entry is never pruned. Returns (merged,
    total_count, added_count)."""
    dst = target / ADOPTED_FILES_REL
    existing: set = set()
    existing_hashes: dict = {}
    merged = False
    if dst.is_file():
        try:
            doc = json.loads(dst.read_text(encoding="utf-8-sig"))
            if isinstance(doc, dict):
                existing = {p for p in (doc.get("paths") or []) if isinstance(p, str)}
                raw_hashes = doc.get("hashes")
                if isinstance(raw_hashes, dict):
                    existing_hashes = {k: v for k, v in raw_hashes.items() if isinstance(k, str) and isinstance(v, str)}
            merged = True
        except (OSError, ValueError):
            existing = set()
    combined = sorted(existing | set(new_paths))
    added = len(set(new_paths) - existing)
    all_hashes = dict(existing_hashes)
    all_hashes.update(hashes or {})
    doc = {"template_version": template_version, "paths": combined, "hashes": dict(sorted(all_hashes.items()))}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    return merged, len(combined), added


# --------------------------------------------------------------------------
# upgrade (refresh an already-adopted host from a newer template)
# --------------------------------------------------------------------------

# Every host-facing root file plain adopt only ever installs when the target
# does not already have it (ROOT_FILES: README.md, AGENTS.md, CLAUDE.md,
# CONTRIBUTING.md, SECURITY.md, LICENSE, NOTICE, THIRD-PARTY.md, .gitignore,
# .gitattributes), plus the registry/contract files adopt itself writes for
# the target rather than copying. None of these is ever refreshed by
# --upgrade: an adopted host owns its own copy from the moment adopt ran.
UPGRADE_FIXED_HOST_OWNED = set(ROOT_FILES) | {
    "harness/registry/structure.json",
    "harness/registry/selection.json",
    ADOPTED_FILES_REL,
    "harness/CONTRACT.host.md",
}
HARNESS_SIBLING_SUFFIX_RE = re.compile(r"\.harness(\.[A-Za-z0-9]+)?$")


def is_harness_sibling_path(rel: str) -> bool:
    """True for a `.harness` non-overwrite landing sibling (e.g.
    README.harness.md, git-workflow.harness.md): a one-time adoption
    artifact the checklist asks a human to merge or delete, never something
    --upgrade should recreate or refresh on its own."""
    return bool(HARNESS_SIBLING_SUFFIX_RE.search(Path(rel).name))


def is_safe_candidate_path(rel: str) -> bool:
    """Strict POSIX-relative path: no backslash, no colon (a Windows drive
    letter or an alternate data stream), not absolute, and no empty, '.', or
    '..' segment. Checked before a candidate path is ever joined onto a
    filesystem path, for both source-manifest/tree paths and
    adopted-files.json entries: either can carry an adversarial or corrupted
    value."""
    if not rel or "\\" in rel or ":" in rel or rel.startswith("/"):
        return False
    parts = rel.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def in_plain_adopt_scope(rel: str) -> bool:
    """True when a path is inside what plain adopt.py itself ever installs:
    harness/ (minus HARNESS_SKIP_DIRS/HARNESS_SKIP_FILES, the same exclusions
    plan_actions applies), or one of ROOT_FILES, ROOT_TREES, or ROOT_EXTRA.
    --upgrade must never create a path (e.g. under brain/) that a plain
    adopt on this same target would never have written in the first place;
    only used to gate a manifest-only *new* candidate, never an already
    recorded adopted-files.json path."""
    if rel in HARNESS_SKIP_FILES:
        return False
    parts = rel.split("/")
    if parts[0] == "harness":
        return not any(part in HARNESS_SKIP_DIRS for part in parts[1:-1])
    if rel in ROOT_FILES or rel in ROOT_EXTRA:
        return True
    return parts[0] in ROOT_TREES


def _normalize_crlf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _links_module():
    """Load harness/bootstrap/links.py's is_link without touching sys.path
    (mirrors _registry_module's loader for harness_registry.py)."""
    path = TOOLS_DIR.parent / "bootstrap" / "links.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("harness_links", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - a broken links module means "treat as a link" below
        return None
    return module


def path_has_link_component(target: Path, rel: str) -> bool:
    """True when the destination itself, or any parent directory between
    target and the destination, is a symlink or junction, or when the fully
    resolved destination would fall outside the resolved target directory.
    A missing path component is never a link (is_symlink/is_link is false
    for a path that does not exist at all), so this is safe to call before a
    new file's parent directories are created. Called before any read or
    write through the candidate path: a write that followed a tracked
    symlink out of the target would overwrite (or, for a dangling symlink,
    create) a file entirely outside the host's repository."""
    links = _links_module()
    is_link_fn = links.is_link if links is not None else (lambda p: p.is_symlink())
    current = target
    for part in Path(rel).parts:
        current = current / part
        try:
            if is_link_fn(current):
                return True
        except OSError:
            return True
    try:
        resolved_target = Path(os.path.realpath(target))
        resolved_dst = Path(os.path.realpath(current))
    except OSError:
        return True
    try:
        resolved_dst.relative_to(resolved_target)
    except ValueError:
        return True
    return False


def target_tracked_paths(target: Path) -> set:
    """Every path git tracks in the target's index, as repo-relative POSIX
    strings: the set membership this needs is exactly what
    `git ls-files --error-unmatch <path>` would answer per path, computed
    once for the whole run instead of once per candidate."""
    proc = subprocess.run(["git", "-C", str(target), "ls-files", "-z"], capture_output=True, check=False)
    if proc.returncode != 0:
        return set()
    return {chunk.decode("utf-8") for chunk in proc.stdout.split(b"\x00") if chunk}


def upgrade_target_refusal(target: Path) -> str:
    if not (target / ADOPTED_FILES_REL).is_file():
        return f"target has no {ADOPTED_FILES_REL} (not an adopted host)"
    code, out, _ = git(target, "rev-parse", "--is-inside-work-tree")
    if code != 0 or out.strip() != "true":
        return "target is not a git repository (git rev-parse --is-inside-work-tree failed)"
    code, deleted, _ = git(target, "ls-files", "-d")
    if code != 0:
        return "git ls-files -d failed on the target"
    if deleted.strip():
        return "target has tracked file(s) missing from disk (incomplete checkout); restore them first"
    code, status, _ = git(target, "status", "--porcelain", "--untracked-files=all")
    if code != 0:
        return "git status failed on the target"
    if status.strip():
        return "target has uncommitted changes; commit or stash them first"
    return ""


def upgrade_cross_refusal(source: Path, target: Path) -> str:
    if source.resolve() == target.resolve():
        return "source and target resolve to the same directory"
    return ""


def upgrade_source_refusal(source: Path, ref: str | None = None) -> str:
    """ref None is the legacy local-working-tree check (byte-identical to the
    pre-ref behavior). With a ref (a bare clone or an explicit --ref) the
    checks run at that ref, so they work on a repository with no work tree."""
    if ref is None:
        code, out, _ = git(source, "rev-parse", "--is-inside-work-tree")
        if code != 0 or out.strip() != "true":
            return "source is not a git repository (git rev-parse --is-inside-work-tree failed)"
        if (source / ADOPTED_FILES_REL).is_file():
            return f"source has {ADOPTED_FILES_REL} (it is a host, not the template)"
        return ""
    code, _out, _ = git(source, "rev-parse", "--git-dir")
    if code != 0:
        return "source is not a git repository (git rev-parse --git-dir failed)"
    code, _out, _ = git(source, "cat-file", "-e", f"{ref}:{ADOPTED_FILES_REL}")
    if code == 0:
        return f"source has {ADOPTED_FILES_REL} at the ref (it is a host, not the template)"
    return ""


def resolve_source_ref(source: Path, ref: str) -> tuple:
    """(commit_sha, error). Refuses a ref that starts with '-' and one for
    which `<ref>^{commit}` does not resolve in the source repository."""
    if not ref or ref.startswith("-"):
        return "", f"invalid ref {ref!r} (must not be empty or start with '-')"
    code, out, _ = git(source, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    sha = out.strip()
    if code != 0 or not sha:
        return "", f"ref {ref!r} does not resolve to a commit in the source (git rev-parse {ref}^{{commit}} failed)"
    return sha, ""


def source_head_paths(source: Path, ref: str = "HEAD") -> set:
    """Every path git tracks at the source's ref (default HEAD), as
    repo-relative POSIX strings. Raises RuntimeError on git failure so the
    caller can turn it into a clean refusal.

    Reads straight from git (ls-tree / show below), never an export into a
    directory of its own: mkdtemp's directory is owner-only (0o700) and, since
    Python 3.13 on Windows, an elevated process's "owner" is the
    Administrators group, which leaves a later medium-integrity process unable
    to read anything left there. There is no directory to leak permissions
    from. (A URL source is the one case that needs a directory, for its bare
    clone; see clone_source.)"""
    proc = subprocess.run(["git", "-C", str(source), "ls-tree", "-r", "--name-only", "-z", ref], capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return {chunk.decode("utf-8") for chunk in proc.stdout.split(b"\x00") if chunk}


def read_source_blob(source: Path, rel: str, ref: str = "HEAD") -> bytes:
    """The exact bytes of one path at the source's committed ref (default
    HEAD), never its working tree."""
    proc = subprocess.run(["git", "-C", str(source), "show", f"{ref}:{rel}"], capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def read_kernel_manifest(source: Path, head_paths: set, ref: str = "HEAD") -> tuple:
    """(manifest_dict, version) read from the source's committed ref.
    version is 'unknown' when the manifest is missing, unreadable, or
    carries no string version, matching kernel_template_version's fallback."""
    if "harness/kernel-manifest.json" not in head_paths:
        return {}, "unknown"
    try:
        doc = json.loads(read_source_blob(source, "harness/kernel-manifest.json", ref).decode("utf-8-sig"))
    except (RuntimeError, ValueError, UnicodeDecodeError):
        return {}, "unknown"
    version = doc.get("version") if isinstance(doc, dict) else None
    return doc, (version if isinstance(version, str) and version else "unknown")


def kernel_manifest_paths(manifest: dict) -> list:
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, list):
        return []
    return sorted({f["path"] for f in files if isinstance(f, dict) and isinstance(f.get("path"), str)})


def load_adopted_doc(target: Path) -> dict:
    try:
        doc = json.loads((target / ADOPTED_FILES_REL).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def load_adopted_paths(target: Path) -> list:
    return [p for p in (load_adopted_doc(target).get("paths") or []) if isinstance(p, str)]


def load_adopted_hashes(target: Path) -> dict:
    raw = load_adopted_doc(target).get("hashes")
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}


def load_adopted_template_version(target: Path) -> str:
    version = load_adopted_doc(target).get("template_version")
    return version if isinstance(version, str) else ""


def host_kernel_version(target: Path) -> str:
    """The host's own harness/kernel-manifest.json version, or 'unknown'."""
    try:
        doc = json.loads((target / "harness" / "kernel-manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "unknown"
    version = doc.get("version") if isinstance(doc, dict) else None
    return version if isinstance(version, str) and version else "unknown"


def load_target_harness_owned(target: Path) -> set:
    path = target / "harness" / "registry" / "structure.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return set()
    owned = (doc.get("host") or {}).get("harness_owned") if isinstance(doc, dict) else None
    return {p for p in (owned or []) if isinstance(p, str)}


def build_upgrade_candidates(target: Path, adopted_paths: list, manifest_paths: list, target_tracked: set) -> tuple:
    """(candidates_sorted, adopted_set).

    candidates is every recorded adopted path (safe or not: an unsafe one is
    never stat'd here, only surfaced later so classify can report and skip
    it), plus every safe, in-scope source-manifest path the target's git
    does not track yet. Tracked, not merely present on disk: a path the
    manifest lists that already has some untracked or gitignored file
    sitting on it is still a candidate, so classify can report and skip it
    as `untracked on host` instead of silently vanishing here. adopted_set
    lets classify tell "recorded, now missing" (skip: removed on host)
    apart from "never adopted, manifest-new" (new).

    An unsafe manifest path is still added to the candidate set (without
    ever touching the filesystem) purely so it surfaces as `skip (unsafe
    path)` instead of silently vanishing. Never a path the target already
    tracks that the manifest lists but the target never adopted: an upgrade
    refreshes what it manages, it does not import a host's unrelated file
    that happens to share a path with the template, and never a path plain
    adopt itself would not have installed (brain/, etc.)."""
    adopted_set = set(adopted_paths)
    candidates = set(adopted_set)
    for rel in manifest_paths:
        if not is_safe_candidate_path(rel):
            candidates.add(rel)
            continue
        if not in_plain_adopt_scope(rel):
            continue
        if rel not in target_tracked:
            candidates.add(rel)
    return sorted(candidates), adopted_set


TAG_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]*$")


class BaseResolver:
    """Finds the common ancestor ("base") hash of one path for the three-way
    comparison. Order: the hash recorded in the host's adopted-files.json;
    else the source repository's blob at tag v<host kernel version>; else at
    tag v<adopted-files.json template_version>; else None (no base). A path
    absent at a tag means no base from that tag, and the next one is tried."""

    def __init__(self, source: Path, recorded: dict, versions: list):
        self.source = source
        self.recorded = recorded
        self.tag_shas = []
        seen = set()
        for version in versions:
            if not version or version == "unknown" or version in seen or not TAG_VERSION_RE.match(version):
                continue
            seen.add(version)
            code, out, _ = git(source, "rev-parse", "--verify", "--quiet", f"tags/v{version}^{{commit}}")
            if code == 0 and out.strip():
                self.tag_shas.append((f"v{version}", out.strip()))

    def base_hash(self, rel: str) -> tuple:
        """(hash, origin) or (None, None)."""
        recorded = self.recorded.get(rel)
        if isinstance(recorded, str) and recorded:
            return recorded, "recorded hash"
        for tag, sha in self.tag_shas:
            proc = subprocess.run(["git", "-C", str(self.source), "show", f"{sha}:{rel}"], capture_output=True, check=False)
            if proc.returncode == 0:
                return content_hash(proc.stdout), f"tag {tag}"
        return None, None


def conflict_sibling_path(rel: str) -> str:
    """Where a conflicting source version lands. The rule: `.harness` goes
    after the full name (offline-conformance.yml.harness, test_a.py.harness,
    run.sh.harness, pre-commit.harness) for everything except Markdown, so
    the sibling can never be collected by a test runner, run by CI, sourced
    as a script, or used as a hook. Only a `.md` file keeps the plain adopt
    form (name.harness.md): it is inert and renders as Markdown. Plain
    adopt's own naming (harness_name) is unchanged."""
    if rel.endswith(".md"):
        return harness_name(rel)
    return rel + ".harness"


def classify_upgrade_path(
    source: Path,
    target: Path,
    rel: str,
    head_paths: set,
    harness_owned: set,
    skip_globs: list,
    adopted_set: set,
    target_tracked: set,
    ref: str = "HEAD",
    resolver: "BaseResolver | None" = None,
) -> tuple:
    """(status, reason, src_bytes) for one candidate path. status is one of
    update, new, same, kept, conflict, skip, gone. reason is None except for
    skip, gone, kept and conflict. src_bytes is the fetched source content
    for update, new, or conflict (the caller needs it to write), None otherwise.

    Three-way outcome for a path present on both sides (CRLF-only differences
    count as equal): host == source -> same; host == base -> update; source ==
    base -> kept (a host edit, preserved); otherwise conflict. With no base
    at all, a host that differs from the source is a conflict."""
    if not is_safe_candidate_path(rel):
        return "skip", "unsafe path", None
    if rel in UPGRADE_FIXED_HOST_OWNED:
        return "skip", "host-owned (fixed)", None
    if is_harness_sibling_path(rel):
        return "skip", "harness-sibling (adoption-time artifact)", None
    if rel in harness_owned:
        return "skip", "host-owned (structure.json host.harness_owned)", None
    for pattern in skip_globs:
        if fnmatch.fnmatchcase(rel, pattern):
            return "skip", f"--skip {pattern}", None
    if path_has_link_component(target, rel):
        return "skip", "link in path", None

    dst_path = target / rel
    dst_exists = dst_path.is_file()
    if dst_exists and rel not in target_tracked:
        return "skip", "untracked on host", None
    if not dst_exists and rel in adopted_set:
        # Recorded by an earlier adoption, absent from disk now, and the
        # incomplete-checkout guard already passed: the host removed it on
        # purpose. Never recreate it; report it so a human can decide.
        return "skip", "removed on host", None
    if rel not in head_paths:
        return "gone", "recorded but absent from source HEAD; not deleted", None

    src_bytes = read_source_blob(source, rel, ref)
    if not dst_exists:
        return "new", None, src_bytes
    dst_bytes = dst_path.read_bytes()
    src_h = content_hash(src_bytes)
    dst_h = content_hash(dst_bytes)
    if src_h == dst_h:
        # CRLF-vs-LF alone is not a real difference on an autocrlf checkout;
        # the write path below always writes the source's exact bytes when a
        # genuine difference does trigger `update`.
        return "same", None, None
    base_h, origin = resolver.base_hash(rel) if resolver is not None else (None, None)
    if base_h is None:
        return "conflict", "no base to compare against", src_bytes
    if dst_h == base_h:
        return "update", None, src_bytes
    if src_h == base_h:
        return "kept", "host edit preserved, source unchanged since base", None
    return "conflict", f"host and source both changed since base ({origin})", src_bytes


def changelog_headings(text: str, old: str, new: str) -> list:
    """`## [x.y.z]` heading lines strictly after `old` and up to and
    including `new` (semantic-version order), in file order."""

    def vt(value):
        m = re.match(r"^(\d+)\.(\d+)\.(\d+)", value or "")
        return tuple(int(g) for g in m.groups()) if m else None

    lo, hi = vt(old), vt(new)
    if hi is None:
        return []
    found = []
    for line in text.splitlines():
        m = re.match(r"^## \[(\d+\.\d+\.\d+)[^\]]*\]", line)
        if not m:
            continue
        version = vt(m.group(1))
        if (lo is None or version > lo) and version <= hi:
            found.append(line.strip())
    return found


# --------------------------------------------------------------------------
# source resolution: local path or URL
# --------------------------------------------------------------------------

URL_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]+://", re.IGNORECASE)
SCP_LIKE_RE = re.compile(r"^[A-Za-z0-9._~+-]+@[A-Za-z0-9._-]+:\S")
USERINFO_RE = re.compile(r"([a-z][a-z0-9+.-]*://)[^/@\s]+@", re.IGNORECASE)


def is_url_source(value: str) -> bool:
    """True for scheme://... and user@host:path. A Windows drive path (in
    either slash form) or any relative or absolute local path stays local: the scheme
    needs two or more characters, so a single drive letter never matches."""
    return bool(URL_SCHEME_RE.match(value) or SCP_LIKE_RE.match(value))


def redact_url(value: str) -> str:
    """Drop userinfo (scheme://user:pass@ or scheme://token@) wherever it
    appears in text printed to the console, including git's error output."""
    return USERINFO_RE.sub(r"\1", value)


def _rmtree_force(path: str) -> None:
    """Remove a directory tree, clearing the read-only bit that git sets on
    pack files (shutil.rmtree otherwise fails on Windows)."""

    def handler(func, failed_path, _exc):
        try:
            os.chmod(failed_path, stat.S_IWRITE)
            func(failed_path)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=handler)
    else:
        shutil.rmtree(path, onerror=handler)


def clone_source(url: str) -> str:
    """Bare-clone a URL source into a fresh directory under the system temp
    directory and return its path; the caller removes it (cleanup_clone).
    The directory is made with os.mkdir under a random name rather than
    mkdtemp: mkdtemp's owner-only ACL is the elevated-Python-3.13 trap the
    source_head_paths docstring describes, and a plain mkdir inherits the
    temp directory's normal permissions. On POSIX the directory is owner-only
    (the clone config holds the URL); on Windows no mode is passed, because
    Python 3.13 turns a mode into the same owner-only ACL. Raises
    RuntimeError on failure (the directory is already removed then)."""
    path = os.path.join(tempfile.gettempdir(), "adopt-src-" + secrets.token_hex(8))
    os.mkdir(path)
    if os.name != "nt":
        os.chmod(path, 0o700)  # before the clone writes its config
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        proc = subprocess.run(
            ["git", "-c", "protocol.ext.allow=never", "clone", "--bare", "--quiet", "--", url, path],
            capture_output=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        cleanup_clone(path)
        raise RuntimeError(redact_url(str(exc)))
    if proc.returncode != 0:
        cleanup_clone(path)
        raise RuntimeError(redact_url(proc.stderr.decode("utf-8", "replace").strip()))
    return path


def cleanup_clone(path: str) -> None:
    try:
        _rmtree_force(path)
    except OSError:
        pass
    if os.path.exists(path):
        print(f"adopt --upgrade: WARN: could not remove temporary clone {path}; delete it by hand", file=sys.stderr)


UPGRADE_OUTCOMES = ("update", "new", "same", "kept", "conflict", "skip", "gone")


def upgrade_summary_line(results: dict) -> str:
    counts = ", ".join(f"{name} {len(results[name])}" for name in UPGRADE_OUTCOMES)
    return f"adopt --upgrade: summary: {counts}"


def upgrade_main(args, source: Path, target: Path, ref: str | None = None, display: str | None = None) -> int:
    """ref None: the source is a local working tree read at HEAD, exactly as
    before. A ref (explicit --ref, or any URL source) switches the source
    checks to the ref so they work on a bare clone."""
    why = upgrade_target_refusal(target) or upgrade_cross_refusal(source, target)
    read_ref = "HEAD"
    if not why and ref is None:
        why = upgrade_source_refusal(source)
    elif not why:
        code, _o, _e = git(source, "rev-parse", "--git-dir")
        if code != 0:
            why = "source is not a git repository (git rev-parse --git-dir failed)"
        else:
            sha, why = resolve_source_ref(source, ref)
            if not why:
                read_ref = sha
                why = upgrade_source_refusal(source, sha)
    if why:
        print(f"adopt --upgrade: refused: {why}", file=sys.stderr)
        return 2

    label = ref if ref is not None else "HEAD"
    code, sha_out, _ = git(source, "rev-parse", "--short", read_ref)
    source_sha = sha_out.strip() if code == 0 else "unknown"

    try:
        head_paths = source_head_paths(source, read_ref)
    except RuntimeError as exc:
        print(f"adopt --upgrade: refused: could not read source {label}: {redact_url(str(exc))}", file=sys.stderr)
        return 2

    if "harness/kernel-manifest.json" not in head_paths:
        print(f"adopt --upgrade: refused: source has no harness/kernel-manifest.json at {label}", file=sys.stderr)
        return 2

    manifest, kernel_version = read_kernel_manifest(source, head_paths, read_ref)
    print(f"adopt --upgrade: source {label} {source_sha}, kernel version {kernel_version}")

    old_version = host_kernel_version(target)
    print(f"adopt --upgrade: host kernel version {old_version} -> {kernel_version}")
    if "CHANGELOG.md" in head_paths:
        try:
            changelog_text = read_source_blob(source, "CHANGELOG.md", read_ref).decode("utf-8", "replace")
        except RuntimeError:
            changelog_text = ""
        headings = changelog_headings(changelog_text, old_version, kernel_version)
        if headings:
            print("adopt --upgrade: read these Upgrade notes in the source CHANGELOG.md:")
            for heading in headings:
                print(f"  {heading}")
        else:
            print("adopt --upgrade: no CHANGELOG.md release headings between those versions")
    else:
        print("adopt --upgrade: source has no CHANGELOG.md; no Upgrade notes to list")

    adopted_paths = load_adopted_paths(target)
    manifest_paths = kernel_manifest_paths(manifest)
    target_tracked = target_tracked_paths(target)
    candidates, adopted_set = build_upgrade_candidates(target, adopted_paths, manifest_paths, target_tracked)
    harness_owned = load_target_harness_owned(target)
    skip_globs = args.skip or []
    resolver = BaseResolver(source, load_adopted_hashes(target), [old_version, load_adopted_template_version(target)])

    results = {name: [] for name in UPGRADE_OUTCOMES}
    content_cache = {}
    sibling_writes = {}  # conflicting rel -> sibling path that will be written
    sibling_blocked = set()  # conflicting rel whose sibling already exists
    mode_label = "apply" if args.apply else "dry run"
    print(f"adopt --upgrade ({mode_label}): {display or source} -> {target}")
    for rel in candidates:
        status, reason, src_bytes = classify_upgrade_path(
            source, target, rel, head_paths, harness_owned, skip_globs, adopted_set, target_tracked, read_ref, resolver
        )
        results[status].append(rel)
        if src_bytes is not None:
            content_cache[rel] = src_bytes
        if status == "same":
            continue
        if status == "conflict":
            sibling = conflict_sibling_path(rel)
            if os.path.lexists(target / sibling) or path_has_link_component(target, sibling):
                sibling_blocked.add(rel)
                print(f"  conflict (sibling exists) {rel} -> {sibling} ({reason}); nothing written for it")
            else:
                sibling_writes[rel] = sibling
                print(f"  conflict {rel} -> {sibling} ({reason})")
        elif status in ("skip", "gone", "kept"):
            print(f"  {status:<6} {rel} ({reason})")
        else:
            print(f"  {status:<6} {rel}")
    print(f"  {len(results['same'])} file(s) unchanged (same)")

    write_paths = sorted(results["update"] + results["new"])
    sibling_paths = sorted(sibling_writes.values())
    all_written = sorted(write_paths + sibling_paths)

    if not args.apply:
        if all_written:
            scripts = [rel for rel in all_written if is_script_path(rel)]
            extra = f"; would stage the executable bit on {len(scripts)} script(s)" if scripts else ""
            siblings_note = f" (including {len(sibling_paths)} conflict sibling(s))" if sibling_paths else ""
            print(f"adopt --upgrade: dry run would write {len(all_written)} file(s){siblings_note}{extra}; pass -y/--apply to perform these actions")
        else:
            print("adopt --upgrade: dry run, nothing to write; pass -y/--apply to update adopted-files.json's template_version regardless")
        if results["gone"]:
            print(f"adopt --upgrade: {len(results['gone'])} path(s) recorded but absent from source HEAD; review before deciding")
        print(upgrade_summary_line(results))
        return 0

    written = []
    try:
        for rel in write_paths:
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content_cache[rel])
            written.append(rel)
        for rel, sibling in sorted(sibling_writes.items()):
            dst = target / sibling
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content_cache[rel])
            written.append(sibling)
    except OSError as exc:
        print(
            f"adopt --upgrade: FATAL: write failed after {len(written)} of {len(all_written)} file(s); "
            f"not claiming success: {exc}",
            file=sys.stderr,
        )
        for rel in written:
            print(f"  written: {rel}", file=sys.stderr)
        return 1

    script_paths = [rel for rel in all_written if is_script_path(rel)]
    staged, warning = set_executable_bits(target, script_paths)
    if warning:
        print(f"adopt --upgrade: WARN: could not stage the executable bit; run manually: {warning}", file=sys.stderr)
    elif staged:
        print(f"adopt --upgrade: staged {len(staged)} script(s) with the executable bit")

    # Hashes: the source hash for update, new, same and conflict (a conflict
    # records it so the same upstream change does not conflict again next
    # release), nothing for kept, skip, gone, or a conflict whose sibling
    # could not be written (the source version was not delivered).
    new_hashes = {}
    for rel in write_paths:
        new_hashes[rel] = content_hash(content_cache[rel])
    for rel in sibling_writes:
        new_hashes[rel] = content_hash(content_cache[rel])
    for rel in results["same"]:
        try:
            new_hashes[rel] = content_hash((target / rel).read_bytes())
        except OSError:
            continue
    merged, total, added = write_adopted_files(target, all_written, kernel_version, new_hashes)
    if merged:
        print(f"adopt --upgrade: harness/registry/adopted-files.json merged ({added} new path(s), {total} total, template_version {kernel_version})")
    else:
        print(f"adopt --upgrade: harness/registry/adopted-files.json written ({total} path(s), template_version {kernel_version})")

    code, diff_out, diff_err = git(target, "diff", "--name-status")
    if code != 0:
        print(f"adopt --upgrade: FATAL: could not verify no deletions occurred (git diff failed): {diff_err.strip()}", file=sys.stderr)
        return 1
    code2, ls_deleted, ls_err = git(target, "ls-files", "-d")
    if code2 != 0:
        print(f"adopt --upgrade: FATAL: could not verify no deletions occurred (git ls-files -d failed): {ls_err.strip()}", file=sys.stderr)
        return 1
    deletions = [line for line in diff_out.splitlines() if line.startswith("D\t")]
    if deletions or ls_deleted.strip():
        print("adopt --upgrade: FATAL: a deletion appeared after apply; refusing to proceed silently", file=sys.stderr)
        for line in deletions:
            print(f"  {line}", file=sys.stderr)
        for line in ls_deleted.splitlines():
            if line.strip():
                print(f"  missing: {line}", file=sys.stderr)
        return 1

    if results["gone"]:
        print(f"adopt --upgrade: {len(results['gone'])} path(s) recorded but absent from source HEAD; review before deciding")
    if results["kept"]:
        print(f"adopt --upgrade: {len(results['kept'])} host-edited file(s) kept as they are (listed above as kept)")
    if results["conflict"]:
        print(f"adopt --upgrade: {len(results['conflict'])} conflict(s): merge each source sibling into its file by hand, then delete the sibling")
    print("adopt --upgrade: applied")
    print(upgrade_summary_line(results))
    return 0


def upgrade_entry(args, target: Path) -> int:
    """Resolve --source (local path or URL) and --ref, then run the upgrade."""
    if args.source.startswith("-"):
        print("adopt --upgrade: refused: --source must not start with '-'", file=sys.stderr)
        return 2
    if args.ref is not None and (not args.ref or args.ref.startswith("-")):
        print(f"adopt --upgrade: refused: invalid ref {args.ref!r} (must not be empty or start with '-')", file=sys.stderr)
        return 2
    if is_url_source(args.source):
        try:
            clone = clone_source(args.source)
        except RuntimeError as exc:
            print(f"adopt --upgrade: refused: could not clone {redact_url(args.source)}: {exc}", file=sys.stderr)
            return 2
        try:
            return upgrade_main(args, Path(clone), target, args.ref or "HEAD", redact_url(args.source))
        finally:
            cleanup_clone(clone)
    return upgrade_main(args, Path(args.source).resolve(), target, args.ref)


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
        "host.profile is written as team (an adopted repository is by definition someone else's shared repository). Solo adopter: switch it with python harness/tools/init.py --profile solo --yes",
    ]
    if mode == "branches":
        items.append(f"Branches mode detected: {local_note}. Keep personal notes out of pull requests: the local lane is untracked and, once the validator admits it, lives outside the repository.")
    if structure["contract"]["mode"] == "host-owned":
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
    parser.add_argument("--upgrade", action="store_true", help="refresh an already-adopted host from a newer template at --source, instead of installing into a fresh target")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="print every action and write nothing (default)")
    group.add_argument("-y", "--apply", action="store_true", help="perform the actions")
    parser.add_argument("--source", default=str(ROOT), help="harness repository to install from: a local path, or with --upgrade a git URL (default: this repository)")
    parser.add_argument("--ref", default=None, metavar="REF", help="--upgrade only: read the source at this tag, branch, or commit instead of HEAD (a URL source defaults to the remote HEAD)")
    parser.add_argument("--skip", action="append", default=[], metavar="GLOB", help="exclude a path from --upgrade (fnmatch glob on the repo-relative POSIX path; repeatable)")
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()

    if args.upgrade:
        return upgrade_entry(args, target)
    if args.ref is not None or is_url_source(args.source):
        print("adopt: refused: --ref and a URL --source are for --upgrade only", file=sys.stderr)
        return 2
    source = Path(args.source).resolve()

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
    if structure["contract"]["mode"] == "host-owned":
        print(
            f"  contract: host-owned (target already has AGENTS.md; the template contract lands as "
            f"AGENTS.harness.md, {len(structure['host']['harness_owned'])} pre-existing harness/ path(s) "
            f"recorded as host-owned)"
        )
    else:
        print("  contract: rendered (no pre-existing AGENTS.md; bootstrap renders the root file)")
    print("  host profile: team (adopted default)")
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
        copy_hashes = {}
        for verb, _src_rel, dst_rel in actions:
            if verb == "copy":
                try:
                    copy_hashes[dst_rel] = content_hash((target / dst_rel).read_bytes())
                except OSError:
                    continue
        merged, total, added = write_adopted_files(target, new_adopted_paths, template_version, copy_hashes)
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
