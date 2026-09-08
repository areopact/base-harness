#!/usr/bin/env python3
"""Render runtime-native routing roles from the generated delegation manifest.

This module never parses base-routing.md. The policy compiler owns that source;
this renderer consumes its generated, hash-bound manifest plus runtime-local
model and permission facts from harness/adapters/<runtime>/model-map.json.

Roles carry no persona. Each generated role is a name, a description (the
task's output check), a tool list, a permission class, and a model family
translated to the adapter's provider id.

Model-map contract (owned by the adapters):
    families            the four tier labels -> provider id, or null when the
                        adapter has not resolved that family yet
    permission_classes  read-only | edit | shell -> native tool names

A family KEY that is missing from a runtime's map is an error. A family whose
VALUE is null is unresolved: the roles that need it are skipped for that
runtime and reported in the generated catalog; nothing substitutes a default.

Usage:
    python harness/tools/native_routing.py render            # write every generated role file
    python harness/tools/native_routing.py render --check    # exit 1 on drift, write nothing
    python harness/tools/native_routing.py list              # print the generated role ids per runtime

Generated outputs:
    harness/adapters/<runtime>/agents/routing-<task>-<phase>.<md|toml>
    harness/adapters/<runtime>/agents/<alias>.<md|toml>      compatibility aliases
    harness/adapters/opencode/agents/workflow.md             the OpenCode primary orchestrator
    harness/registry/native-routing-files.json               ownership catalog (generated, untracked)
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
import os
import re
import sys
from pathlib import Path
from typing import Any

import routing_policy  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = routing_policy.MANIFEST
CATALOG = Path("harness/registry/native-routing-files.json")
MODEL_MAP = routing_policy.MODEL_MAP
GENERATED_PREFIX = "routing-"
AGENTS_DIR = "harness/adapters/{runtime}/agents"
PRIMARY_ROLE_ID = "workflow"
PRIMARY_TASK_ID = "orchestrate.workflow"
PERMISSION_CLASSES = ("read-only", "edit", "shell", "shell-readonly")
# Tool-profile capabilities that need a shell on every runtime.
SHELL_CAPABILITIES = {
    "deterministic-parser", "scripts", "recalculation", "bounded-build", "bounded-test",
    "named-shell", "render-tools", "render", "named-lint", "named-test", "named-render",
    "named-check", "git-status", "git-diff", "assigned-local-git-operation", "named-push",
    "named-deploy", "rollback", "health-check",
}
# Write scopes that never touch a production path.
NON_PRODUCTION_SCOPES = ("none", "scratch", ".tmp")
SANDBOX_BY_CLASS = {
    "read-only": "read-only", "edit": "workspace-write", "shell": "workspace-write",
    "shell-readonly": "read-only",
}
RENDER_SUFFIX = {"claude": ".md", "codex": ".toml", "opencode": ".md"}


class NativeRoutingError(ValueError):
    """Generated policy or runtime translation is incomplete or inconsistent."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeRoutingError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise NativeRoutingError(f"{path} must contain one JSON object")
    return value


def runtimes(root: Path) -> tuple[str, ...]:
    try:
        return routing_policy.load_runtimes(root)
    except routing_policy.PolicyError as exc:
        raise NativeRoutingError(str(exc)) from exc


def load_generated_policy(root: Path) -> tuple[dict[str, Any], str]:
    """Load the policy and verify its normalized source hash.

    When the generated manifest exists it must match the authored block: a
    stale manifest means the authored policy changed after the last compile.
    When the manifest is absent (it is an untracked cache) the authored block
    is compiled in memory; nothing is written.
    """
    root = Path(root).resolve()
    try:
        authored = routing_policy.load_policy(root)
    except routing_policy.PolicyError as exc:
        raise NativeRoutingError(f"cannot load the authored routing policy: {exc}") from exc
    authored_hash = routing_policy.policy_digest(authored)
    path = root / MANIFEST
    if not path.is_file():
        return authored, authored_hash
    manifest = _read_json(path)
    if manifest.get("schema_version") != 1:
        raise NativeRoutingError("unsupported delegation-policy manifest schema")
    policy = manifest.get("policy")
    if not isinstance(policy, dict):
        raise NativeRoutingError("delegation-policy manifest has no policy object")
    errors = routing_policy.validate_policy(policy, runtimes(root))
    if errors:
        raise NativeRoutingError("invalid generated policy: " + "; ".join(errors))
    actual = routing_policy.policy_digest(policy)
    expected = manifest.get("source_hash")
    if expected != actual:
        raise NativeRoutingError("delegation-policy source_hash does not match normalized policy")
    if authored_hash != expected or authored != policy:
        raise NativeRoutingError(
            "delegation-policy manifest is stale relative to the authored routing policy; "
            "run: python harness/tools/routing_policy.py compile"
        )
    return policy, actual


def load_model_map(root: Path, runtime: str) -> dict[str, Any]:
    """Read one adapter's model map and validate the shared shape."""
    if runtime not in runtimes(root):
        raise NativeRoutingError(f"unknown runtime: {runtime}")
    path = Path(root) / MODEL_MAP.format(runtime=runtime)
    native = _read_json(path)
    if native.get("schema_version") != 1:
        raise NativeRoutingError(f"{path.as_posix()}: schema_version must be 1")
    if native.get("runtime") not in (None, runtime):
        raise NativeRoutingError(f"{path.as_posix()}: runtime field does not match {runtime}")
    families = native.get("families")
    if not isinstance(families, dict) or not families:
        raise NativeRoutingError(f"{path.as_posix()}: families must be a non-empty object")
    for family, provider_id in families.items():
        if provider_id is not None and (not isinstance(provider_id, str) or not provider_id.strip()):
            raise NativeRoutingError(f"{path.as_posix()}: family {family!r} must be a non-empty string or null")
    classes = native.get("permission_classes")
    if not isinstance(classes, dict):
        raise NativeRoutingError(f"{path.as_posix()}: permission_classes must be an object")
    for name in PERMISSION_CLASSES:
        tools = classes.get(name)
        if not isinstance(tools, list) or not all(isinstance(tool, str) and tool for tool in tools):
            raise NativeRoutingError(f"{path.as_posix()}: permission_classes.{name} must be a list of tool names")
    return {
        "runtime": runtime,
        "families": dict(families),
        "permission_classes": {name: list(classes[name]) for name in PERMISSION_CLASSES},
    }


def family_id(native: dict[str, Any], family: str) -> str | None:
    """Provider id for a family label; None when the adapter left it unresolved."""
    if family not in native["families"]:
        raise NativeRoutingError(f"{native['runtime']} model map has no family {family!r}")
    return native["families"][family]


def _slug(task_id: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", task_id.lower()).strip("-")
    if not value:
        raise NativeRoutingError(f"cannot form native role id from {task_id!r}")
    return value


def permission_class(policy: dict[str, Any], tool_profile: str) -> str:
    """Map a tool profile to the closed permission-class vocabulary."""
    tool = policy["tool_profiles"][tool_profile]
    capabilities = set(tool["capabilities"])
    write_scope = str(tool["write_scope"]).lower().strip()
    if capabilities & SHELL_CAPABILITIES:
        if write_scope.startswith(NON_PRODUCTION_SCOPES):
            return "shell-readonly"
        return "shell"
    if write_scope.startswith(NON_PRODUCTION_SCOPES):
        return "read-only"
    return "edit"


def _permission_limitations(policy: dict[str, Any], tool_profile: str, klass: str, runtime: str) -> list[str]:
    """Native-tool-boundary caveats a role's prompt body must carry."""
    limitations: list[str] = []
    if klass != "read-only":
        limitations.append("path scope is instruction-only inside the native permission class")
    write_scope = str(policy["tool_profiles"][tool_profile]["write_scope"]).lower().strip()
    if klass in ("shell", "shell-readonly") and write_scope.startswith(NON_PRODUCTION_SCOPES):
        if klass == "shell":
            limitations.append("the shell permission class also grants edit tools; the non-production write scope is instruction-only")
        elif runtime == "codex":
            limitations.append("command and argument scope is instruction-only; sandbox_mode read-only enforces it")
        else:
            limitations.append("command and argument scope is instruction-only; Bash is granted, so the write scope is instruction-only")
    return limitations


def _selection(
    root: Path,
    policy: dict[str, Any],
    runtime: str,
    task_id: str,
    profile: str | None,
    kind: str,
    explicit_model_override: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        resolved = routing_policy.resolve_task(
            policy,
            task_id,
            runtime,
            profile=profile,
            assignment="reviewer" if kind == "review" else "executor",
            explicit_model_override=explicit_model_override,
        )
    except routing_policy.PolicyError as exc:
        raise NativeRoutingError(str(exc)) from exc
    native = load_model_map(root, runtime)
    model = family_id(native, resolved["model_family"])
    klass = permission_class(policy, resolved["tool_profile"])
    tools = list(native["permission_classes"][klass])
    task = policy["tasks"][task_id]
    return {
        **resolved,
        "kind": kind,
        "role_id": f"{GENERATED_PREFIX}{_slug(task_id)}-{kind}",
        "native_model": model,
        "permission_class": klass,
        "native_tools": tools,
        "native_permissions": {
            "permission_class": klass,
            "sandbox_mode": SANDBOX_BY_CLASS[klass],
            "tools": tools,
        },
        "output_check": task["output_check"],
        "escalation": task["escalation"],
        "permission_limitations": _permission_limitations(policy, resolved["tool_profile"], klass, runtime),
    }


def resolve_native(
    root: Path,
    task_id: str,
    runtime: str,
    profile: str | None = None,
    explicit_model_override: dict[str, str] | None = None,
    phase: str = "execute",
) -> dict[str, Any]:
    """Resolve one task to factual runtime-native settings.

    The result carries the evidence keys the workflow controller requires.
    ``native_model`` is None and ``support`` is ``unresolved-model-id`` when
    the adapter has not bound the family; the caller decides what that means.
    """
    if phase not in {"execute", "review"}:
        raise NativeRoutingError("phase must be execute or review")
    root = Path(root).resolve()
    policy, source_hash = load_generated_policy(root)
    selection = _selection(root, policy, runtime, task_id, profile, phase, explicit_model_override)
    resolved = selection["native_model"] is not None
    return {
        **selection,
        "phase": phase,
        "missing_capabilities": [],
        "support": "configured" if resolved else "unresolved-model-id",
        "effective_model_evidence": "unknown",
        "observed_effective_model": None,
        "source_hash": source_hash,
    }


def _alias_records(policy: dict[str, Any]) -> list[tuple[str, str, str]]:
    aliases = policy.get("compatibility_aliases")
    if not isinstance(aliases, dict) or not aliases:
        raise NativeRoutingError("policy.compatibility_aliases must be a non-empty object")
    records: list[tuple[str, str, str]] = []
    for alias, spec in sorted(aliases.items()):
        if isinstance(spec, str):
            task_id, profile = spec, policy["tasks"].get(spec, {}).get("executor")
        elif isinstance(spec, dict):
            task_id, profile = spec.get("task_id"), spec.get("profile")
        else:
            raise NativeRoutingError(f"compatibility alias {alias} must be a task id or object")
        if task_id not in policy["tasks"] or profile not in policy["profiles"]:
            raise NativeRoutingError(f"compatibility alias {alias} has invalid references")
        records.append((alias, task_id, profile))
    return records


def build_roles(root: Path, policy: dict[str, Any], runtime: str) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Every child execute/review role for one runtime plus the aliases.

    Returns (roles, unresolved) where unresolved maps a family label to the
    role ids that were skipped because the adapter has no provider id for it.
    """
    roles: list[dict[str, Any]] = []
    unresolved: dict[str, list[str]] = {}
    candidates: list[tuple[str, str, str]] = []
    for task_id, task in sorted(policy["tasks"].items()):
        executor = task["executor"]
        if policy["profiles"][executor]["role"] != "main":
            candidates.append((task_id, executor, "execute"))
        reviewer = task.get("reviewer")
        if reviewer and policy["profiles"][reviewer]["role"] != "main":
            candidates.append((task_id, reviewer, "review"))
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for task_id, profile, kind in candidates:
        role = _selection(root, policy, runtime, task_id, profile, kind)
        if role["role"] != "child":
            raise NativeRoutingError(f"{task_id}/{profile} is not a child role")
        if role["native_model"] is None:
            unresolved.setdefault(role["model_family"], []).append(role["role_id"])
            continue
        roles.append(role)
        by_key[(task_id, profile)] = role
    for alias, task_id, profile in _alias_records(policy):
        base = by_key.get((task_id, profile))
        if base is None:
            probe = _selection(root, policy, runtime, task_id, profile, "execute")
            if probe["native_model"] is None:
                unresolved.setdefault(probe["model_family"], []).append(alias)
                continue
            base = probe
        roles.append({**base, "role_id": alias, "compatibility_alias": True})
    role_ids = [role["role_id"] for role in roles]
    if len(role_ids) != len(set(role_ids)):
        raise NativeRoutingError(f"{runtime} generated duplicate native role ids")
    return roles, {family: sorted(ids) for family, ids in sorted(unresolved.items())}


def _prompt(role: dict[str, Any]) -> str:
    lines = [
        f"Generated routing role for `{role['task_id']}` ({role['kind']}).",
        f"Profile: {role['profile']}; tool profile: {role['tool_profile']}; "
        f"permission class: {role['permission_class']}.",
        ("Orchestrate the workflow through the generated task roles and managed completion gates."
         if role.get("role") == "main" else
         "Work only on the assigned package. Do not spawn another child."),
        f"Required output check: {role['output_check']}",
        f"Escalate: {role['escalation']}",
        "Return evidence, changed paths if any, checks run, and unresolved issues.",
    ]
    limitations = role.get("permission_limitations") or []
    if limitations:
        lines.append("Native enforcement limits: " + "; ".join(limitations) + ".")
    return "\n".join(lines)


def _yaml_scalar(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _render_claude(role: dict[str, Any]) -> bytes:
    lines = [
        "---",
        f"name: {role['role_id']}",
        f"description: {_yaml_scalar(role['output_check'])}",
        f"model: {role['native_model']}",
        "tools: " + (", ".join(role["native_tools"]) if role["native_tools"] else "[]"),
        "---",
        "",
        _prompt(role),
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _render_codex(role: dict[str, Any]) -> bytes:
    lines = [
        f"name = {json.dumps(role['role_id'])}",
        f"description = {json.dumps(role['output_check'])}",
        f"model = {json.dumps(role['native_model'])}",
        f"sandbox_mode = {json.dumps(role['native_permissions']['sandbox_mode'])}",
        # Codex's native `tools` key is a table of specific toggles
        # (web_search, experimental_request_user_input, update_plan); it has
        # no shape for the read-only, edit, or shell permission-class
        # vocabulary used elsewhere in this renderer, so that vocabulary is
        # documented in the prompt body (see permission class in _prompt)
        # instead of emitted here.
        'developer_instructions = """',
        _prompt(role),
        '"""',
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _opencode_permissions(role: dict[str, Any]) -> dict[str, Any]:
    if role.get("role") == "main":
        return {
            "*": "deny",
            "read": "allow",
            "glob": "allow",
            "grep": "allow",
            "task": {"*": "deny", f"{GENERATED_PREFIX}*": "allow", "explorer": "allow", "worker": "allow", "reviewer": "allow"},
        }
    permissions: dict[str, Any] = {"*": "deny"}
    for tool in sorted(set(role["native_tools"])):
        permissions[tool] = "ask" if tool == "bash" else "allow"
    permissions["task"] = "deny"
    return permissions


def _render_opencode(role: dict[str, Any], *, mode: str = "subagent") -> bytes:
    lines = [
        "---",
        f"description: {_yaml_scalar(role['output_check'])}",
        f"mode: {mode}",
        f"model: {role['native_model']}",
        "permission:",
    ]
    for key, value in _opencode_permissions(role).items():
        if isinstance(value, dict):
            lines.append(f"  {key}:")
            for pattern, action in value.items():
                lines.append(f"    {_yaml_scalar(pattern)}: {action}")
        else:
            lines.append(f"  {_yaml_scalar(key)}: {value}")
    lines.extend(["---", "", _prompt(role), ""])
    return "\n".join(lines).encode("utf-8")


RENDERERS = {"claude": _render_claude, "codex": _render_codex, "opencode": _render_opencode}


def _validate_main_configs(root: Path, policy: dict[str, Any]) -> None:
    """Generic main/child boundary check driven by policy.runtime_constraints.

    For every runtime: the declared main family must be a key of the adapter's
    model map (its value may still be null), and no child role may resolve to
    a family outside the runtime's child_families list. No runtime or family
    is special-cased.
    """
    for runtime, constraint in policy["runtime_constraints"].items():
        native = load_model_map(root, runtime)
        family_id(native, constraint["main_family"])
        allowed = set(constraint["child_families"])
        roles, _ = build_roles(root, policy, runtime)
        for role in roles:
            if role["model_family"] not in allowed:
                raise NativeRoutingError(
                    f"{runtime} child role {role['role_id']} resolves to {role['model_family']!r}, "
                    "which is outside the runtime's child families"
                )


def _primary_role(root: Path, policy: dict[str, Any], runtime: str) -> dict[str, Any] | None:
    """The main-loop orchestrator role, or None when its family is unresolved."""
    constraint = policy["runtime_constraints"][runtime]
    try:
        resolved = routing_policy.resolve_task(policy, PRIMARY_TASK_ID, runtime, profile=constraint["main_profile"])
    except routing_policy.PolicyError as exc:
        raise NativeRoutingError(str(exc)) from exc
    native = load_model_map(root, runtime)
    model = family_id(native, resolved["model_family"])
    if model is None:
        return None
    task = policy["tasks"][PRIMARY_TASK_ID]
    return {
        **resolved,
        "kind": "execute",
        "role_id": PRIMARY_ROLE_ID,
        "native_model": model,
        "permission_class": "read-only",
        "native_tools": list(native["permission_classes"]["read-only"]),
        "native_permissions": {"permission_class": "read-only", "sandbox_mode": "read-only"},
        "output_check": task["output_check"],
        "escalation": task["escalation"],
        "permission_limitations": _permission_limitations(policy, resolved["tool_profile"], "read-only", runtime),
    }


def render_files(root: Path) -> tuple[dict[str, bytes], str, dict[str, Any]]:
    """Return every generated file (path -> bytes), the policy hash, and the catalog."""
    root = Path(root).resolve()
    policy, source_hash = load_generated_policy(root)
    _validate_main_configs(root, policy)
    files: dict[str, bytes] = {}
    unresolved: dict[str, dict[str, list[str]]] = {}
    for runtime in runtimes(root):
        if runtime not in RENDERERS:
            raise NativeRoutingError(f"no native role renderer for runtime {runtime!r}")
        roles, skipped = build_roles(root, policy, runtime)
        for role in roles:
            relative = f"{AGENTS_DIR.format(runtime=runtime)}/{role['role_id']}{RENDER_SUFFIX[runtime]}"
            files[relative] = RENDERERS[runtime](role)
        if runtime == "opencode":
            primary = _primary_role(root, policy, runtime)
            if primary is None:
                skipped.setdefault(policy["runtime_constraints"][runtime]["main_family"], []).append(PRIMARY_ROLE_ID)
            else:
                files[f"{AGENTS_DIR.format(runtime=runtime)}/{PRIMARY_ROLE_ID}.md"] = _render_opencode(primary, mode="primary")
        if skipped:
            unresolved[runtime] = {family: sorted(ids) for family, ids in sorted(skipped.items())}
    catalog = {
        "schema_version": 1,
        "source_hash": source_hash,
        "files": sorted(files),
        "unresolved": unresolved,
    }
    files[CATALOG.as_posix()] = (json.dumps(catalog, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return files, source_hash, catalog


def _owned_previous_files(root: Path) -> set[str]:
    path = root / CATALOG
    if not path.is_file():
        return set()
    catalog = _read_json(path)
    rows = catalog.get("files", [])
    if not isinstance(rows, list) or any(not isinstance(item, str) for item in rows):
        raise NativeRoutingError("native routing ownership catalog is invalid")
    return set(rows)


def diff_generated(root: Path, expected: dict[str, bytes]) -> list[str]:
    """Exact drift between the expected files and the tree.

    The ownership catalog is an untracked cache: its absence is not drift,
    only a present-and-different catalog is.
    """
    root = Path(root).resolve()
    drift: list[str] = []
    catalog_name = CATALOG.as_posix()
    for relative, content in sorted(expected.items()):
        path = root / relative
        if not path.is_file():
            if relative != catalog_name:
                drift.append(f"missing {relative}")
        elif path.read_bytes() != content:
            drift.append(f"content {relative}")
    expected_names = set(expected) - {catalog_name}
    for stale in sorted(_owned_previous_files(root) - expected_names):
        if (root / stale).exists():
            drift.append(f"stale-owned {stale}")
    return drift


def _write_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_bytes(content)
    temporary.replace(path)


def generate(root: Path, check: bool = False) -> tuple[list[str], dict[str, Any]]:
    """Generate native routing files, or return exact drift in check mode."""
    root = Path(root).resolve()
    expected, _, catalog = render_files(root)
    drift = diff_generated(root, expected)
    if check:
        return drift, catalog
    previous = _owned_previous_files(root)
    for relative, content in sorted(expected.items()):
        _write_atomic(root / relative, content)
    # Delete only files named by the prior ownership catalog, and only when
    # they carry the generated prefix or are a known alias or primary file.
    current = set(expected) - {CATALOG.as_posix()}
    alias_names = {alias for alias, _, _ in _alias_records(load_generated_policy(root)[0])} | {PRIMARY_ROLE_ID}
    for stale in sorted(previous - current):
        path = (root / stale).resolve()
        if root not in path.parents or not (
            path.name.startswith(GENERATED_PREFIX) or path.stem in alias_names
        ):
            raise NativeRoutingError(f"refusing to remove unowned generated path: {path}")
        if path.is_file():
            path.unlink()
    return drift, catalog


def _print_unresolved(catalog: dict[str, Any]) -> None:
    for runtime, families in sorted(catalog.get("unresolved", {}).items()):
        for family, ids in sorted(families.items()):
            print(
                f"UNRESOLVED {runtime}: family {family!r} has no provider id in "
                f"{MODEL_MAP.format(runtime=runtime)}; {len(ids)} role(s) not rendered"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render runtime-native routing roles from the delegation manifest.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render", help="write the generated role files")
    render.add_argument("--check", action="store_true", help="exit 1 on drift instead of writing")
    sub.add_parser("list", help="print generated role ids per runtime")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "list":
            policy, _ = load_generated_policy(root)
            for runtime in runtimes(root):
                roles, skipped = build_roles(root, policy, runtime)
                for role in roles:
                    print(f"{runtime}\t{role['role_id']}\t{role['model_family']}\t{role['permission_class']}\t{role['native_model']}")
                for family, ids in sorted(skipped.items()):
                    for role_id in ids:
                        print(f"{runtime}\t{role_id}\t{family}\tunresolved\t-")
            return 0
        drift, catalog = generate(root, check=args.check)
        _print_unresolved(catalog)
        if args.check:
            for item in drift:
                print(f"DRIFT {item}")
            if not drift:
                print("OK native routing files match")
            return 1 if drift else 0
        print(f"OK native routing files rendered ({len(drift)} written or updated)")
        return 0
    except (NativeRoutingError, routing_policy.PolicyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
