#!/usr/bin/env python3
"""Single-process dispatcher for Codex and OpenCode hook envelopes.

One Python process per event runs the hook modules in a fixed order, merges
their JSON outputs, and applies the runtime's context limit from
harness/registry/runtimes.json. A deny short-circuits every later module.
The dispatcher itself always exits 0; the decision lives in the JSON.

SessionStart output is budgeted per lane (identity, knowledge, journal,
other) with weights, never tail-truncated, and always carries a footer
naming the trimmed and omitted sources when the budget applied.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

import close_the_loop
import dangerous_ops_guard
import delegation_guard
import frontmatter_guard
import load_identity
import memory_first
import openpyxl_guard
import pre_bootstrap_detector
import prose_lint
import read_deny
from hook_io import REPO_ROOT, canonical_tool_name, lane_paths

EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}
RUNTIMES = ("codex", "opencode")
WEB_TOOLS = {"WebSearch", "WebFetch", "web_search", "web__run", "web.run"}
EDIT_TOOLS = {"Edit", "Write", "NotebookEdit", "apply_patch"}
REGISTRY = REPO_ROOT / "harness" / "registry" / "runtimes.json"
SESSION_HEADER = re.compile(r"(?m)^=== (.+?) ===\s*$")
HEADER_PATH = re.compile(r"\(([^()]+)\)\s*$")
SESSION_WEIGHTS = {"identity": 40, "knowledge": 20, "journal": 10, "other": 5}
FOOTER_RESERVE = 600
CAP_SUFFIX = "\n[hook context capped; read the named source files on demand]"
TRIM_SUFFIX = "\n[... trimmed; read the named source on demand]"


def context_limit(runtime: str, event: str) -> int | None:
    """Return the registry limit; fail open when the registry is unavailable."""
    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8-sig"))
        value = registry["hook_events"][event]["runtimes"][runtime]["context_limit"]
        return value if isinstance(value, int) and value > 0 else None
    except (OSError, KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


def cap_context(value: str, limit: int | None) -> str:
    if limit is None or len(value) <= limit:
        return value
    if limit <= len(CAP_SUFFIX):
        return value[:limit]
    cut = value[: limit - len(CAP_SUFFIX)].rsplit("\n", 1)[0]
    return cut + CAP_SUFFIX


def _lane_kind(path: str, root: Path | None = None) -> str:
    """Classify a source path by the structure.json lane that contains it."""
    for kind in ("identity", "knowledge", "journal"):
        for lane in lane_paths(kind, root):
            if path == lane or path.startswith(lane + "/"):
                return kind
    return "other"


def _identity_lanes(value: str, root: Path | None = None) -> list[tuple[str, str, str]]:
    """Split load_identity output into (kind, source, text) lanes by header."""
    matches = list(SESSION_HEADER.finditer(value))
    lanes: list[tuple[str, str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        text = value[match.start():end].strip()
        header = match.group(1)
        path_match = HEADER_PATH.search(header)
        source = path_match.group(1).strip() if path_match else header.strip()
        lanes.append((_lane_kind(source, root), source, text))
    return lanes


def _session_lanes(values: list[str], root: Path | None = None) -> list[tuple[str, str, str]]:
    lanes: list[tuple[str, str, str]] = []
    for value in values:
        identity = _identity_lanes(value, root)
        if identity:
            lanes.extend(identity)
        else:
            lanes.append(("other", "unclassified SessionStart hook output", value.strip()))
    order = {name: index for index, name in enumerate(SESSION_WEIGHTS)}
    return sorted(lanes, key=lambda lane: order[lane[0]])


def _trim_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= len(TRIM_SUFFIX) + 20:
        return value[:limit]
    cut = value[: limit - len(TRIM_SUFFIX)].rsplit(" ", 1)[0]
    if cut.rfind("[[") > cut.rfind("]]"):
        cut = cut[:cut.rfind("[[")].rstrip()
    return cut + TRIM_SUFFIX


def _trim_lane(kind: str, source: str, value: str, limit: int) -> str:
    if kind == "identity":
        header, newline, body = value.partition("\n")
        if newline:
            budget = max(0, limit - len(header) - 1)
            return header + "\n" + load_identity.truncate_identity(body, budget, source)
    return _trim_text(value, limit)


def budget_session_context(values: list[str], limit: int, root: Path | None = None) -> str:
    """Compose weighted lanes; never tail-truncate SessionStart context."""
    full = "\n\n".join(value for value in values if value.strip())
    if len(full) <= limit:
        return full
    lanes = _session_lanes(values, root)
    if not lanes:
        return cap_context(full, limit)
    separator_cost = 2 * max(0, len(lanes) - 1)
    content_budget = max(0, limit - FOOTER_RESERVE - separator_cost)
    weight_total = sum(SESSION_WEIGHTS[kind] for kind, _source, _text in lanes)
    chunks: list[str] = []
    trimmed: list[str] = []
    omitted: list[str] = []
    for kind, source, value in lanes:
        allocation = content_budget * SESSION_WEIGHTS[kind] // weight_total
        if allocation < 80:
            omitted.append(source)
            continue
        chunk = _trim_lane(kind, source, value, allocation)
        if len(chunk) < len(value):
            trimmed.append(source)
        chunks.append(chunk)
    footer = (
        "[boot context budget; trimmed sources (read on demand): "
        + (", ".join(dict.fromkeys(trimmed)) or "none")
        + "; omitted sources: "
        + (", ".join(dict.fromkeys(omitted)) or "none")
        + "]"
    )
    result = "\n\n".join(chunks + [footer])
    return result if len(result) <= limit else cap_context(result, limit)


def read_deny_enabled(environ=None) -> bool:
    environ = environ if environ is not None else os.environ
    return environ.get("HARNESS_READ_DENY", "") == "1"


def modules_for(event: str, data: dict, environ=None) -> list[object]:
    tool = canonical_tool_name(data)
    raw_tool = data.get("tool_name", "")
    if event == "SessionStart":
        return [load_identity, pre_bootstrap_detector]
    if event == "PreToolUse":
        if raw_tool in WEB_TOOLS:
            return [memory_first]
        if tool == "Bash":
            return [dangerous_ops_guard, openpyxl_guard]
        if tool == "Read":
            return [read_deny] if read_deny_enabled(environ) else []
        if tool in ("Agent", "Workflow"):
            return [delegation_guard]
    if event == "PostToolUse":
        if tool in EDIT_TOOLS:
            return [frontmatter_guard, prose_lint]
        if tool in ("Agent", "Workflow"):
            return [delegation_guard]
    if event == "Stop":
        return [close_the_loop]
    return []


def invoke(module: object, raw: str, event: str | None = None, runtime: str | None = None) -> list[dict]:
    old_stdin = sys.stdin
    output = io.StringIO()
    try:
        sys.stdin = io.StringIO(raw)
        with contextlib.redirect_stdout(output):
            try:
                if module is delegation_guard:
                    module.main(event_override=event)
                elif module in (load_identity, pre_bootstrap_detector):
                    module.main(runtime=runtime)
                else:
                    module.main()
            except SystemExit:
                pass
    except Exception as exc:
        print(f"hook-dispatch: {module.__name__} failed: {exc}", file=sys.stderr)
        return []
    finally:
        sys.stdin = old_stdin
    results = []
    for line in output.getvalue().splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            print(f"hook-dispatch: {module.__name__} emitted non-JSON output", file=sys.stderr)
            continue
        if isinstance(value, dict):
            results.append(value)
    return results


def is_deny(payload: dict) -> bool:
    specific = payload.get("hookSpecificOutput")
    return isinstance(specific, dict) and specific.get("permissionDecision") == "deny"


def combine(event: str, payloads: Iterable[dict], limit: int | None = None) -> dict | None:
    contexts: list[str] = []
    messages: list[str] = []
    for payload in payloads:
        specific = payload.get("hookSpecificOutput")
        if isinstance(specific, dict):
            if specific.get("permissionDecision") == "deny":
                specific["hookEventName"] = event
                return {"hookSpecificOutput": specific}
            context = specific.get("additionalContext")
            if isinstance(context, str) and context.strip():
                contexts.append(context.strip())
        message = payload.get("systemMessage")
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    if event == "Stop":
        combined = messages + contexts
        return {"systemMessage": "\n\n".join(combined)} if combined else None
    combined = contexts + messages
    if not combined:
        return None
    additional_context = (
        budget_session_context(combined, limit)
        if event == "SessionStart" and limit is not None
        else cap_context("\n\n".join(combined), limit)
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": additional_context,
        }
    }


def dispatch(event: str, raw: str, runtime: str = "codex") -> dict | None:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    payloads: list[dict] = []
    for module in modules_for(event, data):
        module_payloads = invoke(module, raw, event, runtime)
        payloads.extend(module_payloads)
        if any(is_deny(payload) for payload in module_payloads):
            break
    return combine(event, payloads, context_limit(runtime, event))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, choices=sorted(EVENTS))
    parser.add_argument("--runtime", default="codex", choices=RUNTIMES)
    args = parser.parse_args(argv)
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    result = dispatch(args.event, raw, runtime=args.runtime)
    if result is not None:
        if hasattr(sys.stdout, "reconfigure"):
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
