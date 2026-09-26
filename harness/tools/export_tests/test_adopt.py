"""E17: adopt.py refusals, non-overwrite, dry-run default, detection."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _helpers import ROOT, TempDirCase, commit_all, git, init_repo, make_link, walk_files, write, load_tool  # noqa: E402

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
        assert isinstance(doc["host"]["harness_owned"], list)  # the seed target carries its own harness/ files
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


class TestUpgrade(TempDirCase):
    """E: adopt.py --upgrade refreshes an already-adopted host from a newer
    template. Both source and target are synthetic temporary git repos, not
    ROOT, so these tests stay fast and independent of this checkout's own
    adoption state."""

    def seed_source(self, name: str = "src") -> Path:
        source = init_repo(self.tmp / name)
        write(source / "harness" / "kernel-manifest.json", json.dumps({
            "version": "0.2.0",
            "files": [
                {"path": "harness/rules/a.md"},
                {"path": "harness/tools/b.sh"},
                {"path": "harness/new-file.md"},
                {"path": "harness/rules/host-only.md"},
                {"path": "harness/rules/same.md"},
            ],
        }, indent=2) + "\n")
        write(source / "harness" / "rules" / "a.md", "v1\n")
        write(source / "harness" / "tools" / "b.sh", "#!/bin/sh\necho new\n")
        write(source / "harness" / "new-file.md", "brand new content\n")
        write(source / "harness" / "rules" / "host-only.md", "source thinks this is template content\n")
        write(source / "harness" / "rules" / "same.md", "identical\n")
        commit_all(source, "seed source v0.2.0")
        return source

    def seed_target(self, name: str = "tgt") -> Path:
        target = init_repo(self.tmp / name)
        write(target / "harness" / "rules" / "a.md", "v0\n")
        write(target / "harness" / "rules" / "same.md", "identical\n")
        write(target / "harness" / "rules" / "host-only.md", "host's own version, never touched\n")
        write(target / "harness" / "tools" / "removed.md", "should stay even though source dropped it\n")
        write(target / "harness" / "CONTRACT.host.md", "host contract, never touched\n")
        write(target / "harness" / "registry" / "structure.json", json.dumps({
            "host": {"harness_owned": ["harness/rules/host-only.md"]},
        }, indent=2) + "\n")
        write(target / "harness" / "registry" / "adopted-files.json", json.dumps({
            "template_version": "0.1.0",
            "paths": [
                "harness/rules/a.md",
                "harness/rules/same.md",
                "harness/rules/host-only.md",
                "harness/tools/removed.md",
                "harness/CONTRACT.host.md",
                "harness/registry/structure.json",
            ],
        }, indent=2) + "\n")
        commit_all(target, "seed adopted host at 0.1.0")
        return target

    def test_refuses_non_adopted_target(self):
        target = init_repo(self.tmp / "plain")
        write(target / "README.md", "x\n")
        commit_all(target, "seed")
        source = self.seed_source()
        code, _, err = run(["--upgrade", str(target), "--source", str(source)])
        assert code == 2 and "not an adopted host" in err

    def test_refuses_dirty_target(self):
        target = self.seed_target("dirty-upgrade")
        write(target / "harness" / "rules" / "a.md", "locally edited\n")
        source = self.seed_source()
        code, _, err = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 2 and "uncommitted" in err
        assert (target / "harness" / "rules" / "a.md").read_text() == "locally edited\n"

    def test_refuses_incomplete_checkout(self):
        target = self.seed_target("incomplete")
        (target / "harness" / "rules" / "same.md").unlink()
        source = self.seed_source()
        code, _, err = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 2 and "missing from disk" in err

    def test_refuses_source_without_kernel_manifest(self):
        target = self.seed_target("nomanifest")
        source = init_repo(self.tmp / "src-nomanifest")
        write(source / "README.md", "x\n")
        commit_all(source, "seed")
        code, _, err = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 2 and "kernel-manifest.json" in err

    def test_dry_run_writes_nothing(self):
        target = self.seed_target("dry")
        source = self.seed_source()
        before = walk_files(target)
        code, out, _ = run(["--upgrade", str(target), "--source", str(source)])
        assert code == 0, out
        assert "update harness/rules/a.md" in out
        assert "new    harness/tools/b.sh" in out
        assert walk_files(target) == before
        assert git(target, "status", "--porcelain").stdout.strip() == ""
        assert json.loads((target / "harness" / "registry" / "adopted-files.json").read_text())["template_version"] == "0.1.0"

    def test_apply_updates_adds_and_leaves_host_owned_alone(self):
        target = self.seed_target("apply")
        source = self.seed_source()
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out

        # updated: template-owned, byte-differing file
        assert (target / "harness" / "rules" / "a.md").read_text() == "v1\n"
        # new: absent from target, present in the source manifest
        assert (target / "harness" / "tools" / "b.sh").read_text() == "#!/bin/sh\necho new\n"
        # host-owned fixed paths untouched even though recorded in adopted-files.json
        assert (target / "harness" / "CONTRACT.host.md").read_text() == "host contract, never touched\n"
        assert json.loads((target / "harness" / "registry" / "structure.json").read_text()) == {
            "host": {"harness_owned": ["harness/rules/host-only.md"]}
        }
        # host-owned via structure.json host.harness_owned: untouched
        assert (target / "harness" / "rules" / "host-only.md").read_text() == "host's own version, never touched\n"
        # gone: recorded in adopted-files.json, absent from source HEAD; kept, reported, never deleted
        assert (target / "harness" / "tools" / "removed.md").read_text() == "should stay even though source dropped it\n"
        assert "gone   harness/tools/removed.md" in out
        assert "recorded but absent from source HEAD" in out

        doc = json.loads((target / "harness" / "registry" / "adopted-files.json").read_text())
        assert doc["template_version"] == "0.2.0"
        assert "harness/tools/b.sh" in doc["paths"]
        assert "harness/rules/a.md" in doc["paths"]

    def test_apply_honors_skip(self):
        target = self.seed_target("skip")
        source = self.seed_source()
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source), "--skip", "harness/tools/b.sh"])
        assert code == 0, out
        assert not (target / "harness" / "tools" / "b.sh").exists()
        assert "skip   harness/tools/b.sh (--skip harness/tools/b.sh)" in out

    def test_content_comes_from_source_head_not_working_tree(self):
        target = self.seed_target("head-only")
        source = self.seed_source("head-source")
        write(source / "harness" / "rules" / "a.md", "uncommitted local edit, never adopted\n")
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert (target / "harness" / "rules" / "a.md").read_text() == "v1\n"

    def test_new_script_lands_executable(self):
        target = self.seed_target("execbit")
        source = self.seed_source()
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        result = git(target, "ls-files", "-s", "harness/tools/b.sh")
        assert result.stdout.strip(), "expected harness/tools/b.sh to be tracked"
        mode = result.stdout.split()[0]
        assert mode == "100755", f"expected 100755, got {mode}"

    def test_prints_source_sha_and_kernel_version(self):
        target = self.seed_target("shaprint")
        source = self.seed_source()
        sha = git(source, "rev-parse", "--short", "HEAD").stdout.strip()
        code, out, _ = run(["--upgrade", str(target), "--source", str(source)])
        assert code == 0, out
        assert f"source HEAD {sha}" in out
        assert "kernel version 0.2.0" in out

    # -- item 1: writes never follow a link out of the target ------------

    def _can_symlink(self) -> bool:
        probe_dir = self.tmp / "symlink-probe"
        probe_dir.mkdir(exist_ok=True)
        probe_target = probe_dir / "target.txt"
        write(probe_target, "x\n")
        probe_link = probe_dir / "link.txt"
        try:
            os.symlink("target.txt", str(probe_link))
        except (OSError, NotImplementedError):
            return False
        return True

    def _link_source(self, name: str, manifest_path: str, content: str) -> Path:
        source = init_repo(self.tmp / name)
        write(source / "harness" / "kernel-manifest.json", json.dumps({
            "version": "0.3.0",
            "files": [{"path": manifest_path}],
        }, indent=2) + "\n")
        write(source / manifest_path, content)
        commit_all(source, "seed source")
        return source

    def test_tracked_symlink_file_is_skipped_and_outside_target_untouched(self):
        if not self._can_symlink():
            self.skipTest("this OS/checkout cannot create symlinks")
        target = init_repo(self.tmp / "link-file-target")
        outside = self.tmp / "outside-file.md"
        write(outside, "outside content, must never change\n")
        write(target / "harness" / "registry" / "adopted-files.json", json.dumps({
            "template_version": "0.1.0", "paths": ["harness/link.md"],
        }, indent=2) + "\n")
        link_path = target / "harness" / "link.md"
        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(outside, link_path.parent), str(link_path))
        commit_all(target, "seed with a tracked symlink at a candidate path")

        source = self._link_source("link-file-source", "harness/link.md", "template content, must never land through the link\n")
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "link in path" in out
        assert outside.read_text() == "outside content, must never change\n"

    def test_dangling_symlink_is_skipped_and_creates_nothing(self):
        if not self._can_symlink():
            self.skipTest("this OS/checkout cannot create symlinks")
        target = init_repo(self.tmp / "link-dangling-target")
        write(target / "harness" / "registry" / "adopted-files.json", json.dumps({
            "template_version": "0.1.0", "paths": ["harness/dangling.md"],
        }, indent=2) + "\n")
        link_path = target / "harness" / "dangling.md"
        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink("does-not-exist.md", str(link_path))
        commit_all(target, "seed with a dangling tracked symlink")

        source = self._link_source("link-dangling-source", "harness/dangling.md", "template content\n")
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "link in path" in out
        assert not (target / "harness" / "does-not-exist.md").exists()
        assert not (link_path.parent / "does-not-exist.md").exists()

    def test_symlinked_parent_directory_is_skipped(self):
        if not self._can_symlink():
            self.skipTest("this OS/checkout cannot create symlinks")
        target = init_repo(self.tmp / "link-parent-target")
        outside_dir = self.tmp / "outside-dir"
        outside_dir.mkdir()
        write(outside_dir / "inside.md", "outside directory content, must never change\n")
        write(target / "harness" / "registry" / "adopted-files.json", json.dumps({
            "template_version": "0.1.0", "paths": ["harness/linkdir/inside.md"],
        }, indent=2) + "\n")
        linkdir_path = target / "harness" / "linkdir"
        linkdir_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(os.path.relpath(outside_dir, linkdir_path.parent), str(linkdir_path), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this OS/checkout cannot create directory symlinks")
        commit_all(target, "seed with a tracked symlinked parent directory")

        source = self._link_source("link-parent-source", "harness/linkdir/inside.md", "template content, must never land through the link\n")
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "link in path" in out
        assert (outside_dir / "inside.md").read_text() == "outside directory content, must never change\n"

    # -- item 2: only a strict POSIX-relative path is ever accepted -------

    def test_unsafe_manifest_path_is_skipped_never_probed_on_disk(self):
        target = self.seed_target("unsafe-manifest")
        source = init_repo(self.tmp / "unsafe-manifest-source")
        # The manifest lists a backslash-separated escape attempt. classify
        # rejects it on the path-safety check alone, before ever resolving
        # it against the target's filesystem or looking it up in the
        # source's tree, so no blob needs to exist at this literal path.
        write(source / "harness" / "kernel-manifest.json", json.dumps({
            "version": "0.3.0",
            "files": [{"path": "..\\..\\ESCAPED.md"}],
        }, indent=2) + "\n")
        commit_all(source, "seed source with an unsafe manifest path")

        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "unsafe path" in out
        assert "..\\..\\ESCAPED.md" in out

    def test_unsafe_adopted_paths_are_skipped(self):
        target = init_repo(self.tmp / "unsafe-adopted")
        write(target / "harness" / "registry" / "adopted-files.json", json.dumps({
            "template_version": "0.1.0",
            "paths": ["../x.md", "C:/abs.md"],
        }, indent=2) + "\n")
        commit_all(target, "seed adopted host with unsafe recorded paths")
        source = self.seed_source("unsafe-adopted-source")

        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "unsafe path" in out
        assert "../x.md" in out
        assert "C:/abs.md" in out
        assert not (self.tmp / "x.md").exists()  # never escaped upward from target

    # -- item 3: a recorded path missing from disk was removed on purpose -

    def test_recorded_path_missing_from_disk_is_never_recreated(self):
        target = init_repo(self.tmp / "removed-on-host")
        write(target / "harness" / "registry" / "adopted-files.json", json.dumps({
            "template_version": "0.1.0",
            "paths": ["harness/rules/deleted-by-host.md"],
        }, indent=2) + "\n")
        commit_all(target, "seed; harness/rules/deleted-by-host.md was recorded but is not on disk")
        source = init_repo(self.tmp / "removed-on-host-source")
        write(source / "harness" / "kernel-manifest.json", json.dumps({
            "version": "0.3.0",
            "files": [{"path": "harness/rules/deleted-by-host.md"}],
        }, indent=2) + "\n")
        write(source / "harness" / "rules" / "deleted-by-host.md", "template still ships this\n")
        commit_all(source, "seed source")

        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "removed on host" in out
        assert not (target / "harness" / "rules" / "deleted-by-host.md").exists()

    # -- item 4: every plain-adopt host-facing root file is host-owned ----

    def test_root_files_are_host_owned_and_never_touched(self):
        target = init_repo(self.tmp / "root-owned")
        write(target / "README.md", "host's own readme, never touched\n")
        write(target / "LICENSE", "host's own license, never touched\n")
        write(target / "harness" / "registry" / "adopted-files.json", json.dumps({
            "template_version": "0.1.0",
            "paths": ["README.md", "LICENSE"],
        }, indent=2) + "\n")
        commit_all(target, "seed adopted host")
        source = init_repo(self.tmp / "root-owned-source")
        write(source / "harness" / "kernel-manifest.json", json.dumps({
            "version": "0.3.0",
            "files": [{"path": "README.md"}, {"path": "LICENSE"}],
        }, indent=2) + "\n")
        write(source / "README.md", "template readme, must never land\n")
        write(source / "LICENSE", "template license, must never land\n")
        commit_all(source, "seed source")

        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert (target / "README.md").read_text() == "host's own readme, never touched\n"
        assert (target / "LICENSE").read_text() == "host's own license, never touched\n"
        assert "host-owned" in out

    # -- item 5: source/target identity refusals --------------------------

    def test_refuses_when_source_and_target_are_the_same_directory(self):
        target = self.seed_target("same-dir")
        code, _, err = run(["--upgrade", str(target), "--source", str(target)])
        assert code == 2 and "same directory" in err

    def test_refuses_when_source_is_itself_an_adopted_host(self):
        target = self.seed_target("adopted-target")
        source = self.seed_target("adopted-source")  # also carries adopted-files.json
        code, _, err = run(["--upgrade", str(target), "--source", str(source)])
        assert code == 2 and "it is a host, not the template" in err

    # -- item 6: an on-disk file the target's git does not track ----------

    def test_untracked_file_at_a_candidate_path_is_skipped(self):
        target = self.seed_target("untracked-candidate")
        write(target / ".gitignore", "harness/tools/b.sh\n")
        commit_all(target, "add a gitignore rule before the stray file exists")
        write(target / "harness" / "tools" / "b.sh", "#!/bin/sh\necho pre-existing stray file\n")
        # b.sh is now on disk but git-ignored: git status stays clean even
        # with --untracked-files=all, so the target-refusal check does not
        # itself catch it; only the classify-time tracked check should.
        source = self.seed_source()
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "untracked on host" in out
        assert (target / "harness" / "tools" / "b.sh").read_text() == "#!/bin/sh\necho pre-existing stray file\n"

    # -- item 7: manifest-new candidates stay inside plain adopt's scope --

    def test_manifest_new_outside_plain_adopt_scope_is_never_created(self):
        target = self.seed_target("scope-limited")
        source = self.seed_source("scope-limited-source")
        write(source / "brain" / "shared" / "extra.md", "plain adopt never installs brain/ files\n")
        manifest = json.loads((source / "harness" / "kernel-manifest.json").read_text())
        manifest["files"].append({"path": "brain/shared/extra.md"})
        write(source / "harness" / "kernel-manifest.json", json.dumps(manifest, indent=2) + "\n")
        commit_all(source, "add an out-of-scope manifest path")

        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert not (target / "brain").exists()
        assert "brain/shared/extra.md" not in out

    # -- item 11: CRLF alone is not a real difference ----------------------

    def test_crlf_only_difference_classifies_as_same(self):
        target = self.seed_target("crlf-same")
        write(target / "harness" / "rules" / "a.md", "v1\r\n")  # CRLF, same content as the source's LF "v1\n"
        commit_all(target, "host checked this file out with CRLF line endings")
        source = self.seed_source()
        code, out, _ = run(["--upgrade", str(target), "--source", str(source)])
        assert code == 0, out
        assert "update harness/rules/a.md" not in out
        assert (target / "harness" / "rules" / "a.md").read_bytes() == b"v1\r\n"  # untouched (dry run)

    def test_update_writes_source_bytes_unchanged_even_with_crlf_present(self):
        target = self.seed_target("crlf-update")
        write(target / "harness" / "rules" / "a.md", "v0\r\n")  # CRLF, genuinely different content
        commit_all(target, "host checked this file out with CRLF line endings")
        source = self.seed_source()
        code, out, _ = run(["--upgrade", str(target), "-y", "--source", str(source)])
        assert code == 0, out
        assert "update harness/rules/a.md" in out
        # written byte-exact from the source blob, not CRLF-preserved
        assert (target / "harness" / "rules" / "a.md").read_bytes() == b"v1\n"


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
