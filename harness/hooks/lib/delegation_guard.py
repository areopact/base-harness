#!/usr/bin/env python3
"""Delegation advisory for Agent and Workflow dispatches, gated by the host.

Enforcement rung: advisory. The hook is a no-op unless structure.json sets
delegation.mandatory to true; the shipped default is false, so out of the
box it emits nothing. When enabled it reminds the model that every dispatch
resolves through the authored routing policy (harness/rules/base-routing.md)
and that a launch or task id is not completion evidence.

Stateless: no file writes, no network, no receipt state. The policy is
referenced, never copied.

main(event_override=None) keeps the signature dispatch.py relies on, since
the same module serves PreToolUse and PostToolUse.
"""
import json
import sys

from _debug import debug
from hook_io import advisory_for, canonical_tool_name, load_structure

HOOK_NAME = "delegation-guard"
PRE_MSG = (
    "delegation-guard: resolve this dispatch's task ID, role, model, and tools "
    "through harness/rules/base-routing.md and the generated native routing. "
    "Complex execution uses the workflow skill. A model argument alone does not "
    "prove policy compliance; inherited defaults and escalation must obey the "
    "same child-model ceiling. This hook is advisory, not completion evidence."
)
POST_MSG = (
    "delegation-guard: quality-gate this subagent result using the actual terminal "
    "lifecycle and the current artifact revision. A launch or task ID is not completion. "
    "Reject null, failed, incomplete, or stale results; obtain independent review "
    "before managed completion. Resolve any retry through harness/rules/base-routing.md; "
    "do not upgrade beyond its authorized child-model ceiling."
)


def mandatory(structure=None):
    structure = structure if structure is not None else load_structure()
    value = structure.get("delegation") if isinstance(structure, dict) else None
    return bool(isinstance(value, dict) and value.get("mandatory") is True)


def decide(data, event_override=None, structure=None):
    """Return the advisory JSON string, or None when silent."""
    if not mandatory(structure):
        return None
    if not isinstance(data, dict) or canonical_tool_name(data) not in ("Agent", "Workflow"):
        return None
    event = event_override or data.get("hook_event_name")
    if event in ("PreToolUse", "PostToolUse"):
        mode = "post" if event == "PostToolUse" else "pre"
    else:
        mode = "post" if ("tool_response" in data or "output" in data) else "pre"
    return advisory_for(
        data,
        "PostToolUse" if mode == "post" else "PreToolUse",
        POST_MSG if mode == "post" else PRE_MSG,
    )


def main(event_override=None):
    debug.start()
    try:
        data = json.load(sys.stdin)
    except (ValueError, TypeError):
        debug.end(HOOK_NAME, out_bytes=0, extra="bad-json")
        return
    out = decide(data, event_override)
    if out is None:
        debug.end(HOOK_NAME, out_bytes=0, extra="silent")
        return
    print(out)
    debug.end(HOOK_NAME, out_bytes=len(out), extra="advisory")


if __name__ == "__main__":
    main()
