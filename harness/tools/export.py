#!/usr/bin/env python
"""Tiered export of a repository into a history-free destination (copy mode only).

Usage:
    python harness/tools/export.py --tier <label> --out <dir> [--root <repo>] [--collaborators <file>]

Tier labels are ordered public < internal < confidential < restricted < secret.
A file is copied when its effective tier is at or below the requested tier.

Effective tier, in order:
  1. the file's frontmatter `access:` label (Markdown only)
  2. the structure.json `tiers.lane_defaults` value of the deepest lane the path
     falls under
  3. `tiers.unlisted_path`: "internal" includes the file at internal, "exclude"
     drops it

Invariants:
  * "secret" is excluded from every export, whatever tier is requested.
  * "restricted" requires a non-empty, validated collaborators file; otherwise
    the run refuses with exit 2 and writes nothing.
  * Fail closed: an unparseable frontmatter (BOM, carriage return in the
    frontmatter region, duplicate access key, unknown or empty label, unclosed
    block) marks the file UNPARSEABLE; it is excluded, counted, listed, and the
    run exits 1. A label is never guessed.
  * Symlinks and junctions are never followed and never copied; they are
    counted as skipped.
  * Nothing named .git is ever enumerated, read, or written; the destination is
    created by this tool and must be empty, outside the source repository, and
    reachable without a symlink component.
  * Binaries are copied byte-exact.
  * An attachment referenced by a copied Markdown file is copied when its own
    tier allows and named in the summary when its tier blocks it.

Summary counts reconcile: copied + excluded-by-tier + unparseable +
skipped-symlink == input file count. blocked-attachment is a subset of
excluded-by-tier and is reported separately.

Exit codes: 0 clean, 1 when unparseable > 0, 2 on a refused precondition.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import unquote

TOOLS_DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]

TIERS = ["public", "internal", "confidential", "restricted", "secret"]
TIER_RANK = {name: index for index, name in enumerate(TIERS)}
BOM = b"\xef\xbb\xbf"

MD_LINK_RE = re.compile(r"\]\(\s*<?([^)\s>]+)>?\s*(?:\"[^\"]*\")?\)")
HTML_SRC_RE = re.compile(r"(?:src|href)=[\"']([^\"']+)[\"']")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


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
    when that module is absent: the shipped default object merged key by key
    with the host file. A malformed host file is an error for an export
    because a guessed tier policy could widen what leaves the repository."""
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
# frontmatter
# --------------------------------------------------------------------------


class Unparseable(Exception):
    pass


def frontmatter_access(data: bytes):
    """Return the access label, None when the file has no frontmatter or no
    access key, or raise Unparseable with a reason. Only the bounded header
    is parsed; the body is never interpreted."""
    if data.startswith(BOM):
        raise Unparseable("byte-order mark")
    newline = data.find(b"\n")
    first = data if newline < 0 else data[:newline]
    if first.rstrip(b"\r") != b"---":
        return None
    if b"\r" in first:
        raise Unparseable("carriage return in frontmatter")
    rest = data[newline + 1:] if newline >= 0 else b""
    region_lines = []
    closed = False
    for raw in rest.split(b"\n"):
        if raw.rstrip(b"\r") in (b"---", b"..."):
            if b"\r" in raw:
                raise Unparseable("carriage return in frontmatter")
            closed = True
            break
        region_lines.append(raw)
    if not closed:
        raise Unparseable("unclosed frontmatter")
    region = b"\n".join(region_lines)
    if b"\r" in region:
        raise Unparseable("carriage return in frontmatter")
    try:
        text = region.decode("utf-8")
    except UnicodeDecodeError:
        raise Unparseable("frontmatter is not valid UTF-8")
    values = []
    for line in text.split("\n"):
        if not line or line[0] in " \t":
            continue
        match = re.match(r"^([A-Za-z0-9_-]+)\s*:(.*)$", line)
        if match and match.group(1) == "access":
            values.append(match.group(2).strip())
    if not values:
        return None
    if len(values) > 1:
        raise Unparseable("duplicate access key")
    value = values[0]
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    if not value:
        raise Unparseable("empty access label")
    if value not in TIER_RANK:
        raise Unparseable(f"unknown tier value '{value}'")
    return value


# --------------------------------------------------------------------------
# lanes and tiers
# --------------------------------------------------------------------------


def lane_for(rel: str, lanes: dict):
    """Deepest (longest) lane path the file falls under, or None."""
    best = None
    best_len = -1
    for lane, paths in (lanes or {}).items():
        if not isinstance(paths, list):
            continue
        for lane_path in paths:
            if not isinstance(lane_path, str):
                continue
            normalized = lane_path.strip("/")
            if not normalized:
                continue
            if rel == normalized or rel.startswith(normalized + "/"):
                if len(normalized) > best_len:
                    best, best_len = lane, len(normalized)
    return best


def default_tier(rel: str, structure: dict):
    """Lane default, else the unlisted policy. Returns a label or None (drop)."""
    tiers = structure.get("tiers") or {}
    lane = lane_for(rel, structure.get("lanes") or {})
    if lane is not None:
        label = (tiers.get("lane_defaults") or {}).get(lane)
        if label in TIER_RANK:
            return label
    policy = tiers.get("unlisted_path", "internal")
    if policy == "exclude":
        return None
    return "internal"


# --------------------------------------------------------------------------
# collaborators
# --------------------------------------------------------------------------


def validate_collaborators(path: Path):
    """Minimal reader for the collaborators file: a `collaborators:` list whose
    entries carry id, name, and tier_max (a tier label or 1..5).
    Returns (ok, message)."""
    if not path.is_file():
        return False, f"collaborators file missing: {path}"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return False, f"collaborators file unreadable: {exc}"
    entries = []
    current = None
    in_list = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if re.match(r"^collaborators\s*:", line):
            in_list = True
            continue
        if not in_list:
            continue
        item = re.match(r"^\s*-\s*(.*)$", line)
        if item:
            current = {}
            entries.append(current)
            line = item.group(1)
            if not line.strip():
                continue
        field = re.match(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$", line)
        if field and current is not None:
            current[field.group(1)] = field.group(2).strip().strip("\"'")
    if not entries:
        return False, "collaborators file lists no collaborators"
    for index, entry in enumerate(entries, start=1):
        for key in ("id", "name", "tier_max"):
            if not entry.get(key):
                return False, f"collaborator #{index} lacks {key}"
        tier_max = entry["tier_max"]
        numeric = tier_max.isdigit() and 1 <= int(tier_max) <= 5
        if not numeric and tier_max not in TIER_RANK:
            return False, f"collaborator #{index} tier_max must be a tier label or 1..5"
    return True, f"{len(entries)} collaborator(s)"


# --------------------------------------------------------------------------
# filesystem
# --------------------------------------------------------------------------


def is_link(path) -> bool:
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(path))


def enumerate_entries(root: Path) -> list:
    """(relative posix path, kind) for every entry under root, kind in
    {"file", "symlink"}. Anything named .git (directory or file) is never
    enumerated. Links are reported and never followed."""
    entries = []

    def walk(directory: Path):
        try:
            children = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError:
            return
        for child in children:
            if child.name == ".git":
                continue
            full = Path(child.path)
            rel = full.relative_to(root).as_posix()
            if is_link(full):
                entries.append((rel, "symlink"))
                continue
            if child.is_dir(follow_symlinks=False):
                walk(full)
            elif child.is_file(follow_symlinks=False):
                entries.append((rel, "file"))

    walk(root)
    return entries


def refuse_destination(out: Path, root: Path):
    """Return a refusal message or None."""
    resolved_root = root.resolve()
    for candidate in [out] + list(out.parents):
        if candidate.exists() and is_link(candidate):
            return f"destination has a symlink component: {candidate}"
    resolved = out.resolve()
    if resolved == Path(resolved.anchor):
        return "destination is the filesystem root"
    try:
        resolved.relative_to(resolved_root)
        return f"destination is inside the source repository: {resolved}"
    except ValueError:
        pass
    try:
        resolved_root.relative_to(resolved)
        return f"destination contains the source repository: {resolved}"
    except ValueError:
        pass
    if resolved.exists():
        if not resolved.is_dir():
            return f"destination exists and is not a directory: {resolved}"
        if (resolved / ".git").exists():
            return f"destination contains a .git directory: {resolved}"
        if any(resolved.iterdir()):
            return f"destination is not empty: {resolved}"
    return None


# --------------------------------------------------------------------------
# attachments
# --------------------------------------------------------------------------


def referenced_attachments(root: Path, rel: str, text: str) -> list:
    base = (root / rel).parent
    targets = []
    for regex in (MD_LINK_RE, HTML_SRC_RE):
        for match in regex.finditer(text):
            raw = match.group(1).strip()
            if not raw or raw.startswith("#") or SCHEME_RE.match(raw) or raw.startswith("/") or raw.startswith("\\"):
                continue
            raw = raw.split("#", 1)[0].split("?", 1)[0]
            raw = unquote(raw)
            if not raw:
                continue
            candidate = os.path.normpath(os.path.join(str(base), raw))
            try:
                target = Path(candidate).relative_to(root).as_posix()
            except ValueError:
                continue
            if target not in targets:
                targets.append(target)
    return targets


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------


class Refused(Exception):
    pass


def classify(root: Path, structure: dict, tier: str) -> tuple:
    """Return (entries, decisions): decisions maps rel -> (status, detail) with
    status in {copy, excluded, unparseable, symlink}."""
    requested = TIER_RANK[tier]
    entries = enumerate_entries(root)
    decisions = {}
    for rel, kind in entries:
        if kind == "symlink":
            decisions[rel] = ("symlink", "not followed")
            continue
        label = None
        if rel.lower().endswith(".md"):
            try:
                data = (root / rel).read_bytes()
            except OSError as exc:
                decisions[rel] = ("unparseable", f"unreadable ({exc})")
                continue
            try:
                label = frontmatter_access(data)
            except Unparseable as exc:
                decisions[rel] = ("unparseable", str(exc))
                continue
        if label is None:
            label = default_tier(rel, structure)
            if label is None:
                decisions[rel] = ("excluded", "unlisted path (policy exclude)")
                continue
        if label == "secret":
            decisions[rel] = ("excluded", "secret is excluded from every export")
            continue
        if TIER_RANK[label] > requested:
            decisions[rel] = ("excluded", f"tier {label} above {tier}")
            continue
        decisions[rel] = ("copy", label)
    return entries, decisions


def export_tree(root: Path, out: Path, tier: str, collaborators: Path) -> dict:
    """Perform the export. Raises Refused before anything is written. Returns
    the result dict the summary prints from."""
    root = root.resolve()
    if tier not in TIER_RANK:
        raise Refused(f"unknown tier '{tier}'; choose one of {', '.join(TIERS)}")
    refusal = refuse_destination(out, root)
    if refusal:
        raise Refused(refusal)
    try:
        structure = load_structure(root)
    except Exception as exc:  # noqa: BLE001 - a malformed policy must stop the export
        raise Refused(f"structure.json unreadable ({exc})")
    if TIER_RANK[tier] >= TIER_RANK["restricted"]:
        ok, message = validate_collaborators(collaborators)
        if not ok:
            raise Refused(f"tier '{tier}' requires a validated collaborators file: {message}")

    entries, decisions = classify(root, structure, tier)

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    copied = []
    blocked = []
    for rel, (status, label) in decisions.items():
        if status != "copy":
            continue
        source = root / rel
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append(rel)
        if rel.lower().endswith(".md"):
            try:
                text = source.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            for attachment in referenced_attachments(root, rel, text):
                decision = decisions.get(attachment)
                if decision and decision[0] in ("excluded", "unparseable", "symlink"):
                    blocked.append((attachment, rel, decision[1]))

    return {
        "tier": tier,
        "destination": out,
        "input_files": len(entries),
        "copied": copied,
        "excluded": [(rel, why) for rel, (status, why) in decisions.items() if status == "excluded"],
        "unparseable": [(rel, why) for rel, (status, why) in decisions.items() if status == "unparseable"],
        "symlinks": [rel for rel, (status, _) in decisions.items() if status == "symlink"],
        "blocked": blocked,
    }


def print_summary(result: dict, stream=None) -> None:
    stream = stream or sys.stdout
    copied, excluded = result["copied"], result["excluded"]
    unparseable, symlinks, blocked = result["unparseable"], result["symlinks"], result["blocked"]
    print(f"export summary (requested tier: {result['tier']})", file=stream)
    print(f"  copied              {len(copied)}", file=stream)
    print(f"  excluded-by-tier    {len(excluded)}", file=stream)
    print(f"  unparseable         {len(unparseable)}", file=stream)
    print(f"  skipped-symlink     {len(symlinks)}", file=stream)
    print(f"  blocked-attachment  {len(blocked)}", file=stream)
    reconciled = len(copied) + len(excluded) + len(unparseable) + len(symlinks)
    print(f"  input files         {result['input_files']} (copied + excluded-by-tier + unparseable + skipped-symlink = {reconciled})", file=stream)
    print(f"  destination         {result['destination']}", file=stream)
    if unparseable:
        print("unparseable (excluded, never guessed):", file=stream)
        for rel, why in unparseable:
            print(f"  {rel}: {why}", file=stream)
    if symlinks:
        print("skipped symlinks:", file=stream)
        for rel in symlinks:
            print(f"  {rel}", file=stream)
    if blocked:
        print("blocked attachments (referenced by a copied file, not copied):", file=stream)
        for attachment, referrer, why in blocked:
            print(f"  {attachment} (from {referrer}): {why}", file=stream)


def run_export(root: Path, out: Path, tier: str, collaborators: Path, stream=None) -> int:
    try:
        result = export_tree(root, out, tier, collaborators)
    except Refused as exc:
        print(f"export: refused: {exc}", file=sys.stderr)
        return 2
    print_summary(result, stream)
    return 1 if result["unparseable"] else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Copy every file at or below a tier into an empty destination.")
    parser.add_argument("--tier", required=True, choices=TIERS, help="requested tier")
    parser.add_argument("--out", required=True, help="destination directory (created; must be empty)")
    parser.add_argument("--root", default=str(ROOT), help="source repository (default: this repository)")
    parser.add_argument("--collaborators", default=None, help="collaborators file (default: harness/registry/collaborators.yaml under --root)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"export: refused: source is not a directory: {root}", file=sys.stderr)
        return 2
    collaborators = Path(args.collaborators) if args.collaborators else root / "harness" / "registry" / "collaborators.yaml"
    return run_export(root, Path(args.out), args.tier, collaborators)


if __name__ == "__main__":
    sys.exit(main())
