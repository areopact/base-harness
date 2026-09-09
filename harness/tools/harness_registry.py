#!/usr/bin/env python3
"""Load and validate the harness registries under harness/registry/.

Every kernel tool that needs a host fact reads it through this module, so no
kernel file carries a hardcoded lane path. The environment check is
declaration-only: it never opens an environment file, MCP config, credential
store, OAuth cache, or private key.

CLI: ``python harness/tools/harness_registry.py`` validates every registry,
prints one line per error, and exits 1 on any error.
"""

from __future__ import annotations

import argparse
import copy
import json
import posixpath
import re
from pathlib import Path
from typing import Any, Optional


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_RELATIVE = "harness/registry"

RUNTIME_IDS = ("claude", "codex", "opencode")
RUNTIME_TIERS = {"tier-1", "experimental"}
RUNTIME_STATUS = {"active", "configured-beta", "configured-alpha", "unconfigured"}
MATERIALIZATION_MODES = {"link", "managed-copy", "generated", "contract-render"}
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
HOOK_EVENT_DIRS = {
    "SessionStart": "session-start",
    "UserPromptSubmit": "user-prompt-submit",
    "PreToolUse": "pre-tool-use",
    "PostToolUse": "post-tool-use",
    "Stop": "stop",
}
HOOK_SUPPORT = {"native", "configured-beta", "configured-alpha", "experimental", "partial", "unsupported"}
HOOK_DELIVERY = {
    "individual-wrapper",
    "individual-wrappers",
    "dispatcher",
    "plugin-system-transform",
    "plugin-tool-before",
    "contract-fallback",
}
HOOK_RUNGS = {"native-hook", "contract-text", "git-floor"}
HOOK_IMPLEMENTATION = re.compile(r"^(session-start|user-prompt-submit|pre-tool-use|post-tool-use|stop)/[a-z0-9-]+$")
EXPECTED_DOCTORS = {
    "claude": "harness/bootstrap/doctor.{ps1,sh}",
    "codex": "harness/bootstrap/doctor_codex.py --offline",
    "opencode": "harness/bootstrap/doctor_opencode.py --offline",
    "antigravity": None,
}
CAPABILITY_VALUES = {
    "contract": {"native-render", "native-root", "native-root-unverified"},
    "skills": {"native-linked", "generated-catalog", "unverified"},
    "subagents": {"native-linked", "unverified"},
    "hooks": {"native", "configured-beta", "partial-plugin", "unverified"},
    "command_policy": {"native-permissions", "native-linked", "unverified"},
}
DESTINATION_SURFACES = {
    "claude": {"prefixes": (".claude/",), "files": set()},
    "codex": {"prefixes": (".codex/", ".agents/"), "files": {"AGENTS.md"}},
    "opencode": {"prefixes": (".opencode/",), "files": {"AGENTS.md", "opencode.json"}},
}
# Sources under this prefix are produced by bootstrap; they need not exist in a fresh clone.
GENERATED_SOURCE_PREFIXES = ("harness/.selected/",)

LANE_NAMES = ("identity", "knowledge", "decisions", "records", "docs")
TIER_LABELS = ("public", "internal", "confidential", "restricted", "secret")
GIT_MODES = {"main-only", "branches"}
HOST_PROFILES = ("solo", "team")
VERIFY_COMMAND_RE = re.compile(r"^(npm run|pnpm run|yarn|make) [A-Za-z0-9:_.-]+$")
UNLISTED_PATH_POLICIES = {"internal", "exclude"}
CONTRACT_MODES = {"rendered", "host-owned"}
SELECTION_SCOPES = {"repo", "user"}

DEFAULT_STRUCTURE: dict[str, Any] = {
    "schema_version": 1,
    "lanes": {
        "identity": ["brain/shared/IDENTITY.md", "brain/local/OPERATOR.md"],
        "knowledge": ["brain/shared/knowledge", "brain/local/knowledge"],
        "decisions": ["docs/decisions"],
        "records": None,
        "docs": ["docs"],
    },
    "git": {"mode": "main-only"},
    "outbound_globs": [],
    "brain": {"local_tracked": False, "local_path": "brain/local"},
    "tiers": {
        "lane_defaults": {
            "identity": "internal",
            "knowledge": "internal",
            "decisions": "internal",
            "records": "internal",
            "docs": "public",
        },
        "unlisted_path": "internal",
    },
    "delegation": {"mandatory": False},
    "selection_scope": "repo",
    "contract": {"mode": "rendered"},
    "host": {"adopted": False, "roots": [], "harness_owned": [], "profile": "solo", "verify_command": None},
}

CAPABILITY_KINDS = {"runtime-tool", "mcp", "cli", "local-script"}
CAPABILITY_STATES = {"provided", "absent", "unknown"}
PROBE_TYPES = {"none", "file-exists", "command"}
SOURCE_LICENSES = {"MIT", "Apache-2.0", "BSD-3-Clause", "source-available", "none"}
MANIFEST_STATES = {"ported", "new"}

ENV_PRINCIPAL_KINDS = {"operator", "session-agent", "persistent-agent"}
ENV_SYNC_POLICIES = {"manual", "isolated", "machine-local"}
ENV_CLASSES = {"secret", "oauth-cache", "private-key", "identifier", "configuration", "path"}
ENV_SHARING_MODES = {"isolated", "shared-principal", "machine-local"}
ENV_BINDING_STATUSES = {"live", "planned"}
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# The policy block declares the rule ("values": "forbidden"); the walk covers everything else.
FORBIDDEN_ENV_KEYS = {
    "value",
    "values",
    "secret_value",
    "token",
    "digest",
    "sha256",
    "present",
    "exists",
    "home",
    "absolute_path",
}
EXPECTED_ENV_POLICY = {
    "values": "forbidden",
    "presence_checks": "human-attested-only",
    "default_sharing": "isolated",
    "automatic_cross_identity_sync": "forbidden",
}


class StructureError(ValueError):
    """Raised when structure.json is malformed or violates the schema."""


# ---------------------------------------------------------------------------
# Paths and loading
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """Return the repository root derived from this file's location."""
    return ROOT


def _root(root: Optional[Path]) -> Path:
    return Path(root) if root is not None else ROOT


def registry_dir(root: Optional[Path] = None) -> Path:
    return _root(root) / "harness" / "registry"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.as_posix()} must contain one object")
    return value


def _load_registry(name: str, root: Optional[Path]) -> dict[str, Any]:
    return load_json(registry_dir(root) / name)


def load_selection(root: Optional[Path] = None) -> dict[str, Any]:
    return _load_registry("selection.json", root)


def load_runtimes(root: Optional[Path] = None) -> dict[str, Any]:
    return _load_registry("runtimes.json", root)


def load_capabilities(root: Optional[Path] = None) -> dict[str, Any]:
    return _load_registry("capabilities.json", root)


def load_sources(root: Optional[Path] = None) -> dict[str, Any]:
    return _load_registry("sources.json", root)


def load_kernel_manifest(root: Optional[Path] = None) -> dict[str, Any]:
    return load_json(_root(root) / "harness" / "kernel-manifest.json")


def load_junctions(root: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Return junctions.json, or None when bootstrap has not landed it yet."""
    path = _root(root) / "harness" / "bootstrap" / "junctions.json"
    if not path.is_file():
        return None
    return load_json(path)


def _merge_defaults(default: Any, override: Any) -> Any:
    """Merge an override key-by-key over a default; a null override stays null."""
    if isinstance(default, dict) and isinstance(override, dict):
        merged = copy.deepcopy(default)
        for key, value in override.items():
            merged[key] = _merge_defaults(default.get(key), value) if key in default else copy.deepcopy(value)
        return merged
    return copy.deepcopy(override)


def load_structure(root: Optional[Path] = None) -> dict[str, Any]:
    """Return the host structure: the documented default merged with structure.json.

    A missing file yields the default verbatim. A malformed file, an unknown
    top-level key, or any schema violation raises StructureError.
    """
    path = registry_dir(root) / "structure.json"
    if not path.is_file():
        return copy.deepcopy(DEFAULT_STRUCTURE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StructureError(f"structure.json cannot be parsed: {exc}") from exc
    if not isinstance(raw, dict):
        raise StructureError("structure.json must contain one object")
    unknown = sorted(set(raw) - set(DEFAULT_STRUCTURE))
    if unknown:
        raise StructureError(f"structure.json: unknown top-level keys: {', '.join(unknown)}")
    merged = _merge_defaults(DEFAULT_STRUCTURE, raw)
    errors = validate_structure(merged)
    if errors:
        raise StructureError("; ".join(errors))
    return merged


def lane_paths(name: str, root: Optional[Path] = None) -> list[str]:
    """Return the configured paths for one lane, or [] when the lane is null."""
    if name not in LANE_NAMES:
        raise StructureError(f"unknown lane {name!r}")
    value = load_structure(root)["lanes"].get(name)
    return list(value) if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# Path-safety helpers
# ---------------------------------------------------------------------------


def _normalized_relative(value: str) -> Optional[str]:
    """Return a portable comparison key for one canonical repo path."""
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    normalized = posixpath.normpath(value)
    if normalized != value or normalized in {".", ".."} or normalized.startswith("../"):
        return None
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return None
    return normalized.casefold()


def _safe_relative(value: str) -> bool:
    return _normalized_relative(value) is not None


def _resolves_inside(root: Path, candidate: Path) -> bool:
    """Return whether candidate resolves beneath root, including through links."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _unknown_fields(item: dict[str, Any], allowed: set[str], label: str, errors: list[str]) -> None:
    unknown = sorted(set(item) - allowed)
    if unknown:
        errors.append(f"{label}: unknown fields: {', '.join(unknown)}")


def _surface_present(root: Path, relative: str) -> bool:
    """Return whether the directory that owns a harness path has landed.

    Existence checks apply once the owning directory exists; before that the
    package that owns it may not have landed, which is a note, not an error.
    """
    parts = relative.split("/")
    if len(parts) < 2 or parts[0] != "harness":
        return True
    return (root / posixpath.dirname(relative)).is_dir()


# ---------------------------------------------------------------------------
# structure.json
# ---------------------------------------------------------------------------


def validate_structure(registry: dict[str, Any], root: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    label = "structure"
    if not isinstance(registry, dict):
        return [f"{label}: must be an object"]
    _unknown_fields(registry, set(DEFAULT_STRUCTURE), label, errors)
    if registry.get("schema_version") != 1:
        errors.append(f"{label}: schema_version must be 1")

    lanes = registry.get("lanes")
    if not isinstance(lanes, dict):
        errors.append(f"{label}.lanes: must be an object")
    else:
        _unknown_fields(lanes, set(LANE_NAMES), f"{label}.lanes", errors)
        missing = sorted(set(LANE_NAMES) - set(lanes))
        if missing:
            errors.append(f"{label}.lanes: missing {', '.join(missing)}")
        for lane, value in lanes.items():
            if lane not in LANE_NAMES:
                continue
            if value is None:
                continue
            if not isinstance(value, list) or not value:
                errors.append(f"{label}.lanes.{lane}: must be null or a non-empty list of paths")
                continue
            for item in value:
                if not isinstance(item, str) or not _safe_relative(item):
                    errors.append(f"{label}.lanes.{lane}: unsafe path {item!r}")

    git = registry.get("git")
    if not isinstance(git, dict):
        errors.append(f"{label}.git: must be an object")
    else:
        _unknown_fields(git, {"mode"}, f"{label}.git", errors)
        if git.get("mode") not in GIT_MODES:
            errors.append(f"{label}.git.mode: must be one of {sorted(GIT_MODES)}")

    globs = registry.get("outbound_globs")
    if not isinstance(globs, list) or any(not isinstance(item, str) or not item for item in globs):
        errors.append(f"{label}.outbound_globs: must be a list of non-empty strings")

    brain = registry.get("brain")
    if not isinstance(brain, dict):
        errors.append(f"{label}.brain: must be an object")
    else:
        _unknown_fields(brain, {"local_tracked", "local_path"}, f"{label}.brain", errors)
        if not isinstance(brain.get("local_tracked"), bool):
            errors.append(f"{label}.brain.local_tracked: must be a boolean")
        local_path = brain.get("local_path")
        if not isinstance(local_path, str) or not _safe_relative(local_path):
            errors.append(f"{label}.brain.local_path: must be a safe repository-relative path")

    tiers = registry.get("tiers")
    if not isinstance(tiers, dict):
        errors.append(f"{label}.tiers: must be an object")
    else:
        _unknown_fields(tiers, {"lane_defaults", "unlisted_path"}, f"{label}.tiers", errors)
        defaults = tiers.get("lane_defaults")
        if not isinstance(defaults, dict) or set(defaults) != set(LANE_NAMES):
            errors.append(f"{label}.tiers.lane_defaults: must name every lane exactly once")
        else:
            for lane, tier in defaults.items():
                if tier not in TIER_LABELS:
                    errors.append(f"{label}.tiers.lane_defaults.{lane}: invalid tier {tier!r}")
        if tiers.get("unlisted_path") not in UNLISTED_PATH_POLICIES:
            errors.append(f"{label}.tiers.unlisted_path: must be one of {sorted(UNLISTED_PATH_POLICIES)}")

    delegation = registry.get("delegation")
    if not isinstance(delegation, dict):
        errors.append(f"{label}.delegation: must be an object")
    else:
        _unknown_fields(delegation, {"mandatory"}, f"{label}.delegation", errors)
        if not isinstance(delegation.get("mandatory"), bool):
            errors.append(f"{label}.delegation.mandatory: must be a boolean")

    if registry.get("selection_scope") not in SELECTION_SCOPES:
        errors.append(f"{label}.selection_scope: must be one of {sorted(SELECTION_SCOPES)}")

    contract = registry.get("contract")
    if not isinstance(contract, dict):
        errors.append(f"{label}.contract: must be an object")
    else:
        _unknown_fields(contract, {"mode"}, f"{label}.contract", errors)
        if contract.get("mode") not in CONTRACT_MODES:
            errors.append(f"{label}.contract.mode: must be one of {sorted(CONTRACT_MODES)}")

    host = registry.get("host")
    if not isinstance(host, dict):
        errors.append(f"{label}.host: must be an object")
    else:
        _unknown_fields(host, {"adopted", "roots", "harness_owned", "profile", "verify_command"}, f"{label}.host", errors)
        if not isinstance(host.get("adopted"), bool):
            errors.append(f"{label}.host.adopted: must be a boolean")
        for field in ("roots", "harness_owned"):
            value = host.get(field)
            if not isinstance(value, list) or any(not isinstance(item, str) or not _safe_relative(item) for item in value):
                errors.append(f"{label}.host.{field}: must be a list of safe repository-relative paths")
        if "profile" in host and host["profile"] not in HOST_PROFILES:
            errors.append(f"{label}.host.profile: must be one of {sorted(HOST_PROFILES)}")
        if "verify_command" in host:
            verify_command = host["verify_command"]
            if verify_command is not None and (
                not isinstance(verify_command, str) or not VERIFY_COMMAND_RE.fullmatch(verify_command)
            ):
                errors.append(f"{label}.host.verify_command: must be null or a package-manager/make verify command")
    return errors


# ---------------------------------------------------------------------------
# selection.json
# ---------------------------------------------------------------------------


def validate_selection(registry: dict[str, Any], root: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    label = "selection"
    _unknown_fields(registry, {"schema_version", "packs", "include", "exclude"}, label, errors)
    if registry.get("schema_version") != 1:
        errors.append(f"{label}: schema_version must be 1")
    for field in ("packs", "include", "exclude"):
        value = registry.get(field)
        if not isinstance(value, list):
            errors.append(f"{label}.{field}: must be a list of kebab-case slugs")
            continue
        if len(value) != len(set(value)):
            errors.append(f"{label}.{field}: contains duplicates")
        for item in value:
            if not isinstance(item, str) or not KEBAB.fullmatch(item):
                errors.append(f"{label}.{field}: invalid slug {item!r}")
    include = registry.get("include")
    exclude = registry.get("exclude")
    if isinstance(include, list) and isinstance(exclude, list):
        overlap = sorted(set(include) & set(exclude))
        if overlap:
            errors.append(f"{label}: include and exclude both name {', '.join(overlap)}")
    return errors


# ---------------------------------------------------------------------------
# runtimes.json
# ---------------------------------------------------------------------------


def _destination_allowed(runtime_id: str, destination: str) -> bool:
    surface = DESTINATION_SURFACES.get(runtime_id)
    if surface is None:
        return False
    return destination in surface["files"] or destination.startswith(surface["prefixes"])


def _validate_materialization(
    runtime_id: str,
    index: int,
    materialization: Any,
    root: Path,
    destinations: dict[str, tuple[str, str]],
    seen: set[tuple[str, str, str, str]],
    errors: list[str],
    notes: list[str],
) -> None:
    mlabel = f"runtimes.{runtime_id}.materializations[{index}]"
    if not isinstance(materialization, dict):
        errors.append(f"{mlabel}: must be an object")
        return
    _unknown_fields(materialization, {"source", "destination", "mode"}, mlabel, errors)
    source = materialization.get("source")
    destination = materialization.get("destination")
    mode = materialization.get("mode")
    if mode not in MATERIALIZATION_MODES:
        errors.append(f"{mlabel}: invalid mode {mode!r}")
    for field, value in (("source", source), ("destination", destination)):
        if not isinstance(value, str) or not _safe_relative(value):
            errors.append(f"{mlabel}: {field} must be a safe repository-relative path")
    if isinstance(source, str) and not source.startswith("harness/"):
        errors.append(f"{mlabel}: source must stay under harness/")
    if isinstance(source, str) and _safe_relative(source) and source.startswith("harness/"):
        if source.startswith(GENERATED_SOURCE_PREFIXES):
            pass
        elif not _surface_present(root, source):
            notes.append(f"{mlabel}: source surface not landed yet, existence unchecked: {source}")
        elif not (root / source).exists():
            errors.append(f"{mlabel}: source missing: {source}")
        elif not _resolves_inside(root, root / source):
            errors.append(f"{mlabel}: source resolves outside the repository: {source}")
        elif mode in {"managed-copy", "contract-render"} and not (root / source).is_file():
            errors.append(f"{mlabel}: {mode} source must be a file: {source}")
        elif mode in {"link", "generated"} and not (root / source).is_dir():
            errors.append(f"{mlabel}: {mode} source must be a directory: {source}")
    if all(isinstance(value, str) for value in (source, destination, mode)):
        entry = (runtime_id, source, destination, mode)
        if entry in seen:
            errors.append(f"{mlabel}: duplicate materialization entry")
        seen.add(entry)
    if not isinstance(destination, str):
        return
    if not _destination_allowed(runtime_id, destination):
        errors.append(f"{mlabel}: destination is outside the {runtime_id} runtime surface")
    if _safe_relative(destination):
        destination_path = root / destination
        if not _resolves_inside(root, destination_path.parent):
            errors.append(f"{mlabel}: destination parent resolves outside the repository")
        if (destination_path.exists() or destination_path.is_symlink()) and not _resolves_inside(root, destination_path):
            errors.append(f"{mlabel}: existing destination resolves outside the repository")
    key = _normalized_relative(destination)
    if key is None:
        return
    prior = destinations.get(key)
    if prior is None:
        destinations[key] = (runtime_id, f"{source}|{mode}")
    elif not (mode == "contract-render" and prior[1] == f"{source}|{mode}"):
        # One rendered root contract may serve several runtimes; every other destination has one owner.
        errors.append(f"{mlabel}: destination {destination} is already owned by {prior[0]}")


def _validate_hook_coverage(
    event: str,
    runtime_id: str,
    state: Any,
    implementation_names: set[str],
    errors: list[str],
) -> None:
    slabel = f"runtimes.hook_events.{event}.{runtime_id}"
    if not isinstance(state, dict):
        errors.append(f"{slabel}: must be an object")
        return
    _unknown_fields(state, {"support", "delivery", "context_limit", "rung", "implementation_support"}, slabel, errors)
    support = state.get("support")
    if support not in HOOK_SUPPORT:
        errors.append(f"{slabel}: invalid support state {support!r}")
    if state.get("delivery") not in HOOK_DELIVERY:
        errors.append(f"{slabel}: invalid delivery {state.get('delivery')!r}")
    if state.get("rung") not in HOOK_RUNGS:
        errors.append(f"{slabel}: rung must be one of {sorted(HOOK_RUNGS)}")
    limit = state.get("context_limit")
    if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
        errors.append(f"{slabel}: context_limit must be null or a positive integer")
    if event == "SessionStart" and support != "unsupported" and (not isinstance(limit, int) or limit <= 0):
        errors.append(f"{slabel}: SessionStart delivery requires a positive context_limit")
    implementation_support = state.get("implementation_support")
    if implementation_support is None:
        if support == "partial":
            errors.append(f"{slabel}: partial support requires implementation_support")
        return
    if not isinstance(implementation_support, dict) or set(implementation_support) != implementation_names:
        errors.append(f"{slabel}: implementation_support must name every event implementation")
        return
    for name, value in implementation_support.items():
        ilabel = f"{slabel}.implementation_support[{name}]"
        if isinstance(value, str):
            if value not in HOOK_SUPPORT:
                errors.append(f"{ilabel}: invalid support state {value!r}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{ilabel}: must be a support state or an object")
            continue
        _unknown_fields(value, {"support", "default_registered"}, ilabel, errors)
        if value.get("support") not in HOOK_SUPPORT:
            errors.append(f"{ilabel}: invalid support state {value.get('support')!r}")
        if "default_registered" in value and not isinstance(value["default_registered"], bool):
            errors.append(f"{ilabel}: default_registered must be a boolean")


def validate_runtimes(registry: dict[str, Any], root: Optional[Path] = None, notes: Optional[list[str]] = None) -> list[str]:
    root = _root(root)
    notes = notes if notes is not None else []
    errors: list[str] = []
    _unknown_fields(
        registry,
        {"schema_version", "tier_definitions", "runtimes", "retired_materializations", "hook_events"},
        "runtimes",
        errors,
    )
    if registry.get("schema_version") != 1:
        errors.append("runtimes: schema_version must be 1")
    tier_definitions = registry.get("tier_definitions")
    if not isinstance(tier_definitions, dict) or set(tier_definitions) != RUNTIME_TIERS:
        errors.append("runtimes: tier_definitions must define exactly tier-1 and experimental")
    elif not all(isinstance(value, str) and value.strip() for value in tier_definitions.values()):
        errors.append("runtimes: tier_definitions values must be non-empty strings")
    runtimes = registry.get("runtimes")
    if not isinstance(runtimes, dict):
        return errors + ["runtimes: runtimes must be an object"]
    required = set(RUNTIME_IDS) | {"antigravity"}
    if set(runtimes) != required:
        errors.append(f"runtimes: expected {sorted(required)}, found {sorted(runtimes)}")

    destinations: dict[str, tuple[str, str]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    tier_one: set[str] = set()
    for runtime_id, runtime in runtimes.items():
        label = f"runtimes.{runtime_id}"
        if not isinstance(runtime, dict):
            errors.append(f"{label}: must be an object")
            continue
        _unknown_fields(
            runtime,
            {"display_name", "tier", "status", "adapter", "doctor", "capabilities", "identity_context_limit", "materializations"},
            label,
            errors,
        )
        if not isinstance(runtime.get("display_name"), str) or not runtime["display_name"].strip():
            errors.append(f"{label}: display_name must be a non-empty string")
        tier = runtime.get("tier")
        if tier not in RUNTIME_TIERS:
            errors.append(f"{label}: invalid tier {tier!r}")
        if tier == "tier-1":
            tier_one.add(runtime_id)
            if not runtime.get("adapter") or not runtime.get("doctor"):
                errors.append(f"{label}: Tier-1 runtimes require adapter and doctor")
        if runtime.get("status") not in RUNTIME_STATUS:
            errors.append(f"{label}: invalid status {runtime.get('status')!r}")
        if runtime.get("doctor") != EXPECTED_DOCTORS.get(runtime_id):
            errors.append(f"{label}: doctor must be {EXPECTED_DOCTORS.get(runtime_id)!r}")
        adapter = runtime.get("adapter")
        if adapter is not None:
            if not isinstance(adapter, str) or not _safe_relative(adapter):
                errors.append(f"{label}: adapter must be a safe repository-relative path")
            elif not _surface_present(root, adapter):
                notes.append(f"{label}: adapter surface not landed yet, existence unchecked: {adapter}")
            elif not (root / adapter).is_dir():
                errors.append(f"{label}: adapter directory missing: {adapter}")
            elif not _resolves_inside(root, root / adapter):
                errors.append(f"{label}: adapter resolves outside the repository: {adapter}")
        limit = runtime.get("identity_context_limit")
        if tier == "tier-1":
            if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
                errors.append(f"{label}: identity_context_limit must be a positive integer")
        elif limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
            errors.append(f"{label}: identity_context_limit must be null or a positive integer")
        capabilities = runtime.get("capabilities")
        expected_capabilities = set(CAPABILITY_VALUES)
        if not isinstance(capabilities, dict) or set(capabilities) != expected_capabilities:
            errors.append(f"{label}: capabilities must contain exactly {sorted(expected_capabilities)}")
        else:
            for capability, value in capabilities.items():
                if value not in CAPABILITY_VALUES[capability]:
                    errors.append(f"{label}.capabilities.{capability}: invalid value {value!r}")
        materializations = runtime.get("materializations")
        if not isinstance(materializations, list):
            errors.append(f"{label}: materializations must be a list")
            continue
        for index, materialization in enumerate(materializations):
            _validate_materialization(runtime_id, index, materialization, root, destinations, seen, errors, notes)

    retired = registry.get("retired_materializations")
    if not isinstance(retired, list):
        errors.append("runtimes: retired_materializations must be a list")
    else:
        retired_entries: set[tuple[Any, Any, Any]] = set()
        for index, item in enumerate(retired):
            label = f"runtimes.retired_materializations[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{label}: must be an object")
                continue
            _unknown_fields(item, {"runtime", "destination", "replacement"}, label, errors)
            entry = (item.get("runtime"), item.get("destination"), item.get("replacement"))
            if entry in retired_entries:
                errors.append(f"{label}: duplicate retired materialization entry")
            retired_entries.add(entry)
            if item.get("runtime") not in runtimes:
                errors.append(f"{label}: unknown runtime {item.get('runtime')!r}")
            for field in ("destination", "replacement"):
                value = item.get(field)
                if not isinstance(value, str) or not _safe_relative(value):
                    errors.append(f"{label}: {field} must be a safe repository-relative path")

    if tier_one != set(RUNTIME_IDS):
        errors.append(f"runtimes: Tier-1 set must be exactly {sorted(RUNTIME_IDS)}, found {sorted(tier_one)}")

    events = registry.get("hook_events")
    if not isinstance(events, dict) or set(events) != set(HOOK_EVENTS):
        errors.append(f"runtimes: hook_events must contain exactly {sorted(HOOK_EVENTS)}")
        return errors
    for event, spec in events.items():
        label = f"runtimes.hook_events.{event}"
        if not isinstance(spec, dict):
            errors.append(f"{label}: must be an object")
            continue
        _unknown_fields(spec, {"implementations", "runtimes"}, label, errors)
        implementations = spec.get("implementations")
        if not isinstance(implementations, list):
            errors.append(f"{label}: implementations must be a list")
            implementations = []
        if len(implementations) != len(set(implementations)):
            errors.append(f"{label}: implementations contains duplicates")
        for implementation in implementations:
            if not isinstance(implementation, str) or not HOOK_IMPLEMENTATION.fullmatch(implementation):
                errors.append(f"{label}: invalid implementation {implementation!r}")
                continue
            if not implementation.startswith(HOOK_EVENT_DIRS[event] + "/"):
                errors.append(f"{label}: implementation {implementation} belongs to another event directory")
            if not (root / "harness" / "hooks" / HOOK_EVENT_DIRS[event]).is_dir():
                notes.append(f"{label}: hook event directory not landed yet, wrapper existence unchecked: {implementation}")
                continue
            for extension in ("sh", "ps1"):
                if not (root / "harness" / "hooks" / f"{implementation}.{extension}").is_file():
                    errors.append(f"{label}: missing {implementation}.{extension}")
        implementation_names = {item for item in implementations if isinstance(item, str)}
        coverage = spec.get("runtimes")
        if not isinstance(coverage, dict) or set(coverage) != set(RUNTIME_IDS):
            errors.append(f"{label}: coverage must name every Tier-1 runtime")
            continue
        for runtime_id, state in coverage.items():
            _validate_hook_coverage(event, runtime_id, state, implementation_names, errors)
    return errors


# ---------------------------------------------------------------------------
# environment.json
# ---------------------------------------------------------------------------


def _walk_forbidden_keys(value: Any, path: str, errors: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_ENV_KEYS:
                errors.append(f"environment.{path or '<root>'}: forbidden secret-state field {key!r}")
            _walk_forbidden_keys(child, f"{path}.{key}" if path else str(key), errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_forbidden_keys(child, f"{path}[{index}]", errors)


def validate_environment(registry: dict[str, Any], root: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    label = "environment"
    for key, child in registry.items():
        if key == "policy":
            # The policy block's own keys state the rule ("values": "forbidden");
            # anything nested beneath them is still walked.
            if isinstance(child, dict):
                for policy_key, policy_child in child.items():
                    _walk_forbidden_keys(policy_child, f"policy.{policy_key}", errors)
            continue
        if isinstance(key, str) and key.lower() in FORBIDDEN_ENV_KEYS:
            errors.append(f"{label}.<root>: forbidden secret-state field {key!r}")
        _walk_forbidden_keys(child, str(key), errors)
    _unknown_fields(registry, {"schema_version", "policy", "principals", "locations", "bindings"}, label, errors)
    if registry.get("schema_version") != 1:
        errors.append(f"{label}: schema_version must be 1")
    policy = registry.get("policy")
    if not isinstance(policy, dict):
        errors.append(f"{label}: policy must be an object")
    else:
        _unknown_fields(policy, set(EXPECTED_ENV_POLICY), f"{label}.policy", errors)
        for field, expected in EXPECTED_ENV_POLICY.items():
            if policy.get(field) != expected:
                errors.append(f"{label}.policy.{field}: must be {expected!r}")
    principals = registry.get("principals")
    locations = registry.get("locations")
    bindings = registry.get("bindings")
    for name, value in (("principals", principals), ("locations", locations), ("bindings", bindings)):
        if not isinstance(value, dict):
            errors.append(f"{label}: {name} must be an object")
    if not all(isinstance(value, dict) for value in (principals, locations, bindings)):
        return errors

    for principal_id, principal in principals.items():
        plabel = f"{label}.principals.{principal_id}"
        if not KEBAB.fullmatch(str(principal_id)) or not isinstance(principal, dict):
            errors.append(f"{plabel}: invalid principal")
            continue
        _unknown_fields(principal, {"kind"}, plabel, errors)
        if principal.get("kind") not in ENV_PRINCIPAL_KINDS:
            errors.append(f"{plabel}: invalid kind {principal.get('kind')!r}")

    for location_id, location in locations.items():
        llabel = f"{label}.locations.{location_id}"
        if not KEBAB.fullmatch(str(location_id)) or not isinstance(location, dict):
            errors.append(f"{llabel}: invalid location")
            continue
        _unknown_fields(location, {"path_template", "owner_principal", "consumers", "sync_policy"}, llabel, errors)
        template = location.get("path_template")
        if not isinstance(template, str) or not re.match(r"^(repo|home|runtime):", template):
            errors.append(f"{llabel}: path_template must use repo:, home:, or runtime:")
        elif re.search(r"(?:^[A-Za-z]:[\\/]|/home/|/Users/|\\Users\\)", template) or re.search(r"[A-Za-z]:[\\/]", template):
            errors.append(f"{llabel}: path_template must not contain an absolute path")
        if location.get("owner_principal") not in principals:
            errors.append(f"{llabel}: unknown owner_principal {location.get('owner_principal')!r}")
        consumers = location.get("consumers")
        if not isinstance(consumers, list) or not consumers or any(item not in principals for item in consumers):
            errors.append(f"{llabel}: consumers must name known principals")
        if location.get("sync_policy") not in ENV_SYNC_POLICIES:
            errors.append(f"{llabel}: invalid sync_policy {location.get('sync_policy')!r}")

    for variable, binding in bindings.items():
        blabel = f"{label}.bindings.{variable}"
        if not isinstance(variable, str) or not ENV_NAME.fullmatch(variable):
            errors.append(f"{blabel}: variable must match ^[A-Z][A-Z0-9_]*$")
        if not isinstance(binding, dict):
            errors.append(f"{blabel}: must be an object")
            continue
        _unknown_fields(binding, {"class", "locations", "sharing", "status"}, blabel, errors)
        if binding.get("class") not in ENV_CLASSES:
            errors.append(f"{blabel}: invalid class {binding.get('class')!r}")
        binding_locations = binding.get("locations")
        if not isinstance(binding_locations, list) or not binding_locations or any(item not in locations for item in binding_locations):
            errors.append(f"{blabel}: locations must name known locations")
        elif len(set(binding_locations)) > 1 and binding.get("sharing") == "isolated":
            errors.append(f"{blabel}: an isolated binding cannot span several locations")
        if binding.get("sharing") not in ENV_SHARING_MODES:
            errors.append(f"{blabel}: invalid sharing {binding.get('sharing')!r}")
        if binding.get("status") not in ENV_BINDING_STATUSES:
            errors.append(f"{blabel}: invalid status {binding.get('status')!r}")
    return errors


# ---------------------------------------------------------------------------
# capabilities.json and sources.json
# ---------------------------------------------------------------------------


def validate_capabilities(registry: dict[str, Any], root: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    label = "capabilities"
    _unknown_fields(registry, {"schema_version", "capabilities"}, label, errors)
    if registry.get("schema_version") != 1:
        errors.append(f"{label}: schema_version must be 1")
    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, dict):
        return errors + [f"{label}: capabilities must be an object"]
    for capability_id, capability in capabilities.items():
        clabel = f"{label}.{capability_id}"
        if not KEBAB.fullmatch(str(capability_id)) or not isinstance(capability, dict):
            errors.append(f"{clabel}: invalid capability")
            continue
        _unknown_fields(capability, {"kind", "runtimes", "probe", "unready_behavior"}, clabel, errors)
        if capability.get("kind") not in CAPABILITY_KINDS:
            errors.append(f"{clabel}: invalid kind {capability.get('kind')!r}")
        runtimes = capability.get("runtimes")
        if not isinstance(runtimes, dict) or set(runtimes) != set(RUNTIME_IDS):
            errors.append(f"{clabel}: runtimes must name exactly {', '.join(RUNTIME_IDS)}")
        else:
            for runtime_id, state in runtimes.items():
                if state not in CAPABILITY_STATES:
                    errors.append(f"{clabel}.runtimes.{runtime_id}: invalid state {state!r}")
        probe = capability.get("probe")
        if not isinstance(probe, dict):
            errors.append(f"{clabel}: probe must be an object")
        else:
            _unknown_fields(probe, {"type", "value"}, f"{clabel}.probe", errors)
            probe_type = probe.get("type")
            probe_value = probe.get("value")
            if probe_type not in PROBE_TYPES:
                errors.append(f"{clabel}.probe: invalid type {probe_type!r}")
            elif probe_type == "none" and probe_value is not None:
                errors.append(f"{clabel}.probe: a none probe carries a null value")
            elif probe_type == "file-exists" and (not isinstance(probe_value, str) or not _safe_relative(probe_value)):
                errors.append(f"{clabel}.probe: file-exists value must be a safe repository-relative path")
            elif probe_type == "command" and (not isinstance(probe_value, str) or not probe_value.strip() or "/" in probe_value or "\\" in probe_value):
                errors.append(f"{clabel}.probe: command value must be a bare executable name")
        behavior = capability.get("unready_behavior")
        if not isinstance(behavior, str) or not behavior.strip():
            errors.append(f"{clabel}: unready_behavior must be a non-empty sentence")
    return errors


def validate_sources(registry: dict[str, Any], root: Optional[Path] = None) -> list[str]:
    errors: list[str] = []
    label = "sources"
    _unknown_fields(registry, {"schema_version", "sources"}, label, errors)
    if registry.get("schema_version") != 1:
        errors.append(f"{label}: schema_version must be 1")
    sources = registry.get("sources")
    if not isinstance(sources, dict):
        return errors + [f"{label}: sources must be an object"]
    claimed: dict[str, str] = {}
    for source_id, source in sources.items():
        slabel = f"{label}.{source_id}"
        if not KEBAB.fullmatch(str(source_id)) or not isinstance(source, dict):
            errors.append(f"{slabel}: invalid source")
            continue
        _unknown_fields(source, {"origin", "license", "notice", "modified", "assets"}, slabel, errors)
        origin = source.get("origin")
        if not isinstance(origin, str) or not (origin == "internal" or origin.startswith("https://")):
            errors.append(f"{slabel}: origin must be internal or an https URL")
        if source.get("license") not in SOURCE_LICENSES:
            errors.append(f"{slabel}: invalid license {source.get('license')!r}")
        notice = source.get("notice")
        if notice is not None and (not isinstance(notice, str) or not notice.strip()):
            errors.append(f"{slabel}: notice must be null or a non-empty string")
        if not isinstance(source.get("modified"), bool):
            errors.append(f"{slabel}: modified must be a boolean")
        assets = source.get("assets")
        if not isinstance(assets, list):
            errors.append(f"{slabel}: assets must be a list")
            continue
        for asset in assets:
            if not isinstance(asset, str) or not _safe_relative(asset):
                errors.append(f"{slabel}: unsafe asset path {asset!r}")
                continue
            key = _normalized_relative(asset)
            if key in claimed and claimed[key] != source_id:
                errors.append(f"{slabel}: asset {asset} is already claimed by {claimed[key]}")
            claimed[key] = str(source_id)
    return errors


# ---------------------------------------------------------------------------
# kernel-manifest.json
# ---------------------------------------------------------------------------


def validate_kernel_manifest(manifest: dict[str, Any], root: Optional[Path] = None) -> list[str]:
    """Check the manifest shape only; reconciliation to disk is a lint step."""
    errors: list[str] = []
    label = "kernel-manifest"
    _unknown_fields(manifest, {"version", "files"}, label, errors)
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append(f"{label}: version must be MAJOR.MINOR.PATCH")
    files = manifest.get("files")
    if not isinstance(files, list):
        return errors + [f"{label}: files must be a list"]
    seen: set[str] = set()
    for index, item in enumerate(files):
        flabel = f"{label}.files[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{flabel}: must be an object")
            continue
        _unknown_fields(item, {"path", "state", "source"}, flabel, errors)
        path = item.get("path")
        if not isinstance(path, str) or not _safe_relative(path):
            errors.append(f"{flabel}: path must be a safe repository-relative path")
        else:
            key = _normalized_relative(path)
            if key in seen:
                errors.append(f"{flabel}: duplicate path {path}")
            seen.add(key)
        state = item.get("state")
        source = item.get("source")
        if state not in MANIFEST_STATES:
            errors.append(f"{flabel}: state must be ported or new")
        elif state == "ported":
            if not isinstance(source, str) or not source.strip():
                errors.append(f"{flabel}: a ported file names its source")
            else:
                relative = source[len("basic-harness:"):] if source.startswith("basic-harness:") else source
                if not _safe_relative(relative):
                    errors.append(f"{flabel}: source must be a safe source-repo-relative path")
        elif source is not None:
            errors.append(f"{flabel}: a new file has a null source")
    return errors


# ---------------------------------------------------------------------------
# junctions.json cross-check
# ---------------------------------------------------------------------------


def validate_materialization_manifest(
    runtime_registry: dict[str, Any],
    root: Optional[Path] = None,
    notes: Optional[list[str]] = None,
) -> list[str]:
    """Require exact parity between junctions.json and runtimes.json materializations."""
    root = _root(root)
    notes = notes if notes is not None else []
    errors: list[str] = []
    path = root / "harness" / "bootstrap" / "junctions.json"
    if not path.is_file():
        notes.append("materializations: harness/bootstrap/junctions.json absent; parity unchecked until bootstrap lands")
        return []
    try:
        manifest = load_json(path)
    except (OSError, ValueError) as exc:
        return [f"materializations: cannot load junctions.json ({exc})"]
    _unknown_fields(manifest, {"schema_version", "junctions", "retired_destinations", "per_skill"}, "materializations", errors)
    if manifest.get("schema_version") != 1:
        errors.append("materializations: schema_version must be 1")
    junctions = manifest.get("junctions")
    if not isinstance(junctions, list):
        return errors + ["materializations: junctions must be a list"]
    declared: set[tuple[str, str, str]] = set()
    for index, item in enumerate(junctions):
        label = f"materializations.junctions[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        _unknown_fields(item, {"src", "dst", "mode", "runtime", "description"}, label, errors)
        entry = (item.get("src"), item.get("dst"), item.get("mode"))
        if not all(isinstance(value, str) for value in entry) or entry in declared:
            errors.append(f"{label}: src, dst, and mode must be strings and the triple must be unique")
        else:
            declared.add(entry)
        if item.get("mode") not in MATERIALIZATION_MODES:
            errors.append(f"{label}: mode must be one of {sorted(MATERIALIZATION_MODES)}")
        runtime = item.get("runtime")
        if runtime not in set(RUNTIME_IDS) | {"all"}:
            errors.append(f"{label}: runtime must be a Tier-1 runtime id or all")
        if not isinstance(item.get("description"), str) or not item["description"].strip():
            errors.append(f"{label}: description must be a non-empty string")
    expected: set[tuple[str, str, str]] = set()
    runtimes = runtime_registry.get("runtimes", {})
    if isinstance(runtimes, dict):
        for runtime in runtimes.values():
            if not isinstance(runtime, dict):
                continue
            for item in runtime.get("materializations", []):
                if isinstance(item, dict):
                    entry = (item.get("source"), item.get("destination"), item.get("mode"))
                    if all(isinstance(value, str) for value in entry):
                        expected.add(entry)
    for source, destination, mode in sorted(expected - declared):
        errors.append(f"materializations: registry entry {source} -> {destination} ({mode}) missing from junctions.json")
    for source, destination, mode in sorted(declared - expected):
        errors.append(f"materializations: undeclared junction {source} -> {destination} ({mode})")

    retired_manifest = manifest.get("retired_destinations")
    if not isinstance(retired_manifest, list):
        errors.append("materializations: retired_destinations must be a list")
        retired_manifest = []
    declared_retired: set[tuple[Any, Any]] = set()
    for index, item in enumerate(retired_manifest):
        label = f"materializations.retired_destinations[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        _unknown_fields(item, {"dst", "replacement", "description"}, label, errors)
        pair = (item.get("dst"), item.get("replacement"))
        if not all(isinstance(value, str) for value in pair) or pair in declared_retired:
            errors.append(f"{label}: destination/replacement pair must be unique strings")
        else:
            declared_retired.add(pair)
        if not isinstance(item.get("description"), str) or not item["description"].strip():
            errors.append(f"{label}: description must be a non-empty string")
    expected_retired = {
        (item.get("destination"), item.get("replacement"))
        for item in runtime_registry.get("retired_materializations", [])
        if isinstance(item, dict)
    }
    for pair in sorted(expected_retired - declared_retired):
        errors.append(f"materializations: retired registry entry {pair[0]} -> {pair[1]} missing from junctions.json")
    for pair in sorted(declared_retired - expected_retired):
        errors.append(f"materializations: undeclared retired destination {pair[0]} -> {pair[1]}")

    per_skill = manifest.get("per_skill")
    if per_skill is not None:
        if not isinstance(per_skill, dict) or set(per_skill) != set(RUNTIME_IDS):
            errors.append("materializations: per_skill must name every Tier-1 runtime")
        else:
            for runtime_id, spec in per_skill.items():
                label = f"materializations.per_skill.{runtime_id}"
                if not isinstance(spec, dict):
                    errors.append(f"{label}: must be an object")
                    continue
                _unknown_fields(spec, {"mode", "dst_dir", "link_as", "commands_dir"}, label, errors)
                if spec.get("mode") not in {"link", "generated"}:
                    errors.append(f"{label}: mode must be link or generated")
                for field in ("dst_dir", "link_as", "commands_dir"):
                    value = spec.get(field)
                    if field in spec and (not isinstance(value, str) or not _safe_relative(value)):
                        errors.append(f"{label}: {field} must be a safe repository-relative path")
    return errors


# ---------------------------------------------------------------------------
# collaborators.yaml (shape only; no YAML parser in the stdlib)
# ---------------------------------------------------------------------------


def validate_collaborators(root: Optional[Path] = None) -> list[str]:
    path = registry_dir(root) / "collaborators.yaml"
    if not path.is_file():
        return ["collaborators: harness/registry/collaborators.yaml is missing"]
    text = path.read_text(encoding="utf-8")
    if not re.search(r"^collaborators:\s*(\[\]|$)", text, re.MULTILINE):
        return ["collaborators: file must declare a top-level collaborators key"]
    return []


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def validate_all(root: Optional[Path] = None, notes: Optional[list[str]] = None) -> list[str]:
    """Validate every registry; return error lines, collecting informational notes."""
    root = _root(root)
    notes = notes if notes is not None else []
    errors: list[str] = []
    checks: list[tuple[str, Any]] = []
    loaders = (
        ("runtimes.json", load_runtimes, validate_runtimes),
        ("environment.json", lambda r: _load_registry("environment.json", r), validate_environment),
        ("selection.json", load_selection, validate_selection),
        ("capabilities.json", load_capabilities, validate_capabilities),
        ("sources.json", load_sources, validate_sources),
        ("kernel-manifest.json", load_kernel_manifest, validate_kernel_manifest),
    )
    loaded: dict[str, dict[str, Any]] = {}
    for name, loader, _ in loaders:
        try:
            loaded[name] = loader(root)
        except (OSError, ValueError) as exc:
            errors.append(f"registry: cannot load {name} ({exc})")
    try:
        structure = load_structure(root)
    except StructureError as exc:
        errors.append(f"structure: {exc}")
    else:
        checks.append(("structure", validate_structure(structure, root)))
    for name, _, validator in loaders:
        if name not in loaded:
            continue
        if validator is validate_runtimes:
            checks.append((name, validator(loaded[name], root, notes)))
        else:
            checks.append((name, validator(loaded[name], root)))
    if "runtimes.json" in loaded:
        checks.append(("junctions.json", validate_materialization_manifest(loaded["runtimes.json"], root, notes)))
    checks.append(("collaborators.yaml", validate_collaborators(root)))
    for _, found in checks:
        errors.extend(found)
    validate_all.last_check_count = len(checks)  # type: ignore[attr-defined]
    return errors


validate_all.last_check_count = 0  # type: ignore[attr-defined]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the harness registries; secret stores are never opened.")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    parser.add_argument("--quiet-notes", action="store_true", help="suppress informational notes")
    args = parser.parse_args(argv)
    notes: list[str] = []
    errors = validate_all(args.root.resolve(), notes)
    if not args.quiet_notes:
        for note in notes:
            print(f"  note {note}")
    if errors:
        for error in errors:
            print(f"  ERROR {error}")
        print(f"registries: {len(errors)} error(s)")
        return 1
    print(f"registries OK ({validate_all.last_check_count} checks)")  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
