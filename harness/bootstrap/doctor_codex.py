#!/usr/bin/env python3
"""Tiered health check for the Codex CLI adapter.

Default mode is a pure offline repository audit: file reads only, with no
regeneration, Codex invocation, authentication, or network access. Runtime,
prompt/runtime, connector, and skill-loading probes require explicit flags.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_codex_adapter  # noqa: E402
import doctor_common as dc  # noqa: E402
from doctor_common import TIERS, Audit  # noqa: E402,F401  (Audit lives in doctor_common; re-exported here)
from skill_catalog import SkillError, selected_skills  # noqa: E402

try:
    import tomllib
except ImportError:  # Python 3.10: TOML parsing unavailable in the stdlib
    tomllib = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
CONFIG_SOURCE = "harness/adapters/codex/config.toml"
CONFIG_OUTPUT = ".codex/config.toml"
HOOKS_SOURCE = "harness/adapters/codex/hooks.json"
HOOKS_OUTPUT = ".codex/hooks.json"
SCHEMA = "harness/adapters/codex/schema.json"
CATALOG_DIR = ".agents/skills"
OPERATOR_PERMISSION_KEYS = frozenset({
    "approval_policy",
    "approvals_reviewer",
    "sandbox_mode",
    "sandbox_workspace_write",
    "default_permissions",
    "permissions",
})
DISPATCHER = re.compile(r"harness[\\/]hooks[\\/](codex-dispatch)\.(sh|ps1)")
EVIDENCE_VALUES = {"passed", "unproven", "not-attempted"}


def command(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str] | None:
    """Run an explicit opt-in probe. Offline checks never call this function."""
    if args and args[0] == "codex":
        executable = shutil.which("codex.cmd" if os.name == "nt" else "codex")
        if not executable:
            return None
        args = (["cmd.exe", "/d", "/s", "/c", executable, *args[1:]]
                if os.name == "nt" else [executable, *args[1:]])
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        return subprocess.run(
            args, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
            capture_output=True, timeout=timeout, check=False, env=env, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value)
    return tuple(map(int, match.groups())) if match else ()


def _toml_paths(value: object, prefix: str = "") -> list[str]:
    if not isinstance(value, dict):
        return []
    paths: list[str] = []
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.append(path)
        paths.extend(_toml_paths(child, path))
    return paths


def _operator_permission_paths(value: object, path: str = "") -> list[str]:
    """Return forbidden permission-control keys anywhere in the project config."""
    if not isinstance(value, dict):
        return []
    found: list[str] = []
    for key, child in value.items():
        child_path = f"{path}.{key}" if path else str(key)
        if key in OPERATOR_PERMISSION_KEYS:
            found.append(child_path)
        found.extend(_operator_permission_paths(child, child_path))
    return found


def _schema(root: Path, audit: Audit) -> dict | None:
    return dc.read_json(root / SCHEMA, audit, SCHEMA)


def check_project_config(root: Path, audit: Audit) -> None:
    if not dc.check_managed_copy(root, audit, CONFIG_SOURCE, CONFIG_OUTPUT):
        return
    if tomllib is None:
        audit.fail("configured", f"{CONFIG_OUTPUT}: Python 3.11+ is required (tomllib is stdlib-only from 3.11); this interpreter cannot verify operator permission keys")
        return
    try:
        data = tomllib.loads((root / CONFIG_OUTPUT).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        audit.fail("configured", f"{CONFIG_OUTPUT} is invalid TOML ({exc})")
        return
    schema = _schema(root, audit) or {}
    forbidden = set(schema.get("config_toml_forbidden_keys", [])) | OPERATOR_PERMISSION_KEYS
    allowed = set(schema.get("config_toml_allowed_keys", []))
    found = [path for path in _operator_permission_paths(data) if path.split(".")[-1] in forbidden]
    if found:
        audit.fail("configured", "project config must not set operator permission controls: " + ", ".join(found))
    else:
        audit.ok("configured", "project config omits every operator permission control")
    if allowed:
        unknown = [path for path in _toml_paths(data) if path not in allowed]
        if unknown:
            audit.fail("configured", "project config carries keys outside the closed allowed list: " + ", ".join(unknown))
        else:
            audit.ok("configured", f"project config keys are all in the closed allowed list ({len(allowed)} entries)")
    if data.get("features", {}).get("hooks") is not True:
        audit.fail(
            "configured",
            "project config lacks features.hooks = true (a compatibility shim for CLI releases where "
            "hooks were feature-gated; a no-op once `codex features list` reports hooks stable)",
        )
    elif data.get("shell_environment_policy", {}).get("inherit") != "core":
        audit.fail("configured", "project config shell_environment_policy.inherit must be core")
    else:
        audit.ok("configured", "project config declares environment inheritance, hooks, and agents only")


def check_adapter_links(root: Path, audit: Audit) -> None:
    dc.check_junction_rows(root, audit, "codex")


def check_runtime_json_schema(root: Path, audit: Audit) -> bool:
    """Validate the generated hooks file against the adapter schema (rejects underscore keys)."""
    return dc.check_schema_file(root, audit, HOOKS_OUTPUT, SCHEMA, "hooks_json")


def check_hooks(root: Path, audit: Audit) -> None:
    if not dc.check_managed_copy(root, audit, HOOKS_SOURCE, HOOKS_OUTPUT):
        return
    check_runtime_json_schema(root, audit)
    document = dc.read_json(root / HOOKS_OUTPUT, audit, HOOKS_OUTPUT)
    if document is None:
        return
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        audit.fail("configured", f"{HOOKS_OUTPUT} lacks a hooks object")
        return
    runtime_registry = dc.load_runtimes(root) or {}
    hook_events = runtime_registry.get("hook_events") or {}
    # Only an event whose runtimes.json rung is native-hook for Codex is
    # required in the dispatcher registry; a contract-text rung (e.g.
    # UserPromptSubmit, which nothing registers) must NOT appear here.
    expected_events = {
        event for event in dc.HOOK_EVENTS
        if hook_events.get(event, {}).get("runtimes", {}).get("codex", {}).get("rung") == "native-hook"
    }
    missing_events = sorted(expected_events - set(hooks))
    unexpected_events = sorted(set(hooks) - expected_events)
    if missing_events:
        audit.fail("configured", "Codex hook registry misses events: " + ", ".join(missing_events))
    if unexpected_events:
        audit.fail("configured", "Codex hook registry has undeclared events: " + ", ".join(unexpected_events))
    handler_count = 0
    errors: list[str] = []
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            errors.append(f"{event}: groups must be a list")
            continue
        if len(groups) != 1:
            errors.append(f"{event}: expected exactly one dispatcher group, found {len(groups)}")
        for group in groups:
            handlers = group.get("hooks", []) if isinstance(group, dict) else []
            if len(handlers) != 1:
                errors.append(f"{event}: expected exactly one dispatcher handler, found {len(handlers)}")
            for handler in handlers:
                handler_count += 1
                if not isinstance(handler, dict):
                    errors.append(f"{event}: handler is not an object")
                    continue
                for field in ("command", "commandWindows"):
                    match = DISPATCHER.search(str(handler.get(field, "")))
                    if not match:
                        errors.append(f"{event}: {field} does not route through harness/hooks/codex-dispatch")
                    elif not (root / "harness" / "hooks" / f"{match.group(1)}.{match.group(2)}").is_file():
                        errors.append(f"{event}: missing dispatcher wrapper harness/hooks/{match.group(1)}.{match.group(2)}")
                    elif f"--event {event}" not in str(handler.get(field, "")) and f"-Event {event}" not in str(handler.get(field, "")):
                        errors.append(f"{event}: {field} dispatches a different event")
                if not isinstance(handler.get("timeout"), (int, float)) or handler["timeout"] <= 0:
                    errors.append(f"{event}: handler timeout missing or invalid")
                expected_limit = (
                    runtime_registry.get("hook_events", {})
                    .get(event, {})
                    .get("runtimes", {})
                    .get("codex", {})
                    .get("context_limit")
                )
                if handler.get("additionalContextLimit") != expected_limit:
                    errors.append(
                        f"{event}: additionalContextLimit {handler.get('additionalContextLimit')!r} "
                        f"does not match registry {expected_limit!r}"
                    )
    if errors:
        for error in errors:
            audit.fail("configured", f"hook registry: {error}")
    else:
        audit.ok("configured", f"Codex hook registry routes {len(hooks)} events through {handler_count} dispatcher handler(s) with registry context limits")
    audit.unknown("fired", "offline registry validation does not prove native Codex event delivery")
    audit.unknown("enforced", "offline registry validation does not prove hook deny decisions")


def check_skill_catalog(root: Path, audit: Audit) -> None:
    catalog = root / CATALOG_DIR
    if not catalog.is_dir():
        audit.fail("configured", f"{CATALOG_DIR} generated catalog is missing; run bootstrap")
        return
    try:
        expected, warnings = build_codex_adapter.render_catalog(root)
    except (OSError, SkillError, json.JSONDecodeError) as exc:
        audit.fail("configured", f"Codex skill catalog cannot render ({exc})")
        return
    for warning in warnings:
        audit.warn("configured", warning)
    problems, notes = build_codex_adapter.diff_catalog(catalog, expected)
    for note in notes:
        audit.ok("configured", f"{CATALOG_DIR}/{note}")
    if problems:
        for problem in problems:
            audit.fail("configured", f"Codex skill catalog drift: {problem}")
    else:
        summary = json.loads(expected[".catalog.json"])
        audit.ok(
            "configured",
            f"Codex skill catalog is exact: {summary['skills']} wrappers "
            f"({summary['implicit']} implicit, {summary['explicit_only']} explicit-only)",
        )
    generated_names = {relative.split("/", 1)[0] for relative in expected if "/" in relative}
    dc.check_selection(root, audit, CATALOG_DIR, "generated", generated_names)


def check_rules_and_compatibility(root: Path, audit: Audit) -> dict | None:
    rules = root / "harness/adapters/codex/rules/default.rules"
    try:
        text = rules.read_text(encoding="utf-8")
    except OSError as exc:
        audit.fail("configured", f"Codex command rules missing ({exc})")
    else:
        if 'decision = "forbidden"' in text and '"git", "add"' in text:
            audit.ok("configured", "command-rule source declares a broad-staging deny sentinel")
        else:
            audit.fail("configured", "command-rule source lacks the broad-staging deny sentinel")
    compatibility = dc.read_json(root / "harness/adapters/codex/compatibility.json", audit, "Codex compatibility record")
    if compatibility is not None:
        minimum = str(compatibility.get("minimum_cli", ""))
        tested = compatibility.get("tested_cli")
        evidence = compatibility.get("evidence", {})
        bad = [
            name for name, value in (evidence.items() if isinstance(evidence, dict) else [])
            if not (value in EVIDENCE_VALUES or (isinstance(value, str) and value.startswith("passed:")))
        ]
        if not version_tuple(minimum):
            audit.fail("configured", "compatibility record lacks a parseable minimum_cli version")
        elif bad:
            audit.fail("configured", "compatibility record evidence values outside the closed vocabulary: " + ", ".join(bad))
        else:
            status = compatibility.get("adapter_status", "unspecified")
            audit.ok(
                "configured",
                f"compatibility record is {status}; minimum {minimum}, tested {tested or 'none recorded'}, "
                f"observed {compatibility.get('observed_cli') or 'none recorded'}",
            )
    return compatibility


AGENTS_OUTPUT = ".codex/agents"


def check_agent_roles(root: Path, audit: Audit) -> None:
    """Every generated Codex agent role must parse as TOML the Codex role
    loader accepts. Codex's native `tools` key is a table of specific
    toggles (web_search, experimental_request_user_input, update_plan); an
    array there is the shape codex-cli 0.153.4 rejects with "Ignoring
    malformed agent role definition ... data did not match any variant of
    untagged enum WebSearchToolConfigInput" (one warning per role file)."""
    agents_dir = root / AGENTS_OUTPUT
    if not agents_dir.is_dir():
        audit.fail("configured", f"{AGENTS_OUTPUT} is missing; run bootstrap")
        return
    if tomllib is None:
        audit.fail("configured", f"{AGENTS_OUTPUT}: Python 3.11+ is required (tomllib is stdlib-only from 3.11); this interpreter cannot verify agent role files")
        return
    roles = sorted(agents_dir.glob("*.toml"))
    if not roles:
        # Native routing may not have been rendered yet in this repository
        # state; whether roles should exist is a different check's concern.
        # There is nothing to validate the shape of, so this check stays
        # silent rather than asserting a tier state either way.
        return
    problems: list[str] = []
    for path in roles:
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            problems.append(f"{path.name}: invalid TOML ({exc})")
            continue
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            problems.append(f"{path.name}: missing name")
        if not isinstance(data.get("developer_instructions"), str) or not data["developer_instructions"].strip():
            problems.append(f"{path.name}: missing developer_instructions")
        if "tools" in data:
            problems.append(f"{path.name}: carries a top-level tools key ({data['tools']!r}); Codex's native tools key is a table of specific toggles, not this vocabulary's array shape")
    if problems:
        for problem in problems:
            audit.fail("configured", f"Codex agent role: {problem}")
    else:
        audit.ok("configured", f"{len(roles)} Codex agent role(s) parse and carry name, developer_instructions, and no rejected tools array")


def check_repository(root: Path, audit: Audit) -> dict | None:
    """Pure repository audit. This function performs file reads only."""
    dc.check_contract_files(root, audit)
    dc.check_gitignore_floor(root, audit, "codex")
    check_project_config(root, audit)
    check_adapter_links(root, audit)
    check_hooks(root, audit)
    check_agent_roles(root, audit)
    check_skill_catalog(root, audit)
    compatibility = check_rules_and_compatibility(root, audit)
    dc.check_git_floor(root, audit)
    dc.check_model_map(root, audit, "codex")
    dc.check_capabilities(root, audit, "codex")
    dc.check_degradation_rungs(root, audit, "codex")
    return compatibility


def check_runtime(audit: Audit, compatibility: dict | None) -> None:
    result = command(["codex", "--version"])
    if not result or result.returncode != 0:
        audit.fail("loaded", "Codex CLI not found or version probe failed")
        return
    installed = result.stdout.strip()
    audit.ok("loaded", f"Codex CLI executable responded: {installed}")
    if compatibility:
        minimum, tested = str(compatibility.get("minimum_cli", "")), compatibility.get("tested_cli")
        if version_tuple(installed) < version_tuple(minimum):
            audit.fail("loaded", f"{installed} is below minimum {minimum}")
        elif not tested:
            audit.warn("loaded", f"{installed} meets minimum {minimum}; no live-tested CLI is recorded")
        elif version_tuple(installed) != version_tuple(str(tested)):
            audit.warn("loaded", f"installed CLI differs from tested {tested}; runtime conformance is required")
    features = command(["codex", "features", "list"])
    if features and features.returncode == 0 and re.search(r"(?m)^hooks\s+\S+\s+true\b", features.stdout):
        audit.ok("loaded", "effective Codex feature list reports hooks enabled")
    else:
        audit.fail("loaded", "effective Codex feature list does not report hooks enabled")
    policy = command([
        "codex", "execpolicy", "check", "--rules",
        "harness/adapters/codex/rules/default.rules", "--", "git", "add", ".",
    ])
    if policy and policy.returncode == 0 and "forbidden" in policy.stdout.lower():
        audit.ok("enforced", "Codex policy evaluator forbids broad git staging")
    else:
        audit.fail("enforced", "Codex command-rule deny sentinel failed")
    audit.unknown("enforced", "command-rule proof does not prove PreToolUse hook denials")
    audit.unknown("trusted", "project trust and per-hook hash approval are not exposed by a CLI probe; use --network")


def check_network_runtime(audit: Audit) -> None:
    prompt = command(["codex", "debug", "prompt-input", "adapter doctor probe"], timeout=45)
    if prompt and prompt.returncode == 0 and "[base-harness codex adapter]" in prompt.stdout:
        audit.ok("loaded", "project developer instructions rendered in Codex")
    elif prompt and prompt.returncode == 0:
        audit.warn("loaded", "Codex rendered a prompt without project developer instructions; verify project trust")
    else:
        audit.fail("loaded", "Codex prompt-input probe failed")
    doctor_output = command(["codex", "doctor", "--json"], timeout=45)
    try:
        doctor = json.loads(doctor_output.stdout) if doctor_output and doctor_output.returncode == 0 else {}
        sandbox = doctor["checks"]["sandbox.helpers"]["details"]
        if not isinstance(sandbox, dict):
            raise TypeError("runtime permission details must be an object")
        fields = {
            "filesystem": sandbox.get("filesystem sandbox"),
            "approval": sandbox.get("approval policy"),
            "network": sandbox.get("network sandbox"),
        }
        if all(isinstance(value, str) and value.strip() for value in fields.values()):
            audit.ok(
                "loaded",
                "effective runtime permissions observed: "
                + ", ".join(f"{name}={value}" for name, value in fields.items()),
            )
        else:
            audit.unknown("loaded", "effective runtime permission fields are missing or malformed")
    except (KeyError, TypeError, json.JSONDecodeError):
        audit.unknown("loaded", "effective runtime permission fields are missing or malformed")
    audit.unknown("trusted", "prompt rendering does not expose exact hook-definition hash trust")
    audit.unknown("fired", "no scrubbed native event capture is persisted by this probe")


def check_auth_configuration(root: Path, audit: Audit) -> None:
    registry = dc.read_json(root / "harness/registry/capabilities.json", audit, "capability registry")
    result = command(["codex", "mcp", "list", "--json"])
    try:
        configured = {item["name"] for item in json.loads(result.stdout)} if result and result.returncode == 0 else set()
    except (KeyError, TypeError, json.JSONDecodeError):
        configured = set()
    if registry:
        for name, capability in registry.get("capabilities", {}).items():
            kind = capability.get("kind")
            probe = capability.get("probe", {}) if isinstance(capability.get("probe"), dict) else {}
            if kind == "mcp":
                if name in configured:
                    audit.ok("loaded", f"MCP capability {name} is configured")
                else:
                    audit.warn("loaded", f"MCP capability {name} is not configured")
            elif kind == "cli":
                command_name = str(probe.get("value") or "")
                if command_name and shutil.which(command_name):
                    audit.ok("loaded", f"CLI capability {name} has command {command_name}")
                else:
                    audit.warn("loaded", f"CLI capability {name} is missing its command")
            elif kind == "local-script":
                path = root / str(probe.get("value") or "")
                if probe.get("value") and path.is_file():
                    audit.ok("loaded", f"script capability {name} is installed")
                else:
                    audit.warn("loaded", f"script capability {name} is missing its script")
    audit.unknown("trusted", "MCP server-name presence does not prove authentication")
    audit.unknown("outcome-proven", "configured capability presence does not prove authentication or a semantic operation")


def parse_prompt_skill_paths(stdout: str) -> set[str]:
    return set(
        re.findall(
            r"(?i)(?:^|[\\/])[.]agents[\\/]skills[\\/]([^\\/\s]+)[\\/]SKILL[.]md",
            stdout,
        )
    )


def _prompt_skills(prompt: str) -> set[str] | None:
    result = command(["codex", "debug", "prompt-input", prompt], timeout=45)
    if not result or result.returncode != 0:
        return None
    return parse_prompt_skill_paths(result.stdout)


def check_skill_loading(root: Path, audit: Audit) -> None:
    """Opt-in Codex prompt probe. Never called by the offline repository audit."""
    try:
        skills, selected, _ = selected_skills(root)
    except (SkillError, json.JSONDecodeError, OSError) as exc:
        audit.fail("loaded", f"skill-loading probe cannot load the catalog ({exc})")
        return
    baseline = {name for name in selected if build_codex_adapter.catalog_policy(skills[name]) == "implicit"}
    explicit = [name for name in selected if build_codex_adapter.catalog_policy(skills[name]) == "explicit-only"]
    omitted = [name for name, skill in skills.items() if skill.status == "stub"]
    natural = _prompt_skills("adapter doctor skill-loading probe")
    if natural is None:
        audit.fail("loaded", "implicit skill-loading prompt probe failed")
        return
    if natural != baseline:
        audit.fail("loaded", f"implicit skill set mismatch: missing={sorted(baseline - natural)}, unexpected={sorted(natural - baseline)}")
    else:
        audit.ok("loaded", f"Codex prompt exposes the exact {len(baseline)} implicit-skill baseline")
    for name in explicit:
        observed = _prompt_skills(f"${name} adapter doctor skill-loading probe")
        if observed is None or name not in observed:
            audit.fail("loaded", f"explicit ${name} did not expose its wrapper")
        elif not baseline.issubset(observed):
            audit.fail("loaded", f"explicit ${name} dropped baseline implicit wrappers: {sorted(baseline - observed)}")
        else:
            audit.ok("loaded", f"explicit ${name} exposed its wrapper and retained the implicit baseline")
    for name in omitted:
        stub = _prompt_skills(f"${name} adapter doctor skill-loading probe")
        if stub is None:
            audit.fail("loaded", f"stub skill-loading prompt probe failed for {name}")
        elif name in stub:
            audit.fail("loaded", f"omitted stub {name} appeared in the Codex prompt")
        else:
            audit.ok("loaded", f"omitted stub {name} stayed out of the Codex prompt")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="explicitly select the default pure repository audit")
    parser.add_argument("--runtime", action="store_true", help="also run local Codex CLI and command-policy probes")
    parser.add_argument("--network", action="store_true", help="also run explicit prompt/doctor probes that may contact the Codex runtime")
    parser.add_argument("--auth", action="store_true", help="also inspect connector configuration; semantic authentication remains unproven")
    parser.add_argument("--probe-skill-loading", action="store_true", help="run opt-in Codex explicit, implicit, and stub prompt probes")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (defaults to this checkout)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    runtime = args.runtime or args.network or args.auth or args.probe_skill_loading
    modes = ["offline"] + (["runtime"] if runtime else []) + (["network"] if args.network else []) + (["auth"] if args.auth else []) + (["skill-loading"] if args.probe_skill_loading else [])
    dc.print_header("Codex", root, modes)
    audit = Audit()
    compatibility = check_repository(root, audit)
    if runtime:
        check_runtime(audit, compatibility)
    if args.network:
        check_network_runtime(audit)
    if args.auth:
        check_auth_configuration(root, audit)
    if args.probe_skill_loading:
        check_skill_loading(root, audit)
    if not runtime:
        audit.unknown("loaded", "runtime probe not requested; use --runtime")
        audit.unknown("trusted", "project and hook-definition trust not probed; use --network")
        if not audit.entries["fired"]:
            audit.unknown("fired", "native event delivery not probed; use --network")
    dc.finish_unknown(audit, {
        "configured": "no repository configuration evidence was collected",
        "loaded": "effective runtime state was not observed",
        "trusted": "project and hook-definition trust were not observed",
        "fired": "native event delivery was not observed",
        "enforced": "no deny sentinel was observed through Codex",
        "outcome-proven": "no artifact-level workflow evidence was collected",
    })
    audit.summary()
    return 1 if audit.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
