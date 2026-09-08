#!/usr/bin/env python3
"""Shared audit model and repository checks for the three runtime doctors.

Every doctor prints the same per-check line, the same six-layer roll-up, and
the same final result line (the interfaces contract, section 10). The checks
here are pure file reads plus local git config reads; none of them launches a
runtime CLI, touches the network, or regenerates anything.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
BOOTSTRAP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BOOTSTRAP_DIR))
import build_codex_adapter  # noqa: E402
import contract_files  # noqa: E402
import materialize  # noqa: E402
import schema_check  # noqa: E402
from contract_files import check_contract  # noqa: E402
from skill_catalog import SkillError, selected_skills  # noqa: E402

TIERS = ("configured", "loaded", "trusted", "fired", "enforced", "outcome-proven")
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
GIT_HOOKS_DIR = ".githooks"


class Audit:
    def __init__(self) -> None:
        self.entries: dict[str, list[tuple[str, str]]] = {tier: [] for tier in TIERS}
        self.failures = 0
        self.warnings = 0

    def emit(self, tier: str, state: str, message: str) -> None:
        self.entries[tier].append((state, message))
        self.failures += state == "FAIL"
        self.warnings += state == "WARN"
        print(f"  [{tier:<14}] {state:<7} {message}")

    def ok(self, tier: str, message: str) -> None:
        self.emit(tier, "OK", message)

    def warn(self, tier: str, message: str) -> None:
        self.emit(tier, "WARN", message)

    def fail(self, tier: str, message: str) -> None:
        self.emit(tier, "FAIL", message)

    def unknown(self, tier: str, message: str) -> None:
        self.emit(tier, "UNKNOWN", message)

    def ensure_unknown(self, tier: str, message: str) -> None:
        if not self.entries[tier]:
            self.unknown(tier, message)

    def tier_state(self, tier: str) -> str:
        states = {state for state, _ in self.entries[tier]}
        if "FAIL" in states:
            return "FAIL"
        if "UNKNOWN" in states and states.intersection({"OK", "WARN"}):
            return "PARTIAL"
        if "UNKNOWN" in states:
            return "UNKNOWN"
        if "WARN" in states:
            return "PARTIAL"
        return "PASS" if "OK" in states else "UNKNOWN"

    def summary(self) -> None:
        print("\nEvidence tiers:")
        for tier in TIERS:
            print(f"  {tier:<14} {self.tier_state(tier)}")
        repository = "FAIL" if self.failures else "PASS"
        runtime = "PROVEN" if all(self.tier_state(t) == "PASS" for t in TIERS[1:]) else "INCOMPLETE"
        print(
            f"\nResult: repository {repository}; runtime evidence {runtime}; "
            f"{self.warnings} warning(s), {self.failures} failure(s)"
        )


# ---------------------------------------------------------------- loading --


def read_json(path: Path, audit: Audit, label: str, tier: str = "configured") -> dict | None:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        audit.fail(tier, f"{label} is unreadable or invalid JSON ({exc})")
        return None
    if not isinstance(value, dict):
        audit.fail(tier, f"{label} must be a JSON object")
        return None
    return value


def load_junctions(root: Path, audit: Audit) -> dict | None:
    try:
        return materialize.load_manifest(root)
    except materialize.ManifestError as exc:
        audit.fail("configured", f"junctions.json: {exc}")
        return None


def load_runtimes(root: Path) -> dict | None:
    try:
        value = json.loads((Path(root) / "harness" / "registry" / "runtimes.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def same_target(path: Path, target: Path) -> bool:
    try:
        return path.exists() and os.path.realpath(path) == os.path.realpath(target)
    except OSError:
        return False


def print_header(name: str, root: Path, modes: list[str]) -> None:
    print(f"base-harness {name} doctor - root: {Path(root).as_posix()}")
    print("Mode: " + " + ".join(modes) + "\n")


# ------------------------------------------------------------ contract --


def check_contract_files(root: Path, audit: Audit) -> None:
    issues = check_contract(root)
    if issues:
        for issue in issues:
            audit.fail("configured", f"agent contract: {issue}; run bootstrap to repair")
    elif contract_files.contract_mode(root) == "host-owned":
        audit.ok("configured", "contract: host-owned (AGENTS.md is the host's; template block at AGENTS.harness.md)")
    else:
        audit.ok("configured", "agent contract: AGENTS.md rendered from CONTRACT.md + CONTRACT.host.md; CLAUDE.md pointer exact")
    advisory = contract_files.contract_advisory(root)
    if advisory:
        audit.warn("configured", advisory)


def check_gitignore_floor(root: Path, audit: Audit, runtime: str) -> None:
    """Warn when a host .gitignore rule hides a bootstrap-managed copy for this runtime."""
    git = shutil.which("git")
    if not git:
        return
    manifest = load_junctions(root, audit)
    if manifest is None:
        return
    for entry in manifest["junctions"]:
        if entry.get("runtime", "all") not in (runtime, "all"):
            continue
        if entry["mode"] != "managed-copy":
            continue
        dst_rel = entry["dst"]
        try:
            result = subprocess.run(
                [git, "-C", str(root), "check-ignore", "-v", dst_rel],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and result.stdout.strip():
            rule = result.stdout.strip().split("\t", 1)[0]
            audit.warn(
                "configured",
                f"{dst_rel} is hidden by a host ignore rule ({rule}); narrow the rule to the "
                f"link subpaths, or accept this runtime's config as bootstrap-local per clone",
            )


# ----------------------------------------------------- junction rows --


def check_managed_copy(root: Path, audit: Audit, src_rel: str, dst_rel: str) -> bool:
    src, dst = Path(root) / src_rel, Path(root) / dst_rel
    if not src.is_file():
        audit.fail("configured", f"{dst_rel}: canonical source {src_rel} is missing")
        return False
    if dst.is_symlink():
        audit.fail("configured", f"{dst_rel} is a symlink; managed copies are independent files (run bootstrap)")
        return False
    if not dst.is_file():
        audit.fail("configured", f"{dst_rel} is not materialized; run bootstrap")
        return False
    try:
        if os.path.samefile(src, dst):
            audit.fail("configured", f"{dst_rel} is a hardlink of {src_rel}; run bootstrap for an independent copy")
            return False
    except OSError:
        pass
    if src.read_bytes() != dst.read_bytes():
        audit.fail("configured", f"{dst_rel} differs from its canonical source {src_rel}; run bootstrap")
        return False
    audit.ok("configured", f"{dst_rel} is a byte-exact independent copy of {src_rel}")
    return True


def check_link_target(root: Path, audit: Audit, src_rel: str, dst_rel: str) -> bool:
    src, dst = Path(root) / src_rel, Path(root) / dst_rel
    if not src.is_dir():
        audit.fail("configured", f"{dst_rel}: canonical source {src_rel} is missing")
        return False
    if not dst.exists() and not dst.is_symlink():
        audit.fail("configured", f"{dst_rel} is missing; run bootstrap")
        return False
    if materialize.is_link(dst):
        if same_target(dst, src):
            audit.ok("configured", f"{dst_rel} resolves to {src_rel}")
            return True
        audit.fail("configured", f"{dst_rel} links to the wrong target; run bootstrap")
        return False
    if dst.is_dir():
        if materialize.dirs_equal(src, dst):
            audit.ok("configured", f"{dst_rel} is a content-equal copy of {src_rel} (copy mode)")
            return True
        audit.fail("configured", f"{dst_rel} is a real directory whose content differs from {src_rel}")
        return False
    audit.fail("configured", f"{dst_rel} is a file where a directory link belongs")
    return False


def check_absent_contract_copy(root: Path, audit: Audit, dst_rel: str) -> None:
    dst = Path(root) / dst_rel
    if dst.exists() or dst.is_symlink():
        audit.fail("configured", f"{dst_rel} exists; the root AGENTS.md render serves this runtime (run bootstrap)")
    else:
        audit.ok("configured", f"{dst_rel} absent by design; the root AGENTS.md render serves this runtime")


def check_junction_rows(root: Path, audit: Audit, runtime: str) -> dict | None:
    """Audit every link, managed-copy, and contract-render row for one runtime."""
    manifest = load_junctions(root, audit)
    if manifest is None:
        return None
    owned = materialize.per_skill_destinations(manifest)
    for entry in manifest["junctions"]:
        if entry.get("runtime", "all") not in (runtime, "all"):
            continue
        mode, src_rel, dst_rel = entry["mode"], entry["src"], entry["dst"]
        if mode == "contract-render":
            if dst_rel != materialize.CONTRACT_OUTPUT:
                check_absent_contract_copy(root, audit, dst_rel)
            continue
        if mode == "generated" or dst_rel in owned:
            continue
        if mode == "managed-copy":
            check_managed_copy(root, audit, src_rel, dst_rel)
        elif mode == "link":
            check_link_target(root, audit, src_rel, dst_rel)
    for entry in manifest.get("retired_destinations", []):
        dst = Path(root) / entry["dst"]
        if dst.exists() or dst.is_symlink():
            audit.fail("configured", f"retired {entry['dst']} still exists (replacement {entry.get('replacement', '')}); run bootstrap")
        else:
            audit.ok("configured", f"retired {entry['dst']} is absent")
    return manifest


# ------------------------------------------------------------- schemas --


def check_schema_file(root: Path, audit: Audit, path_rel: str, schema_rel: str, schema_key: str | None = None) -> bool:
    """Validate one generated runtime JSON file against its adapter schema."""
    schema_path = Path(root) / schema_rel
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        if schema_key:
            schema = schema[schema_key]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        audit.fail("configured", f"{schema_rel} is unusable ({exc})")
        return False
    try:
        errors = schema_check.validate_file(Path(root) / path_rel, schema)
    except schema_check.SchemaError as exc:
        audit.fail("configured", f"{schema_rel}: {exc}")
        return False
    if errors:
        for error in errors[:8]:
            audit.fail("configured", f"{path_rel} violates {schema_rel}: {error}")
        if len(errors) > 8:
            audit.fail("configured", f"{path_rel}: {len(errors) - 8} further schema violation(s)")
        return False
    audit.ok("configured", f"{path_rel} validates against {schema_rel} (closed objects, no underscore keys)")
    return True


# ---------------------------------------------------------- selection --


def materialized_skills(root: Path, dst_dir_rel: str, kind: str) -> set[str]:
    """Names of harness-managed skill entries under a per-skill directory.

    kind "link": links that resolve into harness/skills, or directories that
    carry the materialize marker (copy mode). kind "generated": directories
    that carry the generator marker.
    """
    dst_dir = Path(root) / dst_dir_rel
    if not dst_dir.is_dir():
        return set()
    names: set[str] = set()
    skills_root = os.path.realpath(Path(root) / materialize.SKILLS_DIR)
    for entry in sorted(dst_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if kind == "generated":
            if build_codex_adapter.is_generated_dir(entry):
                names.add(entry.name)
            continue
        if materialize.is_link(entry):
            try:
                target = os.path.realpath(entry)
                if os.path.commonpath([skills_root, target]) == skills_root:
                    names.add(entry.name)
            except (OSError, ValueError):
                continue
        elif entry.is_dir() and (entry / materialize.MARKER).is_file():
            names.add(entry.name)
    return names


def check_selection(root: Path, audit: Audit, dst_dir_rel: str, kind: str, expected: set[str] | None = None) -> None:
    """Reconcile materialized skill entries with selection.json."""
    try:
        skills, selected, warnings = selected_skills(Path(root))
    except (SkillError, json.JSONDecodeError, OSError) as exc:
        audit.fail("configured", f"selection cannot be computed ({exc})")
        return
    for warning in warnings:
        audit.warn("configured", warning)
    wanted = set(selected) if expected is None else expected
    found = materialized_skills(root, dst_dir_rel, kind)
    if found == wanted:
        audit.ok(
            "configured",
            f"{dst_dir_rel}: {len(found)} materialized; {len(selected)} selected of {len(skills)} available",
        )
        return
    missing = sorted(wanted - found)
    extra = sorted(found - wanted)
    detail = []
    if missing:
        detail.append("missing " + ", ".join(missing))
    if extra:
        detail.append("stale " + ", ".join(extra))
    audit.fail(
        "configured",
        f"{dst_dir_rel}: {len(found)} materialized but {len(wanted)} selected "
        f"({len(skills)} available; {'; '.join(detail)}); run bootstrap",
    )


# ----------------------------------------------------------- git floor --


def git_config(root: Path, key: str) -> str | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        completed = subprocess.run(
            [git, "-C", str(root), "config", "--local", key],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else ""


def check_git_floor(root: Path, audit: Audit) -> None:
    git = shutil.which("git")
    if not git:
        audit.warn("configured", "git is not on PATH; the pre-commit floor cannot be registered")
        return
    try:
        probe = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        audit.warn("configured", "git could not be run; the pre-commit floor state is unknown")
        return
    if probe.returncode != 0:
        audit.warn("configured", "not a git repository; the pre-commit floor is not registered (run git init, then bootstrap)")
        return
    value = (git_config(root, "core.hooksPath") or "").rstrip("/\\")
    # core.hooksPath registered to .githooks but the directory itself is
    # absent is a worse state than "not configured yet": git will silently
    # skip every hook (nothing to find at that path), so this is a FAIL on
    # every platform, not the WARN an unregistered/never-bootstrapped
    # repository gets. The directory check therefore runs AFTER reading
    # core.hooksPath, not before, so it can tell the two states apart.
    if not (Path(root) / GIT_HOOKS_DIR).is_dir():
        if value == GIT_HOOKS_DIR:
            audit.fail("configured", f"core.hooksPath = {GIT_HOOKS_DIR} but no {GIT_HOOKS_DIR}/ directory exists; the pre-commit floor is not registered")
        else:
            audit.warn("configured", f"no {GIT_HOOKS_DIR}/ directory; the git pre-commit floor is unavailable")
        return
    if value != GIT_HOOKS_DIR:
        audit.fail("configured", f"core.hooksPath is {value or 'unset'}, expected {GIT_HOOKS_DIR}; run bootstrap")
        return
    chained = git_config(root, "harness.chainedHooksPath") or ""
    if chained:
        audit.ok("configured", f"core.hooksPath = {GIT_HOOKS_DIR}; prior hooks path {chained} chained via harness.chainedHooksPath")
    else:
        audit.ok("configured", f"core.hooksPath = {GIT_HOOKS_DIR} (pre-commit floor registered)")
    # A registered core.hooksPath is inert if the hook file is missing (any
    # platform) or, on POSIX, not executable: git prints an "ignoredHook"
    # advice and silently skips it rather than failing. The missing-file
    # check applies everywhere; only the executable-bit check is POSIX-only
    # (Windows has no executable bit to inspect).
    hook_path = Path(root) / GIT_HOOKS_DIR / "pre-commit"
    if not hook_path.is_file():
        audit.fail("configured", f"{GIT_HOOKS_DIR}/pre-commit is missing; the pre-commit floor is not registered")
    elif os.name != "nt":
        if not os.access(hook_path, os.X_OK):
            audit.fail("configured", f"{GIT_HOOKS_DIR}/pre-commit is not executable; core.hooksPath silently ignores it (run bootstrap, or chmod +x)")
        else:
            audit.ok("configured", f"{GIT_HOOKS_DIR}/pre-commit is executable")
    else:
        audit.ok("configured", f"{GIT_HOOKS_DIR}/pre-commit is present")


# -------------------------------------------------- adapters and registry --


def _adapter_model_map_module(root: Path):
    path = Path(root) / "harness" / "adapters" / "model_map.py"
    if not path.is_file():
        path = BOOTSTRAP_DIR.parents[0] / "adapters" / "model_map.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("harness_model_map", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_model_map(root: Path, audit: Audit, runtime: str) -> None:
    module = _adapter_model_map_module(root)
    if module is None:
        audit.unknown("configured", "model map loader (harness/adapters/model_map.py) not present")
        return
    try:
        lines = module.doctor_lines(runtime, Path(root))
    except Exception as exc:  # noqa: BLE001 - the loader reports its own errors as lines
        audit.fail("configured", f"model map: {exc}")
        return
    for layer, state, message in lines:
        audit.emit(layer, state, message)


def check_capabilities(root: Path, audit: Audit, runtime: str) -> None:
    registry = read_json(Path(root) / "harness" / "registry" / "capabilities.json", audit, "capability registry")
    if registry is None:
        return
    capabilities = registry.get("capabilities")
    if not isinstance(capabilities, dict):
        audit.fail("configured", "capability registry lacks a capabilities object")
        return
    if not capabilities:
        audit.ok("configured", "capability registry declares no capabilities")
        return
    for name, capability in capabilities.items():
        if not isinstance(capability, dict):
            audit.fail("configured", f"capability {name} is not an object")
            continue
        state = capability.get("runtimes", {}).get(runtime, "unknown")
        probe = capability.get("probe", {}) if isinstance(capability.get("probe"), dict) else {}
        probe_type, probe_value = probe.get("type", "none"), probe.get("value")
        if state == "unknown":
            audit.unknown("configured", f"capability {name}: declared unknown on {runtime}; nothing probed")
            continue
        if probe_type == "file-exists" and isinstance(probe_value, str):
            if (Path(root) / probe_value).exists():
                audit.ok("configured", f"capability {name}: declared {state}; probe file {probe_value} present")
            else:
                audit.fail("configured", f"capability {name}: declared {state}; probe file {probe_value} missing")
        elif probe_type == "command" and isinstance(probe_value, str):
            if shutil.which(probe_value):
                audit.ok("configured", f"capability {name}: declared {state}; command {probe_value} on PATH")
            else:
                audit.warn("configured", f"capability {name}: declared {state}; command {probe_value} not on PATH")
        else:
            audit.ok("configured", f"capability {name}: declared {state} on {runtime} (no offline probe)")


def check_degradation_rungs(root: Path, audit: Audit, runtime: str) -> None:
    registry = load_runtimes(root)
    events = registry.get("hook_events") if isinstance(registry, dict) else None
    for event in HOOK_EVENTS:
        try:
            event_spec = events[event]
            rung = event_spec["runtimes"][runtime]["rung"]
        except (KeyError, TypeError):
            audit.unknown("configured", f"degradation rung for {event}: not declared in runtimes.json")
            continue
        implementations = event_spec.get("implementations") if isinstance(event_spec, dict) else None
        if rung == "native-hook" and not implementations:
            audit.warn(
                "configured",
                f"degradation rung for {event}: native-hook with zero implementations registered; nothing actually fires",
            )
        else:
            audit.ok("configured", f"degradation rung for {event}: {rung}")


def finish_unknown(audit: Audit, reasons: dict[str, str]) -> None:
    """Fill every layer that gathered no evidence with an explicit reason."""
    for tier in TIERS:
        audit.ensure_unknown(tier, reasons.get(tier, f"no {tier} evidence was collected"))
