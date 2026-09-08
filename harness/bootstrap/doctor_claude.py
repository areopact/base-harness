#!/usr/bin/env python3
"""Offline repository audit for the Claude Code adapter.

Behind ``harness/bootstrap/doctor.sh`` and ``doctor.ps1``. File reads and
local git config reads only: it never launches Claude Code, never touches
the network, and never regenerates anything. The ``configured`` layer is the
only one this audit can populate; ``loaded``, ``trusted``, ``fired``,
``enforced``, and ``outcome-proven`` stay UNKNOWN with an explicit reason
until a person records a live run in docs/VERIFICATION.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import doctor_common as dc  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_SOURCE = "harness/adapters/claude/settings.base.json"
SETTINGS_OUTPUT = ".claude/settings.json"
SETTINGS_SCHEMA = "harness/adapters/claude/schema.json"
SKILLS_DIR = ".claude/skills"
POSTURE_KEYS = ("defaultMode", "bypassPermissions", "skipDangerousModePermissionPrompt", "autoMode", "dangerouslySkipPermissions")
HOOK_COMMAND = re.compile(r"\$\{CLAUDE_PROJECT_DIR\}/(harness/hooks/(?:[\w.-]+/)+[\w.-]+\.sh)")


def _posture_paths(value: object, path: str = "") -> list[str]:
    if not isinstance(value, dict):
        return []
    found: list[str] = []
    for key, child in value.items():
        child_path = f"{path}.{key}" if path else str(key)
        if key in POSTURE_KEYS:
            found.append(child_path)
        found.extend(_posture_paths(child, child_path))
    return found


def check_settings(root: Path, audit: dc.Audit) -> None:
    if not dc.check_managed_copy(root, audit, SETTINGS_SOURCE, SETTINGS_OUTPUT):
        return
    dc.check_schema_file(root, audit, SETTINGS_OUTPUT, SETTINGS_SCHEMA)
    settings = dc.read_json(root / SETTINGS_OUTPUT, audit, SETTINGS_OUTPUT)
    if settings is None:
        return
    widened = _posture_paths(settings)
    if widened:
        audit.fail("configured", "settings widen the permission posture: " + ", ".join(widened))
    else:
        audit.ok("configured", "settings carry no prompt-skipping keys")
    permissions = settings.get("permissions")
    deny = permissions.get("deny") if isinstance(permissions, dict) else None
    if isinstance(deny, list) and deny:
        audit.ok("configured", f"permissions.deny is non-empty ({len(deny)} rule(s))")
    else:
        audit.fail("configured", "permissions.deny is empty or missing; the schema alone does not catch a widened allow list")
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        audit.fail("configured", "settings carry no hooks object")
        return
    registered = 0
    missing: list[str] = []
    unexpected_events = sorted(set(hooks) - set(dc.HOOK_EVENTS))
    if unexpected_events:
        audit.fail("configured", "settings register undeclared hook events: " + ", ".join(unexpected_events))
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            missing.append(f"{event}: not a list")
            continue
        for group in groups:
            for handler in (group.get("hooks", []) if isinstance(group, dict) else []):
                registered += 1
                command = str(handler.get("command", "")) if isinstance(handler, dict) else ""
                match = HOOK_COMMAND.search(command)
                if not match:
                    missing.append(f"{event}: command does not name a harness/hooks wrapper")
                elif not (root / match.group(1)).is_file():
                    missing.append(f"{event}: wrapper {match.group(1)} is missing")
    if missing:
        for item in missing:
            audit.fail("configured", f"hook registration: {item}")
    else:
        audit.ok("configured", f"{registered} hook registration(s) name existing harness/hooks wrappers")


def check_repository(root: Path, audit: dc.Audit) -> None:
    """Pure repository audit: file reads and local git config reads only."""
    dc.check_contract_files(root, audit)
    dc.check_gitignore_floor(root, audit, "claude")
    dc.check_junction_rows(root, audit, "claude")
    check_settings(root, audit)
    dc.check_selection(root, audit, SKILLS_DIR, "link")
    dc.check_git_floor(root, audit)
    dc.check_model_map(root, audit, "claude")
    dc.check_capabilities(root, audit, "claude")
    dc.check_degradation_rungs(root, audit, "claude")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="explicitly select the default pure repository audit")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    dc.print_header("Claude Code", root, ["offline"])
    audit = dc.Audit()
    check_repository(root, audit)
    dc.finish_unknown(audit, {
        "configured": "no repository configuration evidence was collected",
        "loaded": "Claude Code was not launched; settings and skill loading not observed",
        "trusted": "Claude Code trust prompts are per user; not observed offline",
        "fired": "native hook delivery not observed; record a live run in docs/VERIFICATION.md",
        "enforced": "no PreToolUse deny was observed through Claude Code",
        "outcome-proven": "no artifact-level workflow evidence was collected",
    })
    audit.summary()
    return 1 if audit.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
