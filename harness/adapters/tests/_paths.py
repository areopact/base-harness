"""Shared path helpers for the adapter tests. Stdlib only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTERS = ROOT / "harness" / "adapters"
RUNTIMES = ("claude", "codex", "opencode")

if str(ADAPTERS) not in sys.path:
    sys.path.insert(0, str(ADAPTERS))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def bind_unittest(namespace: dict, class_name: str) -> None:
    """Expose module-level test_ functions to ``python -m unittest discover``.

    Pytest collects the bare functions directly; under unittest they are bound
    as methods on a generated TestCase. A ``tmp_path`` parameter receives a
    fresh temporary directory. No-op when pytest is the runner.
    """
    if "pytest" in sys.modules:
        return
    import tempfile
    import unittest

    bridge = type(class_name, (unittest.TestCase,), {})

    def bind(name, function):
        def method(self):
            argnames = function.__code__.co_varnames[: function.__code__.co_argcount]
            if "tmp_path" in argnames:
                with tempfile.TemporaryDirectory() as tmp:
                    # macOS: TemporaryDirectory lands under /var, a symlink
                    # to /private/var. Resolve it so a path built from this
                    # root never trips a symlink-component refusal (export.py)
                    # or a downstream identity check that expects a real path.
                    function(Path(tmp).resolve())
            else:
                function()

        method.__name__ = name
        setattr(bridge, name, method)

    for name, function in list(namespace.items()):
        if name.startswith("test_") and callable(function) and not isinstance(function, type):
            bind(name, function)
    namespace[class_name] = bridge
