#!/usr/bin/env python3
"""Local-only skill usage telemetry over a caller-supplied transcript log.

This tool stays local to each adopter. It reads transcript files that the
caller names, counts invocation signals, and prints a table. It writes
nothing unless ``--write <path>`` is given, touches no network, and its output
is never committed: the counts describe one machine's sessions and nothing
more.

Counted signals (prompt mentions never count):
  1. Skill tool calls          a line carrying "name":"Skill" and "skill":"<name>"
  2. user-typed slash commands <command-name>/x</command-name>

The report splits catalog skills (present under harness/skills) from
external names, and lists catalog skills with zero hits grouped by status. A
zero means zero in the supplied logs, never "never used": inline work leaves
no transcript signal and log retention is bounded.

Usage:
    python harness/tools/skill_usage.py --log <file-or-dir> [--json] [--write <ndjson-path>]

``--log`` accepts a .jsonl file or a directory that is searched recursively
for .jsonl files. Privacy: the tool stores counts only, never line content.
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
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import gen_manifest as gm  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RE_SKILL_NAME = re.compile(r'"skill"\s*:\s*"([^"]+)"')
RE_CMD = re.compile(r"<command-name>/?([a-zA-Z0-9:_-]+)</command-name>")
STATUS_ORDER = ("implemented", "spec-only", "stub")


def transcript_files(log: Path) -> list[Path]:
    """The .jsonl files under a caller-supplied path (a file or a directory)."""
    log = Path(log)
    if log.is_file():
        return [log]
    if log.is_dir():
        return sorted(path for path in log.rglob("*.jsonl") if path.is_file())
    return []


def scan_transcripts(files: list[Path]) -> tuple[Counter, Counter, tuple[str, str] | None]:
    tool_calls: Counter = Counter()
    slash_cmds: Counter = Counter()
    mtimes: list[float] = []
    for path in files:
        try:
            mtimes.append(path.stat().st_mtime)
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if '"name":"Skill"' in line or '"name": "Skill"' in line:
                        tool_calls.update(RE_SKILL_NAME.findall(line))
                    if "<command-name>" in line:
                        slash_cmds.update(RE_CMD.findall(line))
        except OSError:
            continue
    window = None
    if mtimes:
        stamp = lambda value: datetime.fromtimestamp(value).strftime("%Y-%m-%d")  # noqa: E731
        window = (stamp(min(mtimes)), stamp(max(mtimes)))
    return tool_calls, slash_cmds, window


def catalog_status(root: Path) -> dict[str, str]:
    return {skill.name: skill.status or "unknown" for skill in gm.scan_skills(root)}


def build_summary(root: Path, log: Path) -> dict:
    files = transcript_files(log)
    tool_calls, slash_cmds, window = scan_transcripts(files)
    status_of = catalog_status(root)
    names = set(tool_calls) | set(slash_cmds)
    totals = {name: tool_calls.get(name, 0) + slash_cmds.get(name, 0) for name in names}
    catalog = {name: count for name, count in totals.items() if name in status_of}
    external = {name: count for name, count in totals.items() if name not in status_of}
    zero: dict[str, list[str]] = {}
    for name, status in status_of.items():
        if name not in totals:
            zero.setdefault(status, []).append(name)
    for values in zero.values():
        values.sort()
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "log": str(log),
        "window": window,
        "transcripts": len(files),
        "catalog": catalog,
        "external": external,
        "zero_by_status": zero,
        "tool_calls": dict(tool_calls),
        "slash_cmds": dict(slash_cmds),
        "scope": "counts from the supplied logs only; inline work leaves no signal",
    }


def print_table(summary: dict) -> None:
    window = summary["window"]
    span = f"{window[0]} .. {window[1]}" if window else "no transcripts found"
    print(f"skill-usage: {summary['transcripts']} transcript(s), window {span}")
    print("  (zero means zero in the supplied logs, not never)")
    if summary["catalog"]:
        print("-- catalog skills (tool calls + slash commands)")
        for name, count in sorted(summary["catalog"].items(), key=lambda item: (-item[1], item[0])):
            print(f"  {count:4d}  {name}")
    if summary["external"]:
        print("-- external (bundled, plugin, or runtime builtins)")
        for name, count in sorted(summary["external"].items(), key=lambda item: (-item[1], item[0])):
            print(f"  {count:4d}  {name}")
    print("-- zero uses in window, by status")
    for status in STATUS_ORDER:
        names = summary["zero_by_status"].get(status, [])
        if names:
            print(f"  {status} ({len(names)}): {', '.join(names)}")
    print(f"  scope: {summary['scope']}")


def append_snapshot(summary: dict, target: Path) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = {key: summary[key] for key in ("ts", "log", "window", "transcripts", "catalog", "external")}
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, sort_keys=True) + "\n")
    print(f"snapshot appended -> {target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Count skill invocations in caller-supplied transcript logs.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--log", type=Path, required=True, help="a .jsonl transcript or a directory of them")
    parser.add_argument("--json", action="store_true", help="print the machine-readable summary")
    parser.add_argument("--write", type=Path, default=None, help="append a dated NDJSON snapshot to this path")
    args = parser.parse_args(argv)
    summary = build_summary(args.root.resolve(), args.log)
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        print_table(summary)
    if args.write is not None:
        append_snapshot(summary, args.write)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
