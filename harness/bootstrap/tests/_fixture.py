"""Build a small, complete repository under tmp_path for the bootstrap tests.

The fixture copies the real contract, adapter, and registry files from this
checkout, writes fake skills and hook wrappers, and optionally initializes a
git repository. It deliberately omits harness/tools so the engine's registry
preflight is skipped and the tests exercise materialization alone. Stdlib
only; every write stays under the tmp_path the test passed in.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = REAL_ROOT / "harness" / "bootstrap"
if str(BOOTSTRAP) not in sys.path:
    sys.path.insert(0, str(BOOTSTRAP))

DEFAULT_SKILLS = (("alpha", ["core"]), ("beta", ["maintain"]), ("gamma", ["decks"]))
ENGINE_FILES = (
    "materialize.py",
    "skill_catalog.py",
    "contract_files.py",
    "build_codex_adapter.py",
    "build_opencode_adapter.py",
    "schema_check.py",
    "doctor_common.py",
    "doctor_claude.py",
    "doctor_codex.py",
    "doctor_opencode.py",
    "validate_skills.py",
    "bootstrap.sh",
    "bootstrap.ps1",
    "doctor.sh",
    "doctor.ps1",
)
ADAPTER_FILES = (
    "harness/adapters/model_map.py",
    "harness/adapters/claude/settings.base.json",
    "harness/adapters/claude/schema.json",
    "harness/adapters/claude/model-map.json",
    "harness/adapters/codex/config.toml",
    "harness/adapters/codex/hooks.json",
    "harness/adapters/codex/schema.json",
    "harness/adapters/codex/compatibility.json",
    "harness/adapters/codex/model-map.json",
    "harness/adapters/codex/rules/default.rules",
    "harness/adapters/opencode/opencode.json",
    "harness/adapters/opencode/schema.json",
    "harness/adapters/opencode/compatibility.json",
    "harness/adapters/opencode/model-map.json",
    "harness/adapters/opencode/plugins/harness-bridge.js",
    "harness/adapters/opencode/lib/harness-bridge-internal.js",
)


def _copy(relative: str, root: Path) -> None:
    source = REAL_ROOT / relative
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # copyfile only copies data and drops the mode bits; .githooks/pre-commit
    # (and the bootstrap/*.sh engine files) are tracked 100755 in this repo,
    # and a fixture repository needs that bit to reach the doctor's
    # executable-bit check honestly. copy (unlike copyfile) also copies
    # permissions.
    shutil.copy(source, target)


def write_skill(root: Path, name: str, packs: list[str], status: str = "implemented") -> Path:
    directory = root / "harness" / "skills" / name
    directory.mkdir(parents=True, exist_ok=True)
    packs_text = "[" + ", ".join(packs) + "]"
    (directory / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Fixture skill {name}. WHEN: the user asks for {name}. WHEN NOT: anything else.\n"
        "metadata:\n"
        f"  packs: {packs_text}\n"
        "  triggers:\n"
        f'    - "{name} please"\n'
        "  distribution: native\n"
        f"  status: {status}\n"
        "  license: MIT\n"
        "  notice: null\n"
        "---\n\n"
        f"# {name}\n\nDo the {name} thing.\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / "notes.md").write_text(f"supporting file for {name}\n", encoding="utf-8", newline="\n")
    return directory


def write_selection(root: Path, packs: list[str], include: list[str] | None = None, exclude: list[str] | None = None) -> None:
    registry = root / "harness" / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    document = {"schema_version": 1, "packs": packs, "include": include or [], "exclude": exclude or []}
    (registry / "selection.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def _resolve_model_maps(root: Path) -> None:
    for runtime in ("claude", "codex", "opencode"):
        path = root / "harness" / "adapters" / runtime / "model-map.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["families"] = {family: f"fixture/{family}" for family in data["families"]}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def _write_capabilities(root: Path) -> None:
    document = {
        "schema_version": 1,
        "capabilities": {
            "user-file-delivery": {
                "kind": "runtime-tool",
                "runtimes": {"claude": "provided", "codex": "absent", "opencode": "absent"},
                "probe": {"type": "none", "value": None},
                "unready_behavior": "write the file to the repository and print its path",
            }
        },
    }
    path = root / "harness" / "registry" / "capabilities.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")


def _write_hook_wrappers(root: Path) -> None:
    hooks = root / "harness" / "hooks"
    (hooks / "lib").mkdir(parents=True, exist_ok=True)
    (hooks / "lib" / "hook_io.py").write_text("# fixture hook library\n", encoding="utf-8", newline="\n")
    registry = json.loads((REAL_ROOT / "harness" / "registry" / "runtimes.json").read_text(encoding="utf-8"))
    names = ["codex-dispatch"]
    for event in registry["hook_events"].values():
        names.extend(event["implementations"])
    for name in names:
        for suffix, body in (("sh", "#!/bin/sh\nexit 0\n"), ("ps1", "exit 0\n")):
            path = hooks / f"{name}.{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8", newline="\n")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def build_repo(
    tmp_path: Path,
    skills=DEFAULT_SKILLS,
    packs: list[str] | None = None,
    with_git: bool = True,
    with_skills_dir: bool = True,
    copy_engine: bool = True,
) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for relative in ("harness/CONTRACT.md", "harness/CONTRACT.host.md", "harness/bootstrap/junctions.json",
                     "harness/registry/runtimes.json", "harness/registry/structure.json",
                     ".githooks/pre-commit", ".githooks/secret-patterns.txt"):
        _copy(relative, root)
    for relative in ADAPTER_FILES:
        _copy(relative, root)
    for runtime in ("claude", "codex", "opencode"):
        agents = root / "harness" / "adapters" / runtime / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / ".gitkeep").write_text("", encoding="utf-8")
    rules = root / "harness" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "README.md").write_text("# rules\n", encoding="utf-8", newline="\n")
    _resolve_model_maps(root)
    _write_capabilities(root)
    _write_hook_wrappers(root)
    if copy_engine:
        for name in ENGINE_FILES:
            _copy("harness/bootstrap/" + name, root)
    if with_skills_dir:
        for name, skill_packs in skills:
            write_skill(root, name, skill_packs)
    write_selection(root, packs if packs is not None else ["core", "maintain"])
    if with_git:
        assert git(root, "init", "-q").returncode == 0
        git(root, "config", "user.email", "fixture@example.invalid")
        git(root, "config", "user.name", "fixture")
    return root


def bash_executable() -> str | None:
    """Return a bash that runs POSIX scripts (Git's bash on Windows, never the WSL launcher)."""
    if os.name == "nt":
        git_path = shutil.which("git")
        if git_path:
            base = Path(git_path).resolve().parent.parent
            for candidate in (base / "bin" / "bash.exe", base / "usr" / "bin" / "bash.exe"):
                if candidate.is_file():
                    return str(candidate)
        found = shutil.which("bash")
        if found and "system32" in found.lower():
            return None
        return found
    return shutil.which("bash")


def run_bootstrap_sh(root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    bash = bash_executable()
    assert bash, "no usable bash"
    script = (root / "harness" / "bootstrap" / "bootstrap.sh").as_posix()
    return subprocess.run(
        [bash, script, *flags],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def powershell_executable() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def run_bootstrap_ps1(root: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    shell = powershell_executable()
    assert shell, "no PowerShell"
    script = str(root / "harness" / "bootstrap" / "bootstrap.ps1")
    return subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, *flags],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def bind_unittest(namespace: dict, class_name: str) -> None:
    """Expose module-level test_ functions to ``python -m unittest discover``.

    Pytest collects the bare functions directly; under unittest they are bound
    as methods on a generated TestCase. A ``tmp_path`` parameter receives a
    fresh temporary directory. Skip markers set by ``unittest.skipIf`` on the
    plain function carry over to the bound method. No-op under pytest.
    """
    if "pytest" in sys.modules:
        return
    bridge = type(class_name, (unittest.TestCase,), {})

    def bind(name, function):
        def method(self):
            if "tmp_path" in inspect.signature(function).parameters:
                with tempfile.TemporaryDirectory() as tmp:
                    # macOS: TemporaryDirectory lands under /var, a symlink
                    # to /private/var. Resolve it so a path built from this
                    # root never trips a symlink-component refusal or a
                    # downstream identity check that expects a real path.
                    function(Path(tmp).resolve())
            else:
                function()

        method.__name__ = name
        for attribute in ("__unittest_skip__", "__unittest_skip_why__"):
            if hasattr(function, attribute):
                setattr(method, attribute, getattr(function, attribute))
        setattr(bridge, name, method)

    for name, function in list(namespace.items()):
        if name.startswith("test_") and callable(function):
            bind(name, function)
    namespace[class_name] = bridge
