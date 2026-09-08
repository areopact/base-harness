#!/usr/bin/env python3
"""Materialization engine behind bootstrap.sh and bootstrap.ps1.

Both shell entry points delegate here so behavior cannot diverge across
operating systems. The engine reads harness/bootstrap/junctions.json plus
harness/registry/selection.json, renders the contract, creates or repairs
every declared destination, materializes the selected skills per runtime,
prunes deselected harness-managed entries, runs the optional extension
point, and registers the git hook floor.

Invariants (each has a test under harness/bootstrap/tests):

- A destination that is empty, resolves to the repository root, or resolves
  outside the repository root is refused before any removal happens and
  counts as drift.
- A real directory that carries no harness marker is never recursively
  removed. Reparse points and symlinks are unlinked non-recursively.
- A manifest that fails to parse aborts with exit 3; it never yields zero
  entries silently.
- managed-copy destinations are independent byte copies, never hardlinks or
  symlinks; a linked destination is reported as drift and replaced.
- A junction row whose destination is a per-skill directory is fulfilled by
  per-skill materialization (one link per selected skill), never by a link
  to the whole skill tree, so selection stays enforcing.

Exit codes: 0 clean, 1 drift or unresolved conflict, 2 missing prerequisite,
3 manifest parse failure.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.dont_write_bytecode = True
BOOTSTRAP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BOOTSTRAP_DIR))
import build_codex_adapter  # noqa: E402
import build_opencode_adapter  # noqa: E402
import contract_files  # noqa: E402
from skill_catalog import SKILLS_RELATIVE, SkillError, selected_skills  # noqa: E402

ROOT = BOOTSTRAP_DIR.parents[1]
MANIFEST = Path("harness/bootstrap/junctions.json")
SKILLS_DIR = Path(SKILLS_RELATIVE)
EXTENSIONS_DIR = Path("harness/bootstrap/extensions")
GIT_HOOKS_DIR = ".githooks"
CONTRACT_OUTPUT = "AGENTS.md"
MODES = ("link", "managed-copy", "generated", "contract-render")
RUNTIMES = ("claude", "codex", "opencode")
MARKER = ".generated-by"
MARKER_BYTES = b"harness/bootstrap/materialize.py\n"
IGNORED_NAMES = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc"}
EXIT_CLEAN, EXIT_DRIFT, EXIT_PREREQ, EXIT_MANIFEST = 0, 1, 2, 3


class ManifestError(Exception):
    """junctions.json is missing, unparseable, or has an invalid shape."""


@dataclass(frozen=True)
class Action:
    kind: str
    src: str
    dst: str
    mode: str
    runtime: str = "all"
    description: str = ""


@dataclass
class Result:
    changed: int = 0
    drift: int = 0
    conflicts: int = 0
    lines: list[str] = field(default_factory=list)

    def say(self, tag: str, message: str) -> None:
        self.lines.append(f"  {tag:<8} {message}")

    def ok(self, message: str) -> None:
        self.say("OK", message)

    def made(self, message: str) -> None:
        self.changed += 1
        self.say("MADE", message)

    def synced(self, message: str) -> None:
        self.changed += 1
        self.say("SYNCED", message)

    def pruned(self, message: str) -> None:
        self.changed += 1
        self.say("PRUNED", message)

    def drifted(self, message: str) -> None:
        self.drift += 1
        self.say("DRIFT", message)

    def conflict(self, message: str) -> None:
        self.conflicts += 1
        self.say("CONFLICT", message)

    def abort(self, message: str) -> None:
        self.drift += 1
        self.say("ABORT", message)

    def note(self, message: str) -> None:
        self.say("NOTE", message)

    def warn(self, message: str) -> None:
        self.say("WARN", message)

    @property
    def clean(self) -> bool:
        return self.drift == 0 and self.conflicts == 0


# ---------------------------------------------------------------- manifest --


def load_manifest(root: Path) -> dict:
    """Parse and shape-check junctions.json. Any failure raises ManifestError."""
    path = Path(root) / MANIFEST
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"cannot parse {MANIFEST.as_posix()}: {exc}") from exc
    if not isinstance(document, dict):
        raise ManifestError(f"{MANIFEST.as_posix()} must contain one object")
    if document.get("schema_version") != 1:
        raise ManifestError(f"{MANIFEST.as_posix()} schema_version must be 1")
    junctions = document.get("junctions")
    if not isinstance(junctions, list):
        raise ManifestError(f"{MANIFEST.as_posix()} junctions must be a list")
    for index, entry in enumerate(junctions):
        if not isinstance(entry, dict):
            raise ManifestError(f"junctions[{index}] must be an object")
        for key in ("src", "dst", "mode"):
            if not isinstance(entry.get(key), str):
                raise ManifestError(f"junctions[{index}] {key} must be a string")
        if entry["mode"] not in MODES:
            raise ManifestError(f"junctions[{index}] mode '{entry['mode']}' is not one of {', '.join(MODES)}")
        if not entry["src"].strip():
            raise ManifestError(f"junctions[{index}] src is empty")
    retired = document.get("retired_destinations", [])
    if not isinstance(retired, list):
        raise ManifestError(f"{MANIFEST.as_posix()} retired_destinations must be a list")
    for index, entry in enumerate(retired):
        if not isinstance(entry, dict) or not isinstance(entry.get("dst"), str):
            raise ManifestError(f"retired_destinations[{index}] must be an object with a dst string")
    per_skill = document.get("per_skill", {})
    if not isinstance(per_skill, dict):
        raise ManifestError(f"{MANIFEST.as_posix()} per_skill must be an object")
    for runtime, block in per_skill.items():
        if runtime not in RUNTIMES or not isinstance(block, dict):
            raise ManifestError(f"per_skill.{runtime} is not a known runtime block")
        if block.get("mode") not in {"link", "generated"} or not isinstance(block.get("dst_dir"), str):
            raise ManifestError(f"per_skill.{runtime} needs mode link|generated and a dst_dir string")
        for key in ("link_as", "commands_dir"):
            if key in block and not isinstance(block[key], str):
                raise ManifestError(f"per_skill.{runtime}.{key} must be a string")
    return document


def per_skill_destinations(manifest: dict) -> set[str]:
    """Destinations owned by per-skill materialization rather than a whole-tree link."""
    owned: set[str] = set()
    for block in manifest.get("per_skill", {}).values():
        owned.add(block["dst_dir"])
        if block.get("link_as"):
            owned.add(block["link_as"])
    return owned


def safe_destination(root: Path, relative: str) -> Path | None:
    """Return the absolute destination when it is strictly inside root, else None."""
    if not isinstance(relative, str) or not relative.strip():
        return None
    if os.path.isabs(relative) or relative.startswith(("\\", "/")) or (len(relative) > 1 and relative[1] == ":"):
        return None
    root_real = Path(os.path.realpath(root))
    candidate = Path(os.path.abspath(os.path.join(root_real, relative)))
    if candidate == root_real:
        return None
    try:
        if os.path.commonpath([root_real, candidate]) != str(root_real):
            return None
    except ValueError:
        return None
    return candidate


def plan(root: Path, mode: str = "link") -> list[Action]:
    """Return the ordered actions the engine would apply for root."""
    root = Path(root)
    manifest = load_manifest(root)
    owned = per_skill_destinations(manifest)
    actions: list[Action] = [Action("contract", "harness/CONTRACT.md", CONTRACT_OUTPUT, "contract-render")]
    for entry in manifest["junctions"]:
        if entry["mode"] == "contract-render" or entry["dst"] in owned:
            continue
        actions.append(
            Action("junction", entry["src"], entry["dst"], entry["mode"], entry.get("runtime", "all"), entry.get("description", ""))
        )
    for entry in manifest.get("retired_destinations", []):
        actions.append(Action("retired", "", entry["dst"], "retire", "all", entry.get("replacement", "")))
    per_skill = manifest.get("per_skill", {})
    try:
        skills, selected, _ = selected_skills(root)
    except (SkillError, json.JSONDecodeError, OSError):
        skills, selected = {}, []
    for runtime in RUNTIMES:
        block = per_skill.get(runtime)
        if not block:
            continue
        if block["mode"] == "link" or block.get("link_as"):
            for name in selected:
                actions.append(Action("skill", skills[name].relative, f"{block['dst_dir']}/{name}", mode, runtime))
        if block.get("link_as"):
            actions.append(Action("junction", block["dst_dir"], block["link_as"], "link", runtime, "selected skill tree"))
    return actions


# ------------------------------------------------------------ filesystem --


def _is_junction(path: Path) -> bool:
    checker = getattr(os.path, "isjunction", None)
    try:
        if checker is not None:
            return bool(checker(path))
        if os.name == "nt":
            attributes = os.lstat(path).st_file_attributes
            return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT) and not os.path.islink(path)
    except OSError:
        return False
    return False


def is_link(path: Path) -> bool:
    return path.is_symlink() or _is_junction(path)


def remove_link(path: Path) -> None:
    """Unlink a symlink or junction without touching what it points at."""
    try:
        os.rmdir(path)
    except OSError:
        os.unlink(path)


def make_link(src: Path, dst: Path) -> str:
    """Create a directory link from dst to src; return the link kind."""
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(src), str(dst))
        return "junction"
    os.symlink(str(src), str(dst))
    if not dst.is_symlink():
        raise OSError(f"{dst} is a copy, not a symlink (filesystem or shell substituted a copy)")
    return "symlink"


def link_matches(dst: Path, src: Path) -> bool:
    try:
        return os.path.realpath(dst) == os.path.realpath(src)
    except OSError:
        return False


def _ignored(relative_parts: tuple[str, ...]) -> bool:
    if any(part in IGNORED_NAMES for part in relative_parts):
        return True
    return Path(relative_parts[-1]).suffix in IGNORED_SUFFIXES if relative_parts else False


def _file_map(directory: Path) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        parts = path.relative_to(directory).parts
        if _ignored(parts):
            continue
        relative = "/".join(parts)
        if relative == MARKER:
            continue
        files[relative] = path
    return files


def dirs_equal(left: Path, right: Path) -> bool:
    left_files, right_files = _file_map(left), _file_map(right)
    if set(left_files) != set(right_files):
        return False
    for relative, path in left_files.items():
        if path.read_bytes() != right_files[relative].read_bytes():
            return False
    return True


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, symlinks=False, ignore=shutil.ignore_patterns(*IGNORED_NAMES, "*.pyc"))


def sync_tree(src: Path, dst: Path) -> None:
    """Bring an existing copy in line with src file by file; never rmtree."""
    src_files = _file_map(src)
    dst_files = _file_map(dst)
    for relative, path in src_files.items():
        target = dst / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_bytes()
        if not target.is_file() or target.read_bytes() != content:
            target.write_bytes(content)
    for relative, path in dst_files.items():
        if relative not in src_files:
            path.unlink()
    for directory in sorted((p for p in dst.rglob("*") if p.is_dir() and not is_link(p)), key=lambda p: len(p.parts), reverse=True):
        if not any(directory.iterdir()):
            os.rmdir(directory)


def is_hardlink_of(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def write_file_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    temporary = dst.with_name(f".{dst.name}.tmp")
    shutil.copyfile(src, temporary)
    os.replace(temporary, dst)


# -------------------------------------------------------------- engine --


class Engine:
    def __init__(self, root: Path, check: bool, force: bool, copy: bool) -> None:
        self.root = Path(os.path.realpath(root))
        self.check = check
        self.force = force
        self.copy = copy
        self.result = Result()
        self.refused: set[str] = set()

    # -- helpers ---------------------------------------------------------

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def destination(self, relative: str) -> Path | None:
        if relative in self.refused:
            return None
        path = safe_destination(self.root, relative)
        if path is None:
            self.refused.add(relative)
            self.result.abort(f"refusing dangerous or empty destination '{relative}'")
        return path

    # -- preflight -------------------------------------------------------

    def validate_manifest_destinations(self, manifest: dict) -> None:
        """Refuse every unsafe destination before any removal happens."""
        candidates: list[str] = [entry["dst"] for entry in manifest["junctions"]]
        candidates += [entry["dst"] for entry in manifest.get("retired_destinations", [])]
        for block in manifest.get("per_skill", {}).values():
            candidates.append(block["dst_dir"])
            for key in ("link_as", "commands_dir"):
                if key in block:
                    candidates.append(block[key])
        for relative in candidates:
            self.destination(relative)

    def registry_preflight(self) -> bool:
        tools = self.root / "harness" / "tools"
        validator = tools / "harness_registry.py"
        if not validator.is_file():
            self.result.note("registry validator not present (harness/tools/harness_registry.py); preflight skipped")
            return True
        sys.path.insert(0, str(tools))
        try:
            module = __import__("harness_registry")
        except Exception as exc:  # noqa: BLE001 - a broken validator must not crash the engine
            self.result.drifted(f"registry validator failed to import ({exc})")
            return False
        finally:
            sys.path.pop(0)
        validate_all = getattr(module, "validate_all", None)
        if validate_all is None:
            self.result.note("registry validator exposes no validate_all(); preflight skipped")
            return True
        try:
            try:
                errors = validate_all(self.root)
            except TypeError:
                errors = validate_all()
        except Exception as exc:  # noqa: BLE001
            self.result.drifted(f"registry preflight raised ({exc})")
            return False
        if errors:
            for error in errors:
                self.result.drifted(f"registry preflight: {error}")
            return False
        self.result.ok("registry preflight passed")
        return True

    # -- contract --------------------------------------------------------

    def contract(self, manifest: dict) -> None:
        host_owned = contract_files.contract_mode(self.root) == "host-owned"
        ok_message = (
            "contract: host-owned (AGENTS.md is the host's; template block at AGENTS.harness.md)"
            if host_owned
            else "AGENTS.md rendered from CONTRACT.md + CONTRACT.host.md; CLAUDE.md pointer exact"
        )
        if self.check:
            issues = contract_files.check_contract(self.root)
            if issues:
                for issue in issues:
                    self.result.drifted(f"contract: {issue}")
            else:
                self.result.ok(ok_message)
        else:
            try:
                changed = contract_files.repair_contract(self.root)
            except (OSError, UnicodeDecodeError) as exc:
                self.result.drifted(f"contract render failed: {exc}")
                return
            if changed:
                self.result.synced("contract: " + ", ".join(changed))
            else:
                self.result.ok(ok_message)
        advisory = contract_files.contract_advisory(self.root)
        if advisory:
            self.result.warn(advisory)
        # Every contract-render row is served by the root render. A second
        # rendered copy elsewhere would load the contract twice in a runtime
        # that also reads the root pointer, so any other declared destination
        # is kept absent.
        for entry in manifest["junctions"]:
            if entry["mode"] != "contract-render" or entry["dst"] == CONTRACT_OUTPUT:
                continue
            self.absent_contract_copy(entry["dst"])

    def absent_contract_copy(self, dst_rel: str) -> None:
        dst = self.destination(dst_rel)
        if dst is None:
            return
        if not dst.exists() and not dst.is_symlink():
            self.result.ok(f"{dst_rel} absent (the root {CONTRACT_OUTPUT} render serves this runtime)")
            return
        if dst.is_symlink() or dst.is_file():
            if self.check:
                self.result.drifted(f"{dst_rel} exists; the contract is served by the root render only (run bootstrap)")
                return
            dst.unlink()
            self.result.pruned(f"{dst_rel} (second contract copy removed; root {CONTRACT_OUTPUT} serves it)")
            return
        self.result.conflict(f"{dst_rel} is a directory where no contract copy belongs; move it aside")

    # -- junction entries ------------------------------------------------

    def link_entry(self, src_rel: str, dst_rel: str) -> None:
        dst = self.destination(dst_rel)
        if dst is None:
            return
        src = self.root / src_rel
        if not src.is_dir():
            self.result.drifted(f"{dst_rel}: canonical source {src_rel} missing or not a directory")
            return
        if not dst.exists() and not dst.is_symlink():
            if self.check:
                self.result.drifted(f"{dst_rel} missing (run bootstrap)")
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                if self.copy:
                    copy_tree(src, dst)
                    kind = "copy"
                else:
                    kind = make_link(src, dst)
            except OSError as exc:
                self.result.drifted(f"{dst_rel}: cannot create ({exc})")
                return
            self.result.made(f"{dst_rel} -> {src_rel} ({kind})")
            return
        if is_link(dst):
            if link_matches(dst, src):
                self.result.ok(f"{dst_rel} -> {src_rel}")
                return
            if self.check:
                self.result.drifted(f"{dst_rel} links to the wrong target")
                return
            remove_link(dst)
            kind = make_link(src, dst)
            self.result.synced(f"{dst_rel} -> {src_rel} (stale link replaced, {kind})")
            return
        if dst.is_dir():
            if dirs_equal(src, dst):
                self.result.ok(f"{dst_rel} (content-equal copy of {src_rel})")
                return
            if self.check:
                self.result.drifted(f"{dst_rel} is a real directory whose content differs from {src_rel}")
                return
            if self.copy:
                sync_tree(src, dst)
                self.result.synced(f"{dst_rel} (copy resynced from {src_rel})")
                return
            if self.force:
                self.result.conflict(
                    f"{dst_rel} is a real directory; refusing to recursively remove it even with --force. "
                    f"Move it aside, or run --copy to resync it in place."
                )
            else:
                self.result.conflict(f"{dst_rel} is a real directory with different content; move it aside or run --copy")
            return
        # A regular file (or other non-directory) where a directory link belongs.
        if self.check:
            self.result.drifted(f"{dst_rel} is a file where a directory link belongs")
            return
        if not self.force:
            self.result.conflict(f"{dst_rel} exists and is not a link; rerun with --force to replace the file")
            return
        dst.unlink()
        if self.copy:
            copy_tree(src, dst)
            kind = "copy"
        else:
            kind = make_link(src, dst)
        self.result.made(f"{dst_rel} -> {src_rel} (replaced file, {kind})")

    def managed_copy_entry(self, src_rel: str, dst_rel: str) -> None:
        dst = self.destination(dst_rel)
        if dst is None:
            return
        src = self.root / src_rel
        if not src.is_file():
            self.result.drifted(f"{dst_rel}: canonical source {src_rel} missing or not a file")
            return
        content = src.read_bytes()
        if dst.is_symlink():
            if self.check:
                self.result.drifted(f"{dst_rel} is a symlink; managed copies are independent files")
                return
            dst.unlink()
            write_file_copy(src, dst)
            self.result.synced(f"{dst_rel} (symlink replaced by an independent copy)")
            return
        if not dst.exists():
            if self.check:
                self.result.drifted(f"{dst_rel} missing (run bootstrap)")
                return
            write_file_copy(src, dst)
            self.result.made(f"{dst_rel} <- {src_rel} (managed copy)")
            return
        if dst.is_dir():
            self.result.conflict(f"{dst_rel} is a directory where a managed file belongs; move it aside")
            return
        if is_hardlink_of(src, dst):
            if self.check:
                self.result.drifted(f"{dst_rel} is a hardlink of {src_rel}; managed copies are independent files")
                return
            dst.unlink()
            write_file_copy(src, dst)
            self.result.synced(f"{dst_rel} (hardlink replaced by an independent copy)")
            return
        if dst.read_bytes() == content:
            self.result.ok(f"{dst_rel} <- {src_rel} (managed copy)")
            return
        if self.check:
            self.result.drifted(f"{dst_rel} differs from {src_rel}")
            return
        write_file_copy(src, dst)
        self.result.synced(f"{dst_rel} <- {src_rel} (managed copy resynced)")

    def generated_entry(self, src_rel: str, dst_rel: str) -> None:
        dst = self.destination(dst_rel)
        if dst is None:
            return
        normalized = dst_rel.replace("\\", "/").rstrip("/")
        if normalized.endswith(".agents/skills"):
            builder, label = build_codex_adapter, "Codex skill catalog"
            render, diff, write = builder.render_catalog, builder.diff_catalog, builder.write_catalog
        elif normalized.endswith(".opencode/commands"):
            builder, label = build_opencode_adapter, "OpenCode command catalog"
            render, diff, write = builder.render_commands, builder.diff_commands, builder.write_commands
        else:
            self.result.drifted(f"{dst_rel}: no generator is registered for this generated destination")
            return
        try:
            if self.check:
                files, warnings = render(self.root)
                problems, notes = diff(dst, files)
                for message in warnings + notes:
                    self.result.note(f"{dst_rel}: {message}")
                if problems:
                    for problem in problems:
                        self.result.drifted(f"{dst_rel}: {problem}")
                else:
                    stats = json.loads(files[".catalog.json"])
                    count = stats.get("skills", stats.get("commands", 0))
                    self.result.ok(f"{dst_rel} exact ({count} generated from {src_rel})")
                return
            files, _ = render(self.root)
            problems, _ = diff(dst, files)
            stats, notes = write(self.root, dst)
            for message in notes:
                if message.startswith("pruned "):
                    self.result.pruned(f"{dst_rel}/{message[7:]}")
                else:
                    self.result.note(f"{dst_rel}: {message}")
            count = stats.get("skills", stats.get("commands", 0))
            if problems:
                self.result.synced(f"{dst_rel} ({label}: {count} generated)")
            else:
                self.result.ok(f"{dst_rel} exact ({count} generated from {src_rel})")
        except (OSError, RuntimeError, SkillError, json.JSONDecodeError) as exc:
            self.result.drifted(f"{dst_rel}: {label} failed ({exc})")

    def retired_entry(self, dst_rel: str, replacement: str) -> None:
        dst = self.destination(dst_rel)
        if dst is None:
            return
        if not dst.exists() and not dst.is_symlink():
            return
        if is_link(dst):
            if self.check:
                self.result.drifted(f"{dst_rel} is retired (replacement: {replacement}); run bootstrap")
                return
            remove_link(dst)
            self.result.pruned(f"{dst_rel} (retired; replacement {replacement})")
            return
        self.result.conflict(f"{dst_rel} is retired but is not a managed link; move it aside manually")

    # -- per-skill materialization ---------------------------------------

    def skill_dir_entry(self, dst_dir_rel: str, name: str, src_rel: str) -> None:
        dst_rel = f"{dst_dir_rel}/{name}"
        dst = self.destination(dst_rel)
        if dst is None:
            return
        src = self.root / src_rel
        if not src.is_dir():
            self.result.drifted(f"{dst_rel}: skill source {src_rel} missing")
            return
        if not dst.exists() and not dst.is_symlink():
            if self.check:
                self.result.drifted(f"{dst_rel} missing (selected skill not materialized)")
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            if self.copy:
                copy_tree(src, dst)
                (dst / MARKER).write_bytes(MARKER_BYTES)
                self.result.made(f"{dst_rel} (copy of {src_rel})")
            else:
                kind = make_link(src, dst)
                self.result.made(f"{dst_rel} -> {src_rel} ({kind})")
            return
        if is_link(dst):
            if link_matches(dst, src):
                self.result.ok(f"{dst_rel} -> {src_rel}")
                return
            if self.check:
                self.result.drifted(f"{dst_rel} links to the wrong target")
                return
            remove_link(dst)
            kind = make_link(src, dst)
            self.result.synced(f"{dst_rel} (stale link replaced, {kind})")
            return
        if dst.is_dir():
            managed = (dst / MARKER).is_file()
            if dirs_equal(src, dst):
                self.result.ok(f"{dst_rel} (content-equal copy)")
                return
            if self.check:
                self.result.drifted(f"{dst_rel} is a real directory whose content differs from the skill source")
                return
            if managed or self.copy:
                sync_tree(src, dst)
                (dst / MARKER).write_bytes(MARKER_BYTES)
                self.result.synced(f"{dst_rel} (copy resynced)")
                return
            self.result.conflict(f"{dst_rel} is an unmanaged real directory with different content; move it aside")
            return
        if self.check:
            self.result.drifted(f"{dst_rel} is a file where a skill directory belongs")
            return
        if not self.force:
            self.result.conflict(f"{dst_rel} exists and is not a link; rerun with --force to replace the file")
            return
        dst.unlink()
        self.skill_dir_entry(dst_dir_rel, name, src_rel)

    def prune_dir(self, dst_dir_rel: str, selected: list[str]) -> None:
        dst_dir = self.destination(dst_dir_rel)
        if dst_dir is None or not dst_dir.is_dir():
            return
        skills_root = os.path.realpath(self.root / SKILLS_DIR)
        for entry in sorted(dst_dir.iterdir()):
            if entry.name in selected or entry.name == MARKER:
                continue
            managed = False
            if is_link(entry):
                try:
                    target = os.path.realpath(entry)
                    managed = os.path.commonpath([skills_root, target]) == skills_root
                except (OSError, ValueError):
                    managed = False
            elif entry.is_dir() and (entry / MARKER).is_file():
                managed = True
            relative = f"{dst_dir_rel}/{entry.name}"
            if not managed:
                self.result.note(f"{relative}: unmanaged, left in place")
                continue
            if self.check:
                self.result.drifted(f"{relative} is a deselected harness-managed entry; run bootstrap to prune it")
                continue
            if is_link(entry):
                remove_link(entry)
            else:
                shutil.rmtree(entry)
            self.result.pruned(f"{relative} (deselected)")

    def per_skill(self, manifest: dict) -> list[str]:
        per_skill = manifest.get("per_skill", {})
        try:
            skills, selected, warnings = selected_skills(self.root)
        except (SkillError, json.JSONDecodeError, OSError) as exc:
            self.result.drifted(f"skill selection cannot be computed ({exc})")
            return []
        for warning in warnings:
            self.result.warn(warning)
        self.result.note(f"selection: {len(selected)} selected of {len(skills)} available")
        for runtime in RUNTIMES:
            block = per_skill.get(runtime)
            if not block:
                continue
            dst_dir_rel = block["dst_dir"]
            if block["mode"] == "link" or block.get("link_as"):
                for name in selected:
                    self.skill_dir_entry(dst_dir_rel, name, skills[name].relative)
                self.prune_dir(dst_dir_rel, selected)
                if selected and not self.check:
                    dst_dir = self.destination(dst_dir_rel)
                    if dst_dir is not None and dst_dir.is_dir() and not (dst_dir / MARKER).is_file():
                        (dst_dir / MARKER).write_bytes(MARKER_BYTES)
            if block.get("link_as"):
                dst_dir = self.destination(dst_dir_rel)
                if dst_dir is not None and not self.check:
                    dst_dir.mkdir(parents=True, exist_ok=True)
                    if not (dst_dir / MARKER).is_file():
                        (dst_dir / MARKER).write_bytes(MARKER_BYTES)
                self.link_entry(dst_dir_rel, block["link_as"])
        return selected

    # -- extensions and git floor ---------------------------------------

    def extensions(self) -> None:
        directory = self.root / EXTENSIONS_DIR
        if not directory.is_dir():
            return
        for script in sorted(p for p in directory.iterdir() if p.is_file()):
            command: list[str] | None = None
            suffix = script.suffix.lower()
            if suffix == ".py":
                command = [sys.executable, "-B", str(script)]
            elif suffix == ".sh":
                bash = shutil.which("bash")
                if not bash:
                    self.result.warn(f"extension {script.name} skipped: bash not on PATH")
                    continue
                command = [bash, str(script)]
            elif suffix == ".ps1":
                shell = shutil.which("pwsh") or shutil.which("powershell")
                if not shell:
                    self.result.warn(f"extension {script.name} skipped: PowerShell not on PATH")
                    continue
                command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
            elif os.access(script, os.X_OK):
                command = [str(script)]
            else:
                continue
            if self.check:
                command.append("--check")
            try:
                completed = subprocess.run(command, cwd=self.root, check=False, timeout=300)
                code = completed.returncode
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.result.drifted(f"extension {script.name} could not run ({exc})")
                continue
            if code == 0:
                self.result.ok(f"extension {script.name}")
            else:
                self.result.drifted(f"extension {script.name} exited {code}")

    def _git(self, *args: str) -> subprocess.CompletedProcess[str] | None:
        git = shutil.which("git")
        if not git:
            return None
        try:
            return subprocess.run(
                [git, "-C", str(self.root), *args],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None

    def _ensure_scripts_executable(self) -> None:
        """POSIX belt and braces: a clone made through a mode-losing
        transport (tar export, some CI checkouts) can land the working
        tree with the executable bit stripped even though the git index
        carries 100755 for every tracked *.sh file under harness/ and
        .githooks/pre-commit. Without it, core.hooksPath silently ignores
        the hook (git prints an "ignoredHook" advice rather than failing).
        Windows has no POSIX executable bit to restore, so this is a no-op
        there.

        Scope is harness/*.sh plus .githooks/pre-commit, the same scope
        lint check L18 uses: an adopted host's own scripts (e.g. a
        sourced-only env.sh outside harness/, deliberately left
        non-executable) are host content, not the template's, and must
        never be rewritten.

        In --check mode this reports missing executable access as drift
        instead of returning immediately: apply mode repairs it with chmod,
        but check mode must still be able to see the gap (chmod stays
        exclusive to apply mode)."""
        if os.name == "nt":
            return
        result = self._git("ls-files", "-z")
        if result is None or result.returncode != 0:
            return
        names = [name for name in result.stdout.split("\x00") if name]
        for name in names:
            in_scope = (name.startswith("harness/") and name.endswith(".sh")) or name == f"{GIT_HOOKS_DIR}/pre-commit"
            if not in_scope:
                continue
            path = self.root / name
            if not path.is_file():
                continue
            try:
                mode = path.stat().st_mode
            except OSError:
                continue
            if mode & 0o111:
                continue
            if self.check:
                self.result.drifted(f"{name} is not executable on disk (chmod +x; run bootstrap)")
                continue
            try:
                path.chmod(mode | 0o111)
            except OSError:
                continue

    def git_floor(self) -> None:
        probe = self._git("rev-parse", "--git-dir")
        # The pre-commit floor is the lowest degradation rung, not a
        # materialized destination: outside a git repository there is nothing
        # to register, so the doctor and the bootstrap both report a warning
        # and the exit code stays clean. A wrong hooksPath inside a repository
        # is still drift.
        if probe is None:
            self.result.warn("git is not on PATH; the pre-commit floor is not registered (install git, then rerun bootstrap)")
            return
        if probe.returncode != 0:
            self.result.warn("not a git repository; the pre-commit floor is not registered (run git init, then rerun bootstrap)")
            return
        if not (self.root / GIT_HOOKS_DIR).is_dir():
            self.result.warn(f"no {GIT_HOOKS_DIR}/ directory in this repository; git hook floor unavailable")
            return
        current = self._git("config", "--local", "core.hooksPath")
        value = (current.stdout.strip() if current and current.returncode == 0 else "").rstrip("/\\")
        if value == GIT_HOOKS_DIR:
            self.result.ok(f"core.hooksPath = {GIT_HOOKS_DIR}")
            self._ensure_scripts_executable()
            chained = self._git("config", "--local", "harness.chainedHooksPath")
            if chained is not None and chained.returncode == 0 and chained.stdout.strip():
                self.result.ok(f"harness.chainedHooksPath = {chained.stdout.strip()} (chained prior hooks path)")
        elif self.check:
            self.result.drifted(f"core.hooksPath is {value or 'unset'}, expected {GIT_HOOKS_DIR} (run bootstrap)")
        else:
            if value:
                chained = self._git("config", "--local", "harness.chainedHooksPath", value)
                if chained is None or chained.returncode != 0:
                    self.result.drifted(f"failed to record prior hooks path {value}")
                    return
                self.result.made(f"harness.chainedHooksPath = {value} (chained prior hooks path)")
            setting = self._git("config", "--local", "core.hooksPath", GIT_HOOKS_DIR)
            if setting is None or setting.returncode != 0:
                self.result.drifted("failed to set core.hooksPath")
                return
            self.result.made(f"core.hooksPath = {GIT_HOOKS_DIR}")
            self._ensure_scripts_executable()
        driver = self._git("config", "--local", "merge.ours.driver")
        if driver is not None and driver.returncode == 0 and driver.stdout.strip() == "true":
            self.result.ok("merge.ours.driver = true (generated files regenerate-and-diff)")
        elif not self.check:
            self._git("config", "--local", "merge.ours.driver", "true")
            self.result.made("merge.ours.driver = true (generated files regenerate-and-diff)")
        else:
            self.result.note("merge.ours.driver not set (bootstrap sets it; only meaningful in branches mode)")

    # -- run ------------------------------------------------------------

    def run(self) -> Result:
        manifest = load_manifest(self.root)
        if not manifest["junctions"]:
            self.result.warn("junctions.json declares zero entries")
        self.validate_manifest_destinations(manifest)
        if not self.registry_preflight():
            self.result.drifted("registry preflight failed; bootstrap made no changes")
            return self.result
        owned = per_skill_destinations(manifest)
        self.contract(manifest)
        for entry in manifest["junctions"]:
            mode = entry["mode"]
            if mode in ("contract-render", "generated") or entry["dst"] in owned:
                continue
            if mode == "link":
                self.link_entry(entry["src"], entry["dst"])
            elif mode == "managed-copy":
                self.managed_copy_entry(entry["src"], entry["dst"])
        for entry in manifest.get("retired_destinations", []):
            self.retired_entry(entry["dst"], entry.get("replacement", ""))
        self.per_skill(manifest)
        for entry in manifest["junctions"]:
            if entry["mode"] == "generated":
                self.generated_entry(entry["src"], entry["dst"])
        self.extensions()
        self.git_floor()
        return self.result


def apply(root: Path, mode: str = "link", check: bool = False, force: bool = False, copy: bool = False) -> Result:
    """Materialize root. mode is 'link' or 'copy'; copy=True is the same as mode='copy'."""
    engine = Engine(root, check=check, force=force, copy=copy or mode == "copy")
    return engine.run()


def prune(root: Path, selected: list[str]) -> list[str]:
    """Remove deselected harness-managed skill entries; return the report lines."""
    engine = Engine(root, check=False, force=False, copy=False)
    manifest = load_manifest(engine.root)
    engine.validate_manifest_destinations(manifest)
    for runtime in RUNTIMES:
        block = manifest.get("per_skill", {}).get(runtime)
        if not block:
            continue
        if block["mode"] == "link" or block.get("link_as"):
            engine.prune_dir(block["dst_dir"], selected)
        if block["mode"] == "generated" and block.get("dst_dir"):
            dst = engine.destination(block["dst_dir"])
            if dst is not None and dst.is_dir():
                for entry in sorted(dst.iterdir()):
                    if entry.name in selected:
                        continue
                    if build_codex_adapter.is_generated_dir(entry):
                        shutil.rmtree(entry)
                        engine.result.pruned(f"{block['dst_dir']}/{entry.name} (deselected)")
        if block.get("commands_dir"):
            dst = engine.destination(block["commands_dir"])
            if dst is not None and dst.is_dir():
                for entry in sorted(dst.iterdir()):
                    if entry.stem in selected or entry.name in {MARKER, ".catalog.json"}:
                        continue
                    if build_opencode_adapter.is_generated_file(entry):
                        entry.unlink()
                        engine.result.pruned(f"{block['commands_dir']}/{entry.name} (deselected)")
    return engine.result.lines


def main(argv: list[str] | None = None) -> int:
    # README's "bootstrap refuses to run without it" is enforced here:
    # bootstrap.sh and bootstrap.ps1 only probe for a working Python 3 on
    # PATH, then delegate to this module, so this is the one place that
    # actually knows the 3.11 floor (tomllib is stdlib-only from 3.11).
    if sys.version_info < (3, 11):
        print(
            f"bootstrap: Python 3.11+ is required (found {sys.version_info[0]}.{sys.version_info[1]}); "
            "tomllib is stdlib-only from 3.11",
            file=sys.stderr,
        )
        return EXIT_PREREQ
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="verify only; exit 1 on drift; change nothing")
    parser.add_argument("--copy", action="store_true", help="recursive copies instead of links")
    parser.add_argument("--force", action="store_true", help="replace conflicting unmanaged files (never directories)")
    args = parser.parse_args(argv)
    root = Path(os.path.realpath(args.root))
    mode = "check" if args.check else ("copy" if args.copy else "link")
    print(f"base-harness bootstrap - root: {root.as_posix()} (mode: {mode})")
    try:
        result = apply(root, check=args.check, force=args.force, copy=args.copy)
    except ManifestError as exc:
        print(f"  ABORT    {exc}")
        print("bootstrap: aborting (manifest parse error)", file=sys.stderr)
        return EXIT_MANIFEST
    for line in result.lines:
        print(line)
    print()
    if args.check:
        if not result.clean:
            print(f"check FAILED: {result.drift + result.conflicts} drift item(s)")
            return EXIT_DRIFT
        print("check OK: no drift")
        return EXIT_CLEAN
    if not result.clean:
        print(f"done with {result.drift + result.conflicts} unresolved item(s); {result.changed} change(s)")
        return EXIT_DRIFT
    print(f"done: {result.changed} change(s)")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
