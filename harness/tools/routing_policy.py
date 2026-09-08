#!/usr/bin/env python3
"""Compile and resolve the authored delegation policy in base-routing.md.

This is the only parser for the authored Markdown block. Runtime builders and
doctors consume the generated JSON manifest instead of parsing Markdown.

Runtime names come from harness/registry/runtimes.json and model-family labels
are validated against harness/adapters/<runtime>/model-map.json. This module
carries no provider or family literal of its own.

Usage:
    python harness/tools/routing_policy.py compile              # write the manifest, print its digest
    python harness/tools/routing_policy.py check                # exit 1 when the manifest drifted
    python harness/tools/routing_policy.py resolve --task <id> [--runtime <r>] [--assignment executor|reviewer]

The manifest (harness/registry/delegation-policy.json) is a generated file:
regenerate it after editing the authored block, never edit it by hand.
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
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("harness/rules/base-routing.md")
MANIFEST = Path("harness/registry/delegation-policy.json")
RUNTIME_REGISTRY = Path("harness/registry/runtimes.json")
MODEL_MAP = "harness/adapters/{runtime}/model-map.json"
BEGIN = "<!-- routing-policy:begin -->"
END = "<!-- routing-policy:end -->"
SCHEMA_VERSION = 1
# The interface contract fixes these three runtime names. The registry is the
# authority at runtime; the tuple is only the fallback when no registry exists.
DEFAULT_RUNTIMES = ("claude", "codex", "opencode")
PLANNING_RANK = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}
CAPABILITY_RANK = {"Fast": 0, "Balanced": 1, "Strong": 2, "Strong main": 3}


class PolicyError(ValueError):
    """The authored or requested routing policy is invalid."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def policy_digest(policy: dict[str, Any]) -> str:
    """Hash normalized authored policy only, excluding generated views."""
    return hashlib.sha256(_canonical(policy).encode("utf-8")).hexdigest()


def load_runtimes(root: Path = ROOT) -> tuple[str, ...]:
    """Return the tier-1 runtime names declared in the registry, in declaration order.

    The policy allocates only to runtimes that carry an adapter. Experimental
    entries stay in the registry for the doctors but never appear in a profile.
    """
    path = Path(root) / RUNTIME_REGISTRY
    if not path.is_file():
        return DEFAULT_RUNTIMES
    try:
        registry = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read {RUNTIME_REGISTRY.as_posix()}: {exc}") from exc
    runtimes = registry.get("runtimes") if isinstance(registry, dict) else None
    if not isinstance(runtimes, dict) or not runtimes:
        raise PolicyError(f"{RUNTIME_REGISTRY.as_posix()} declares no runtimes")
    names = tuple(
        name for name, spec in runtimes.items()
        if isinstance(spec, dict) and spec.get("tier") == "tier-1"
    )
    if not names:
        raise PolicyError(f"{RUNTIME_REGISTRY.as_posix()} declares no tier-1 runtimes")
    return names


def model_map_families(root: Path, runtime: str) -> set[str] | None:
    """Family labels the runtime adapter can translate; None when no map exists."""
    path = Path(root) / MODEL_MAP.format(runtime=runtime)
    if not path.is_file():
        return None
    try:
        native = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"cannot read {path.as_posix()}: {exc}") from exc
    families = native.get("families") if isinstance(native, dict) else None
    if not isinstance(families, dict):
        raise PolicyError(f"{path.as_posix()} has no families object")
    return set(families)


def _extract(text: str) -> dict[str, Any]:
    pattern = re.compile(
        re.escape(BEGIN) + r"\s*```json\s*(.*?)\s*```\s*" + re.escape(END),
        re.DOTALL,
    )
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise PolicyError("base-routing must contain exactly one authored routing-policy block")
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise PolicyError(f"routing-policy block is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PolicyError("routing-policy block must contain one JSON object")
    return value


def _keys(value: dict[str, Any], required: set[str], label: str, errors: list[str]) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing:
        errors.append(f"{label}: missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"{label}: unknown fields: {', '.join(unknown)}")


def validate_policy(policy: dict[str, Any], runtimes: tuple[str, ...] | None = None) -> list[str]:
    """Return every structural error in the authored policy (empty when valid)."""
    runtimes = tuple(runtimes or DEFAULT_RUNTIMES)
    errors: list[str] = []
    _keys(
        policy,
        {"policy_version", "planning", "scheduling", "compatibility_aliases", "profiles", "runtime_constraints", "tool_profiles", "tasks", "floors"},
        "policy",
        errors,
    )
    if not isinstance(policy.get("policy_version"), str) or not policy.get("policy_version"):
        errors.append("policy.policy_version must be a non-empty string")

    planning = policy.get("planning", {})
    if not isinstance(planning, dict):
        errors.append("policy.planning must be an object")
        planning = {}
    else:
        _keys(planning, {"default_substantive", "tiers"}, "policy.planning", errors)
    if planning.get("default_substantive") != "T2":
        errors.append("policy.planning.default_substantive must be T2")
    tiers = planning.get("tiers", {})
    if not isinstance(tiers, dict) or set(tiers) != set(PLANNING_RANK):
        errors.append("policy.planning.tiers must define exactly T0, T1, T2, and T3")

    scheduling = policy.get("scheduling", {})
    if not isinstance(scheduling, dict):
        errors.append("policy.scheduling must be an object")
    else:
        _keys(scheduling, {"max_concurrent_children", "workers_may_spawn", "one_canonical_writer", "effective_limit"}, "policy.scheduling", errors)
        if not isinstance(scheduling.get("max_concurrent_children"), int) or scheduling.get("max_concurrent_children", 0) < 1:
            errors.append("policy.scheduling.max_concurrent_children must be positive")

    profiles = policy.get("profiles", {})
    if not isinstance(profiles, dict) or not profiles:
        errors.append("policy.profiles must be a non-empty object")
        profiles = profiles if isinstance(profiles, dict) else {}
    for profile_id, profile in profiles.items():
        label = f"policy.profiles.{profile_id}"
        if not isinstance(profile, dict):
            errors.append(f"{label} must be an object")
            continue
        _keys(profile, {"tier", "role", "work_kind", "purpose", "families", "effort", "fallbacks"}, label, errors)
        if profile.get("tier") not in CAPABILITY_RANK:
            errors.append(f"{label}.tier is invalid")
        if profile.get("role") not in {"main", "child"}:
            errors.append(f"{label}.role must be main or child")
        if profile.get("work_kind") not in {"read", "general", "build", "analyze", "review", "main", "visual"}:
            errors.append(f"{label}.work_kind is invalid")
        for field in ("families", "effort", "fallbacks"):
            value = profile.get(field)
            if not isinstance(value, dict) or set(value) != set(runtimes):
                errors.append(f"{label}.{field} must name exactly {', '.join(runtimes)}")
        for runtime, family in (profile.get("families") or {}).items():
            if not isinstance(family, str) or not family:
                errors.append(f"{label}.families.{runtime} must be a non-empty family label")
        for runtime, fallbacks in (profile.get("fallbacks") or {}).items():
            if not isinstance(fallbacks, list) or any(not isinstance(item, str) for item in fallbacks):
                errors.append(f"{label}.fallbacks.{runtime} must be a string list")

    if profiles.get("S-MAIN", {}).get("role") != "main":
        errors.append("policy.profiles.S-MAIN must exist and be main-only")

    constraints = policy.get("runtime_constraints", {})
    if not isinstance(constraints, dict) or set(constraints) != set(runtimes):
        errors.append(f"policy.runtime_constraints must name exactly {', '.join(runtimes)}")
        constraints = constraints if isinstance(constraints, dict) else {}
    for runtime, constraint in constraints.items():
        label = f"policy.runtime_constraints.{runtime}"
        if not isinstance(constraint, dict):
            errors.append(f"{label} must be an object")
            continue
        _keys(
            constraint,
            {"main_profile", "main_family", "child_families", "explicit_child_overrides"},
            label,
            errors,
        )
        if constraint.get("main_profile") != "S-MAIN":
            errors.append(f"{label}.main_profile must be S-MAIN")
        if profiles.get(constraint.get("main_profile"), {}).get("families", {}).get(runtime) != constraint.get("main_family"):
            errors.append(f"{label}.main_family must match its declared main profile")
        child_families = constraint.get("child_families")
        if not isinstance(child_families, list) or not child_families:
            errors.append(f"{label}.child_families must be a non-empty list")
        overrides = constraint.get("explicit_child_overrides")
        if not isinstance(overrides, list):
            errors.append(f"{label}.explicit_child_overrides must be a list")
        if isinstance(child_families, list) and isinstance(overrides, list) and set(child_families) & set(overrides):
            errors.append(f"{label}.explicit_child_overrides must be disjoint from normal child families")
        if isinstance(child_families, list):
            for profile_id, profile in profiles.items():
                if not isinstance(profile, dict) or profile.get("role") != "child":
                    continue
                family = (profile.get("families") or {}).get(runtime)
                fallbacks = (profile.get("fallbacks") or {}).get(runtime, [])
                if family not in child_families:
                    errors.append(f"{label}: {profile_id} family {family!r} is not allowed for children")
                for fallback in fallbacks if isinstance(fallbacks, list) else []:
                    if fallback not in child_families:
                        errors.append(f"{label}: {profile_id} fallback {fallback!r} is not allowed for children")

    aliases = policy.get("compatibility_aliases", {})
    if not isinstance(aliases, dict) or not aliases:
        errors.append("policy.compatibility_aliases must be a non-empty object")

    tools = policy.get("tool_profiles", {})
    if not isinstance(tools, dict) or not tools:
        errors.append("policy.tool_profiles must be a non-empty object")
        tools = tools if isinstance(tools, dict) else {}
    for tool_id, tool in tools.items():
        label = f"policy.tool_profiles.{tool_id}"
        if not isinstance(tool, dict):
            errors.append(f"{label} must be an object")
            continue
        _keys(tool, {"capabilities", "write_scope", "gate"}, label, errors)
        if not isinstance(tool.get("capabilities"), list) or not tool.get("capabilities"):
            errors.append(f"{label}.capabilities must be a non-empty list")

    tasks = policy.get("tasks", {})
    if not isinstance(tasks, dict) or not tasks:
        errors.append("policy.tasks must be a non-empty object")
        tasks = tasks if isinstance(tasks, dict) else {}
    for task_id, task in tasks.items():
        label = f"policy.tasks.{task_id}"
        if not re.fullmatch(r"[a-z]+(?:[.-][a-z]+)+", task_id):
            errors.append(f"{label}: invalid stable task ID")
        if not isinstance(task, dict):
            errors.append(f"{label} must be an object")
            continue
        _keys(
            task,
            {"planning_floor", "executor", "reviewer", "capability", "tool_profile", "output_check", "escalation"},
            label,
            errors,
        )
        if task.get("planning_floor") not in PLANNING_RANK:
            errors.append(f"{label}.planning_floor is invalid")
        executor = task.get("executor")
        reviewer = task.get("reviewer")
        if executor not in profiles:
            errors.append(f"{label}.executor references unknown profile {executor!r}")
        if reviewer is not None and reviewer not in profiles:
            errors.append(f"{label}.reviewer references unknown profile {reviewer!r}")
        if task.get("tool_profile") not in tools:
            errors.append(f"{label}.tool_profile references an unknown tool profile")
        if task.get("capability") not in CAPABILITY_RANK:
            errors.append(f"{label}.capability is invalid")
        if executor in profiles and task.get("capability") in CAPABILITY_RANK:
            if CAPABILITY_RANK[profiles[executor]["tier"]] < CAPABILITY_RANK[task["capability"]]:
                errors.append(f"{label}.executor is below the declared capability floor")
        if executor in profiles and profiles[executor].get("role") == "main" and executor != "S-MAIN":
            errors.append(f"{label}: only S-MAIN may execute main-session tasks")

    if isinstance(aliases, dict):
        for alias, record in aliases.items():
            label = f"policy.compatibility_aliases.{alias}"
            if not isinstance(alias, str) or not alias or not isinstance(record, dict):
                errors.append(f"{label} must be a named object")
                continue
            _keys(record, {"task_id", "profile", "tool_profile"}, label, errors)
            task = tasks.get(record.get("task_id"))
            if task is None:
                errors.append(f"{label}.task_id references unknown task {record.get('task_id')!r}")
            if record.get("profile") not in profiles:
                errors.append(f"{label}.profile references unknown profile {record.get('profile')!r}")
            if record.get("tool_profile") not in tools:
                errors.append(f"{label}.tool_profile references unknown tool {record.get('tool_profile')!r}")
            if task and task.get("tool_profile") != record.get("tool_profile"):
                errors.append(f"{label}.tool_profile must match its task")
            if task and task.get("executor") != record.get("profile"):
                errors.append(f"{label}.profile must match its task executor")

    floors = policy.get("floors", {})
    required_floors = {"T2", "T3", "numeric_deliverable", "dense_legal_financial", "external_write", "high_stakes"}
    if not isinstance(floors, dict) or set(floors) != required_floors:
        errors.append("policy.floors must define the canonical composite floors")
    elif profiles:
        refs = {
            floors.get("numeric_deliverable", {}).get("executor"),
            floors.get("numeric_deliverable", {}).get("reviewer"),
            floors.get("dense_legal_financial", {}).get("reader"),
            floors.get("external_write", {}).get("conflict_reviewer"),
            floors.get("high_stakes", {}).get("builder"),
            floors.get("high_stakes", {}).get("analyst"),
            floors.get("high_stakes", {}).get("reviewer"),
        }
        for ref in refs:
            if ref not in profiles:
                errors.append(f"policy.floors references unknown profile {ref!r}")
        for planning_floor in ("T2", "T3"):
            review_tool = floors.get(planning_floor, {}).get("review_tool_profile")
            if review_tool not in tools:
                errors.append(f"policy.floors.{planning_floor}.review_tool_profile references unknown tool {review_tool!r}")
    return errors


def validate_families(policy: dict[str, Any], root: Path = ROOT) -> list[str]:
    """Every family a profile names must exist in that runtime's model map.

    A runtime without a model map is skipped: the adapter has not declared its
    translation yet, and this check never invents one.
    """
    errors: list[str] = []
    for runtime in load_runtimes(root):
        known = model_map_families(root, runtime)
        if known is None:
            continue
        for profile_id, profile in policy.get("profiles", {}).items():
            family = profile.get("families", {}).get(runtime)
            if family not in known:
                errors.append(
                    f"policy.profiles.{profile_id}.families.{runtime}: {family!r} is not in "
                    f"{MODEL_MAP.format(runtime=runtime)}"
                )
            for fallback in profile.get("fallbacks", {}).get(runtime, []):
                if fallback not in known:
                    errors.append(
                        f"policy.profiles.{profile_id}.fallbacks.{runtime}: {fallback!r} is not in "
                        f"{MODEL_MAP.format(runtime=runtime)}"
                    )
    return errors


def load_policy(root: Path = ROOT) -> dict[str, Any]:
    """Load, validate, and normalize the single authored policy block."""
    root = Path(root)
    path = root / SOURCE
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PolicyError(f"cannot read {SOURCE.as_posix()}: {exc}") from exc
    policy = _extract(text)
    errors = validate_policy(policy, load_runtimes(root))
    if not errors:
        errors = validate_families(policy, root)
    if errors:
        raise PolicyError("; ".join(errors))
    return json.loads(_canonical(policy))


def classify_planning(
    policy: dict[str, Any], task_id: str | None = None, *, substantive: bool = False
) -> str:
    """Classify a known task; unknown substantive work defaults to T2."""
    if task_id is None:
        return policy["planning"]["default_substantive"] if substantive else "T0"
    try:
        return policy["tasks"][task_id]["planning_floor"]
    except KeyError as exc:
        raise PolicyError(f"unknown task ID: {task_id}") from exc


def _higher_planning(*values: str) -> str:
    for value in values:
        if value not in PLANNING_RANK:
            raise PolicyError(f"unknown planning floor: {value}")
    return max(values, key=PLANNING_RANK.__getitem__)


def _higher_profile(policy: dict[str, Any], current: str | None, floor: str | None) -> str | None:
    if floor is None:
        return current
    if floor not in policy["profiles"]:
        raise PolicyError(f"unknown profile ID: {floor}")
    if current is not None and current not in policy["profiles"]:
        raise PolicyError(f"unknown profile ID: {current}")
    rank = lambda profile_id: CAPABILITY_RANK[policy["profiles"][profile_id]["tier"]]
    if current is None or rank(floor) > rank(current):
        return floor
    return current


def _strong_executor(policy: dict[str, Any], task: dict[str, Any]) -> str:
    high_stakes = policy["floors"]["high_stakes"]
    work_kind = policy["profiles"][task["executor"]]["work_kind"]
    return high_stakes["builder"] if work_kind == "build" else high_stakes["analyst"]


def composite_floor(
    policy: dict[str, Any],
    task_id: str,
    *,
    planning_floor: str | None = None,
    executor_profile: str | None = None,
    reviewer_profile: str | None = None,
    numeric_deliverable: bool = False,
    dense_legal_financial: bool = False,
    external_write: bool = False,
    bidirectional_conflict: bool = False,
    high_stakes: bool = False,
) -> dict[str, Any]:
    """Apply the strictest task, domain, destination, skill, and stakes floors."""
    if task_id not in policy["tasks"]:
        raise PolicyError(f"unknown task ID: {task_id}")
    task = policy["tasks"][task_id]
    plan = _higher_planning(task["planning_floor"], planning_floor or "T0")
    executor = _higher_profile(policy, task["executor"], executor_profile)
    reviewer = _higher_profile(policy, task["reviewer"], reviewer_profile)
    reasons: list[str] = ["task"]
    if numeric_deliverable:
        numeric_executor = policy["floors"]["numeric_deliverable"]["executor"]
        executor = _higher_profile(policy, executor, numeric_executor)
        reviewer = _higher_profile(policy, reviewer, policy["floors"]["numeric_deliverable"]["reviewer"])
        reasons.append("numeric_deliverable")
    if dense_legal_financial:
        executor = _higher_profile(policy, executor, policy["floors"]["dense_legal_financial"]["reader"])
        reasons.append("dense_legal_financial")
    if external_write:
        plan = _higher_planning(plan, policy["floors"]["external_write"]["planning_floor"])
        required_tier = policy["floors"]["external_write"]["executor_tier"]
        if CAPABILITY_RANK[policy["profiles"][executor]["tier"]] < CAPABILITY_RANK[required_tier]:
            executor = policy["floors"]["numeric_deliverable"]["executor"]
        reasons.append("external_write")
    if bidirectional_conflict:
        if not external_write:
            raise PolicyError("bidirectional_conflict requires external_write")
        reviewer = _higher_profile(policy, reviewer, policy["floors"]["external_write"]["conflict_reviewer"])
        reasons.append("bidirectional_conflict")
    if high_stakes:
        high = policy["floors"]["high_stakes"]
        plan = _higher_planning(plan, high["planning_floor"])
        executor = _higher_profile(policy, executor, _strong_executor(policy, task))
        reviewer = _higher_profile(policy, reviewer, high["reviewer"])
        reasons.append("high_stakes")
    return {
        "task_id": task_id,
        "planning_floor": plan,
        "executor_profile": executor,
        "reviewer_profile": reviewer,
        "reasons": reasons,
    }


def resolve_task(
    policy: dict[str, Any],
    task_id: str,
    runtime: str,
    profile: str | None = None,
    assignment: str = "executor",
    explicit_model_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve a task to a logical family; adapters later supply provider IDs.

    A child override is accepted only as a structured, user-authored per-run
    input. A bare family string is deliberately insufficient evidence.
    """
    if runtime not in policy["runtime_constraints"]:
        raise PolicyError(f"unknown runtime: {runtime}")
    if task_id not in policy["tasks"]:
        raise PolicyError(f"unknown task ID: {task_id}")
    task = policy["tasks"][task_id]
    if assignment not in {"executor", "reviewer"}:
        raise PolicyError("assignment must be executor or reviewer")
    floor_profile = task[assignment]
    if floor_profile is None:
        raise PolicyError(f"{task_id} declares no {assignment} profile")
    selected = profile or floor_profile
    if selected not in policy["profiles"]:
        raise PolicyError(f"unknown profile ID: {selected}")
    spec = policy["profiles"][selected]
    role = spec["role"]
    floor_role = policy["profiles"][floor_profile]["role"]
    if assignment == "reviewer" and role == "main":
        raise PolicyError("a reviewer must be an independent child profile")
    if assignment == "executor" and role != floor_role:
        raise PolicyError(f"{task_id} {assignment} cannot cross the main/child boundary")
    selected_rank = CAPABILITY_RANK[policy["profiles"][selected]["tier"]]
    floor_rank = CAPABILITY_RANK[policy["profiles"][floor_profile]["tier"]]
    if selected_rank < floor_rank:
        raise PolicyError(f"profile {selected} is below the {task_id} {assignment} floor")
    family = spec["families"][runtime]
    override_record = None
    if explicit_model_override is not None:
        if role != "child":
            raise PolicyError("main-session model is fixed and cannot be overridden per task")
        if not isinstance(explicit_model_override, dict):
            raise PolicyError("explicit model override must be a recorded per-run object")
        override_errors: list[str] = []
        _keys(
            explicit_model_override,
            {"model_family", "authorized_by", "instruction"},
            "explicit_model_override",
            override_errors,
        )
        if override_errors:
            raise PolicyError("; ".join(override_errors))
        if explicit_model_override.get("authorized_by") != "user":
            raise PolicyError("explicit model override must be authorized_by user")
        instruction = explicit_model_override.get("instruction")
        if not isinstance(instruction, str) or not instruction.strip():
            raise PolicyError("explicit model override must record the user's instruction")
        requested = explicit_model_override.get("model_family")
        allowed = policy["runtime_constraints"][runtime]["explicit_child_overrides"]
        if requested not in allowed:
            raise PolicyError(f"{requested!r} is not an eligible explicit {runtime} child override")
        family = requested
        override_record = copy.deepcopy(explicit_model_override)
    elif family not in policy["runtime_constraints"][runtime]["child_families"] and role == "child":
        raise PolicyError(f"{family} is not an allowed normal {runtime} child family")
    return {
        "task_id": task_id,
        "planning_floor": task["planning_floor"],
        "capability_tier": spec["tier"],
        "profile": selected,
        "role": role,
        "assignment": assignment,
        "runtime": runtime,
        "model_family": family,
        "effort": spec["effort"][runtime],
        "tool_profile": (
            policy["floors"]["T3" if task["planning_floor"] == "T3" else "T2"]["review_tool_profile"]
            if assignment == "reviewer" else task["tool_profile"]
        ),
        "reviewer_profile": task["reviewer"],
        "explicit_model_override": override_record,
    }


def render_task_table(policy: dict[str, Any]) -> str:
    rows = [
        "| Task ID | Plan | Executor | Reviewer | Capability | Tool profile |",
        "|---|---:|---|---|---|---|",
    ]
    for task_id, task in policy["tasks"].items():
        reviewer = f"`{task['reviewer']}`" if task["reviewer"] else "none"
        rows.append(
            f"| `{task_id}` | {task['planning_floor']} | `{task['executor']}` | "
            f"{reviewer} | "
            f"{task['capability']} | `{task['tool_profile']}` |"
        )
    return "\n".join(rows)


def render_profile_table(policy: dict[str, Any]) -> str:
    runtimes = list(policy["runtime_constraints"])
    rows = [
        "| Profile | Role | Tier | " + " | ".join(runtimes) + " |",
        "|---|---|---|" + "---|" * len(runtimes),
    ]
    for profile_id, profile in policy["profiles"].items():
        families = profile["families"]
        rows.append(
            f"| `{profile_id}` | {profile['role']} | {profile['tier']} | "
            + " | ".join(families[runtime] for runtime in runtimes) + " |"
        )
    return "\n".join(rows)


def render_tool_table(policy: dict[str, Any]) -> str:
    rows = [
        "| Tool profile | Capabilities | Write scope | Gate |",
        "|---|---|---|---|",
    ]
    for tool_id, tool in policy["tool_profiles"].items():
        rows.append(
            f"| `{tool_id}` | {', '.join(tool['capabilities'])} | "
            f"{tool['write_scope']} | {tool['gate']} |"
        )
    return "\n".join(rows)


def build_manifest(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE.as_posix(),
        "source_hash": policy_digest(policy),
        "policy": policy,
    }


def render_manifest(policy: dict[str, Any]) -> str:
    return json.dumps(build_manifest(policy), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_manifest(root: Path, policy: dict[str, Any]) -> Path:
    """Write the manifest atomically and return its path."""
    path = Path(root) / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_manifest(policy))
    temporary.replace(path)
    return path


def manifest_drift(root: Path, policy: dict[str, Any]) -> list[str]:
    """Describe how the on-disk manifest differs from the compiled policy.

    A missing manifest is never drift (docs/ARCHITECTURE.md: the generated
    caches under harness/registry/ are untracked and rebuilt on demand, and
    their absence is never drift); the caller distinguishes "no cache" from
    "stale cache" with Path.is_file() before deciding what to print."""
    path = Path(root) / MANIFEST
    if not path.is_file():
        return []
    try:
        current = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [f"unreadable {MANIFEST.as_posix()}: {exc}"]
    if current != render_manifest(policy):
        try:
            recorded = json.loads(current).get("source_hash")
        except (json.JSONDecodeError, AttributeError):
            recorded = None
        return [f"stale {MANIFEST.as_posix()}: recorded {recorded}, authored {policy_digest(policy)}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile, check, and resolve the authored delegation policy.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("compile", help="validate the authored block, write the manifest, print the digest")
    sub.add_parser("check", help="compile in memory and exit 1 when the on-disk manifest drifted")
    resolve = sub.add_parser("resolve", help="print one resolved work package as JSON")
    resolve.add_argument("--task", required=True, help="stable task ID from the authored policy")
    resolve.add_argument("--runtime", default=None, help="runtime name (default: first registry entry)")
    resolve.add_argument("--assignment", choices=("executor", "reviewer"), default="executor")
    resolve.add_argument("--profile", default=None, help="profile ID at or above the task floor")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        policy = load_policy(root)
        if args.command == "compile":
            write_manifest(root, policy)
            print(policy_digest(policy))
            return 0
        if args.command == "check":
            manifest_path = root / MANIFEST
            if not manifest_path.is_file():
                # The cache is generated and rebuilt on demand; its absence
                # is never drift (docs/ARCHITECTURE.md). Compile in memory
                # and print the digest so the reader still gets the check's
                # verification value without writing anything.
                print(f"OK no cache at {MANIFEST.as_posix()} (never drift); authored policy digest {policy_digest(policy)[:12]}")
                return 0
            drift = manifest_drift(root, policy)
            for item in drift:
                print(f"DRIFT {item}")
            if not drift:
                print(f"OK {MANIFEST.as_posix()} matches the authored policy ({policy_digest(policy)[:12]})")
            return 1 if drift else 0
        runtime = args.runtime or load_runtimes(root)[0]
        resolved = resolve_task(policy, args.task, runtime, profile=args.profile, assignment=args.assignment)
        print(json.dumps(resolved, indent=2, sort_keys=True))
        return 0
    except PolicyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
