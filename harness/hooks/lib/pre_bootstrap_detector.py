#!/usr/bin/env python3
"""SessionStart advisory: detect a clone that has not been bootstrapped.

For every entry in harness/bootstrap/junctions.json the destination must
exist; for the "link" mode a symlink or junction must additionally resolve
into harness/. A destination that is a plain directory or file (copy mode)
counts as materialized. Two kinds of row are never required, decided from
manifest data rather than from filesystem presence: a secondary
contract-render row (mode "contract-render" whose dst is not the root
contract output, e.g. the .claude/CLAUDE.md row, declared for registry
parity only, the same predicate materialize.py's own engine uses to skip
it), and a per-skill dst_dir row (per_skill.<runtime>.dst_dir with no
link_as) when the effective skill selection resolves to zero skills, read
from the codex-generated .catalog.json "selected" count (itself written by
the same skill_catalog.selected_skills() resolver the materialization
engine uses) so the two can never disagree, without this stdlib-only hook
importing harness/bootstrap Python. When any remaining destination for the
active runtime (or
for "all") is missing, one advisory names the exact bootstrap command for
the current platform. Silent when everything required is present, when
junctions.json is absent, or when the manifest is malformed. Never denies;
always exits 0.

The runtime comes from --runtime on argv, then HARNESS_RUNTIME, then
"claude" (the runtime whose wrappers call this module directly).
"""
import json
import os
import sys
from pathlib import Path

from _debug import debug
from hook_io import REPO_ROOT, advisory

HOOK_NAME = "pre-bootstrap-detector"
JUNCTIONS_RELATIVE = ("harness", "bootstrap", "junctions.json")
# Kept in sync with materialize.CONTRACT_OUTPUT: the one contract-render row
# that IS the root render (every other contract-render row is a declared,
# never-materialized parity entry; see _is_secondary_contract_row below).
CONTRACT_OUTPUT = "AGENTS.md"
# The stable filename build_codex_adapter.py writes at the codex per-skill
# dst_dir: {"selected": N, ...}, computed by skill_catalog.selected_skills().
CATALOG_FILENAME = ".catalog.json"


def _skill_selection_is_empty(root, data):
    """True when the effective skill selection resolves to zero skills.
    Reads the "selected" count out of the already-materialized codex skill
    catalog rather than recomputing selection here: that file is written by
    harness/bootstrap/build_codex_adapter.py from the exact same
    skill_catalog.selected_skills() resolver materialize.py uses for every
    runtime (selection.json is global, not per-runtime), so this can never
    disagree with what bootstrap actually materializes. This stdlib-only
    hook module deliberately never imports harness/bootstrap Python (see
    harness/hooks/tests/test_structure_parameterization.py). Fails to False
    (treat as non-empty, i.e. still required) when the catalog is absent or
    malformed: an absent catalog usually means the clone genuinely has not
    been bootstrapped, and every other required row already reports missing
    in that case, so failing closed here costs nothing.
    """
    per_skill = data.get("per_skill") if isinstance(data, dict) else None
    codex_block = per_skill.get("codex") if isinstance(per_skill, dict) else None
    dst_dir = codex_block.get("dst_dir") if isinstance(codex_block, dict) else None
    if not isinstance(dst_dir, str) or not dst_dir:
        return False
    catalog = Path(root) / dst_dir / CATALOG_FILENAME
    try:
        stats = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    selected = stats.get("selected") if isinstance(stats, dict) else None
    return isinstance(selected, int) and selected == 0


def _is_secondary_contract_row(entry):
    """True for a contract-render row that is not the root AGENTS.md render:
    declared for registry parity, deliberately kept absent by design. This
    mirrors materialize.py's own Engine.check() rule ("every contract-render
    row is served by the root render") so the detector and the engine read
    the same manifest fact the same way, rather than each inferring its own
    notion of "required" from what happens to exist on disk.
    """
    return entry.get("mode") == "contract-render" and entry.get("dst") != CONTRACT_OUTPUT


def _per_skill_dst_dirs(data, runtime):
    """dst values fulfilled by per-skill materialization instead of a
    whole-tree link: per_skill.<runtime>.dst_dir, but only when that block
    has no link_as (a link_as destination, e.g. .opencode/skills, is always
    materialized as an empty link even with zero skills selected)."""
    per_skill = data.get("per_skill") if isinstance(data, dict) else None
    if not isinstance(per_skill, dict):
        return set()
    block = per_skill.get(runtime)
    if not isinstance(block, dict) or block.get("link_as"):
        return set()
    dst_dir = block.get("dst_dir")
    return {dst_dir} if isinstance(dst_dir, str) and dst_dir else set()


def bootstrap_command(platform=None):
    platform = platform if platform is not None else sys.platform
    if platform.startswith("win"):
        return "powershell -NoProfile -ExecutionPolicy Bypass -File harness\\bootstrap\\bootstrap.ps1"
    return "bash harness/bootstrap/bootstrap.sh"


def runtime_from(argv=None, environ=None):
    argv = argv if argv is not None else sys.argv[1:]
    environ = environ if environ is not None else os.environ
    for index, item in enumerate(argv):
        if item == "--runtime" and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith("--runtime="):
            return item.split("=", 1)[1]
    return environ.get("HARNESS_RUNTIME") or "claude"


def _resolves_into_harness(destination, root):
    try:
        resolved = destination.resolve()
        harness = (root / "harness").resolve()
        return harness == resolved or harness in resolved.parents
    except OSError:
        return False


def _is_link(destination):
    try:
        if destination.is_symlink():
            return True
        if os.name == "nt" and destination.is_dir():
            return bool(os.stat(destination, follow_symlinks=False).st_file_attributes & 0x400)
    except OSError:
        return False
    return False


def missing_destinations(root=None, runtime="claude"):
    root = Path(root) if root is not None else REPO_ROOT
    manifest = root.joinpath(*JUNCTIONS_RELATIVE)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    entries = data.get("junctions") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    skip_dst_dirs = _per_skill_dst_dirs(data, runtime)
    selection_empty = None  # computed lazily, at most once
    missing = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        dst = entry.get("dst")
        mode = entry.get("mode")
        scope = entry.get("runtime", "all")
        if not isinstance(dst, str) or not dst:
            continue
        if scope not in ("all", runtime):
            continue
        if _is_secondary_contract_row(entry):
            continue
        if dst in skip_dst_dirs:
            if selection_empty is None:
                selection_empty = _skill_selection_is_empty(root, data)
            if selection_empty:
                continue
        destination = root / dst
        if not destination.exists():
            missing.append(dst)
            continue
        if mode == "link" and _is_link(destination) and not _resolves_into_harness(destination, root):
            missing.append(dst)
    return missing


def decide(root=None, runtime="claude", platform=None):
    missing = missing_destinations(root, runtime)
    if not missing:
        return None
    shown = ", ".join(missing[:6]) + (f" (+{len(missing) - 6} more)" if len(missing) > 6 else "")
    return advisory(
        "SessionStart",
        f"pre-bootstrap-detector: this clone is not bootstrapped for {runtime}; "
        f"missing {shown}. Run: {bootstrap_command(platform)}",
    )


def main(runtime=None):
    debug.start()
    try:
        sys.stdin.read()
    except Exception:
        pass
    out = decide(runtime=runtime or runtime_from())
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="materialized")
        sys.exit(0)
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="missing")
    sys.exit(0)


if __name__ == "__main__":
    main()
