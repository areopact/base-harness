#!/usr/bin/env python3
"""PreToolUse(Read) guard, Claude Code only, shipped OFF.

Denies the native Read tool on a file whose frontmatter carries exactly
`access: secret`. Every other label, a missing label, a missing block, an
unreadable file, or a non-Markdown target passes.

Activation: the environment variable HARNESS_READ_DENY must equal "1". The
module checks it and dispatch.py checks it again before routing, so the
guard is inert unless the operator turns it on for their own session.

On Codex and OpenCode the five tier labels are documentation only: neither
runtime routes a file read through a hookable PreToolUse event with this
shape, and this hook is not registered there. Bash reads on any runtime are
outside this hook; dangerous_ops_guard covers credential paths for those.
"""
import hashlib
import json
import os
import sys

from _debug import debug
from hook_io import absolute_path, canonical_tool_name, deny, parse_frontmatter, tool_input

HOOK_NAME = "read-deny"
TIER = "secret-label"
ENV_FLAG = "HARNESS_READ_DENY"
MAX_HEADER_BYTES = 64 * 1024


def enabled(environ=None):
    environ = environ if environ is not None else os.environ
    return environ.get(ENV_FLAG, "") == "1"


def access_label(path, root=None):
    """The access label of a Markdown file, lowercased; "" when absent.

    A relative path resolves against the repository root, never the process
    working directory, so a payload behaves the same from any cwd.
    """
    try:
        with open(absolute_path(path, root), "r", encoding="utf-8-sig", errors="replace") as handle:
            head = handle.read(MAX_HEADER_BYTES)
    except OSError:
        return ""
    fields, closed = parse_frontmatter(head)
    if not fields or not closed:
        return ""
    value = fields.get("access", "")
    return value.strip().lower() if isinstance(value, str) else ""


def decide(data, environ=None, root=None):
    """Return the deny JSON string, or None to allow."""
    if not enabled(environ):
        return None
    if not isinstance(data, dict) or canonical_tool_name(data) != "Read":
        return None
    target = tool_input(data).get("file_path")
    if not isinstance(target, str) or not target:
        return None
    if access_label(target, root) != "secret":
        return None
    digest = hashlib.sha256(target.encode("utf-8")).hexdigest()
    return deny(
        HOOK_NAME,
        TIER,
        f"{target} is labeled access: secret and is excluded from every agent session",
        digest,
        "Ask the operator to relabel the file or to summarize it for you.",
    )


def main():
    debug.start()
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        debug.end(HOOK_NAME, out_bytes=0, extra="bad-json")
        sys.exit(0)
    out = decide(data)
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="allow")
        sys.exit(0)
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="deny")
    sys.exit(0)


if __name__ == "__main__":
    main()
