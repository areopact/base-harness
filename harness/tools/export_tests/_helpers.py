"""Shared helpers for the P4b tool tests.

Plain unittest.TestCase classes with bare asserts, so the suite runs under
both pytest and `python -m unittest discover -s harness/tools/export_tests`.
Tool modules are loaded from their file paths under private names so the
stdlib `select` module is never shadowed and harness/tools never enters
sys.path.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS_DIR = HERE.parent
ROOT = TOOLS_DIR.parents[1]

LANE_NAMES = ("identity", "knowledge", "journal", "decisions", "records", "docs")
TIERS = ["public", "internal", "confidential", "restricted", "secret"]


def load_tool(name: str):
    path = TOOLS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"p4b_tool_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path: Path, content) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        content = content.encode("utf-8")
    path.write_bytes(content)
    return path


def structure(lanes=None, lane_defaults=None, unlisted="internal", git_mode="main-only", **overrides) -> dict:
    """A complete, validator-clean structure.json object."""
    doc = {
        "schema_version": 1,
        "lanes": {name: None for name in LANE_NAMES},
        "git": {"mode": git_mode},
        "outbound_globs": [],
        "brain": {"local_tracked": False, "local_path": "brain/local"},
        "tiers": {
            "lane_defaults": {name: "internal" for name in LANE_NAMES},
            "unlisted_path": unlisted,
        },
        "delegation": {"mandatory": False},
        "selection_scope": "repo",
        "contract": {"mode": "rendered"},
        "host": {"adopted": False, "roots": [], "harness_owned": []},
    }
    doc["tiers"]["lane_defaults"]["docs"] = "public"
    for name, value in (lanes or {}).items():
        doc["lanes"][name] = value
    for name, value in (lane_defaults or {}).items():
        doc["tiers"]["lane_defaults"][name] = value
    doc.update(overrides)
    return doc


def write_structure(root: Path, doc: dict) -> Path:
    return write(root / "harness" / "registry" / "structure.json", json.dumps(doc, indent=2) + "\n")


def make_link(target: Path, link: Path) -> bool:
    """Create a symlink, falling back to a directory junction on Windows.
    Returns False when the host cannot create any link."""
    try:
        os.symlink(str(target), str(link), target_is_directory=target.is_dir())
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt" and target.is_dir():
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return result.returncode == 0
    return False


def walk_files(root: Path) -> list:
    """Relative POSIX paths of every non-.git entry (files and links), never
    following links."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        base = Path(dirpath)
        for name in list(dirnames):
            full = base / name
            if os.path.islink(full) or (hasattr(os.path, "isjunction") and os.path.isjunction(str(full))):
                found.append(full.relative_to(root).as_posix())
                dirnames.remove(name)
        for name in filenames:
            if name == ".git":
                continue
            found.append((base / name).relative_to(root).as_posix())
    return sorted(found)


def git(repo: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    assert git(path, "init", "-q", "-b", "main").returncode == 0
    git(path, "config", "user.email", "tests@example.com")
    git(path, "config", "user.name", "tests")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    return path


def commit_all(repo: Path, message: str) -> str:
    assert git(repo, "add", "-A").returncode == 0
    result = git(repo, "commit", "-q", "-m", message)
    assert result.returncode == 0, result.stderr
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def _clear_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="p4b-")
        # macOS: mkdtemp lands under /var, a symlink to /private/var, and
        # export.py refuses any destination with a symlink component in its
        # path. Resolve so self.tmp is the real path the export code walks.
        self.tmp = Path(self._tmpdir).resolve()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, onerror=_clear_readonly)


def run_cli(script: str, *args, stdin: str | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOLS_DIR / f"{script}.py"), *args],
        capture_output=True,
        text=True,
        input=stdin,
        cwd=str(cwd or ROOT),
        check=False,
    )
