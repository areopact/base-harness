#!/usr/bin/env python3
"""Copy the workstation kit into the current user's configuration folders.

The kit is four standalone files: the Alacritty and Herdr configurations,
the ccstatusline layout, and the Claude Code keybindings. This script writes
only to the four resolved targets and their backups. It never edits the
Claude Code settings.json (merge workstation/claude/settings.snippet.json by
hand, see README.md), never writes through a symbolic link, and never
overwrites a file that differs from the kit unless --force is given, in which
case the old file is first copied to <name>.bak-<timestamp> beside it.

Usage:
    python workstation/install.py                 # dry run: report each target
    python workstation/install.py --diff          # dry run with a unified diff
    python workstation/install.py --apply         # write new targets
    python workstation/install.py --apply --force # also replace differing ones
    python workstation/install.py --only herdr,claude-keybindings --apply

Target states: new (absent), same (byte-identical, left alone), differs,
link (a symbolic link, always skipped), blocked (not a regular file, or
unreadable; always skipped).

Exit status: 0 on a dry run, or when --apply wrote or left alone every
selected target; 1 when --apply skipped or failed on a target; 2 on a usage
error.
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

KIT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Item:
    name: str
    source: Path
    target: Path


def targets(env: dict[str, str], home: Path, windows: bool) -> list[Item]:
    """Where each kit file goes for this user. Pure: the caller passes the
    environment, the home directory, and the platform, so tests can resolve
    either platform's paths on any host."""
    config_home = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    if windows:
        appdata = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
        alacritty = appdata / "alacritty" / "alacritty.toml"
        herdr = appdata / "herdr" / "config.toml"
    else:
        alacritty = config_home / "alacritty" / "alacritty.toml"
        # Herdr documents ~/.config on macOS and Linux, not XDG_CONFIG_HOME.
        herdr = home / ".config" / "herdr" / "config.toml"
    if env.get("HERDR_CONFIG_PATH"):
        herdr = Path(env["HERDR_CONFIG_PATH"])
    claude_dir = Path(env["CLAUDE_CONFIG_DIR"]) if env.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    return [
        Item("alacritty", KIT / "alacritty" / "alacritty.toml", alacritty),
        Item("herdr", KIT / "herdr" / "config.toml", herdr),
        # ccstatusline reads ~/.config on every platform, Windows included.
        Item("ccstatusline", KIT / "ccstatusline" / "settings.json", home / ".config" / "ccstatusline" / "settings.json"),
        Item("claude-keybindings", KIT / "claude" / "keybindings.json", claude_dir / "keybindings.json"),
    ]


def state(item: Item) -> str:
    """new, same, differs, link, or blocked."""
    target = item.target
    if target.is_symlink():
        return "link"
    if not target.exists():
        return "new"
    if not target.is_file():
        return "blocked"
    try:
        current = target.read_bytes()
    except OSError:
        return "blocked"
    return "same" if current == item.source.read_bytes() else "differs"


def diff(item: Item) -> str:
    """Unified diff from the target to the kit file. Lines keep their endings,
    so a file that differs only in CRLF still shows every line."""
    old = item.target.read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)
    new = item.source.read_bytes().decode("utf-8").splitlines(keepends=True)
    text = "".join(difflib.unified_diff(old, new, str(item.target), f"kit/{item.source.relative_to(KIT).as_posix()}"))
    if text and any(line.endswith("\r\n") for line in old) and not any(line.endswith("\r\n") for line in new):
        text += "(the target uses CRLF line endings; the kit uses LF)\n"
    return text


def backup_path(target: Path, stamp: str) -> Path:
    """A backup name beside the target that does not exist yet."""
    candidate = target.with_name(f"{target.name}.bak-{stamp}")
    counter = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = target.with_name(f"{target.name}.bak-{stamp}-{counter}")
        counter += 1
    return candidate


def install(item: Item, force: bool, stamp: str) -> tuple[bool, str]:
    """Write one target. Returns (ok, what happened); ok is False when the
    target was skipped or the write failed."""
    current = state(item)
    if current == "same":
        return True, "same, left as is"
    if current == "link":
        return False, "is a symbolic link, skipped (edit the file it points to by hand)"
    if current == "blocked":
        return False, "is not a readable regular file, skipped"
    if current == "differs" and not force:
        return False, "differs, skipped (rerun with --force to replace it after a backup)"
    note = "written"
    try:
        item.target.parent.mkdir(parents=True, exist_ok=True)
        if current == "differs":
            backup = backup_path(item.target, stamp)
            shutil.copy2(item.target, backup)
            note = f"replaced, old file kept at {backup}"
        item.target.write_bytes(item.source.read_bytes())
    except OSError as exc:
        return False, f"failed: {exc}"
    return True, note


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy the workstation kit into this user's configuration folders.")
    parser.add_argument("--apply", action="store_true", help="write the files (default: dry run)")
    parser.add_argument("--force", action="store_true", help="with --apply, replace differing files after a backup")
    parser.add_argument("--diff", action="store_true", help="show a unified diff for each differing file")
    parser.add_argument("--only", default="", help="comma-separated item names to limit the run to")
    args = parser.parse_args(argv)
    if args.force and not args.apply:
        parser.error("--force needs --apply")

    items = targets(dict(os.environ), Path.home(), os.name == "nt")
    if args.only:
        wanted = [name.strip() for name in args.only.split(",") if name.strip()]
        unknown = sorted(set(wanted) - {item.name for item in items})
        if unknown:
            parser.error(f"unknown item(s) {', '.join(unknown)}; choose from {', '.join(item.name for item in items)}")
        items = [item for item in items if item.name in wanted]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    failed = 0
    for item in items:
        if args.diff and state(item) == "differs":
            print(diff(item), end="")
        if args.apply:
            ok, outcome = install(item, args.force, stamp)
            failed += not ok
            print(f"{item.name:<20} {item.target}: {outcome}")
        else:
            print(f"{item.name:<20} {state(item):<9} {item.target}")
    if not args.apply:
        print("dry run: nothing written; rerun with --apply")
    print("next: merge workstation/claude/settings.snippet.json into your Claude Code settings.json by hand (README.md, step 3)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
