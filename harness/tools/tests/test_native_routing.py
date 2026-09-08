"""native_routing: role generation, drift check, model-map binding, and the CLI."""

from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ._repo import RUNTIMES, install_bridge, routing_repo  # noqa: F401

import native_routing as nr
import routing_policy as rp

ROLE_NAME = re.compile(r"^(routing-[a-z0-9-]+-(execute|review)|explorer|worker|reviewer|workflow)$")


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = nr.main(argv)
    return code, out.getvalue(), err.getvalue()


def _resolved_repo(tmp_path: Path) -> Path:
    """Every family resolved on every runtime so each renderer produces files."""
    repo = routing_repo(tmp_path)
    for runtime in RUNTIMES:
        path = repo / "harness/adapters" / runtime / "model-map.json"
        native = json.loads(path.read_text(encoding="utf-8"))
        for family in native["families"]:
            native["families"][family] = f"fixture/{runtime}-{family}"
        path.write_text(json.dumps(native, indent=2) + "\n", encoding="utf-8")
    return repo


def test_render_check_is_clean_after_render_and_dirty_after_a_mutation(tmp_path):
    repo = _resolved_repo(tmp_path)
    code, out, err = _run(["--root", str(repo), "render"])
    assert code == 0, err
    code, out, _ = _run(["--root", str(repo), "render", "--check"])
    assert code == 0 and "OK native routing files match" in out
    generated = sorted((repo / "harness/adapters/claude/agents").glob("routing-*.md"))
    assert generated
    target = generated[0]
    target.write_text(target.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
    code, out, _ = _run(["--root", str(repo), "render", "--check"])
    assert code == 1
    assert f"DRIFT content harness/adapters/claude/agents/{target.name}" in out
    target.unlink()
    code, out, _ = _run(["--root", str(repo), "render", "--check"])
    assert code == 1 and "DRIFT missing" in out


def test_check_tolerates_an_absent_catalog_but_not_a_stale_one(tmp_path):
    repo = _resolved_repo(tmp_path)
    assert _run(["--root", str(repo), "render"])[0] == 0
    catalog = repo / nr.CATALOG
    catalog.unlink()
    assert _run(["--root", str(repo), "render", "--check"])[0] == 0
    catalog.write_text('{"schema_version": 1, "files": [], "source_hash": "x", "unresolved": {}}\n', encoding="utf-8")
    code, out, _ = _run(["--root", str(repo), "render", "--check"])
    assert code == 1 and "DRIFT content harness/registry/native-routing-files.json" in out


def test_generated_roles_carry_no_persona(tmp_path):
    repo = _resolved_repo(tmp_path)
    files, _, _ = nr.render_files(repo)
    role_files = {name: body.decode("utf-8") for name, body in files.items() if name != nr.CATALOG.as_posix()}
    assert role_files
    for name, text in role_files.items():
        for match in re.finditer(r"^name(?: =|:) *\"?([^\"\n]+)\"?$", text, re.MULTILINE):
            assert ROLE_NAME.match(match.group(1).strip()), (name, match.group(1))
        assert not re.search(r"\b(persona|backstory|personality)\b", text, re.IGNORECASE), name
        assert not re.search(r"\bI am [A-Z][a-z]+\b", text), name
        assert not re.search(r"\bYou are [A-Z][a-z]+\b", text), name
        assert "effort" not in text.split("---")[1] if text.startswith("---") else True


def test_roles_are_name_description_tools_permission_class_and_family(tmp_path):
    repo = _resolved_repo(tmp_path)
    policy, _ = nr.load_generated_policy(repo)
    for runtime in RUNTIMES:
        roles, unresolved = nr.build_roles(repo, policy, runtime)
        assert unresolved == {}
        assert roles
        for role in roles:
            assert ROLE_NAME.match(role["role_id"])
            assert role["permission_class"] in nr.PERMISSION_CLASSES
            assert role["native_model"] == f"fixture/{runtime}-{role['model_family']}"
            assert role["role"] == "child"
            assert isinstance(role["native_tools"], list)
            assert role["native_permissions"]["permission_class"] == role["permission_class"]
    claude = {role["role_id"]: role for role in nr.build_roles(repo, policy, "claude")[0]}
    assert claude["routing-retrieve-local-execute"]["permission_class"] == "read-only"
    assert claude["routing-edit-narrative-execute"]["permission_class"] == "edit"
    assert claude["routing-code-feature-execute"]["permission_class"] == "shell"
    assert claude["worker"]["compatibility_alias"] is True


def test_missing_family_key_raises_instead_of_defaulting(tmp_path):
    repo = _resolved_repo(tmp_path)
    path = repo / "harness/adapters/claude/model-map.json"
    native = json.loads(path.read_text(encoding="utf-8"))
    del native["families"]["strong"]
    path.write_text(json.dumps(native, indent=2), encoding="utf-8")
    try:
        nr.render_files(repo)
    except nr.NativeRoutingError as exc:
        assert "strong" in str(exc)
    else:
        raise AssertionError("a runtime lacking a required family rendered roles")


def test_null_family_id_skips_the_role_and_reports_it(tmp_path):
    repo = routing_repo(tmp_path)
    policy, _ = nr.load_generated_policy(repo)
    for runtime in RUNTIMES:
        native = json.loads((repo / "harness/adapters" / runtime / "model-map.json").read_text(encoding="utf-8"))
        nulls = {family for family, provider_id in native["families"].items() if provider_id is None}
        roles, unresolved = nr.build_roles(repo, policy, runtime)
        assert set(unresolved) <= nulls
        assert all(role["native_model"] for role in roles)
        assert all(role["model_family"] not in nulls for role in roles)
    files, _, catalog = nr.render_files(repo)
    for runtime, families in catalog["unresolved"].items():
        for family in families:
            assert not any(
                name.startswith(nr.AGENTS_DIR.format(runtime=runtime)) and f"-{family}" in name for name in files
            )
    codex_native = json.loads((repo / "harness/adapters/codex/model-map.json").read_text(encoding="utf-8"))
    if all(value is None for value in codex_native["families"].values()):
        assert not any(name.startswith(nr.AGENTS_DIR.format(runtime="codex")) for name in files)
        selected = nr.resolve_native(repo, "code.feature", "codex")
        assert selected["native_model"] is None
        assert selected["support"] == "unresolved-model-id"


def test_resolve_native_carries_the_controller_contract(tmp_path):
    repo = _resolved_repo(tmp_path)
    selected = nr.resolve_native(repo, "code.feature", "claude")
    for key in (
        "task_id", "profile", "role", "role_id", "model_family", "native_model", "tool_profile",
        "native_permissions", "native_tools", "missing_capabilities", "permission_limitations",
        "support", "effective_model_evidence", "observed_effective_model", "source_hash",
        "output_check", "escalation",
    ):
        assert key in selected, key
    assert selected["support"] == "configured"
    assert selected["effective_model_evidence"] == "unknown"
    assert selected["observed_effective_model"] is None
    assert selected["missing_capabilities"] == []
    review = nr.resolve_native(repo, "code.feature", "claude", phase="review")
    assert review["assignment"] == "reviewer"
    assert review["tool_profile"] == "review-readonly"
    # review-readonly carries a shell capability (bounded-test) over a
    # non-production write scope, so it resolves to shell-readonly: a shell
    # is allowed but Edit/Write never are, so the old "shell also grants
    # edit tools" caveat no longer applies here.
    assert review["permission_class"] == "shell-readonly"
    assert not any("shell permission class" in item for item in review["permission_limitations"])
    assert any("path scope is instruction-only" in item for item in review["permission_limitations"])
    # shell-readonly still grants Bash on Claude Code and OpenCode, so the
    # write-scope caveat must survive there with runtime-aware wording; on
    # Codex the sandbox itself enforces read-only, so the wording differs.
    assert any("Bash is granted" in item for item in review["permission_limitations"])
    codex_review = nr.resolve_native(repo, "code.feature", "codex", phase="review")
    assert codex_review["permission_class"] == "shell-readonly"
    assert any("sandbox_mode read-only enforces it" in item for item in codex_review["permission_limitations"])
    assert not any("Bash is granted" in item for item in codex_review["permission_limitations"])


def test_children_never_resolve_outside_their_runtime_family_ceiling(tmp_path):
    repo = _resolved_repo(tmp_path)
    policy, _ = nr.load_generated_policy(repo)
    for runtime in RUNTIMES:
        allowed = set(policy["runtime_constraints"][runtime]["child_families"])
        for role in nr.build_roles(repo, policy, runtime)[0]:
            assert role["model_family"] in allowed
            assert role["model_family"] != policy["runtime_constraints"][runtime]["main_family"]


def test_opencode_primary_orchestrates_while_children_cannot_spawn(tmp_path):
    repo = _resolved_repo(tmp_path)
    files, _, _ = nr.render_files(repo)
    primary = files["harness/adapters/opencode/agents/workflow.md"]
    assert b"mode: primary" in primary
    assert b"Orchestrate the workflow" in primary
    children = {name: body for name, body in files.items() if name.startswith("harness/adapters/opencode/agents/routing-")}
    assert children
    assert all(b'"task": deny' in body for body in children.values())
    assert all(b"Do not spawn another child" in body for body in children.values())
    claude_children = {name: body for name, body in files.items() if name.startswith("harness/adapters/claude/agents/routing-")}
    assert all(b"Agent" not in body.split(b"tools:", 1)[1].splitlines()[0] for body in claude_children.values())


def test_hash_mismatch_and_stale_manifest_are_rejected(tmp_path):
    repo = _resolved_repo(tmp_path)
    manifest_path = repo / nr.MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_hash"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    try:
        nr.load_generated_policy(repo)
    except nr.NativeRoutingError as exc:
        assert "source_hash" in str(exc)
    else:
        raise AssertionError("hash mismatch accepted")
    rp.write_manifest(repo, rp.load_policy(repo))
    source = repo / rp.SOURCE
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace('"policy_version": "1.0.0"', '"policy_version": "1.0.2"'), encoding="utf-8")
    try:
        nr.load_generated_policy(repo)
    except nr.NativeRoutingError as exc:
        assert "stale" in str(exc)
    else:
        raise AssertionError("stale manifest accepted")


def test_absent_manifest_compiles_in_memory_without_writing(tmp_path):
    repo = _resolved_repo(tmp_path)
    (repo / nr.MANIFEST).unlink()
    policy, digest = nr.load_generated_policy(repo)
    assert digest == rp.policy_digest(rp.load_policy(repo))
    assert not (repo / nr.MANIFEST).exists()


def test_list_prints_one_row_per_role(tmp_path):
    repo = _resolved_repo(tmp_path)
    code, out, _ = _run(["--root", str(repo), "list"])
    assert code == 0
    rows = [line.split("\t") for line in out.strip().splitlines()]
    assert rows
    assert all(len(row) == 5 and row[0] in RUNTIMES for row in rows)


install_bridge(globals(), "NativeRoutingBridge")
