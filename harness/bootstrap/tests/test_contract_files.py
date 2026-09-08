"""Contract composition (B7)."""

from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fixture import BOOTSTRAP, bind_unittest

sys.path.insert(0, str(BOOTSTRAP))
import contract_files  # noqa: E402


def _seed(root: Path, template: bytes, host: bytes) -> None:
    (root / "harness").mkdir(parents=True, exist_ok=True)
    (root / "harness" / "CONTRACT.md").write_bytes(template)
    (root / "harness" / "CONTRACT.host.md").write_bytes(host)


def _seed_host_owned(root: Path, template: bytes, host: bytes) -> None:
    _seed(root, template, host)
    registry = root / "harness" / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "structure.json").write_text(
        json.dumps({"contract": {"mode": "host-owned"}}), encoding="utf-8"
    )


def test_b7_render_is_template_blank_line_host_normalized_to_lf(tmp_path):
    _seed(tmp_path, b"\xef\xbb\xbf# Contract\r\nline\r\n", b"# Host\r\nnotes")
    assert contract_files.render(tmp_path) == b"# Contract\nline\n\n# Host\nnotes\n"


def test_b7_repair_writes_agents_and_pointer_and_removes_retired_copies(tmp_path):
    _seed(tmp_path, b"# Contract\n", b"# Host\n")
    for retired in (".codex/AGENTS.md", ".claude/CLAUDE.md"):
        path = tmp_path / retired
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"stale copy\n")

    changed = contract_files.repair_contract(tmp_path)

    assert (tmp_path / "AGENTS.md").read_bytes() == b"# Contract\n\n# Host\n"
    assert (tmp_path / "CLAUDE.md").read_bytes() == b"@AGENTS.md\n"
    assert not (tmp_path / ".codex" / "AGENTS.md").exists()
    assert not (tmp_path / ".claude" / "CLAUDE.md").exists()
    assert "AGENTS.md" in changed and "CLAUDE.md" in changed
    assert ".codex/AGENTS.md (removed)" in changed
    assert contract_files.check_contract(tmp_path) == []
    assert contract_files.repair_contract(tmp_path) == []


def test_b7_check_exits_1_after_a_mutation_and_prints_the_byte_offset(tmp_path):
    _seed(tmp_path, b"# Contract\n", b"# Host\n")
    contract_files.repair_contract(tmp_path)
    assert contract_files.main(["check", "--root", str(tmp_path)]) == 0
    agents = tmp_path / "AGENTS.md"
    agents.write_bytes(b"# Contract\n\n# Hoax\n")
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = contract_files.main(["check", "--root", str(tmp_path)])
    assert code == 1
    assert "first difference at byte offset 16" in stream.getvalue()


def test_b7_pointer_drift_and_retired_copy_are_reported(tmp_path):
    _seed(tmp_path, b"# Contract\n", b"# Host\n")
    contract_files.repair_contract(tmp_path)
    (tmp_path / "CLAUDE.md").write_bytes(b"@AGENTS.md\n\n")
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "AGENTS.md").write_bytes(b"x")
    issues = contract_files.check_contract(tmp_path)
    assert any("CLAUDE.md must contain exactly" in issue for issue in issues)
    assert any(".codex/AGENTS.md exists" in issue for issue in issues)


def test_b7_hardlinked_output_is_reported_and_repaired(tmp_path):
    _seed(tmp_path, b"# Contract\n", b"")
    contract_files.repair_contract(tmp_path)
    agents = tmp_path / "AGENTS.md"
    template = tmp_path / "harness" / "CONTRACT.md"
    template.write_bytes(agents.read_bytes())
    agents.unlink()
    try:
        os.link(template, agents)
    except OSError:
        return
    assert any("hardlink" in issue for issue in contract_files.check_contract(tmp_path))
    contract_files.repair_contract(tmp_path)
    assert not os.path.samefile(template, agents)
    assert contract_files.check_contract(tmp_path) == []


def test_b7_render_subcommand_prints_the_bytes(tmp_path):
    _seed(tmp_path, b"# Contract\n", b"# Host\n")
    import subprocess

    completed = subprocess.run(
        [sys.executable, "-B", str(BOOTSTRAP / "contract_files.py"), "render", "--root", str(tmp_path)],
        capture_output=True, check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.replace(b"\r\n", b"\n") == b"# Contract\n\n# Host\n"


def test_d1_rendered_mode_is_unchanged_by_default(tmp_path):
    _seed(tmp_path, b"# Contract\n", b"# Host\n")
    assert contract_files.contract_mode(tmp_path) == "rendered"
    changed = contract_files.repair_contract(tmp_path)
    assert (tmp_path / "AGENTS.md").read_bytes() == b"# Contract\n\n# Host\n"
    assert not (tmp_path / "AGENTS.harness.md").exists()
    assert "AGENTS.md" in changed
    assert contract_files.check_contract(tmp_path) == []


def test_d1_host_owned_mode_never_writes_agents_md_and_renders_the_sibling(tmp_path):
    _seed_host_owned(tmp_path, b"# Contract\n", b"# Host\n")
    (tmp_path / "AGENTS.md").write_bytes(b"host's own contract\nsee AGENTS.harness.md\n")
    before = (tmp_path / "AGENTS.md").read_bytes()

    changed = contract_files.repair_contract(tmp_path)

    assert (tmp_path / "AGENTS.md").read_bytes() == before
    assert (tmp_path / "AGENTS.harness.md").read_bytes() == b"# Contract\n\n# Host\n"
    assert "AGENTS.harness.md" in changed
    assert "AGENTS.md" not in changed
    assert contract_files.check_contract(tmp_path) == []
    assert contract_files.contract_advisory(tmp_path) is None


def test_d1_host_owned_agents_md_byte_identical_across_bootstrap(tmp_path):
    _seed_host_owned(tmp_path, b"# Contract\n", b"# Host\n")
    host_bytes = b"the host's authored contract, never touched\n"
    (tmp_path / "AGENTS.md").write_bytes(host_bytes)
    contract_files.repair_contract(tmp_path)
    contract_files.repair_contract(tmp_path)
    assert (tmp_path / "AGENTS.md").read_bytes() == host_bytes
    assert contract_files.check_contract(tmp_path) == []


def test_d1_host_owned_check_reports_ok_not_drift_or_fail(tmp_path):
    _seed_host_owned(tmp_path, b"# Contract\n", b"# Host\n")
    (tmp_path / "AGENTS.md").write_bytes(b"host contract; see AGENTS.harness.md\n")
    contract_files.repair_contract(tmp_path)
    stream = io.StringIO()
    with redirect_stdout(stream):
        code = contract_files.main(["check", "--root", str(tmp_path)])
    assert code == 0
    assert "host-owned" in stream.getvalue()
    assert "ADVISORY" not in stream.getvalue()


def test_d1_advisory_fires_when_host_agents_md_does_not_reference_the_sibling_and_clears_after(tmp_path):
    _seed_host_owned(tmp_path, b"# Contract\n", b"# Host\n")
    (tmp_path / "AGENTS.md").write_bytes(b"just the host's own text, no reference\n")
    contract_files.repair_contract(tmp_path)
    advisory = contract_files.contract_advisory(tmp_path)
    assert advisory is not None and "AGENTS.harness.md" in advisory

    (tmp_path / "AGENTS.md").write_bytes(b"the host's own text; see AGENTS.harness.md for the harness block\n")
    assert contract_files.contract_advisory(tmp_path) is None


bind_unittest(globals(), "ContractFilesBridge")
