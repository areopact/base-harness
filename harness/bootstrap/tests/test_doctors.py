"""Doctor output format (B12), strict runtime JSON (B14), and doctor behavior."""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

NEEDS_TOMLLIB = sys.version_info < (3, 11)
NEEDS_TOMLLIB_REASON = "requires Python 3.11+ (tomllib is stdlib-only from 3.11)"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import BOOTSTRAP, bind_unittest, build_repo

sys.path.insert(0, str(BOOTSTRAP))
import doctor_claude  # noqa: E402
import doctor_codex  # noqa: E402
import doctor_common  # noqa: E402
import doctor_opencode  # noqa: E402
import materialize  # noqa: E402
import schema_check  # noqa: E402

LINE = re.compile(r"^  \[(?P<layer>[a-z-]+)\s*\] (?P<state>OK|WARN|FAIL|UNKNOWN)\s+(?P<message>.+)$")
ROLLUP = re.compile(r"^  (?P<layer>[a-z-]+)\s+(?P<state>PASS|PARTIAL|UNKNOWN|FAIL)$")
RESULT = re.compile(r"^Result: repository (PASS|FAIL); runtime evidence (PROVEN|INCOMPLETE); \d+ warning\(s\), \d+ failure\(s\)$")


def _run(module, root: Path, *flags: str) -> tuple[int, str]:
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = module.main([*flags, "--root", str(root)])
    return code, stream.getvalue()


def _parse(output: str) -> tuple[list[tuple[str, str, str]], dict[str, str]]:
    lines = output.splitlines()
    checks = [m.groupdict() for m in map(LINE.match, lines) if m]
    start = lines.index("Evidence tiers:")
    rollup: dict[str, str] = {}
    for line in lines[start + 1:]:
        match = ROLLUP.match(line)
        if not match:
            break
        rollup[match.group("layer")] = match.group("state")
    assert RESULT.match(lines[-1]), lines[-1]
    return [(c["layer"], c["state"], c["message"]) for c in checks], rollup


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_b12_every_doctor_prints_the_shared_format_with_every_layer(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    for module in (doctor_claude, doctor_codex, doctor_opencode):
        code, output = _run(module, root, "--offline")
        checks, rollup = _parse(output)
        assert code == 0, output
        assert list(rollup) == list(doctor_common.TIERS)
        layers = {layer for layer, _, _ in checks}
        assert layers == set(doctor_common.TIERS)
        for tier in doctor_common.TIERS[1:]:
            assert rollup[tier] == "UNKNOWN"
        assert rollup["configured"] == "PASS"
        for event in doctor_common.HOOK_EVENTS:
            assert any(message.startswith(f"degradation rung for {event}: ") for _, _, message in checks)
        assert "runtime evidence INCOMPLETE" in output


def test_b12_a_layer_with_zero_entries_is_unknown_never_pass():
    audit = doctor_common.Audit()
    for tier in doctor_common.TIERS:
        assert audit.tier_state(tier) == "UNKNOWN"
    with redirect_stdout(io.StringIO()):
        audit.ok("configured", "one fact")
        audit.ok("enforced", "policy")
        audit.unknown("enforced", "hooks unproven")
        audit.warn("loaded", "soft")
        audit.fail("fired", "broken")
    assert audit.tier_state("configured") == "PASS"
    assert audit.tier_state("enforced") == "PARTIAL"
    assert audit.tier_state("loaded") == "PARTIAL"
    assert audit.tier_state("fired") == "FAIL"
    assert audit.tier_state("trusted") == "UNKNOWN"
    stream = io.StringIO()
    with redirect_stdout(stream):
        audit.summary()
    text = stream.getvalue()
    assert "  trusted        UNKNOWN" in text
    assert text.strip().splitlines()[-1] == "Result: repository FAIL; runtime evidence INCOMPLETE; 1 warning(s), 1 failure(s)"


def test_b12_check_lines_use_the_exact_column_layout():
    stream = io.StringIO()
    with redirect_stdout(stream):
        doctor_common.Audit().ok("outcome-proven", "message")
        doctor_common.Audit().unknown("fired", "x")
    lines = stream.getvalue().splitlines()
    assert lines[0] == "  [outcome-proven] OK      message"
    assert lines[1] == "  [fired         ] UNKNOWN x"


def test_b14_seeded_comment_key_in_generated_runtime_json_fails_the_schema_step(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    source = root / "harness" / "adapters" / "codex" / "hooks.json"
    output = root / ".codex" / "hooks.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    document["_comment"] = "seeded"
    text = json.dumps(document, indent=2) + "\n"
    source.write_text(text, encoding="utf-8")
    output.write_text(text, encoding="utf-8")
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        assert doctor_codex.check_runtime_json_schema(root, audit) is False
    assert audit.failures >= 1
    assert any("_comment" in message for _, message in audit.entries["configured"])

    nested = json.loads(source.read_text(encoding="utf-8"))
    del nested["_comment"]
    nested["hooks"]["Stop"][0]["hooks"][0]["_note"] = "seeded"
    output.write_text(json.dumps(nested, indent=2) + "\n", encoding="utf-8")
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        assert doctor_codex.check_runtime_json_schema(root, audit) is False
    assert any("_note" in message for _, message in audit.entries["configured"])


def test_b14_claude_and_opencode_generated_json_are_schema_checked(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    cases = (
        (".claude/settings.json", "harness/adapters/claude/settings.base.json", doctor_claude),
        ("opencode.json", "harness/adapters/opencode/opencode.json", doctor_opencode),
    )
    for relative, source, module in cases:
        document = json.loads((root / relative).read_text(encoding="utf-8"))
        document["_comment"] = "seeded"
        text = json.dumps(document, indent=2) + "\n"
        (root / relative).write_text(text, encoding="utf-8")
        (root / source).write_text(text, encoding="utf-8")
        code, output = _run(module, root, "--offline")
        assert code == 1
        assert "additional property '_comment' not allowed" in output
        assert "$._comment: underscore-prefixed key rejected" in output


def test_schema_check_rejects_underscore_keys_and_accepts_the_shipped_files():
    adapters = BOOTSTRAP.parents[0] / "adapters"
    cases = (
        (adapters / "claude" / "settings.base.json", adapters / "claude" / "schema.json", None),
        (adapters / "codex" / "hooks.json", adapters / "codex" / "schema.json", "hooks_json"),
        (adapters / "opencode" / "opencode.json", adapters / "opencode" / "schema.json", None),
    )
    for config_path, schema_path, key in cases:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema = schema[key] if key else schema
        assert schema_check.validate_file(config_path, schema) == []
        seeded = json.loads(config_path.read_text(encoding="utf-8"))
        seeded["_comment"] = "x"
        assert schema_check.validate(seeded, schema)
        assert schema_check.underscore_keys(seeded) == ["$._comment"]


def test_selection_mismatch_is_a_configured_fail_with_both_counts(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    materialize.remove_link(root / ".claude" / "skills" / "beta")
    code, output = _run(doctor_claude, root, "--offline")
    assert code == 1
    assert re.search(r"\[configured\s*\] FAIL\s+\.claude/skills: 1 materialized but 2 selected \(3 available; missing beta\)", output)
    assert "1 materialized" in output and "2 selected" in output


def test_opencode_wrapper_bypass_is_a_configured_fail(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    skill_root = root / ".opencode" / "skills"
    materialize.remove_link(skill_root)
    materialize.make_link(root / "harness" / "skills", skill_root)
    code, output = _run(doctor_opencode, root, "--offline")
    assert code == 1
    assert "does not resolve into harness/.selected/skills" in output
    assert "launcher wrapper is bypassed" in output


def test_materialized_plugin_import_check_resolves_side_effect_and_dynamic_imports(tmp_path):
    """A side-effect import (no bindings) and a literal dynamic import must
    both be resolved, not only a `from "..."` import: the doctor must not
    silently ignore a real missing sibling behind either form."""
    root = build_repo(tmp_path)
    materialize.apply(root)
    plugin = root / doctor_opencode.MATERIALIZED_PLUGIN
    lib_dir = plugin.parent.parent / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "present.js").write_text("export const x = 1;\n", encoding="utf-8")
    plugin.write_text(
        plugin.read_text(encoding="utf-8")
        + '\nimport "../lib/present.js";\n'
        + 'const y = await import("../lib/present.js");\n',
        encoding="utf-8",
    )
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_opencode.check_materialized_plugin_imports(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert "missing" not in messages, messages

    plugin.write_text(
        plugin.read_text(encoding="utf-8") + '\nimport "../lib/absent.js";\n',
        encoding="utf-8",
    )
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_opencode.check_materialized_plugin_imports(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert "../lib/absent.js" in messages, messages


def test_materialized_plugin_import_check_ignores_commented_out_imports(tmp_path):
    """A commented-out import must never be reported as a missing sibling:
    the line comment is prose, not a real import statement."""
    root = build_repo(tmp_path)
    materialize.apply(root)
    plugin = root / doctor_opencode.MATERIALIZED_PLUGIN
    plugin.write_text(
        plugin.read_text(encoding="utf-8") + '\n// import "../lib/absent.js";\n',
        encoding="utf-8",
    )
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_opencode.check_materialized_plugin_imports(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert "../lib/absent.js" not in messages, messages
    assert "missing" not in messages, messages


def test_materialized_plugin_import_check_resolves_backtick_and_comment_preceded_dynamic_imports(tmp_path):
    """A backtick template-literal import (no ${} interpolation) and a
    dynamic import preceded by a block comment must both resolve."""
    root = build_repo(tmp_path)
    materialize.apply(root)
    plugin = root / doctor_opencode.MATERIALIZED_PLUGIN
    lib_dir = plugin.parent.parent / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "present.js").write_text("export const x = 1;\n", encoding="utf-8")
    plugin.write_text(
        plugin.read_text(encoding="utf-8")
        + "\nconst y = import(/* chunk */ \"../lib/present.js\");\n"
        + "const z = import(`../lib/present.js`);\n",
        encoding="utf-8",
    )
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_opencode.check_materialized_plugin_imports(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert "missing" not in messages, messages

    plugin.write_text(
        plugin.read_text(encoding="utf-8") + "\nconst w = import(`../lib/absent.js`);\n",
        encoding="utf-8",
    )
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_opencode.check_materialized_plugin_imports(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert "../lib/absent.js" in messages, messages


def test_check_git_floor_fails_on_a_missing_precommit_hook_on_every_platform(tmp_path):
    """The missing-file check must not sit inside the POSIX-only branch: a
    repository with core.hooksPath correctly registered but no
    .githooks/pre-commit file at all must FAIL on Windows too, not print
    'pre-commit floor registered' and PASS."""
    root = build_repo(tmp_path)
    materialize.apply(root)
    (root / ".githooks" / "pre-commit").unlink()
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_common.check_git_floor(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert ".githooks/pre-commit is missing; the pre-commit floor is not registered" in messages, messages
    assert audit.tier_state("configured") == "FAIL"


def test_check_git_floor_fails_when_hooks_path_is_registered_but_the_directory_is_absent(tmp_path):
    """core.hooksPath = .githooks with no .githooks/ directory on disk at
    all is a worse state than never having bootstrapped: git silently
    skips every hook. It must FAIL, not WARN 'the git pre-commit floor is
    unavailable' (the message an unregistered repository gets)."""
    root = build_repo(tmp_path)
    materialize.apply(root)
    shutil.rmtree(root / ".githooks")
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_common.check_git_floor(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert "no .githooks/ directory exists" in messages, messages
    assert audit.tier_state("configured") == "FAIL"


def test_check_git_floor_warns_when_hooks_path_is_unregistered_and_the_directory_is_absent(tmp_path):
    """The unregistered case keeps its WARN: nothing has been bootstrapped
    yet, which is a different (recoverable-by-running-bootstrap) state
    than a registered path pointing at nothing."""
    root = build_repo(tmp_path, with_git=True)
    shutil.rmtree(root / ".githooks")
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_common.check_git_floor(root, audit)
    messages = "\n".join(message for entries in audit.entries.values() for _, message in entries)
    assert "the git pre-commit floor is unavailable" in messages, messages
    assert audit.tier_state("configured") != "FAIL"


def test_missing_hook_wrapper_is_a_configured_fail_for_claude_and_codex(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    (root / "harness" / "hooks" / "stop" / "close-the-loop.sh").unlink()
    code, output = _run(doctor_claude, root, "--offline")
    assert code == 1 and "wrapper harness/hooks/stop/close-the-loop.sh is missing" in output
    (root / "harness" / "hooks" / "codex-dispatch.sh").unlink()
    code, output = _run(doctor_codex, root, "--offline")
    assert code == 1 and "missing dispatcher wrapper harness/hooks/codex-dispatch.sh" in output


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_codex_offline_never_calls_the_probe_command(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    with mock.patch.object(doctor_codex, "command", side_effect=AssertionError("offline called command")):
        code, output = _run(doctor_codex, root, "--offline")
    assert code == 0, output
    assert "Mode: offline" in output
    assert "loaded         UNKNOWN" in output


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_codex_operator_permission_keys_fail_recursively(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    source = root / "harness" / "adapters" / "codex" / "config.toml"
    output = root / ".codex" / "config.toml"
    for key in ("approval_policy", "sandbox_mode", "permissions"):
        for prefix in ("", "[profiles.audit]\n"):
            text = source.read_text(encoding="utf-8") + f"\n{prefix}{key} = \"x\"\n"
            output.write_text(text, encoding="utf-8")
            base = source.read_text(encoding="utf-8")
            source.write_text(text, encoding="utf-8")
            audit = doctor_common.Audit()
            with redirect_stdout(io.StringIO()):
                doctor_codex.check_project_config(root, audit)
            source.write_text(base, encoding="utf-8")
            assert audit.failures >= 1, key
            assert any(key in message for _, message in audit.entries["configured"])


def test_codex_hook_audit_requires_registry_context_limits(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    source = root / "harness" / "adapters" / "codex" / "hooks.json"
    output = root / ".codex" / "hooks.json"
    document = json.loads(source.read_text(encoding="utf-8"))
    document["hooks"]["PreToolUse"][0]["hooks"][0]["additionalContextLimit"] = 601
    text = json.dumps(document, indent=2) + "\n"
    source.write_text(text, encoding="utf-8")
    output.write_text(text, encoding="utf-8")
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_codex.check_hooks(root, audit)
    assert any("additionalContextLimit 601" in message for _, message in audit.entries["configured"])


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_codex_agent_role_with_a_tools_array_is_a_configured_fail(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    agents_dir = root / ".codex" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "fixture-bad-role.toml").write_text(
        'name = "fixture-bad-role"\n'
        'description = "fixture"\n'
        'model = "gpt-5.6-luna"\n'
        'sandbox_mode = "read-only"\n'
        'tools = ["filesystem-read"]\n'
        'developer_instructions = """\nfixture\n"""\n',
        encoding="utf-8",
    )
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_codex.check_agent_roles(root, audit)
    assert audit.failures >= 1
    assert any("tools" in message and "fixture-bad-role.toml" in message for _, message in audit.entries["configured"])


@unittest.skipIf(NEEDS_TOMLLIB, NEEDS_TOMLLIB_REASON)
def test_codex_agent_role_without_tools_or_missing_fields_is_ok_or_flagged(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    agents_dir = root / ".codex" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    good = agents_dir / "fixture-good-role.toml"
    good.write_text(
        'name = "fixture-good-role"\n'
        'description = "fixture"\n'
        'model = "gpt-5.6-luna"\n'
        'sandbox_mode = "read-only"\n'
        'developer_instructions = """\nfixture\n"""\n',
        encoding="utf-8",
    )
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_codex.check_agent_roles(root, audit)
    good.unlink()
    assert audit.failures == 0
    assert any("carry name" in message for _, message in audit.entries["configured"])

    missing = agents_dir / "fixture-missing-fields.toml"
    missing.write_text('model = "gpt-5.6-luna"\nsandbox_mode = "read-only"\n', encoding="utf-8")
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_codex.check_agent_roles(root, audit)
    missing.unlink()
    messages = " ".join(message for _, message in audit.entries["configured"])
    assert "missing name" in messages and "missing developer_instructions" in messages


def test_runtime_probe_flags_are_opt_in():
    assert not doctor_codex.parse_args([]).runtime
    assert doctor_codex.parse_args(["--probe-skill-loading"]).probe_skill_loading
    assert doctor_codex.parse_args(["--offline"]).offline
    assert doctor_opencode.parse_args(["--offline"]).offline
    assert doctor_claude.parse_args(["--offline"]).offline


def test_d1_doctor_reports_host_owned_contract_and_advisory(tmp_path):
    root = build_repo(tmp_path)
    (root / "AGENTS.md").write_text("the host's own contract\n", encoding="utf-8", newline="\n")
    structure_path = root / "harness" / "registry" / "structure.json"
    doc = json.loads(structure_path.read_text(encoding="utf-8"))
    doc["contract"] = {"mode": "host-owned"}
    structure_path.write_text(json.dumps(doc), encoding="utf-8")
    materialize.apply(root)
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_common.check_contract_files(root, audit)
    entries = audit.entries["configured"]
    assert any(state == "OK" and "host-owned" in message for state, message in entries)
    assert any(state == "WARN" and "AGENTS.harness.md" in message for state, message in entries)
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == "the host's own contract\n"
    assert (root / "AGENTS.harness.md").is_file()


def test_d3_gitignore_floor_warns_when_a_host_rule_hides_a_managed_copy(tmp_path):
    root = build_repo(tmp_path)
    (root / ".gitignore").write_text(".codex/\n", encoding="utf-8", newline="\n")
    materialize.apply(root)
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_common.check_gitignore_floor(root, audit, "codex")
    messages = [message for _, message in audit.entries["configured"]]
    assert any(".codex/config.toml" in message and ".codex/" in message for message in messages)
    assert audit.failures == 0


def test_d3_gitignore_floor_silent_without_a_hiding_rule(tmp_path):
    root = build_repo(tmp_path)
    materialize.apply(root)
    audit = doctor_common.Audit()
    with redirect_stdout(io.StringIO()):
        doctor_common.check_gitignore_floor(root, audit, "codex")
    assert audit.entries["configured"] == []
    assert audit.warnings == 0


def test_prompt_path_parser_handles_windows_and_posix_paths():
    text = (
        "C:\\repo\\.agents\\skills\\alpha\\SKILL.md\n"
        "/repo/.agents/skills/beta/SKILL.md\n"
        "/repo/harness/skills/gamma/SKILL.md\n"
    )
    assert doctor_codex.parse_prompt_skill_paths(text) == {"alpha", "beta"}


bind_unittest(globals(), "DoctorsBridge")
