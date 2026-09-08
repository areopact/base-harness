"""Shared helpers for the tool tests: temporary repositories built from the live tree.

Every test builds its own repository under tmp_path by copying the real
authored inputs (routing rule, registries, adapter model maps) and never
writes into the checkout. The unittest bridge lets the plain pytest-style
functions run under ``python -m unittest discover`` as well.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "harness" / "tools"
# The tools directory holds a module named selector.py; keep it at the tail of
# sys.path so the stdlib select module wins, and pin that module now.
sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != TOOLS]
sys.path.append(str(TOOLS))
import selectors  # noqa: E402,F401  (imports the stdlib select module)

RUNTIMES = ("claude", "codex", "opencode")
ROUTING_INPUTS = (
    "harness/rules/base-routing.md",
    "harness/registry/runtimes.json",
    "harness/registry/structure.json",
) + tuple(f"harness/adapters/{runtime}/model-map.json" for runtime in RUNTIMES)


def copy_files(target: Path, relatives: tuple[str, ...] | list[str], source: Path = ROOT) -> Path:
    for relative in relatives:
        origin = source / relative
        if not origin.is_file():
            raise FileNotFoundError(f"live tree lacks {relative}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination)
    return target


def routing_repo(tmp_path: Path, *, compile_manifest: bool = True) -> Path:
    """A repository carrying the routing inputs, with the manifest compiled."""
    repo = copy_files(tmp_path / "repo", ROUTING_INPUTS)
    for runtime in RUNTIMES:
        (repo / "harness" / "adapters" / runtime / "agents").mkdir(parents=True, exist_ok=True)
    if compile_manifest:
        import routing_policy as rp

        rp.write_manifest(repo, rp.load_policy(repo))
    return repo


def install_bridge(namespace: dict, class_name: str) -> None:
    """Bind every test_* function in namespace to a unittest.TestCase (no-op under pytest)."""
    if "pytest" in sys.modules:
        return
    bridge = type(class_name, (unittest.TestCase,), {})

    def bind(name, function):
        def method(self):
            if "tmp_path" in function.__code__.co_varnames[: function.__code__.co_argcount]:
                with tempfile.TemporaryDirectory() as tmp:
                    # macOS: TemporaryDirectory lands under /var, a symlink
                    # to /private/var. Resolve it so a path built from this
                    # root never trips a symlink-component refusal or a
                    # downstream identity check that expects a real path.
                    function(Path(tmp).resolve())
            else:
                function()

        method.__name__ = name
        setattr(bridge, name, method)

    for name, function in list(namespace.items()):
        if name.startswith("test_") and callable(function):
            bind(name, function)
    namespace[class_name] = bridge
