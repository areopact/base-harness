#!/usr/bin/env python3
"""Repository lint: checks L1 through L17 over the harness kernel.

Usage:
    python harness/tools/lint.py [--strict] [--only L3,L4] [--format text|json] [--root <repo>]
    python harness/tools/lint.py --release          # ship gate; implies --strict, see below
    python harness/tools/lint.py --schemas          # generated runtime JSON against each adapter schema

Each check is one function returning a list of Finding objects and is listed
in CHECKS with a stable id. Without --strict the soft checks (L6, L9, L11,
L13, L14) report WARN; with --strict every finding is an ERROR and
harness/bootstrap/junctions.json must exist. Exit 1 on any ERROR.

--strict is the working gate for an ordinary intermediate build state (a
catalog that is legitimately still empty mid-build). --release is the ship
gate: it implies --strict and additionally promotes ship-gate-only conditions
(currently the L4 empty-skill-catalog note and the L10 empty-verification-
table note) from a WARN to an ERROR, because an empty catalog is fine while
building but must never reach a release.

An absent optional tree (skills, docs) makes the affected check SKIPPED, which
is reported and never counted as a pass. Host facts come from
harness/registry/structure.json through harness_registry.load_structure();
nothing here hardcodes a lane path.

Checks:
    L1  contract-composition   AGENTS.md == render(CONTRACT.md, CONTRACT.host.md); CLAUDE.md == "@AGENTS.md\\n"; no .codex copy
    L2  byte-budget            AGENTS.md <= 32768 bytes; identity lane files within the smallest tier-1 context limit
    L3  ascii-and-eol          no em/en dash, smart quote, BOM, CR, trailing whitespace, or tab-indented .py
    L4  skill-frontmatter      required keys and closed vocabularies in every SKILL.md; packs never mix licenses;
                               every metadata.requires entry is a capabilities.json id, lane:<structure.json lane>,
                               or fact:<closed fact key>; a SKILL.md body that says "host.profile" must declare
                               fact:host.profile in metadata.requires; zero skills is a WARN under --strict, an
                               ERROR under --release (ship-gate-only)
    L5  resolver               resolver_lint passes; stub targets warn; targets outside the selection are notes
    L6  kernel-manifest (S)    every kernel file listed, every listed path exists, state/source consistent
    L7  registries             harness_registry.validate_all() returns no errors
    L8  junctions-agreement    junctions.json entries == runtimes.json materializations
    L9  no-bootstrap-links (S) no Markdown link outside the allowlist targets a bootstrap-created path
    L10 verification-rows      every docs/VERIFICATION.md row has status, ISO date, scope, and reproduction cell;
                               zero rows is a WARN under --strict, an ERROR under --release (ship-gate-only)
    L11 generated-drift (S)    the four generators pass --check
    L12 rules-index            harness/rules/index.json matches harness/rules/*.md
    L13 no-hardcoded-lanes (S) no kernel script carries a literal lane path outside the defaults carriers
    L14 deidentify (S)         deidentify_lint --structural is clean
    L15 source-references      every backtick-quoted "`key` source" citation in harness/rules/*.md resolves
                               to a key in harness/registry/sources.json
    L16 security-fixtures      every backtick-quoted fixtures/ path in SECURITY.md resolves on disk
    L17 no-placeholder-text    no bracketed placeholder, literal TBD, or literal YYYY-MM-DD in tracked
                               Markdown outside test/fixture trees
    L18 executable-bit         every tracked *.sh file and .githooks/pre-commit carries git mode
                               100755, so core.hooksPath is not silently ignored on POSIX
    L19 host-profile           the raw on-disk harness/registry/structure.json (never the merged
                               object): host.profile absent is a ship-gate note, present but outside
                               HOST_PROFILES is an ERROR, host.verify_command present but neither null
                               nor a package-manager/make command is an ERROR
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
import fnmatch
import glob
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = Path(__file__).resolve().parent

ERROR, WARN, SKIPPED, INFO = "ERROR", "WARN", "SKIPPED", "INFO"
SOFT_CHECKS = {"L6", "L9", "L11", "L13", "L14"}
# A metadata.requires entry with this prefix names a structure.json lane the
# skill reads or writes; a fact:<key> entry names a closed-vocabulary host
# fact the skill's body relies on; every other entry names a capabilities.json
# row.
LANE_PREFIX = "lane:"
FACT_PREFIX = "fact:"
FACT_KEYS = {
    "host.profile",
    "git.mode",
    "contract.mode",
    "brain.local_tracked",
    "delegation.mandatory",
    "selection_scope",
}
HOST_PROFILE_FACT = f"{FACT_PREFIX}host.profile"
CONTRACT_BUDGET = 32768
EOL_SUFFIXES = {".md", ".py", ".sh", ".ps1", ".json", ".toml"}
EOL_ROOTS = ("harness/", "docs/", "brain/")
BOOTSTRAP_PREFIXES = (".claude/", ".codex/", ".opencode/", ".agents/", "harness/.selected/")
NON_ASCII_PUNCT = {
    chr(0x2014): "em-dash",
    chr(0x2013): "en-dash",
    chr(0x2018): "smart quote",
    chr(0x2019): "smart quote",
    chr(0x201C): "smart quote",
    chr(0x201D): "smart quote",
}
BOM = b"\xef\xbb\xbf"
VERIFICATION = Path("docs/VERIFICATION.md")
VERIFICATION_STATUSES = {"verified", "documented", "pending"}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MARKDOWN_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)")
RULES_INDEX = Path("harness/rules/index.json")
RULE_KINDS = {"always-on", "path-scoped"}
SOURCES_REGISTRY = Path("harness/registry/sources.json")
# Matches the citation shape used in rule prose: "the `gbrain` source" or
# "the `humanizer` source there". A backticked token that is not followed by
# the word "source" is an ordinary code reference, not a source citation.
SOURCE_KEY_RE = re.compile(r"`([A-Za-z0-9][A-Za-z0-9_-]*)`\s+source\b")
SECURITY_FILE = Path("SECURITY.md")
FIXTURE_PATH_RE = re.compile(r"`([^`]*fixtures/[^`]*)`")
PLACEHOLDER_BRACKET_RE = re.compile(r"\[[^\[\]\n]*\b(?:placeholder|TBD|TODO)\b[^\[\]\n]*\]", re.IGNORECASE)
STANDALONE_TBD_RE = re.compile(r"\bTBD\b")
LITERAL_DATE_PLACEHOLDER_RE = re.compile(r"\bYYYY-MM-DD\b")
INLINE_CODE_SPAN_RE = re.compile(r"`[^`]*`")
# The two structure loaders carry the defaults contract by design (interface
# section 1); they are the only kernel scripts allowed to spell a lane path.
DEFAULTS_CARRIERS = {"harness/hooks/lib/hook_io.py", "harness/tools/harness_registry.py"}
L13_EXEMPT_PREFIXES = ("harness/registry/", "harness/tools/templates/")
GENERATED_UNTRACKED = {
    "harness/registry/delegation-policy.json",
    "harness/registry/native-routing-files.json",
    "harness/registry/skill-index.json",
}
GENERATORS = (
    ("harness/tools/gen_manifest.py", ["--check"]),
    ("harness/tools/native_routing.py", ["render", "--check"]),
    ("harness/bootstrap/build_codex_adapter.py", ["--check"]),
    ("harness/bootstrap/build_opencode_adapter.py", ["--check"]),
)
SCHEMA_CASES = (
    # (runtime, generated output, adapter source, schema file, key inside the schema file or None)
    ("claude", ".claude/settings.json", "harness/adapters/claude/settings.base.json", "harness/adapters/claude/schema.json", None),
    ("codex", ".codex/hooks.json", "harness/adapters/codex/hooks.json", "harness/adapters/codex/schema.json", "hooks_json"),
    ("opencode", "opencode.json", "harness/adapters/opencode/opencode.json", "harness/adapters/opencode/schema.json", None),
)
ADOPTED_FILES_REGISTRY = "harness/registry/adopted-files.json"
KERNEL_MANIFEST = "harness/kernel-manifest.json"


def _load_json_lenient(path: Path):
    """Parsed JSON, or None on a missing/malformed file: a lint must not
    crash on the file it is scoping itself by."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def adopted_scope_paths(root: Path) -> set[str]:
    """The default scan set on an adopted host: the union of
    harness/registry/adopted-files.json's recorded paths, every path listed
    in harness/kernel-manifest.json (the files the template owns on this
    host), and harness/registry/structure.json itself."""
    scope: set[str] = {"harness/registry/structure.json"}
    adopted_doc = _load_json_lenient(root / ADOPTED_FILES_REGISTRY)
    if isinstance(adopted_doc, dict):
        scope.update(p for p in (adopted_doc.get("paths") or []) if isinstance(p, str))
    manifest_doc = _load_json_lenient(root / KERNEL_MANIFEST)
    if isinstance(manifest_doc, dict):
        for entry in manifest_doc.get("files") or []:
            if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                scope.add(entry["path"])
    return scope


@dataclass
class Finding:
    id: str
    level: str
    path: str
    line: int | None
    message: str

    def render(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.id:<4} {self.level:<7} {where}: {self.message}" if where else f"{self.id:<4} {self.level:<7} {self.message}"


class Context:
    """Facts shared by every check: root, tracked files, host structure.

    On an adopted host (structure.json host.adopted is true), ctx.files
    defaults to the adopted scope (adopted_scope_paths): the template's own
    files, not the host's content. all_scope=True (the --all flag) restores
    the whole-tree scan. A non-adopted host (the template repository itself)
    always sees the whole tree. ctx.all_files is always the unscoped, whole-
    tree list, for the one check (L6) that must count host-owned files it
    does not judge.
    """

    def __init__(self, root: Path, strict: bool, release: bool = False, all_scope: bool = False):
        self.root = Path(root).resolve()
        self.strict = strict
        self.release = release
        self.all_scope = all_scope
        self._files: list[str] | None = None
        self._all_files: list[str] | None = None
        self._structure: dict | None = None
        self._scope_label: str | None = None

    @property
    def all_files(self) -> list[str]:
        if self._all_files is None:
            self._all_files = tracked_files(self.root)
        return self._all_files

    @property
    def files(self) -> list[str]:
        if self._files is None:
            self._files, self._scope_label = self._compute_scope()
        return self._files

    @property
    def scope_label(self) -> str:
        if self._files is None:
            _ = self.files
        return self._scope_label  # type: ignore[return-value]

    def _compute_scope(self) -> tuple[list[str], str]:
        all_files = self.all_files
        adopted = bool((self.structure.get("host") or {}).get("adopted"))
        if self.all_scope or not adopted:
            return all_files, "whole tree"
        scope = adopted_scope_paths(self.root)
        return [relative for relative in all_files if relative in scope], "adopted-host"

    @property
    def structure(self) -> dict:
        if self._structure is None:
            import harness_registry

            try:
                self._structure = harness_registry.load_structure(self.root)
            except Exception:  # noqa: BLE001 - L7 reports the malformed file; other checks use defaults
                self._structure = harness_registry.load_structure(self.root / "does-not-exist")
        return self._structure

    def read_text(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8-sig")

    def soft(self, check_id: str) -> str:
        return ERROR if (self.strict or check_id not in SOFT_CHECKS) else WARN

    @property
    def ship_gate_level(self) -> str:
        """Level for a condition that is a legitimate intermediate build state
        (an empty catalog) but must never reach a release: INFO by default,
        WARN under --strict (the working gate, visible but non-blocking),
        ERROR under --release (the ship gate)."""
        if self.release:
            return ERROR
        if self.strict:
            return WARN
        return INFO


def tracked_files(root: Path) -> list[str]:
    """Tracked plus untracked-not-ignored files; filesystem walk without git."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            names = [item for item in result.stdout.decode("utf-8", "replace").split("\0") if item]
            return sorted({name for name in names if (root / name).is_file()})
    except OSError:
        pass
    skip_dirs = {".git", "__pycache__", ".pytest_cache", "node_modules"}
    try:
        manifest = json.loads((root / "harness" / "bootstrap" / "junctions.json").read_text(encoding="utf-8-sig"))
        for entry in manifest.get("junctions", []):
            dst = str(entry.get("dst", ""))
            if dst:
                skip_dirs.add(Path(dst).parts[0])
    except (OSError, json.JSONDecodeError, KeyError, IndexError):
        pass
    names: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        for filename in filenames:
            if filename.endswith(".pyc"):
                continue
            names.append((Path(dirpath) / filename).relative_to(root).as_posix())
    return sorted(names)


def _glob_match(pattern: str, relative: str) -> bool:
    """Glob with ** crossing directories (fnmatch treats * as crossing already)."""
    return fnmatch.fnmatchcase(relative, pattern.replace("**/", "*").replace("**", "*"))


# ---------------------------------------------------------------------------
# L1 contract composition
# ---------------------------------------------------------------------------

def check_contract(ctx: Context) -> list[Finding]:
    bootstrap = ctx.root / "harness" / "bootstrap"
    module_path = bootstrap / "contract_files.py"
    if not module_path.is_file():
        return [Finding("L1", SKIPPED, "harness/bootstrap/contract_files.py", None, "renderer absent; composition unchecked")]
    import importlib.util

    spec = importlib.util.spec_from_file_location("contract_files", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return [Finding("L1", ERROR, "", None, issue) for issue in module.check_contract(ctx.root)]


# ---------------------------------------------------------------------------
# L2 byte budget
# ---------------------------------------------------------------------------

def _smallest_identity_limit(ctx: Context) -> int | None:
    path = ctx.root / "harness" / "registry" / "runtimes.json"
    if not path.is_file():
        return None
    try:
        registry = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    limits = [
        spec.get("identity_context_limit")
        for spec in (registry.get("runtimes") or {}).values()
        if isinstance(spec, dict) and spec.get("tier") == "tier-1" and isinstance(spec.get("identity_context_limit"), int)
    ]
    return min(limits) if limits else None


def check_byte_budget(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    contract = ctx.root / "AGENTS.md"
    if contract.is_file():
        size = contract.stat().st_size
        if size > CONTRACT_BUDGET:
            findings.append(Finding("L2", ERROR, "AGENTS.md", None, f"{size} bytes exceeds the {CONTRACT_BUDGET} byte contract budget"))
    else:
        findings.append(Finding("L2", ERROR, "AGENTS.md", None, "missing; render it with contract_files.py repair"))
    limit = _smallest_identity_limit(ctx)
    lanes = (ctx.structure.get("lanes") or {}).get("identity") or []
    if limit is None:
        findings.append(Finding("L2", SKIPPED, "harness/registry/runtimes.json", None, "no tier-1 identity_context_limit; identity budget unchecked"))
        return findings
    for lane_path in lanes:
        target = ctx.root / lane_path
        if not target.is_file():
            findings.append(Finding("L2", INFO, lane_path, None, "identity lane file not present (not written yet)"))
            continue
        size = target.stat().st_size
        if size > limit:
            findings.append(Finding("L2", ERROR, lane_path, None, f"{size} bytes exceeds the smallest tier-1 identity context limit ({limit})"))
    return findings


# ---------------------------------------------------------------------------
# L3 ascii and eol
# ---------------------------------------------------------------------------

def check_ascii_eol(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for relative in ctx.files:
        if not relative.startswith(EOL_ROOTS) or Path(relative).suffix not in EOL_SUFFIXES:
            continue
        if "__pycache__" in relative:
            continue
        try:
            data = (ctx.root / relative).read_bytes()
        except OSError:
            continue
        if data.startswith(BOM):
            findings.append(Finding("L3", ERROR, relative, 1, "byte-order mark"))
            data = data[len(BOM):]
        if b"\r" in data:
            line = data[: data.index(b"\r")].count(b"\n") + 1
            findings.append(Finding("L3", ERROR, relative, line, "carriage return (CRLF or CR line ending)"))
        text = data.decode("utf-8", errors="replace")
        for number, line in enumerate(text.split("\n"), start=1):
            for char in line:
                if char in NON_ASCII_PUNCT:
                    findings.append(Finding("L3", ERROR, relative, number, NON_ASCII_PUNCT[char]))
                    break
            if line.rstrip("\r") != line.rstrip("\r").rstrip(" \t"):
                findings.append(Finding("L3", ERROR, relative, number, "trailing whitespace"))
            if relative.endswith(".py") and line.startswith("\t"):
                findings.append(Finding("L3", ERROR, relative, number, "tab-indented Python line"))
    return findings


# ---------------------------------------------------------------------------
# L4 skill frontmatter
# ---------------------------------------------------------------------------

def _skill_body_text(root: Path, skill_relative: str) -> str:
    """The SKILL.md body below its frontmatter block, or the whole file when
    no closing '---' is found. Mirrors gen_manifest.parse_frontmatter's
    closing-line detection without importing it, so a malformed frontmatter
    block never hides the body from this scan."""
    try:
        text = (root / skill_relative / "SKILL.md").read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1:])
    return text


def check_skill_frontmatter(ctx: Context) -> list[Finding]:
    import gen_manifest

    skills_dir = ctx.root / gen_manifest.SKILLS_DIR
    if not skills_dir.is_dir():
        return [Finding("L4", SKIPPED, gen_manifest.SKILLS_DIR.as_posix(), None, "skills tree absent; frontmatter unchecked")]
    skills = gen_manifest.scan_skills(ctx.root)
    if not skills:
        return [Finding("L4", ctx.ship_gate_level, gen_manifest.SKILLS_DIR.as_posix(), None, "zero skills in the catalog")]
    findings: list[Finding] = []
    capabilities: set[str] = set()
    cap_path = ctx.root / "harness" / "registry" / "capabilities.json"
    if cap_path.is_file():
        try:
            capabilities = set((json.loads(cap_path.read_text(encoding="utf-8-sig")).get("capabilities") or {}))
        except (OSError, json.JSONDecodeError, AttributeError):
            capabilities = set()
    lanes = set((ctx.structure.get("lanes") or {}).keys())
    licenses_by_pack: dict[str, dict[str, list[str]]] = {}
    for skill in skills:
        path = f"{skill.path}/SKILL.md"
        for problem in skill.problems:
            findings.append(Finding("L4", ERROR, path, None, problem))
        capability_ids = [
            entry for entry in skill.requires
            if not entry.startswith(LANE_PREFIX) and not entry.startswith(FACT_PREFIX)
        ]
        if skill.distribution == "runtime-provided" and not capability_ids:
            findings.append(Finding("L4", ERROR, path, None, "runtime-provided skill must name a capability id in metadata.requires"))
        for entry in skill.requires:
            if entry.startswith(LANE_PREFIX):
                if entry[len(LANE_PREFIX):] not in lanes:
                    findings.append(Finding(
                        "L4", ERROR, path, None,
                        f"metadata.requires names unknown lane {entry!r} (structure.json lanes: {', '.join(sorted(lanes)) or 'none'})",
                    ))
            elif entry.startswith(FACT_PREFIX):
                if entry[len(FACT_PREFIX):] not in FACT_KEYS:
                    findings.append(Finding(
                        "L4", ERROR, path, None,
                        f"metadata.requires names unknown fact {entry!r} (valid facts: {', '.join(sorted(FACT_KEYS))})",
                    ))
            elif entry not in capabilities:
                findings.append(Finding("L4", ERROR, path, None, f"metadata.requires names unknown capability {entry!r}"))
        if HOST_PROFILE_FACT not in skill.requires and "host.profile" in _skill_body_text(ctx.root, skill.path):
            findings.append(Finding(
                "L4", ERROR, path, None,
                f"body mentions host.profile but metadata.requires lacks {HOST_PROFILE_FACT!r}",
            ))
        for pack in skill.packs:
            licenses_by_pack.setdefault(pack, {}).setdefault(skill.license or "unset", []).append(skill.name)
    for pack, by_license in sorted(licenses_by_pack.items()):
        if len(by_license) > 1:
            detail = "; ".join(f"{license_value}: {', '.join(sorted(names))}" for license_value, names in sorted(by_license.items()))
            findings.append(Finding("L4", ERROR, gen_manifest.SKILLS_DIR.as_posix(), None, f"pack {pack!r} mixes licenses ({detail})"))
    return findings


# ---------------------------------------------------------------------------
# L5 resolver
# ---------------------------------------------------------------------------

def check_resolver(ctx: Context) -> list[Finding]:
    import resolver_lint

    if not (ctx.root / resolver_lint.SKILLS_DIR).is_dir():
        return [Finding("L5", SKIPPED, resolver_lint.SKILLS_DIR.as_posix(), None, "skills tree absent; resolver unchecked")]
    errors, warns = resolver_lint.lint(ctx.root)
    path = resolver_lint.RESOLVER.as_posix()
    notes = resolver_lint.notes(ctx.root) if not errors else []
    return (
        [Finding("L5", ERROR, path, None, item) for item in errors]
        + [Finding("L5", WARN, path, None, item) for item in warns]
        + [Finding("L5", INFO, path, None, item) for item in notes]
    )


# ---------------------------------------------------------------------------
# L6 kernel manifest
# ---------------------------------------------------------------------------

def is_kernel_file(relative: str) -> bool:
    """Files the kernel manifest must list: the harness tree and the git floor."""
    if relative.startswith((".githooks/", ".github/")):
        return True
    if not relative.startswith("harness/"):
        return False
    name = Path(relative).name
    if name in {".gitkeep"} or name.endswith(".pyc") or "__pycache__" in relative:
        return False
    if relative in GENERATED_UNTRACKED or relative.startswith("harness/.selected/"):
        return False
    if relative == ADOPTED_FILES_REGISTRY:
        return False
    if relative.startswith("harness/skills/"):
        return relative in {"harness/skills/README.md", "harness/skills/RESOLVER.md"}
    if re.match(r"^harness/adapters/[a-z0-9-]+/agents/", relative):
        return False
    return True


def check_kernel_manifest(ctx: Context) -> list[Finding]:
    level = ctx.soft("L6")
    manifest_path = ctx.root / "harness" / "kernel-manifest.json"
    if not manifest_path.is_file():
        return [Finding("L6", level, "harness/kernel-manifest.json", None, "missing")]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding("L6", level, "harness/kernel-manifest.json", None, f"unreadable: {exc}")]
    findings: list[Finding] = []
    listed: set[str] = set()
    # An adopted host's own pre-existing harness/ files are recorded in
    # structure.json's host.harness_owned; the manifest never listed them
    # and they never will be, so L6 does not treat them as unlisted kernel
    # files. A brain module that no lane points into is not scaffolded, so
    # its manifest-listed files are not required to exist on disk.
    harness_owned = set((ctx.structure.get("host") or {}).get("harness_owned") or [])
    lanes = ctx.structure.get("lanes") or {}
    brain_lane_used = any(
        isinstance(value, list) and any(isinstance(item, str) and item.startswith("brain/") for item in value)
        for value in lanes.values()
    )
    for index, entry in enumerate(manifest.get("files") or []):
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            findings.append(Finding("L6", level, "harness/kernel-manifest.json", None, f"files[{index}] is not a {{path, state, source}} object"))
            continue
        path = entry["path"]
        if path in listed:
            findings.append(Finding("L6", level, "harness/kernel-manifest.json", None, f"duplicate entry {path}"))
        listed.add(path)
        state, source = entry.get("state"), entry.get("source")
        if state not in {"ported", "new"}:
            findings.append(Finding("L6", level, path, None, f"state must be ported or new (got {state!r})"))
        elif (state == "ported") != (source is not None):
            findings.append(Finding("L6", level, path, None, "source must be non-null exactly when state is ported"))
        if not (ctx.root / path).is_file():
            if path.startswith("brain/") and not brain_lane_used:
                continue
            findings.append(Finding("L6", level, path, None, "listed in the kernel manifest but absent on disk"))
    # On an adopted host's default scope, ctx.files is already restricted to
    # the template's own files (adopted_scope_paths), so a host-owned or
    # newly-added harness/ file is invisible to the completeness loop below
    # and never becomes an error. Count what the loop is not judging instead
    # of silently dropping it. Under --all (ctx.all_scope) or on a
    # non-adopted host, ctx.files IS ctx.all_files, so this block never fires
    # and the completeness loop covers every harness/ file as before.
    adopted = bool((ctx.structure.get("host") or {}).get("adopted"))
    if adopted and not ctx.all_scope:
        judged = set(ctx.files)
        unjudged = sum(
            1
            for relative in ctx.all_files
            if relative.startswith("harness/") and relative not in judged and relative not in harness_owned
        )
        if unjudged:
            findings.append(Finding("L6", INFO, "harness/", None, f"{unjudged} host-owned file(s) under harness/ not judged"))
    for relative in ctx.files:
        if relative in harness_owned:
            continue
        if is_kernel_file(relative) and relative not in listed:
            findings.append(Finding("L6", level, relative, None, "kernel file not listed in harness/kernel-manifest.json"))
    return findings


# ---------------------------------------------------------------------------
# L7 registries
# ---------------------------------------------------------------------------

def check_registries(ctx: Context) -> list[Finding]:
    import harness_registry

    if not (ctx.root / "harness" / "registry").is_dir():
        return [Finding("L7", SKIPPED, "harness/registry", None, "registry directory absent")]
    errors = harness_registry.validate_all(ctx.root, [])
    return [Finding("L7", ERROR, "harness/registry", None, item) for item in errors]


# ---------------------------------------------------------------------------
# L8 junctions agreement
# ---------------------------------------------------------------------------

def check_junctions(ctx: Context) -> list[Finding]:
    junctions_path = ctx.root / "harness" / "bootstrap" / "junctions.json"
    runtimes_path = ctx.root / "harness" / "registry" / "runtimes.json"
    if not junctions_path.is_file():
        if ctx.strict:
            return [Finding("L8", ERROR, "harness/bootstrap/junctions.json", None, "required with --strict and absent")]
        return [Finding("L8", SKIPPED, "harness/bootstrap/junctions.json", None, "absent; agreement unchecked")]
    if not runtimes_path.is_file():
        return [Finding("L8", ERROR, "harness/registry/runtimes.json", None, "missing")]
    try:
        junctions = json.loads(junctions_path.read_text(encoding="utf-8-sig"))
        runtimes = json.loads(runtimes_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding("L8", ERROR, "harness/bootstrap/junctions.json", None, f"unreadable: {exc}")]
    left = {
        (entry.get("src"), entry.get("dst"), entry.get("mode"))
        for entry in (junctions.get("junctions") or []) if isinstance(entry, dict)
    }
    right = {
        (row.get("source"), row.get("destination"), row.get("mode"))
        for spec in (runtimes.get("runtimes") or {}).values() if isinstance(spec, dict)
        for row in (spec.get("materializations") or []) if isinstance(row, dict)
    }
    findings: list[Finding] = []
    for src, dst, mode in sorted(left - right, key=str):
        findings.append(Finding("L8", ERROR, "harness/bootstrap/junctions.json", None, f"{src} -> {dst} ({mode}) has no runtimes.json materialization"))
    for src, dst, mode in sorted(right - left, key=str):
        findings.append(Finding("L8", ERROR, "harness/registry/runtimes.json", None, f"{src} -> {dst} ({mode}) has no junctions.json entry"))
    return findings


# ---------------------------------------------------------------------------
# L9 no bootstrap links
# ---------------------------------------------------------------------------

def _bootstrap_allowlist(ctx: Context) -> list[str]:
    patterns = ["docs/**", "README.md"]
    path = ctx.root / RULES_INDEX
    if path.is_file():
        try:
            extra = json.loads(path.read_text(encoding="utf-8-sig")).get("bootstrap_path_allowlist") or []
            patterns.extend(item for item in extra if isinstance(item, str))
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    return patterns


def check_no_bootstrap_links(ctx: Context) -> list[Finding]:
    """A Markdown link or wikilink outside the allowlist must not target a bootstrap output.

    The registry, bootstrap scripts, and CI name those paths by design; prose
    that documents them is fine. What must not exist is a link that a reader
    follows into a path that only exists after bootstrap.
    """
    level = ctx.soft("L9")
    allow = _bootstrap_allowlist(ctx)
    findings: list[Finding] = []
    for relative in ctx.files:
        if not relative.endswith(".md") or any(_glob_match(pattern, relative) for pattern in allow):
            continue
        try:
            text = ctx.read_text(relative)
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            targets = MARKDOWN_LINK.findall(line) + WIKILINK.findall(line)
            for target in targets:
                cleaned = target.strip()
                while cleaned.startswith("./"):
                    cleaned = cleaned[2:]
                if cleaned.startswith(BOOTSTRAP_PREFIXES):
                    findings.append(Finding("L9", level, relative, number, f"link targets bootstrap-created path {target.strip()!r}"))
                    break
    return findings


# ---------------------------------------------------------------------------
# L10 verification rows
# ---------------------------------------------------------------------------

def _split_row(line: str) -> list[str]:
    import resolver_lint

    return resolver_lint.split_markdown_row(line)


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def verification_rows(text: str) -> list[tuple[int, dict[str, str]]]:
    """Every data row of every table whose header carries a Status column."""
    rows: list[tuple[int, dict[str, str]]] = []
    header: list[str] | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        cells = _split_row(line)
        if not cells:
            header = None
            continue
        if _is_separator(cells):
            continue
        lowered = [cell.lower() for cell in cells]
        if header is None:
            header = lowered if "status" in lowered else None
            continue
        rows.append((number, {name: (cells[index] if index < len(cells) else "") for index, name in enumerate(header)}))
    return rows


def check_verification_rows(ctx: Context) -> list[Finding]:
    if not (ctx.root / "docs").is_dir():
        return [Finding("L10", SKIPPED, "docs", None, "docs tree absent; verification rows unchecked")]
    path = ctx.root / VERIFICATION
    if not path.is_file():
        return [Finding("L10", ERROR, VERIFICATION.as_posix(), None, "missing")]
    findings: list[Finding] = []
    rows = verification_rows(path.read_text(encoding="utf-8-sig"))
    for number, row in rows:
        status = row.get("status", "").strip().strip("`").lower()
        if status not in VERIFICATION_STATUSES:
            findings.append(Finding("L10", ERROR, VERIFICATION.as_posix(), number, f"status {row.get('status', '')!r} not in verified | documented | pending"))
        date = row.get("last live test", "").strip().strip("`")
        if not ISO_DATE.match(date):
            findings.append(Finding("L10", ERROR, VERIFICATION.as_posix(), number, f"last live test {date!r} is not an ISO date"))
        if not row.get("scope", "").strip():
            findings.append(Finding("L10", ERROR, VERIFICATION.as_posix(), number, "empty scope token"))
        reproducible = next((value for name, value in row.items() if name.startswith("reproducible")), "")
        if not reproducible.strip():
            findings.append(Finding("L10", ERROR, VERIFICATION.as_posix(), number, "empty 'reproducible in your clone by' cell"))
    if not rows:
        findings.append(Finding("L10", ctx.ship_gate_level, VERIFICATION.as_posix(), None, "zero data rows"))
    return findings


# ---------------------------------------------------------------------------
# L11 generated drift
# ---------------------------------------------------------------------------

def check_generated_drift(ctx: Context) -> list[Finding]:
    level = ctx.soft("L11")
    findings: list[Finding] = []
    for script, arguments in GENERATORS:
        path = ctx.root / script
        if not path.is_file():
            findings.append(Finding("L11", SKIPPED, script, None, "generator absent"))
            continue
        result = subprocess.run(
            [sys.executable, str(path), "--root", str(ctx.root), *arguments],
            capture_output=True, text=True, check=False, cwd=str(ctx.root),
        )
        if result.returncode != 0:
            lines = [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]
            detail = lines[-1] if lines else f"exit {result.returncode}"
            findings.append(Finding("L11", level, script, None, f"{' '.join(arguments)} exited {result.returncode}: {detail}"))
    return findings


# ---------------------------------------------------------------------------
# L12 rules index
# ---------------------------------------------------------------------------

def check_rules_index(ctx: Context) -> list[Finding]:
    rules_dir = ctx.root / "harness" / "rules"
    if not rules_dir.is_dir():
        return [Finding("L12", SKIPPED, "harness/rules", None, "rules tree absent")]
    index_path = ctx.root / RULES_INDEX
    if not index_path.is_file():
        return [Finding("L12", ERROR, RULES_INDEX.as_posix(), None, "missing")]
    try:
        index = json.loads(index_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding("L12", ERROR, RULES_INDEX.as_posix(), None, f"unreadable: {exc}")]
    findings: list[Finding] = []
    on_disk = {path.stem for path in rules_dir.glob("*.md") if path.name != "README.md"}
    listed: set[str] = set()
    for entry in index.get("rules") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("slug"), str):
            findings.append(Finding("L12", ERROR, RULES_INDEX.as_posix(), None, "rule entry without a slug"))
            continue
        slug = entry["slug"]
        if slug in listed:
            findings.append(Finding("L12", ERROR, RULES_INDEX.as_posix(), None, f"duplicate entry {slug!r}"))
        listed.add(slug)
        kind = entry.get("kind")
        if kind not in RULE_KINDS:
            findings.append(Finding("L12", ERROR, RULES_INDEX.as_posix(), None, f"{slug}: kind must be always-on or path-scoped (got {kind!r})"))
        globs = entry.get("globs")
        if not isinstance(globs, list) or any(not isinstance(item, str) for item in globs):
            findings.append(Finding("L12", ERROR, RULES_INDEX.as_posix(), None, f"{slug}: globs must be a list of strings"))
        elif kind == "path-scoped" and not globs:
            findings.append(Finding("L12", ERROR, RULES_INDEX.as_posix(), None, f"{slug}: path-scoped rule needs a non-empty globs list"))
        if slug not in on_disk:
            findings.append(Finding("L12", ERROR, RULES_INDEX.as_posix(), None, f"{slug}: dangling entry, harness/rules/{slug}.md does not exist"))
        elif kind in RULE_KINDS:
            rule_path = f"harness/rules/{slug}.md"
            import gen_manifest

            try:
                text = (rules_dir / f"{slug}.md").read_text(encoding="utf-8-sig")
            except OSError as exc:
                findings.append(Finding("L12", ERROR, rule_path, None, f"unreadable: {exc}"))
                text = None
            if text is not None:
                front = gen_manifest.parse_frontmatter(text) or {}
                paths = front.get("paths")
                if kind == "path-scoped":
                    if not isinstance(paths, list) or not paths or any(not isinstance(item, str) for item in paths):
                        findings.append(Finding("L12", ERROR, rule_path, None, "path-scoped rule needs frontmatter paths: as a non-empty list of strings"))
                    elif isinstance(globs, list) and sorted(paths) != sorted(globs):
                        findings.append(Finding("L12", ERROR, rule_path, None, f"frontmatter paths: {paths} does not match index globs {globs}"))
                elif "paths" in front:
                    findings.append(Finding("L12", ERROR, rule_path, None, "always-on rule must not carry frontmatter paths:"))
    # Same pattern as L6: on an adopted host's default scope, a host-owned
    # or newly-added harness/rules/*.md file the template never wrote is
    # invisible to ctx.files, so it must not become an "unlisted" error;
    # count it once instead. --all or a non-adopted host judges every file
    # on disk, unchanged.
    adopted = bool((ctx.structure.get("host") or {}).get("adopted"))
    if adopted and not ctx.all_scope:
        scope_files = set(ctx.files)
        in_scope = {slug for slug in on_disk if f"harness/rules/{slug}.md" in scope_files}
        unjudged = on_disk - in_scope
        if unjudged:
            findings.append(Finding("L12", INFO, "harness/rules/", None, f"{len(unjudged)} host-owned rule file(s) under harness/rules/ not judged"))
        candidates = in_scope
    else:
        candidates = on_disk
    for slug in sorted(candidates - listed):
        findings.append(Finding("L12", ERROR, f"harness/rules/{slug}.md", None, "rule file not listed in harness/rules/index.json"))
    return findings


# ---------------------------------------------------------------------------
# L13 no hardcoded lanes
# ---------------------------------------------------------------------------

def lane_tokens(ctx: Context) -> list[str]:
    """Multi-segment lane paths from structure.json plus any forbidden tokens deidentify_lint exports."""
    tokens: set[str] = set()
    lanes = ctx.structure.get("lanes") or {}
    for value in lanes.values():
        for item in value or []:
            if isinstance(item, str) and "/" in item.strip("/"):
                tokens.add(item.strip("/"))
    local_path = (ctx.structure.get("brain") or {}).get("local_path")
    if isinstance(local_path, str) and "/" in local_path.strip("/"):
        tokens.add(local_path.strip("/"))
    try:
        import deidentify_lint

        tokens.update(str(item) for item in getattr(deidentify_lint, "FORBIDDEN_TOKENS", ()))
    except ImportError:
        pass
    return sorted(tokens)


def _is_test_path(relative: str) -> bool:
    """Test trees seed lane paths on purpose; any directory segment ending in 'tests' is one."""
    return any(part.endswith("tests") for part in Path(relative).parts[:-1])


def check_no_hardcoded_lanes(ctx: Context) -> list[Finding]:
    level = ctx.soft("L13")
    tokens = lane_tokens(ctx)
    if not tokens:
        return [Finding("L13", INFO, "harness/registry/structure.json", None, "no multi-segment lane paths configured")]
    findings: list[Finding] = []
    for relative in ctx.files:
        if not relative.startswith("harness/") or Path(relative).suffix not in {".py", ".sh", ".ps1"}:
            continue
        if relative.startswith(L13_EXEMPT_PREFIXES) or relative in DEFAULTS_CARRIERS or _is_test_path(relative):
            continue
        try:
            text = ctx.read_text(relative)
        except (OSError, UnicodeDecodeError):
            continue
        hits: dict[int, list[str]] = {}
        for token in tokens:
            for number, line in enumerate(text.splitlines(), start=1):
                if token in line:
                    hits.setdefault(number, []).append(token)
                    break
        if hits:
            number = min(hits)
            spelled = ", ".join(repr(token) for token in sorted({token for group in hits.values() for token in group}))
            findings.append(Finding("L13", level, relative, number, f"literal lane path {spelled}; read it from structure.json"))
    return findings


# ---------------------------------------------------------------------------
# L14 deidentify
# ---------------------------------------------------------------------------

def check_deidentify(ctx: Context) -> list[Finding]:
    level = ctx.soft("L14")
    try:
        import deidentify_lint
    except ImportError:
        return [Finding("L14", SKIPPED, "harness/tools/deidentify_lint.py", None, "de-identification lint absent")]
    allowed = deidentify_lint.allowed_first_segments(ctx.root)
    found = deidentify_lint.scan_worktree(ctx.root, [], allowed, True, set(), files=ctx.files)
    return [Finding("L14", level, item.path, item.line, f"{item.check} {item.message}") for item in found]


# ---------------------------------------------------------------------------
# --schemas: generated runtime JSON against each adapter schema
# ---------------------------------------------------------------------------

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _resolve_ref(ref: str, root_schema: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"only local refs are supported: {ref}")
    node = root_schema
    for part in ref[2:].split("/"):
        node = node[part]
    return node



def _ecma_pattern(pattern):
    """A JSON Schema pattern with the end-anchor semantics of the ECMAScript regex dialect JSON Schema uses.

    In that dialect an unescaped trailing `$` matches only at the end of the
    string; Python's `$` also matches before a trailing newline. `\\Z` is
    Python's end-of-string-only anchor, so a trailing unescaped `$` becomes
    `\\Z`. Unanchored patterns are untouched, as JSON Schema leaves them.
    """
    if pattern.endswith("$") and not pattern.endswith("\\$"):
        return pattern[:-1] + "\\Z"
    return pattern

def validate_schema(instance, schema: dict, root_schema: dict | None = None, path: str = "$") -> list[str]:
    """Draft-07 subset: type, properties, required, additionalProperties, propertyNames,
    items, minItems, enum, const, pattern, not, anyOf, allOf, local $ref."""
    root_schema = root_schema if root_schema is not None else schema
    if "$ref" in schema:
        return validate_schema(instance, _resolve_ref(schema["$ref"], root_schema), root_schema, path)
    errors: list[str] = []
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(TYPE_CHECKS[name](instance) for name in types):
            return [f"{path}: expected type {types}"]
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum")
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: {instance!r} != const {schema['const']!r}")
    if "pattern" in schema and isinstance(instance, str) and re.search(_ecma_pattern(schema["pattern"]), instance) is None:
        errors.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")
    if "not" in schema and not validate_schema(instance, schema["not"], root_schema, path):
        errors.append(f"{path}: matches a forbidden 'not' schema")
    if "anyOf" in schema and all(validate_schema(instance, sub, root_schema, path) for sub in schema["anyOf"]):
        errors.append(f"{path}: matches none of anyOf")
    for sub in schema.get("allOf", []):
        errors.extend(validate_schema(instance, sub, root_schema, path))
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required {key!r}")
        if "propertyNames" in schema:
            for key in instance:
                if validate_schema(key, schema["propertyNames"], root_schema, f"{path}.{key}"):
                    errors.append(f"{path}: property name {key!r} rejected")
        properties = schema.get("properties", {})
        for key, value in instance.items():
            if key in properties:
                errors.extend(validate_schema(value, properties[key], root_schema, f"{path}.{key}"))
            else:
                extra = schema.get("additionalProperties", True)
                if extra is False:
                    errors.append(f"{path}: additional property {key!r} not allowed")
                elif isinstance(extra, dict):
                    errors.extend(validate_schema(value, extra, root_schema, f"{path}.{key}"))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(validate_schema(item, schema["items"], root_schema, f"{path}[{index}]"))
    return errors


def _toml_paths(value: dict, prefix: str = ""):
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        yield path
        if isinstance(child, dict):
            yield from _toml_paths(child, path)


def check_schemas(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for runtime, generated, source, schema_file, key in SCHEMA_CASES:
        schema_path = ctx.root / schema_file
        if not schema_path.is_file():
            findings.append(Finding("SCHEMA", SKIPPED, schema_file, None, "schema absent"))
            continue
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
            schema = schema[key] if key else schema
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            findings.append(Finding("SCHEMA", ERROR, schema_file, None, f"unreadable schema: {exc}"))
            continue
        for relative in (source, generated):
            path = ctx.root / relative
            if not path.is_file():
                if relative == generated:
                    findings.append(Finding("SCHEMA", INFO, relative, None, "not materialized (bootstrap not run); source validated instead"))
                else:
                    findings.append(Finding("SCHEMA", ERROR, relative, None, "adapter source missing"))
                continue
            try:
                instance = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(Finding("SCHEMA", ERROR, relative, None, f"not valid JSON: {exc}"))
                continue
            for error in validate_schema(instance, schema):
                findings.append(Finding("SCHEMA", ERROR, relative, None, f"{runtime}: {error}"))
    codex_schema = ctx.root / "harness/adapters/codex/schema.json"
    if codex_schema.is_file():
        try:
            import tomllib
        except ImportError:
            findings.append(Finding("SCHEMA", SKIPPED, "harness/adapters/codex/config.toml", None, "TOML key check needs Python 3.11+ (tomllib is stdlib-only from 3.11)"))
            return findings
        try:
            schema = json.loads(codex_schema.read_text(encoding="utf-8-sig"))
            allowed = set(schema.get("config_toml_allowed_keys") or [])
            forbidden = set(schema.get("config_toml_forbidden_keys") or [])
            for relative in ("harness/adapters/codex/config.toml", ".codex/config.toml"):
                path = ctx.root / relative
                if not path.is_file() or not allowed:
                    continue
                data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
                for key_path in _toml_paths(data):
                    if key_path not in allowed:
                        findings.append(Finding("SCHEMA", ERROR, relative, None, f"codex: key {key_path!r} outside config_toml_allowed_keys"))
                    if key_path.split(".")[-1] in forbidden:
                        findings.append(Finding("SCHEMA", ERROR, relative, None, f"codex: forbidden key {key_path!r}"))
        except (OSError, ValueError) as exc:
            findings.append(Finding("SCHEMA", ERROR, "harness/adapters/codex/config.toml", None, f"cannot check TOML keys: {exc}"))
    return findings


# ---------------------------------------------------------------------------
# L15 source references
# ---------------------------------------------------------------------------

def check_source_references(ctx: Context) -> list[Finding]:
    rules_dir = ctx.root / "harness" / "rules"
    if not rules_dir.is_dir():
        return [Finding("L15", SKIPPED, "harness/rules", None, "rules tree absent")]
    sources_path = ctx.root / SOURCES_REGISTRY
    if not sources_path.is_file():
        return [Finding("L15", ERROR, SOURCES_REGISTRY.as_posix(), None, "missing")]
    try:
        registry = json.loads(sources_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return [Finding("L15", ERROR, SOURCES_REGISTRY.as_posix(), None, f"unreadable: {exc}")]
    known = set((registry.get("sources") or {}) if isinstance(registry, dict) else {})
    findings: list[Finding] = []
    for path in sorted(rules_dir.glob("*.md")):
        relative = path.relative_to(ctx.root).as_posix()
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for match in SOURCE_KEY_RE.finditer(line):
                key = match.group(1)
                if key not in known:
                    findings.append(
                        Finding("L15", ERROR, relative, number, f"source key '{key}' not listed in {SOURCES_REGISTRY.as_posix()}")
                    )
    return findings


# ---------------------------------------------------------------------------
# L16 security fixture paths
# ---------------------------------------------------------------------------

def check_security_fixtures(ctx: Context) -> list[Finding]:
    path = ctx.root / SECURITY_FILE
    if not path.is_file():
        return [Finding("L16", SKIPPED, SECURITY_FILE.as_posix(), None, "SECURITY.md absent")]
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return [Finding("L16", ERROR, SECURITY_FILE.as_posix(), None, f"unreadable: {exc}")]
    findings: list[Finding] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        for match in FIXTURE_PATH_RE.finditer(line):
            token = match.group(1)
            if token in seen:
                continue
            seen.add(token)
            if not glob.glob(str(ctx.root / token)):
                findings.append(Finding("L16", ERROR, SECURITY_FILE.as_posix(), number, f"fixture path does not resolve on disk: {token}"))
    return findings


# ---------------------------------------------------------------------------
# L17 no placeholder text
# ---------------------------------------------------------------------------

def _is_fixture_or_test_path(relative: str) -> bool:
    parts = Path(relative).parts
    return any(part in {"tests", "fixtures", "export_tests"} or "fixtures" in part for part in parts)


def check_no_placeholders(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for relative in ctx.files:
        if Path(relative).suffix != ".md" or _is_fixture_or_test_path(relative):
            continue
        try:
            text = ctx.read_text(relative)
        except (OSError, UnicodeDecodeError):
            continue
        in_fence = False
        for number, line in enumerate(text.splitlines(), start=1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            visible = INLINE_CODE_SPAN_RE.sub(lambda m: " " * len(m.group(0)), line)
            if PLACEHOLDER_BRACKET_RE.search(visible):
                findings.append(Finding("L17", ERROR, relative, number, "bracketed placeholder text"))
            elif STANDALONE_TBD_RE.search(visible):
                findings.append(Finding("L17", ERROR, relative, number, "literal TBD placeholder"))
            elif LITERAL_DATE_PLACEHOLDER_RE.search(visible):
                findings.append(Finding("L17", ERROR, relative, number, "literal YYYY-MM-DD placeholder"))
    return findings


# ---------------------------------------------------------------------------
# L18 executable bit
# ---------------------------------------------------------------------------

def check_executable_bit(ctx: Context) -> list[Finding]:
    """Every tracked shell entry point under harness/, plus
    .githooks/pre-commit, carries git mode 100755, so core.hooksPath is not
    silently ignored on POSIX (git prints an "ignoredHook" advice and skips
    a non-executable hook instead of failing). Not a git repository:
    SKIPPED, since there is no index mode to read.

    Scope is harness/*.sh plus .githooks/pre-commit, the exact predicate
    materialize.py's _ensure_scripts_executable uses: an adopted host's own
    *.sh script outside harness/ (e.g. a sourced-only env.sh under a host
    scripts directory, deliberately left non-executable) is host content,
    not the template's, and is never judged here."""
    # -z: NUL-delimited, unquoted entries, so a git-quoted (non-ASCII) name
    # is read intact instead of arriving still wrapped in its C-style quotes,
    # which would never match ctx.files and silently drop the entry.
    result = subprocess.run(
        ["git", "-C", str(ctx.root), "ls-files", "-s", "-z"],
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        return [Finding("L18", SKIPPED, ".", None, "not a git repository")]
    modes: dict[str, str] = {}
    for entry in result.stdout.decode("utf-8", "replace").split("\0"):
        if not entry or "\t" not in entry:
            continue
        meta, path = entry.split("\t", 1)
        parts = meta.split()
        if parts:
            modes[path] = parts[0]
    findings: list[Finding] = []
    for relative in ctx.files:
        in_scope = (relative.startswith("harness/") and relative.endswith(".sh")) or relative == ".githooks/pre-commit"
        if not in_scope:
            continue
        mode = modes.get(relative)
        if mode is None:
            continue
        if mode != "100755":
            findings.append(Finding("L18", ERROR, relative, None, f"tracked with mode {mode}, expected 100755 (git update-index --chmod=+x)"))
    return findings


# ---------------------------------------------------------------------------
# L19 host profile
# ---------------------------------------------------------------------------

STRUCTURE_JSON = Path("harness/registry/structure.json")
HOST_PROFILE_ABSENT_MESSAGE = "host.profile absent; defaulting to solo; set it with python harness/tools/init.py --profile"
VERIFY_COMMAND_SHAPE = "null or one of: 'npm run <script>', 'pnpm run <script>', 'yarn <script>', 'make <target>'"


def _raw_structure_json(ctx: Context):
    """The on-disk structure.json exactly as written, never merged with
    harness_registry's defaults: L19 judges what the host actually wrote,
    not what load_structure() fills in for an absent field. Returns {} for
    a missing file (nothing written yet), or None when the file cannot be
    read as a JSON object (L7 reports that failure in detail)."""
    path = ctx.root / STRUCTURE_JSON
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def check_host_profile(ctx: Context) -> list[Finding]:
    path = STRUCTURE_JSON.as_posix()
    raw = _raw_structure_json(ctx)
    if raw is None:
        return [Finding("L19", SKIPPED, path, None, "structure.json unreadable or not an object; see L7")]
    import harness_registry

    host = raw.get("host")
    host = host if isinstance(host, dict) else {}
    findings: list[Finding] = []
    if "profile" not in host:
        findings.append(Finding("L19", ctx.ship_gate_level, path, None, HOST_PROFILE_ABSENT_MESSAGE))
    elif host["profile"] not in harness_registry.HOST_PROFILES:
        findings.append(Finding(
            "L19", ERROR, path, None,
            f"host.profile {host['profile']!r} not in {sorted(harness_registry.HOST_PROFILES)}",
        ))
    if "verify_command" in host:
        verify_command = host["verify_command"]
        if verify_command is not None and not (
            isinstance(verify_command, str) and harness_registry.VERIFY_COMMAND_RE.fullmatch(verify_command)
        ):
            findings.append(Finding(
                "L19", ERROR, path, None,
                f"host.verify_command {verify_command!r} must be {VERIFY_COMMAND_SHAPE}",
            ))
    return findings


# ---------------------------------------------------------------------------
# registry and entry point
# ---------------------------------------------------------------------------

CHECKS: list[tuple[str, str, Callable[[Context], list[Finding]]]] = [
    ("L1", "contract-composition", check_contract),
    ("L2", "byte-budget", check_byte_budget),
    ("L3", "ascii-and-eol", check_ascii_eol),
    ("L4", "skill-frontmatter", check_skill_frontmatter),
    ("L5", "resolver", check_resolver),
    ("L6", "kernel-manifest", check_kernel_manifest),
    ("L7", "registries", check_registries),
    ("L8", "junctions-agreement", check_junctions),
    ("L9", "no-bootstrap-links", check_no_bootstrap_links),
    ("L10", "verification-rows", check_verification_rows),
    ("L11", "generated-drift", check_generated_drift),
    ("L12", "rules-index", check_rules_index),
    ("L13", "no-hardcoded-lanes", check_no_hardcoded_lanes),
    ("L14", "deidentify", check_deidentify),
    ("L15", "source-references", check_source_references),
    ("L16", "security-fixtures", check_security_fixtures),
    ("L17", "no-placeholder-text", check_no_placeholders),
    ("L18", "executable-bit", check_executable_bit),
    ("L19", "host-profile", check_host_profile),
]


def run_checks(
    root: Path,
    strict: bool = False,
    only: set[str] | None = None,
    release: bool = False,
    all_scope: bool = False,
    ctx: Context | None = None,
) -> list[Finding]:
    ctx = ctx if ctx is not None else Context(root, strict, release=release, all_scope=all_scope)
    findings: list[Finding] = []
    for check_id, _, function in CHECKS:
        if only and check_id not in only:
            continue
        try:
            findings.extend(function(ctx))
        except Exception as exc:  # noqa: BLE001 - a crashing check is itself a finding, never a silent pass
            findings.append(Finding(check_id, ERROR, "", None, f"check crashed: {type(exc).__name__}: {exc}"))
    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts = {level: 0 for level in (ERROR, WARN, SKIPPED, INFO)}
    for finding in findings:
        counts[finding.level] = counts.get(finding.level, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Lint the harness kernel (checks L1 to L17). "
            "--strict is the working gate (soft checks and ship-gate-only conditions print as WARN, "
            "not ERROR): a normal, legitimate intermediate build state must stay green. "
            "--release is the ship gate: it implies --strict and also promotes ship-gate-only "
            "conditions (an empty skill catalog, an empty verification table) to ERROR, since those "
            "are fine mid-build but must never reach a release."
        )
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--strict", action="store_true", help="promote soft checks to errors; require junctions.json")
    parser.add_argument(
        "--release",
        action="store_true",
        help="ship gate: implies --strict and also promotes ship-gate-only conditions (e.g. zero skills, zero verification rows) to ERROR",
    )
    parser.add_argument("--only", default=None, help="comma-separated check ids, e.g. L3,L4")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--schemas", action="store_true", help="validate generated runtime JSON against each adapter schema")
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "on an adopted host, scan the whole tree instead of the default adopted scope "
            "(harness/registry/adopted-files.json + the kernel manifest paths + structure.json); "
            "no effect on a non-adopted host"
        ),
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    strict = args.strict or args.release
    only = {item.strip().upper() for item in args.only.split(",") if item.strip()} if args.only else None
    if only:
        known = {check_id for check_id, _, _ in CHECKS}
        unknown = sorted(only - known)
        if unknown:
            print(f"lint: unknown check id(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
    ctx = Context(root, strict, release=args.release, all_scope=args.all)
    if args.schemas:
        findings = check_schemas(ctx)
    else:
        findings = run_checks(root, strict=strict, only=only, release=args.release, ctx=ctx)
    counts = summarize(findings)
    scope_label = ctx.scope_label
    scanned = len(ctx.files)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "strict": strict,
                    "release": args.release,
                    "scope": scope_label,
                    "files_scanned": scanned,
                    "findings": [asdict(item) for item in findings],
                    "summary": counts,
                },
                indent=2,
            )
        )
    else:
        print(f"lint: scope {scope_label} ({scanned} file(s) scanned)")
        for finding in findings:
            print(finding.render())
        mode = "schemas" if args.schemas else ("release" if args.release else ("strict" if args.strict else "default"))
        print(
            f"lint ({mode}): {counts[ERROR]} error(s), {counts[WARN]} warning(s), "
            f"{counts[SKIPPED]} skipped, {counts[INFO]} note(s)"
        )
    return 1 if counts[ERROR] else 0


if __name__ == "__main__":
    raise SystemExit(main())
