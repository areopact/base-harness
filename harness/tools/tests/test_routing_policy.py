"""routing_policy: compiler, validator, digest, resolver, composite floors, and CLI."""

from __future__ import annotations

import copy
import io
import json
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from ._repo import ROOT, ROUTING_INPUTS, RUNTIMES, install_bridge, routing_repo  # noqa: F401

import routing_policy as rp

FAMILY_KEYS = ("fast", "balanced", "strong", "strong-main")


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = rp.main(argv)
    return code, out.getvalue(), err.getvalue()


def _policy_text(repo: Path) -> Path:
    return repo / rp.SOURCE


def test_inventory_and_compatibility_aliases(tmp_path):
    policy = rp.load_policy(routing_repo(tmp_path))
    assert len(policy["tasks"]) == 41
    assert len(policy["profiles"]) == 8
    assert len(policy["tool_profiles"]) == 22
    assert set(policy["compatibility_aliases"]) == {"explorer", "worker", "reviewer"}
    for record in policy["compatibility_aliases"].values():
        task = policy["tasks"][record["task_id"]]
        assert task["executor"] == record["profile"]
        assert task["tool_profile"] == record["tool_profile"]


def test_runtimes_come_from_the_registry_and_exclude_experimental(tmp_path):
    repo = routing_repo(tmp_path)
    registry = json.loads((repo / "harness/registry/runtimes.json").read_text(encoding="utf-8"))
    tier_one = tuple(name for name, spec in registry["runtimes"].items() if spec.get("tier") == "tier-1")
    experimental = [name for name, spec in registry["runtimes"].items() if spec.get("tier") != "tier-1"]
    assert rp.load_runtimes(repo) == tier_one
    policy = rp.load_policy(repo)
    assert tuple(policy["runtime_constraints"]) == tier_one
    for name in experimental:
        assert name not in policy["runtime_constraints"]


def test_validator_is_reference_driven_not_count_driven(tmp_path):
    policy = rp.load_policy(routing_repo(tmp_path))
    edited = copy.deepcopy(policy)
    edited["tasks"]["retrieve.extra"] = copy.deepcopy(edited["tasks"]["retrieve.local"])
    assert rp.validate_policy(edited, RUNTIMES) == []
    edited["tasks"]["retrieve.extra"]["tool_profile"] = "missing"
    assert any("unknown tool profile" in item for item in rp.validate_policy(edited, RUNTIMES))


def test_validator_rejects_profile_and_alias_floor_drift(tmp_path):
    policy = rp.load_policy(routing_repo(tmp_path))
    edited = copy.deepcopy(policy)
    edited["profiles"]["S-BUILD"]["tier"] = "Fast"
    assert any("below the declared capability floor" in item for item in rp.validate_policy(edited, RUNTIMES))
    edited = copy.deepcopy(policy)
    edited["compatibility_aliases"]["worker"]["profile"] = "F-READ"
    assert any("must match its task executor" in item for item in rp.validate_policy(edited, RUNTIMES))


def test_digest_is_canonical_and_excludes_generated_views(tmp_path):
    repo = routing_repo(tmp_path)
    policy = rp.load_policy(repo)
    reordered = json.loads(json.dumps(policy))
    reordered["tasks"] = dict(reversed(list(reordered["tasks"].items())))
    assert rp.policy_digest(policy) == rp.policy_digest(reordered)
    source = _policy_text(repo)
    text = source.read_text(encoding="utf-8")
    assert "## Generated task view" in text
    source.write_text(text.replace("## Generated task view", "## Generated task view changed"), encoding="utf-8")
    assert rp.policy_digest(rp.load_policy(repo)) == rp.policy_digest(policy)


def test_compile_writes_a_manifest_whose_digest_is_stable(tmp_path):
    repo = routing_repo(tmp_path, compile_manifest=False)
    code, first, _ = _run(["--root", str(repo), "compile"])
    assert code == 0
    manifest_one = (repo / rp.MANIFEST).read_bytes()
    code, second, _ = _run(["--root", str(repo), "compile"])
    assert code == 0
    assert first == second
    assert re.fullmatch(r"[0-9a-f]{64}\n", first)
    assert (repo / rp.MANIFEST).read_bytes() == manifest_one
    manifest = json.loads(manifest_one)
    assert manifest["source_hash"] == first.strip()
    assert manifest["source"] == rp.SOURCE.as_posix()
    assert manifest["schema_version"] == rp.SCHEMA_VERSION


def test_check_passes_then_fails_after_a_one_character_policy_edit(tmp_path):
    repo = routing_repo(tmp_path)
    code, out, _ = _run(["--root", str(repo), "check"])
    assert code == 0 and out.startswith("OK ")
    source = _policy_text(repo)
    text = source.read_text(encoding="utf-8")
    assert '"policy_version": "1.0.0"' in text
    source.write_text(text.replace('"policy_version": "1.0.0"', '"policy_version": "1.0.1"'), encoding="utf-8")
    code, out, _ = _run(["--root", str(repo), "check"])
    assert code == 1
    assert out.startswith("DRIFT stale ")


def test_check_treats_a_missing_manifest_as_never_drift(tmp_path):
    """The manifest is a generated cache, untracked and rebuilt on demand
    (docs/ARCHITECTURE.md: its absence is never drift). check must compile
    the authored policy in memory, print its digest, and exit 0 rather than
    reporting DRIFT and exit 1 on a fresh clone that has never run compile."""
    repo = routing_repo(tmp_path, compile_manifest=False)
    assert not (repo / rp.MANIFEST).is_file()
    code, out, _ = _run(["--root", str(repo), "check"])
    assert code == 0, out
    assert "DRIFT" not in out
    assert out.startswith("OK ")
    assert "no cache" in out
    digest = rp.policy_digest(rp.load_policy(repo))
    assert digest[:12] in out


def test_check_still_reports_drift_when_a_stale_manifest_exists(tmp_path):
    repo = routing_repo(tmp_path)
    assert (repo / rp.MANIFEST).is_file()
    source = _policy_text(repo)
    text = source.read_text(encoding="utf-8")
    assert '"policy_version": "1.0.0"' in text
    source.write_text(text.replace('"policy_version": "1.0.0"', '"policy_version": "1.0.1"'), encoding="utf-8")
    code, out, _ = _run(["--root", str(repo), "check"])
    assert code == 1
    assert out.startswith("DRIFT stale ")


def test_unknown_task_id_never_resolves(tmp_path):
    policy = rp.load_policy(routing_repo(tmp_path))
    assert rp.classify_planning(policy, substantive=True) == "T2"
    assert rp.classify_planning(policy) == "T0"
    for call in (
        lambda: rp.classify_planning(policy, "unknown.task"),
        lambda: rp.resolve_task(policy, "unknown.task", "claude"),
        lambda: rp.composite_floor(policy, "unknown.task"),
    ):
        try:
            call()
        except rp.PolicyError as exc:
            assert "unknown task ID" in str(exc)
        else:
            raise AssertionError("unknown task id resolved")


def test_resolve_cli_prints_a_work_package_and_rejects_unknown(tmp_path):
    repo = routing_repo(tmp_path)
    code, out, _ = _run(["--root", str(repo), "resolve", "--task", "code.feature", "--runtime", "claude"])
    assert code == 0
    package = json.loads(out)
    assert package["task_id"] == "code.feature"
    assert package["model_family"] in FAMILY_KEYS
    assert package["runtime"] == "claude"
    code, _, err = _run(["--root", str(repo), "resolve", "--task", "no.such"])
    assert code == 1 and "unknown task ID" in err


def test_main_and_child_boundaries_are_generic(tmp_path):
    policy = rp.load_policy(routing_repo(tmp_path))
    for runtime in RUNTIMES:
        constraint = policy["runtime_constraints"][runtime]
        main = rp.resolve_task(policy, "orchestrate.workflow", runtime)
        assert (main["role"], main["model_family"]) == ("main", constraint["main_family"])
        children = {
            profile["families"][runtime]
            for profile in policy["profiles"].values() if profile["role"] == "child"
        }
        assert children <= set(constraint["child_families"])
        assert constraint["main_family"] not in children
    reviewer = rp.resolve_task(policy, "decide.strategy", "codex", assignment="reviewer")
    assert reviewer["role"] == "child"
    assert reviewer["tool_profile"] == "review-readonly"
    try:
        rp.resolve_task(policy, "orchestrate.workflow", "codex", profile="S-REVIEW")
    except rp.PolicyError as exc:
        assert "main/child boundary" in str(exc)
    else:
        raise AssertionError("main/child boundary crossed")


def test_explicit_child_override_requires_a_recorded_user_instruction(tmp_path):
    repo = routing_repo(tmp_path, compile_manifest=False)
    source = _policy_text(repo)
    text = source.read_text(encoding="utf-8")
    needle = '"codex": {"main_profile":"S-MAIN","main_family":"strong-main","child_families":["fast","balanced","strong"],"explicit_child_overrides":[]}'
    assert needle in text
    source.write_text(text.replace(needle, needle.replace('"explicit_child_overrides":[]', '"explicit_child_overrides":["strong-main"]')), encoding="utf-8")
    policy = rp.load_policy(repo)
    request = {"model_family": "strong-main", "authorized_by": "user", "instruction": "Use the main family for this child."}
    selected = rp.resolve_task(policy, "code.debug", "codex", explicit_model_override=request)
    assert selected["model_family"] == "strong-main"
    assert selected["explicit_model_override"] == request
    for bad in (
        "strong-main",
        {"model_family": "strong-main", "authorized_by": "agent", "instruction": "high stakes"},
        {"model_family": "strong-main", "authorized_by": "user", "instruction": ""},
        {"model_family": "strong-main", "authorized_by": "user", "instruction": None},
        {"model_family": "strong-main", "authorized_by": "user", "instruction": ["x"]},
    ):
        try:
            rp.resolve_task(policy, "code.debug", "codex", explicit_model_override=bad)
        except rp.PolicyError:
            continue
        raise AssertionError(f"override accepted: {bad!r}")
    try:
        rp.resolve_task(policy, "orchestrate.workflow", "codex", explicit_model_override=request)
    except rp.PolicyError as exc:
        assert "fixed" in str(exc)
    else:
        raise AssertionError("main-session model was overridden")


def test_strictest_floor_wins_across_task_domain_and_stakes(tmp_path):
    policy = rp.load_policy(routing_repo(tmp_path))
    rank = lambda profile: rp.CAPABILITY_RANK[policy["profiles"][profile]["tier"]]  # noqa: E731
    numeric = rp.composite_floor(policy, "retrieve.local", numeric_deliverable=True)
    assert numeric["executor_profile"] == policy["floors"]["numeric_deliverable"]["executor"]
    assert numeric["reviewer_profile"] == policy["floors"]["numeric_deliverable"]["reviewer"]
    strong_numeric = rp.composite_floor(policy, "plan.work-packages", numeric_deliverable=True)
    assert rank(strong_numeric["executor_profile"]) >= rank(policy["tasks"]["plan.work-packages"]["executor"])
    assert strong_numeric["executor_profile"] == "S-ANALYZE"
    dense = rp.composite_floor(policy, "transform.summarize", dense_legal_financial=True)
    assert dense["executor_profile"] == policy["floors"]["dense_legal_financial"]["reader"]
    external = rp.composite_floor(policy, "connector.write-sync", external_write=True, bidirectional_conflict=True)
    assert external["planning_floor"] == "T2"
    assert external["reviewer_profile"] == policy["floors"]["external_write"]["conflict_reviewer"]
    stakes = rp.composite_floor(policy, "code.feature", high_stakes=True)
    assert stakes["planning_floor"] == "T3"
    assert stakes["executor_profile"] == policy["floors"]["high_stakes"]["builder"]
    assert stakes["reviewer_profile"] == policy["floors"]["high_stakes"]["reviewer"]
    assert stakes["reasons"] == ["task", "high_stakes"]
    stacked = rp.composite_floor(policy, "retrieve.local", numeric_deliverable=True, high_stakes=True, planning_floor="T1")
    assert stacked["planning_floor"] == "T3"
    assert rank(stacked["executor_profile"]) >= rank(numeric["executor_profile"])


def test_model_families_come_from_the_model_map_not_the_module(tmp_path):
    repo = routing_repo(tmp_path, compile_manifest=False)
    map_path = repo / "harness/adapters/claude/model-map.json"
    native = json.loads(map_path.read_text(encoding="utf-8"))
    for provider_id in native["families"].values():
        if isinstance(provider_id, str):
            assert provider_id not in Path(rp.__file__).read_text(encoding="utf-8")
    assert set(native["families"]) == set(FAMILY_KEYS)
    del native["families"]["strong"]
    map_path.write_text(json.dumps(native, indent=2), encoding="utf-8")
    try:
        rp.load_policy(repo)
    except rp.PolicyError as exc:
        assert "model-map.json" in str(exc) and "'strong'" in str(exc)
    else:
        raise AssertionError("policy validated against a model map lacking a family")
    source = Path(rp.__file__).read_text(encoding="utf-8")
    for family in FAMILY_KEYS:
        assert f'"{family}"' not in source, f"family literal {family!r} is hardcoded in routing_policy.py"


def test_a_runtime_without_a_model_map_is_skipped_by_family_validation(tmp_path):
    repo = routing_repo(tmp_path, compile_manifest=False)
    (repo / "harness/adapters/opencode/model-map.json").unlink()
    policy = rp.load_policy(repo)
    assert "opencode" in policy["runtime_constraints"]


install_bridge(globals(), "RoutingPolicyBridge")
