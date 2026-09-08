#!/usr/bin/env python3
"""SessionStart context injector: deliver the identity lane, bounded.

Reads every file in structure.json lanes["identity"], in declared order, and
emits one SessionStart additionalContext block:

    === <stem> (<path>) ===
    <body without frontmatter>

The character budget comes from harness/registry/runtimes.json
runtimes.<runtime>.identity_context_limit for the runtime named by
--runtime on argv or HARNESS_RUNTIME; without a runtime the smallest tier-1
value applies, and without the registry a fixed fallback applies.

Truncation is deterministic: sections (level-two headings) are kept whole in
document order until the budget is spent, the first section that does not fit
is cut at a paragraph boundary, and the block ends with
"[identity truncated at <n> chars; read <path> on demand]".

A file whose frontmatter carries access: secret is skipped. When the identity
lane is null nothing is emitted, so a doctor can tell "not configured" from
"configured but delivery unproven". Always exits 0.
"""
import json
import os
import re
import sys
from pathlib import Path

from _debug import debug
from hook_io import REPO_ROOT, lane_paths, parse_frontmatter

HOOK_NAME = "load-identity"
RUNTIMES_RELATIVE = ("harness", "registry", "runtimes.json")
FALLBACK_LIMIT = 9000
TRUNCATION_NOTE = "[identity truncated at {limit} chars; read {path} on demand]"
SECTION_RE = re.compile(r"(?m)^## ")


def runtime_from(argv=None, environ=None):
    argv = argv if argv is not None else sys.argv[1:]
    environ = environ if environ is not None else os.environ
    for index, item in enumerate(argv):
        if item == "--runtime" and index + 1 < len(argv):
            return argv[index + 1]
        if item.startswith("--runtime="):
            return item.split("=", 1)[1]
    return environ.get("HARNESS_RUNTIME") or None


def identity_limit(runtime=None, root=None):
    """Registry limit for the runtime, else the smallest tier-1 limit, else fallback."""
    base = Path(root) if root is not None else REPO_ROOT
    try:
        registry = json.loads(base.joinpath(*RUNTIMES_RELATIVE).read_text(encoding="utf-8-sig"))
        runtimes = registry["runtimes"]
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
        return FALLBACK_LIMIT
    if not isinstance(runtimes, dict):
        return FALLBACK_LIMIT
    if runtime and isinstance(runtimes.get(runtime), dict):
        value = runtimes[runtime].get("identity_context_limit")
        if isinstance(value, int) and value > 0:
            return value
    candidates = [
        entry.get("identity_context_limit")
        for entry in runtimes.values()
        if isinstance(entry, dict) and entry.get("tier") == "tier-1"
    ]
    candidates = [value for value in candidates if isinstance(value, int) and value > 0]
    return min(candidates) if candidates else FALLBACK_LIMIT


def read_identity_file(path):
    """Body without frontmatter; "" when secret, unreadable, or unclosed."""
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return ""
    fields, closed = parse_frontmatter(text)
    if fields is None:
        return text.strip()
    if not closed:
        return ""
    access = fields.get("access", "")
    if isinstance(access, str) and access.strip().lower() == "secret":
        return ""
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[index + 1:]).strip()
    return ""


def _cut_at_boundary(text, budget):
    """Cut text to the budget at the best boundary that keeps most of it.

    A paragraph break is preferred, then a line break, then a space, but a
    boundary is accepted only when it lies in the back half of the budget;
    otherwise the next finer separator is tried, so a long single paragraph
    is cut at a word instead of collapsing to its heading line.
    """
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    head = text[:budget]
    floor = budget // 2
    for separator in ("\n\n", "\n", " "):
        position = head.rfind(separator)
        if position >= floor:
            return head[:position].rstrip()
    return head.rstrip()


def truncate_identity(text, limit, path):
    """Deterministic section-priority truncation with the standard note."""
    if len(text) <= limit:
        return text
    note = TRUNCATION_NOTE.format(limit=limit, path=path)
    budget = limit - len(note) - 1
    if budget <= 0:
        return note[:limit]
    boundaries = [match.start() for match in SECTION_RE.finditer(text)]
    pieces = []
    if boundaries:
        if boundaries[0] > 0:
            pieces.append(text[:boundaries[0]].rstrip())
        for index, start in enumerate(boundaries):
            end = boundaries[index + 1] if index + 1 < len(boundaries) else len(text)
            pieces.append(text[start:end].rstrip())
    else:
        pieces.append(text.rstrip())
    kept = []
    used = 0
    for piece in pieces:
        if not piece:
            continue
        cost = len(piece) + (1 if kept else 0)
        if used + cost <= budget:
            kept.append(piece)
            used += cost
            continue
        remaining = budget - used - (1 if kept else 0)
        partial = _cut_at_boundary(piece, remaining)
        if partial:
            kept.append(partial)
        break
    body = "\n".join(kept).rstrip()
    return (body + "\n" + note) if body else note


def _allocate(lengths, budget):
    """Split a budget across files: short files keep their length, the rest share."""
    remaining = budget
    allocation = [0] * len(lengths)
    pending = list(range(len(lengths)))
    while pending:
        share = remaining // len(pending)
        satisfied = [index for index in pending if lengths[index] <= share]
        if not satisfied:
            for index in pending:
                allocation[index] = share
            break
        for index in satisfied:
            allocation[index] = lengths[index]
            remaining -= lengths[index]
            pending.remove(index)
    return allocation


def render(root=None, runtime=None, limit=None):
    """Return the composed identity block, or None when the lane is null."""
    base = Path(root) if root is not None else REPO_ROOT
    lanes = lane_paths("identity", base)
    if not lanes:
        return None
    limit = limit if isinstance(limit, int) and limit > 0 else identity_limit(runtime, base)
    entries = []
    for relative in lanes:
        target = base / relative
        if not target.is_file():
            continue
        body = read_identity_file(target)
        if not body:
            continue
        entries.append((relative, f"=== {target.stem} ({relative}) ===", body))
    if not entries:
        return None
    header_cost = sum(len(header) + 1 for _relative, header, _body in entries)
    separator_cost = 2 * (len(entries) - 1)
    budget = max(0, limit - header_cost - separator_cost)
    allocation = _allocate([len(body) for _relative, _header, body in entries], budget)
    blocks = []
    for (relative, header, body), share in zip(entries, allocation):
        blocks.append(header + "\n" + truncate_identity(body, share, relative))
    combined = "\n\n".join(blocks)
    if len(combined) > limit:
        combined = combined[:limit]
    return combined


def main(runtime=None):
    debug.start()
    try:
        sys.stdin.read()
    except Exception:
        pass
    combined = render(runtime=runtime or runtime_from())
    if combined is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="identity-lane-null-or-empty")
        sys.exit(0)
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": combined,
        },
    }
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    out = json.dumps(payload, ensure_ascii=False)
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
