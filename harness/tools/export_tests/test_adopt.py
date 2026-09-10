"""E17: adopt.py refusals, non-overwrite, dry-run default, detection."""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import ROOT, TempDirCase, commit_all, git, init_repo, walk_files, write, load_tool  # noqa: E402

adopt = load_tool("adopt")


def _host_adopted() -> bool:
    """True when ROOT (the checkout these tests adopt from as source) is
    itself an adopted host, not a pristine template."""
    try:
        data = json.loads((ROOT / "harness" / "registry" / "structure.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return bool(isinstance(data, dict) and (data.get("host") or {}).get("adopted"))


def run(args: list) -> tuple:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = adopt.main(args)
    return code, out.getvalue(), err.getvalue()


class TestDeriveHostName(TempDirCase):
    def test_https_origin_uses_repo_basename(self):
        target = init_repo(self.tmp / "checkout")
        write(target / "README.md", "x\n")
        commit_all(target, "seed")
        assert git(target, "remote", "add", "origin", "https://github.com/org/ilmu.git").returncode == 0
        name, source = adopt.derive_host_name(target)
        assert name == "ilmu"
        assert "origin remote" in source

    def test_ssh_origin_uses_repo_basename(self):
        target = init_repo(self.tmp / "checkout2")
        write(target / "README.md", "x\n")
        commit_all(target, "seed")
        assert git(target, "remote", "add", "origin", "git@example.com:org/ilmu.git").returncode == 0
        name, source = adopt.derive_host_name(target)
        assert name == "ilmu"
        assert "origin remote" in source

    def test_no_origin_falls_back_to_folder_name(self):
        target = init_repo(self.tmp / "ilmu-adopt-final")
        write(target / "README.md", "x\n")
        commit_all(target, "seed")
        name, source = adopt.derive_host_name(target)
        assert name == "ilmu-adopt-final"
        assert "folder name" in source

    def test_odd_characters_are_sanitized(self):
        target = init_repo(self.tmp / "checkout3")
        write(target / "README.md", "x\n")
        commit_all(target, "seed")
        assert git(target, "remote", "add", "origin", "https://github.com/org/il mu!@#.git").returncode == 0
        name, source = adopt.derive_host_name(target)
        assert re.fullmatch(r"[A-Za-z0-9._-]+", name), name
        assert "origin remote" in source


class TestRefusals(TempDirCase):
    def test_non_git_target(self):
        target = self.tmp / "plain"
        write(target / "README.md", "x\n")
        code, _, err = run([str(target)])
        assert code == 2 and "not a git repository" in err
        assert walk_files(target) == ["README.md"]

    def test_dirty_target(self):
        target = init_repo(self.tmp / "dirty")
        write(target / "README.md", "x\n")
        commit_all(target, "init")
        write(target / "new.txt", "untracked\n")
        code, _, err = run([str(target), "-y"])
        assert code == 2 and "uncommitted" in err
        assert not (target / "harness").exists()

    def test_itself(self):
        code, _, err = run([str(ROOT)])
        assert code == 2 and "source" in err


class TestApply(TempDirCase):
    def seed_target(self, name: str, codeowners: bool = False) -> Path:
        target = init_repo(self.tmp / name)
        write(target / "README.md", "host readme\n")
        write(target / "harness" / "rules" / "git-workflow.md", "host rule\n")
        write(target / "docs" / "decisions" / "0001.md", "decision\n")
        if codeowners:
            write(target / "CODEOWNERS", "* @owner\n")
        commit_all(target, "seed")
        return target

    def test_default_is_dry_run(self):
        target = self.seed_target("dry")
        before = walk_files(target)
        code, out, _ = run([str(target)])
        assert code == 0
        assert "dry run" in out and "nothing written" in out
        assert "post-adoption checklist:" in out
        assert "host profile: team (adopted default)" in out
        assert walk_files(target) == before
        assert git(target, "status", "--porcelain").stdout.strip() == ""

    def test_checklist_names_the_solo_switch_command(self):
        target = self.seed_target("switch")
        code, out, _ = run([str(target)])
        assert code == 0, out
        assert "python harness/tools/init.py --profile solo --yes" in out

    def test_apply_never_overwrites_and_detects_shape(self):
        target = self.seed_target("apply", codeowners=True)
        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        assert (target / "README.md").read_text() == "host readme\n"
        assert (target / "README.harness.md").read_bytes() == (ROOT / "README.md").read_bytes()
        assert (target / "harness" / "rules" / "git-workflow.md").read_text() == "host rule\n"
        assert (target / "harness" / "rules" / "git-workflow.harness.md").read_bytes() == (ROOT / "harness" / "rules" / "git-workflow.md").read_bytes()
        assert "reserved-name merge" in out
        assert (target / "harness" / "tools" / "adopt.py").is_file()
        assert (target / "harness" / "kernel-manifest.json").is_file()
        assert not (target / "harness" / "registry" / "selection.local.json").exists()
        doc = json.loads((target / "harness" / "registry" / "structure.json").read_text())
        assert doc["git"] == {"mode": "branches"}
        assert doc["lanes"] == {"identity": None, "knowledge": None, "decisions": ["docs/decisions"], "records": None, "docs": ["docs"]}
        assert doc["brain"]["local_tracked"] is False
        assert doc["host"]["profile"] == "team"
        assert doc["host"]["verify_command"] is None
        assert "host profile: team (adopted default)" in out
        registry = adopt._registry_module()
        if registry is not None:
            assert registry.validate_structure(doc) == []
        lines = [line for line in out.splitlines() if line.strip().startswith(tuple(f"{n}." for n in range(1, 12)))]
        assert lines[-2].strip().startswith(tuple(f"{n}. Bootstrap:" for n in range(1, 12)))
        assert lines[-1].strip().startswith(tuple(f"{n}. Doctor:" for n in range(1, 12)))
        assert "doctor_opencode.py --offline" in lines[-1]

    def test_main_only_without_remote_branches(self):
        target = init_repo(self.tmp / "solo")
        write(target / "docs" / "index.md", "x\n")
        commit_all(target, "seed")
        structure, reason, _ = adopt.build_structure(target)
        assert structure["git"]["mode"] == "main-only", reason
        assert structure["lanes"]["docs"] == ["docs"] and structure["lanes"]["decisions"] is None
        assert structure["host"]["profile"] == "team"
        assert structure["host"]["verify_command"] is None

    def test_apply_writes_team_profile_on_main_only_target(self):
        target = init_repo(self.tmp / "main-only-apply")
        write(target / "docs" / "index.md", "x\n")
        commit_all(target, "seed")
        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        doc = json.loads((target / "harness" / "registry" / "structure.json").read_text())
        assert doc["git"] == {"mode": "main-only"}
        assert doc["host"]["profile"] == "team"
        assert doc["host"]["verify_command"] is None
        assert "host profile: team (adopted default)" in out

    def test_d1_pre_existing_agents_md_sets_contract_host_owned(self):
        target = init_repo(self.tmp / "hostowned")
        write(target / "README.md", "host readme\n")
        write(target / "AGENTS.md", "the host's own agent contract\n")
        write(target / "harness" / "rules" / "git-workflow.md", "host rule\n")
        write(target / "courses" / "algebra.md", "host content\n")
        commit_all(target, "seed")

        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        assert "contract: host-owned" in out
        assert (target / "AGENTS.md").read_text() == "the host's own agent contract\n"
        assert (target / "AGENTS.harness.md").read_bytes() == (ROOT / "AGENTS.md").read_bytes()

        doc = json.loads((target / "harness" / "registry" / "structure.json").read_text())
        assert doc["contract"] == {"mode": "host-owned"}
        assert doc["host"]["adopted"] is True
        assert "courses" in doc["host"]["roots"]
        assert "harness" not in doc["host"]["roots"]
        assert "harness/rules/git-workflow.md" in doc["host"]["harness_owned"]
        assert doc["host"]["profile"] == "team"
        assert doc["host"]["verify_command"] is None
        registry = adopt._registry_module()
        if registry is not None:
            assert registry.validate_structure(doc) == []

    def test_d2_harness_owned_records_host_only_paths_with_no_template_counterpart(self):
        target = init_repo(self.tmp / "hostharness")
        write(target / "README.md", "host readme\n")
        write(target / "AGENTS.md", "the host's own agent contract\n")
        write(target / "harness" / "README.md", "the host's own harness readme\n")
        write(target / "harness" / "scripts" / "validate.mjs", "// host validator\n")
        commit_all(target, "seed")

        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        doc = json.loads((target / "harness" / "registry" / "structure.json").read_text())
        assert "harness/README.md" in doc["host"]["harness_owned"]
        assert "harness/scripts/validate.mjs" in doc["host"]["harness_owned"]
        # Neither file collided with a template path, so adopt never touches them.
        assert (target / "harness" / "README.md").read_text() == "the host's own harness readme\n"
        assert (target / "harness" / "scripts" / "validate.mjs").read_text() == "// host validator\n"

    def test_d1_no_pre_existing_agents_md_stays_rendered(self):
        target = self.seed_target("rendered")
        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        assert "contract: rendered" in out
        doc = json.loads((target / "harness" / "registry" / "structure.json").read_text())
        assert doc["contract"] == {"mode": "rendered"}
        # Every adoption is adopted (0.1.2): the flag scopes the lint to the template's files;
        # contract.mode alone records that the target had no AGENTS.md.
        assert doc["host"]["adopted"] is True
        assert doc["host"]["harness_owned"] == []
        assert isinstance(doc["host"]["roots"], list) and "harness" not in doc["host"]["roots"]
        assert doc["host"]["profile"] == "team"
        assert doc["host"]["verify_command"] is None

    def test_branches_with_two_remote_branches(self):
        remote = self.tmp / "remote.git"
        remote.mkdir()
        assert git(remote, "init", "-q", "--bare", "-b", "main").returncode == 0
        target = init_repo(self.tmp / "team")
        write(target / "decisions" / "0001.md", "x\n")
        commit_all(target, "seed")
        assert git(target, "remote", "add", "origin", str(remote)).returncode == 0
        assert git(target, "push", "-q", "origin", "main").returncode == 0
        assert git(target, "branch", "feature").returncode == 0
        assert git(target, "push", "-q", "origin", "feature").returncode == 0
        assert git(target, "fetch", "-q", "origin").returncode == 0
        structure, reason, note = adopt.build_structure(target)
        assert structure["git"]["mode"] == "branches", reason
        assert "remote branches" in reason
        assert structure["lanes"]["decisions"] == ["decisions"]
        assert "brain.local_path" in note
        assert structure["host"]["profile"] == "team"
        assert structure["host"]["verify_command"] is None

    def test_adopted_files_dry_run_prints_count_and_writes_nothing(self):
        target = self.seed_target("adopted-dry")
        code, out, _ = run([str(target)])
        assert code == 0, out
        assert not (target / "harness" / "registry" / "adopted-files.json").exists()
        match = re.search(r"adopted-files\.json: (\d+) path\(s\) would be recorded", out)
        assert match and int(match.group(1)) > 0, out

    @unittest.skipIf(_host_adopted(), "adopts ROOT as the source template; not valid when ROOT is itself an adopted host")
    def test_adopted_files_written_on_apply(self):
        target = self.seed_target("adopted-apply")
        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        path = target / "harness" / "registry" / "adopted-files.json"
        assert path.is_file()
        raw = path.read_bytes()
        assert raw.endswith(b"\n") and b"\r" not in raw
        doc = json.loads(raw)
        assert doc["template_version"], doc
        assert doc["paths"] == sorted(doc["paths"]) and len(doc["paths"]) == len(set(doc["paths"]))
        assert "harness/registry/structure.json" in doc["paths"]
        # git-workflow.md pre-exists in the target (seed_target), so it lands
        # as a .harness sibling rather than at its own path.
        assert "harness/rules/git-workflow.harness.md" in doc["paths"]
        assert "harness/registry/adopted-files.json written" in out

    def test_adopted_files_merges_a_pre_existing_registry(self):
        target = self.seed_target("adopted-merge")
        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        path = target / "harness" / "registry" / "adopted-files.json"
        original = json.loads(path.read_text())
        # Seed a path an earlier adoption recorded that this run's plan does
        # not touch, to prove a second write unions rather than overwrites.
        seeded = sorted(set(original["paths"]) | {"docs/old-adoption-only.md"})
        path.write_text(json.dumps({"template_version": original["template_version"], "paths": seeded}, indent=2) + "\n", encoding="utf-8", newline="\n")
        merged, total, added = adopt.write_adopted_files(target, original["paths"], original["template_version"])
        assert merged is True
        assert added == 0  # every one of this run's paths was already recorded
        doc = json.loads(path.read_text())
        assert "docs/old-adoption-only.md" in doc["paths"]
        assert set(original["paths"]) <= set(doc["paths"])
        assert total == len(doc["paths"])


class TestExecutableBit(TempDirCase):
    """The Windows adoption defect: core.filemode is false there, so a
    commit made on Windows records no executable bit for the landed
    harness/*.sh scripts and .githooks/pre-commit, and the template's own
    lint L18 then fails on the adopter's POSIX CI. adopt stages the bit in
    the index itself so the adopter's own commit carries it forward on
    every platform."""

    def seed_target(self, name: str) -> Path:
        target = init_repo(self.tmp / name)
        write(target / "README.md", "host readme\n")
        commit_all(target, "seed")
        return target

    def _modes(self, target: Path) -> dict:
        result = git(target, "ls-files", "-s")
        modes = {}
        for line in result.stdout.splitlines():
            if "\t" not in line:
                continue
            meta, path = line.split("\t", 1)
            parts = meta.split()
            if parts:
                modes[path] = parts[0]
        return modes

    def test_apply_stages_100755_for_scripts_and_hook(self):
        target = self.seed_target("execbit")
        code, out, _ = run([str(target), "-y"])
        assert code == 0, out
        modes = self._modes(target)
        scripts = [p for p in modes if (p.startswith("harness/") and p.endswith(".sh")) or p == ".githooks/pre-commit"]
        assert scripts, "expected at least one landed script in scope"
        for path in scripts:
            assert modes[path] == "100755", f"{path} is {modes[path]}, expected 100755"
        assert "staged" in out and "executable bit" in out

    def test_dry_run_stages_nothing(self):
        target = self.seed_target("execbit-dry")
        code, out, _ = run([str(target)])
        assert code == 0, out
        assert git(target, "status", "--porcelain").stdout.strip() == ""
        assert not (target / "harness").exists()
        assert "would stage" in out and "executable bit" in out

    def test_target_without_git_warns_and_does_not_crash(self):
        target = self.seed_target("execbit-nogit")
        actions = adopt.plan_actions(ROOT, target)
        paths = adopt.landed_script_paths(actions)
        assert paths, "expected at least one script path in the plan"
        original_which = adopt.shutil.which
        adopt.shutil.which = lambda name: None
        try:
            staged, warning = adopt.set_executable_bits(target, paths)
        finally:
            adopt.shutil.which = original_which
        assert staged == []
        assert warning is not None
        assert "git update-index --add --chmod=+x --" in warning

    def test_no_paths_is_a_no_op(self):
        target = self.seed_target("execbit-empty")
        staged, warning = adopt.set_executable_bits(target, [])
        assert staged == [] and warning is None
