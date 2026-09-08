#!/usr/bin/env python3
"""Render, check, and repair the agent-contract files.

Composition contract:

- root ``AGENTS.md`` is ``harness/CONTRACT.md`` followed by exactly one blank
  line and then ``harness/CONTRACT.host.md``, normalized to UTF-8 with LF line
  endings and no BOM;
- root ``CLAUDE.md`` is exactly the bytes ``@AGENTS.md`` plus one newline;
- there is no ``.codex/AGENTS.md`` copy (Codex reads the root file natively)
  and no ``.claude/CLAUDE.md`` copy (the root pointer already delivers the
  contract; a second copy would load it twice); if either exists it is
  removed by ``repair`` and reported by ``check``.

The rendered files are independent files, never hardlinks to a source.

Host-owned mode: when ``harness/registry/structure.json`` sets
``contract.mode`` to ``host-owned`` (set automatically by ``adopt.py`` when
the target already carries an ``AGENTS.md``), the root ``AGENTS.md`` is the
host's own file. Bootstrap never writes it, ``check_contract`` never compares
it against the render, and the composed template block lands at
``AGENTS.harness.md`` instead. The ``CLAUDE.md`` pointer and the retired-copy
cleanup are unchanged; ``contract_advisory`` separately flags a host
``AGENTS.md`` that does not reference ``AGENTS.harness.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

CONTRACT_TEMPLATE = Path("harness/CONTRACT.md")
CONTRACT_HOST = Path("harness/CONTRACT.host.md")
CONTRACT_OUTPUT = Path("AGENTS.md")
CONTRACT_HOST_OWNED_OUTPUT = Path("AGENTS.harness.md")
CLAUDE_POINTER = Path("CLAUDE.md")
CLAUDE_POINTER_BYTES = b"@AGENTS.md\n"
RETIRED_COPIES = (Path(".codex/AGENTS.md"), Path(".claude/CLAUDE.md"))
UTF8_BOM = b"\xef\xbb\xbf"
CONTRACT_MODES = ("rendered", "host-owned")


def contract_mode(root: Path) -> str:
    """Return structure.json's contract.mode, defaulting to 'rendered'."""
    path = Path(root) / "harness" / "registry" / "structure.json"
    if not path.is_file():
        return "rendered"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return "rendered"
    if not isinstance(data, dict):
        return "rendered"
    mode = (data.get("contract") or {}).get("mode")
    return mode if mode in CONTRACT_MODES else "rendered"


def contract_advisory(root: Path) -> str | None:
    """Return an advisory string when a host-owned AGENTS.md does not point at AGENTS.harness.md."""
    root = Path(root)
    if contract_mode(root) != "host-owned":
        return None
    pointer = root / CONTRACT_OUTPUT
    if not pointer.is_file():
        return None
    try:
        text = pointer.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if CONTRACT_HOST_OWNED_OUTPUT.name in text:
        return None
    return (
        "host contract does not point at AGENTS.harness.md; "
        "add a line so runtimes load the harness block"
    )


def lf_bytes(raw: bytes) -> bytes:
    """Return canonical UTF-8 bytes with no BOM and LF-only newlines."""
    if raw.startswith(UTF8_BOM):
        raw = raw[len(UTF8_BOM):]
    text = raw.decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def render(root: Path) -> bytes:
    """Return the AGENTS.md bytes for this repository without writing."""
    root = Path(root)
    template = lf_bytes((root / CONTRACT_TEMPLATE).read_bytes())
    host = lf_bytes((root / CONTRACT_HOST).read_bytes())
    if not template.endswith(b"\n"):
        template += b"\n"
    if host and not host.endswith(b"\n"):
        host += b"\n"
    return template + b"\n" + host


def _first_difference(left: bytes, right: bytes) -> int:
    for offset, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return offset
    return min(len(left), len(right))


def check_contract(root: Path) -> list[str]:
    """Return invariant violations without changing the filesystem."""
    root = Path(root)
    host_owned = contract_mode(root) == "host-owned"
    issues: list[str] = []
    for source in (CONTRACT_TEMPLATE, CONTRACT_HOST):
        if not (root / source).is_file():
            issues.append(f"{source.as_posix()} missing")
    if issues:
        return issues
    try:
        expected = render(root)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"contract sources are not readable UTF-8 ({exc})"]

    if host_owned:
        output = root / CONTRACT_HOST_OWNED_OUTPUT
        if not output.is_file():
            issues.append(f"{CONTRACT_HOST_OWNED_OUTPUT.as_posix()} missing")
        else:
            actual = output.read_bytes()
            if actual != expected:
                offset = _first_difference(actual, expected)
                issues.append(
                    f"{CONTRACT_HOST_OWNED_OUTPUT.as_posix()} bytes differ from the rendered contract "
                    f"(first difference at byte offset {offset})"
                )
    else:
        output = root / CONTRACT_OUTPUT
        if not output.is_file():
            issues.append(f"{CONTRACT_OUTPUT.as_posix()} missing")
        else:
            for source in (CONTRACT_TEMPLATE, CONTRACT_HOST):
                try:
                    if os.path.samefile(root / source, output):
                        issues.append(f"{CONTRACT_OUTPUT.as_posix()} is a hardlink to {source.as_posix()}")
                except OSError:
                    pass
            actual = output.read_bytes()
            if actual != expected:
                offset = _first_difference(actual, expected)
                issues.append(
                    f"{CONTRACT_OUTPUT.as_posix()} bytes differ from the rendered contract "
                    f"(first difference at byte offset {offset})"
                )

    pointer = root / CLAUDE_POINTER
    if not pointer.is_file():
        issues.append(f"{CLAUDE_POINTER.as_posix()} missing")
    elif pointer.read_bytes() != CLAUDE_POINTER_BYTES:
        issues.append(f"{CLAUDE_POINTER.as_posix()} must contain exactly '@AGENTS.md' and one newline")

    for retired in RETIRED_COPIES:
        path = root / retired
        if path.exists() or path.is_symlink():
            issues.append(f"{retired.as_posix()} exists; the contract is read from the root file only")
    return issues


def _replace_bytes(path: Path, content: bytes) -> None:
    """Atomically replace one managed file, preserving its mode when present."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not path.is_file():
        raise OSError(f"managed contract path is not a file: {path}")
    mode = path.stat().st_mode if path.exists() else None
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_if_needed(path: Path, content: bytes, sources: tuple[Path, ...]) -> bool:
    current = path.read_bytes() if path.is_file() else None
    linked = False
    if path.is_file():
        for source in sources:
            try:
                if os.path.samefile(source, path):
                    linked = True
            except OSError:
                pass
    if path.is_symlink():
        path.unlink()
        current = None
    if current == content and not linked:
        return False
    if linked:
        path.unlink()
    _replace_bytes(path, content)
    return True


def repair_contract(root: Path) -> list[str]:
    """Render AGENTS.md (or AGENTS.harness.md in host-owned mode) and CLAUDE.md, remove retired copies, return changes."""
    root = Path(root)
    host_owned = contract_mode(root) == "host-owned"
    changed: list[str] = []
    for source in (CONTRACT_TEMPLATE, CONTRACT_HOST):
        path = root / source
        if not path.is_file():
            raise OSError(f"contract source missing: {source.as_posix()}")
        raw = path.read_bytes()
        canonical = lf_bytes(raw)
        if raw != canonical:
            _replace_bytes(path, canonical)
            changed.append(source.as_posix())
    expected = render(root)
    if host_owned:
        if _write_if_needed(root / CONTRACT_HOST_OWNED_OUTPUT, expected, ()):
            changed.append(CONTRACT_HOST_OWNED_OUTPUT.as_posix())
    elif _write_if_needed(root / CONTRACT_OUTPUT, expected, (root / CONTRACT_TEMPLATE, root / CONTRACT_HOST)):
        changed.append(CONTRACT_OUTPUT.as_posix())
    if _write_if_needed(root / CLAUDE_POINTER, CLAUDE_POINTER_BYTES, ()):
        changed.append(CLAUDE_POINTER.as_posix())
    for retired in RETIRED_COPIES:
        path = root / retired
        if path.is_symlink() or path.is_file():
            path.unlink()
            changed.append(f"{retired.as_posix()} (removed)")
        elif path.exists():
            raise OSError(f"retired contract path is a directory, not removed: {retired.as_posix()}")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("render", "check", "repair"),
        help="render prints the composed contract; check is read-only; repair writes the outputs",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root (defaults to this script's repository)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.action == "render":
        try:
            content = render(root)
        except (OSError, UnicodeDecodeError) as exc:
            print(f"ERROR: cannot render contract: {exc}")
            return 1
        sys.stdout.buffer.write(content)
        return 0

    if args.action == "check":
        issues = check_contract(root)
        if issues:
            print(f"Agent contract: {len(issues)} violation(s)")
            for issue in issues:
                print(f"  ERROR: {issue}")
            return 1
        if contract_mode(root) == "host-owned":
            print("Agent contract: host-owned (AGENTS.md is the host's; template block at AGENTS.harness.md)")
        else:
            print("Agent contract: OK (AGENTS.md rendered; CLAUDE.md pointer exact; no retired copies)")
        advisory = contract_advisory(root)
        if advisory:
            print(f"  ADVISORY: {advisory}")
        return 0

    try:
        changed = repair_contract(root)
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: agent contract repair failed: {exc}")
        return 1
    if changed:
        print("Agent contract: repaired " + ", ".join(changed))
    else:
        print("Agent contract: OK (no repair needed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
