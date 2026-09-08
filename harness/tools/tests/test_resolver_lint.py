"""resolver_lint: table parsing, row validation, and the standalone CLI."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

from ._repo import install_bridge  # noqa: F401

import resolver_lint as rl


class _Skill:
    def __init__(self, name: str, status: str = "implemented"):
        self.name = name
        self.status = status


def _skills(*items: str) -> dict[str, _Skill]:
    return {item.split(":")[0]: _Skill(item.split(":")[0], item.split(":")[1] if ":" in item else "implemented") for item in items}


def resolver(rows: str) -> str:
    return (
        "# Skill resolver\n\n"
        "| Intent phrase | Target skill | Neighbor | Pack | Status |\n"
        "|---|---|---|---|---|\n"
        f"{rows}\n"
    )


def test_split_markdown_row_preserves_escaped_pipes():
    cells = rl.split_markdown_row("| `/notion [read\\|pull\\|sync]` | notion |")
    assert cells == ["`/notion [read|pull|sync]`", "notion"]


def test_rows_parse_target_neighbor_pack_and_status():
    routes = rl.parse_routes(resolver('| "run alpha" | `alpha` | `beta` | core | spec-only |'))
    assert len(routes) == 1
    route = routes[0]
    assert (route.target, route.neighbor, route.pack, route.status) == ("alpha", "beta", "core", "spec-only")
    assert rl.parse_routes(resolver('| "x" | `alpha` | none | core | stub |'))[0].neighbor == "none"


def test_unknown_target_is_an_error():
    errors, _ = rl.validate_resolver(resolver('| "go" | `ghost` | none | core | spec-only |'), _skills("live"))
    assert any("unknown skill target 'ghost'" in error for error in errors)


def test_unknown_neighbor_is_an_error_and_none_is_accepted():
    skills = _skills("live")
    errors, _ = rl.validate_resolver(resolver('| "go" | `live` | `ghost` | core | spec-only |'), skills)
    assert any("unknown neighbor skill 'ghost'" in error for error in errors)
    errors, _ = rl.validate_resolver(resolver('| "go" | `live` | none | core | spec-only |'), skills)
    assert errors == []


def test_duplicate_intent_phrase_is_an_error():
    text = resolver('| "same" | `first` | none | core | spec-only |\n| "Same" | `second` | none | core | spec-only |')
    errors, _ = rl.validate_resolver(text, _skills("first", "second"))
    assert any("duplicate intent phrase" in error for error in errors)


def test_stub_target_is_a_warning_not_an_error():
    errors, warns = rl.validate_resolver(resolver('| "go" | `stubby` | none | core | stub |'), _skills("stubby:stub"))
    assert errors == []
    assert any("routes to stub skill 'stubby'" in warning for warning in warns)


def _write_skill(repo: Path, name: str, status: str = "spec-only", pack: str = "core") -> None:
    path = repo / "harness" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Does {name}. WHEN: asked for {name}.\n"
        "metadata:\n"
        f"  packs: [{pack}]\n"
        f'  triggers: ["run {name}"]\n'
        "  distribution: native\n"
        f"  status: {status}\n"
        "  license: MIT\n"
        "---\n",
        encoding="utf-8",
    )


def _cli(repo: Path) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = rl.main(["--root", str(repo)])
    return code, out.getvalue()


def test_cli_exit_codes(tmp_path):
    repo = tmp_path / "repo"
    (repo / "harness" / "skills").mkdir(parents=True)
    _write_skill(repo, "alpha")
    _write_skill(repo, "held", status="stub")
    target = repo / rl.RESOLVER
    target.write_text(resolver('| "run alpha" | `alpha` | none | core | spec-only |'), encoding="utf-8")
    code, out = _cli(repo)
    assert code == 0 and "0 error(s)" in out
    target.write_text(resolver('| "run held" | `held` | none | core | stub |'), encoding="utf-8")
    code, out = _cli(repo)
    assert code == 0 and "WARN" in out and "stub" in out
    target.write_text(resolver('| "run ghost" | `ghost` | none | core | spec-only |'), encoding="utf-8")
    code, out = _cli(repo)
    assert code == 1 and "unknown skill target 'ghost'" in out
    target.unlink()
    code, out = _cli(repo)
    assert code == 1 and "missing" in out


def test_targets_outside_the_selection_are_notes_not_errors(tmp_path):
    import json

    repo = tmp_path / "repo"
    (repo / "harness" / "skills").mkdir(parents=True)
    (repo / "harness" / "registry").mkdir(parents=True)
    _write_skill(repo, "alpha")
    _write_skill(repo, "beta", pack="extra")
    _write_skill(repo, "gamma", pack="extra")
    (repo / rl.SELECTION).write_text(
        json.dumps({"schema_version": 1, "packs": ["core"], "include": [], "exclude": []}), encoding="utf-8"
    )
    (repo / rl.RESOLVER).write_text(
        resolver(
            '| "run alpha" | `alpha` | none | core | spec-only |\n'
            '| "run beta" | `beta` | `alpha` | extra | spec-only |\n'
            '| "beta please" | `beta` | `alpha` | extra | spec-only |\n'
            '| "run gamma" | `gamma` | `beta` | extra | spec-only |'
        ),
        encoding="utf-8",
    )
    errors, warns = rl.lint(repo)
    assert errors == [] and warns == []
    found = rl.notes(repo)
    assert len(found) == 2, found
    assert "2 row(s) target 'beta'" in found[0] and "neighbor 'alpha' is selected" in found[0]
    assert "1 row(s) target 'gamma'" in found[1] and "neighbor 'beta' is also outside the selection" in found[1]
    code, out = _cli(repo)
    assert code == 0 and out.count("NOTE") == 2 and "0 error(s)" in out
    (repo / rl.SELECTION).unlink()
    assert rl.notes(repo) == []


install_bridge(globals(), "ResolverLintBridge")
