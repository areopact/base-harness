#!/usr/bin/env python3
"""Directory-link primitives shared by every harness that materializes runtime
paths through links.

One module, byte-identical wherever it is used: the template engine
(materialize.py and the doctors) and the upstream vault's link layer import
it, and the upstream drift gate fails a release when the copies differ, so a
link fix lands once. Stdlib only; no repository knowledge; no side effects on
import.

A link is only healthy when this process can read through it. Windows
Redirection Guard stamps a junction with its creator's trust level and an
elevated process refuses to follow one created non-elevated (Win32 448,
"untrusted mount point"); existence and target checks both pass on such a
link, so link_blocked() performs one directory read.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

UNTRUSTED_MOUNT_POINT = 448  # Win32 ERROR_UNTRUSTED_MOUNT_POINT (Redirection Guard)
UNTRUSTED_LINK_DRIFT = (
    "cannot be traversed by this elevated process (Windows Redirection Guard: the junction "
    "was created non-elevated); run bootstrap from an elevated shell"
)


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


def is_untrusted_mount_point(exc: BaseException) -> bool:
    """True for the Windows Redirection Guard refusal (Win32 448)."""
    return getattr(exc, "winerror", None) == UNTRUSTED_MOUNT_POINT


def link_blocked(path: Path) -> bool:
    """One read through a link: True only when Windows Redirection Guard
    refuses the traversal. Any other error is left to the caller's normal
    handling. Reads at most one entry and never follows further."""
    try:
        with os.scandir(path) as entries:
            next(entries, None)
    except OSError as exc:
        return is_untrusted_mount_point(exc)
    return False


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
