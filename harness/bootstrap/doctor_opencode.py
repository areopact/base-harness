#!/usr/bin/env python3
"""Offline-first OpenCode adapter doctor; never resolves config or auth state.

The offline audit reads files only. It checks the root contract, the managed
project config and its schema, the adapter links, the selected skill tree
that ``.opencode/skills`` must resolve into (the wrapper-bypass check), the
generated command catalog, the plugin bridge surface, the compatibility
record, and the selection count. ``--runtime`` adds version and agent-list
probes; it never prints resolved config and never inspects an auth store.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_opencode_adapter  # noqa: E402
import doctor_common as dc  # noqa: E402
import materialize  # noqa: E402
from doctor_common import Audit  # noqa: E402
from skill_catalog import SkillError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONFIG_SOURCE = "harness/adapters/opencode/opencode.json"
CONFIG_OUTPUT = "opencode.json"
SCHEMA = "harness/adapters/opencode/schema.json"
PLUGIN = "harness/adapters/opencode/plugins/harness-bridge.js"
# The dispatch/normalize helpers live outside plugins/ so OpenCode never
# treats them as a second plugin factory (see harness-bridge.js's header);
# the surface and secret-read boundary checks below cover both files.
PLUGIN_LIB = "harness/adapters/opencode/lib/harness-bridge-internal.js"
COMPATIBILITY = "harness/adapters/opencode/compatibility.json"
EVIDENCE_VALUES = {"passed", "unproven", "not-attempted"}
MATERIALIZED_PLUGIN = ".opencode/plugins/harness-bridge.js"
# A single-quoted, double-quoted, or backtick-literal import argument. A
# backtick literal carrying "${" interpolation is not a static path and is
# deliberately not matched (the "`([^`$]+)`" branch excludes "$").
_IMPORT_STRING_ARG = r"""(?:"([^"]+)"|'([^']+)'|`([^`$]+)`)"""
IMPORT_FROM_RE = re.compile(r"from\s+" + _IMPORT_STRING_ARG)
# A side-effect import (no bindings, no "from"): import '../lib/x.js';
IMPORT_SIDE_EFFECT_RE = re.compile(r"(?<!\w)import\s+" + _IMPORT_STRING_ARG)
# A literal dynamic import, awaited or not: await import('../lib/x.js')
IMPORT_DYNAMIC_RE = re.compile(r"\bimport\s*\(\s*" + _IMPORT_STRING_ARG + r"\s*\)")
# Comment stripping before any import regex runs, so a commented-out import
# (// import "../lib/absent.js";) is never matched, and a comment sitting
# between "import(" and its argument (import(/* chunk */ "../lib/x.js"))
# does not defeat the dynamic-import regex. Not a full JS parser: a "//" or
# "/*" sequence inside a string literal would be misread, an accepted
# trade-off for a materialization doctor over hand-authored plugin source.
_JS_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_JS_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _strip_js_comments(text: str) -> str:
    text = _JS_BLOCK_COMMENT_RE.sub(" ", text)
    return _JS_LINE_COMMENT_RE.sub("", text)


def _import_targets(pattern: re.Pattern, text: str) -> set[str]:
    return {group for match in pattern.findall(text) for group in match if group}


def check_project_config(root: Path, audit: Audit) -> None:
    if not dc.check_managed_copy(root, audit, CONFIG_SOURCE, CONFIG_OUTPUT):
        return
    dc.check_schema_file(root, audit, CONFIG_OUTPUT, SCHEMA)
    config = dc.read_json(root / CONFIG_OUTPUT, audit, CONFIG_OUTPUT)
    if config is None:
        return
    permission = config.get("permission", {}) if isinstance(config.get("permission"), dict) else {}
    read_rules = permission.get("read", {}) if isinstance(permission.get("read"), dict) else {}
    skill_rules = permission.get("skill", {}) if isinstance(permission.get("skill"), dict) else {}
    problems: list[str] = []
    if config.get("share") != "disabled":
        problems.append("share is not disabled")
    for pattern in (".env", "**/.env"):
        if read_rules.get(pattern) != "deny":
            problems.append(f"read rule {pattern} is not deny")
    if skill_rules.get("*") != "allow":
        problems.append("skill rule * is not allow")
    if problems:
        audit.fail("configured", "project config safety floor is incomplete: " + "; ".join(problems))
    else:
        audit.ok("configured", "project config disables sharing, denies credential-file reads, and allows skills")


def check_skill_root(root: Path, audit: Audit, manifest: dict | None) -> None:
    """Wrapper-bypass check: the OpenCode skill root must be the selected tree."""
    block = (manifest or {}).get("per_skill", {}).get("opencode") if manifest else None
    if not block or not block.get("link_as"):
        audit.fail("configured", "junctions.json per_skill.opencode lacks dst_dir/link_as; selection cannot be enforced")
        return
    selected_dir = Path(root) / block["dst_dir"]
    skill_root = Path(root) / block["link_as"]
    if not selected_dir.is_dir():
        audit.fail("configured", f"{block['dst_dir']} selected skill tree is not materialized; run bootstrap")
        return
    if materialize.is_link(skill_root):
        if dc.same_target(skill_root, selected_dir):
            audit.ok("configured", f"{block['link_as']} resolves into {block['dst_dir']} (selection enforcing)")
        else:
            audit.fail("configured", f"{block['link_as']} does not resolve into {block['dst_dir']}; the launcher wrapper is bypassed (run bootstrap)")
    elif skill_root.is_dir():
        if materialize.dirs_equal(selected_dir, skill_root):
            audit.ok("configured", f"{block['link_as']} is a content-equal copy of {block['dst_dir']} (copy mode; selection enforcing)")
        else:
            audit.fail("configured", f"{block['link_as']} is a real directory that differs from {block['dst_dir']}; the launcher wrapper is bypassed (run bootstrap)")
    else:
        audit.fail("configured", f"{block['link_as']} is missing; run bootstrap")
    dc.check_selection(root, audit, block["dst_dir"], "link")


def check_commands(root: Path, audit: Audit, manifest: dict | None) -> None:
    block = (manifest or {}).get("per_skill", {}).get("opencode") if manifest else None
    commands_dir = (block or {}).get("commands_dir") or ".opencode/commands"
    try:
        expected, warnings = build_opencode_adapter.render_commands(root)
    except (OSError, SkillError, json.JSONDecodeError) as exc:
        audit.fail("configured", f"command catalog cannot be rendered ({exc})")
        return
    for warning in warnings:
        audit.warn("configured", warning)
    problems, notes = build_opencode_adapter.diff_commands(root / commands_dir, expected)
    for note in notes:
        audit.ok("configured", f"{commands_dir}/{note}")
    if problems:
        for problem in problems:
            audit.fail("configured", f"command catalog: {problem}")
    else:
        summary = json.loads(expected[".catalog.json"])
        audit.ok("configured", f"generated slash-command catalog is exact ({summary['commands']} commands)")


def check_plugin(root: Path, audit: Audit) -> None:
    try:
        text = (root / PLUGIN).read_text(encoding="utf-8")
        lib_text = (root / PLUGIN_LIB).read_text(encoding="utf-8")
    except OSError as exc:
        audit.fail("configured", f"plugin bridge or its helper module missing ({exc})")
        return
    combined = text + lib_text
    required_hooks = ("tool.execute.before", "experimental.chat.system.transform")
    routed = '"--runtime", "opencode"' in combined
    if all(hook in text for hook in required_hooks) and routed and "readFile" not in combined and ".env" not in combined:
        audit.ok("configured", "plugin bridge declares only the pre-tool and identity surfaces and reads no files itself")
    else:
        audit.fail("configured", "plugin bridge surface or secret-read boundary is invalid")
    check_materialized_plugin_imports(root, audit)


def check_materialized_plugin_imports(root: Path, audit: Audit) -> None:
    """The materialized plugin (link or copy mode) must resolve every relative import.

    Copy mode materializes ``plugins/`` without ``lib/`` unless the junctions
    manifest also links ``harness/adapters/opencode/lib`` to ``.opencode/lib``;
    a missing sibling here means OpenCode will fail every plugin load with
    ERR_MODULE_NOT_FOUND while every source-path check above still passes.
    """
    materialized = root / MATERIALIZED_PLUGIN
    if not materialized.exists():
        audit.fail("configured", f"{MATERIALIZED_PLUGIN} is not materialized; run bootstrap")
        return
    try:
        materialized_text = materialized.read_text(encoding="utf-8")
    except OSError as exc:
        audit.fail("configured", f"{MATERIALIZED_PLUGIN} could not be read ({exc})")
        return
    missing: list[str] = []
    uncommented_text = _strip_js_comments(materialized_text)
    targets = _import_targets(IMPORT_FROM_RE, uncommented_text)
    targets.update(_import_targets(IMPORT_SIDE_EFFECT_RE, uncommented_text))
    targets.update(_import_targets(IMPORT_DYNAMIC_RE, uncommented_text))
    for target in sorted(targets):
        if not target.startswith("."):
            continue
        resolved = (materialized.parent / target).resolve()
        if not resolved.exists():
            missing.append(f"{target} -> {resolved}")
    if missing:
        audit.fail(
            "configured",
            f"{MATERIALIZED_PLUGIN} imports missing from the materialized tree: " + "; ".join(missing),
        )
    else:
        audit.ok("configured", f"{MATERIALIZED_PLUGIN} resolves every relative import in the materialized tree")


def check_compatibility(root: Path, audit: Audit) -> dict | None:
    compatibility = dc.read_json(root / COMPATIBILITY, audit, "OpenCode compatibility record")
    if compatibility is None:
        return None
    evidence = compatibility.get("evidence", {})
    bad = [
        name for name, value in (evidence.items() if isinstance(evidence, dict) else [])
        if not (value in EVIDENCE_VALUES or (isinstance(value, str) and value.startswith("passed:")))
    ]
    if bad:
        audit.fail("configured", "compatibility record evidence values outside the closed vocabulary: " + ", ".join(bad))
    elif compatibility.get("tested_cli") is None and compatibility.get("adapter_status") not in {"configured-alpha", "configured-beta"}:
        audit.fail("configured", "compatibility record claims a status its missing live evidence cannot support")
    else:
        audit.ok(
            "configured",
            f"compatibility record is {compatibility.get('adapter_status', 'unspecified')}; minimum "
            f"{compatibility.get('minimum_cli', '?')}, tested {compatibility.get('tested_cli') or 'none recorded'}",
        )
    return compatibility


def check_offline(root: Path, audit: Audit) -> dict | None:
    dc.check_contract_files(root, audit)
    dc.check_gitignore_floor(root, audit, "opencode")
    check_project_config(root, audit)
    manifest = dc.check_junction_rows(root, audit, "opencode")
    check_skill_root(root, audit, manifest)
    check_commands(root, audit, manifest)
    check_plugin(root, audit)
    compatibility = check_compatibility(root, audit)
    dc.check_git_floor(root, audit)
    dc.check_model_map(root, audit, "opencode")
    dc.check_capabilities(root, audit, "opencode")
    dc.check_degradation_rungs(root, audit, "opencode")
    return compatibility


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def check_runtime(audit: Audit, compatibility: dict | None) -> None:
    executable = shutil.which("opencode")
    if not executable:
        audit.fail("loaded", "OpenCode executable not found")
        return
    try:
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        audit.fail("loaded", f"OpenCode version probe failed ({exc})")
        return
    if version.returncode != 0:
        audit.fail("loaded", "OpenCode version probe failed")
        return
    installed = version.stdout.strip()
    audit.ok("loaded", f"OpenCode executable responded: {installed}")
    if compatibility:
        minimum = str(compatibility.get("minimum_cli", ""))
        if version_tuple(installed) < version_tuple(minimum):
            audit.fail("loaded", f"{installed} is below minimum {minimum}")
        elif compatibility.get("tested_cli") is None:
            audit.warn("loaded", f"{installed} meets minimum {minimum}; no live-tested CLI is recorded")
    try:
        agents = subprocess.run([executable, "agent", "list"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        audit.fail("loaded", f"OpenCode agent-list probe failed ({exc})")
        return
    if agents.returncode == 0:
        audit.ok("loaded", "OpenCode listed its agents (generated roles are proven only by a recorded live run)")
    else:
        audit.fail("loaded", "OpenCode agent-list probe failed")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="explicitly select the default pure repository audit")
    parser.add_argument("--runtime", action="store_true", help="also run version and agent-list probes")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    dc.print_header("OpenCode", root, ["offline"] + (["runtime"] if args.runtime else []))
    audit = Audit()
    compatibility = check_offline(root, audit)
    if args.runtime:
        check_runtime(audit, compatibility)
    dc.finish_unknown(audit, {
        "configured": "no repository configuration evidence was collected",
        "loaded": "offline mode does not require an OpenCode executable; use --runtime",
        "trusted": "project and plugin loading were not observed",
        "fired": "native plugin event delivery was not observed",
        "enforced": "pre-tool denial has no live canary evidence",
        "outcome-proven": "no authenticated workflow was executed",
    })
    audit.summary()
    return 1 if audit.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
