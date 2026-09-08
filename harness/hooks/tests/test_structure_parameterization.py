"""H6: no lib hardcodes a lane path, and every lib is stdlib-only.

Lane paths reach a hook only through structure.json via hook_io. The one
allowed literal occurrence of the default lane paths is hook_io's
DEFAULT_STRUCTURE object, which is the defaults contract itself. Beyond the
defaults, the structural rule is that the only repository paths a lib may
name literally live under harness/ (its own rules and registries); every
other path is host configuration. The private-vocabulary check is
deliberately not here: harness/tools/deidentify_lint.py runs it with a term
file that never enters the repository.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
LIB = TESTS.parent / "lib"
sys.path.insert(0, str(LIB))

import hook_io  # noqa: E402

LOCAL_MODULES = {path.stem for path in LIB.glob("*.py")}
# A plain repo-relative path: segments of word characters, dots, or dashes
# joined by "/", with no regex or format metacharacters.
PLAIN_PATH = re.compile(r"^[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)+$")


def string_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def lane_tokens():
    tokens = []
    for value in hook_io.DEFAULT_STRUCTURE["lanes"].values():
        if isinstance(value, list):
            tokens.extend(value)
    tokens.append(hook_io.DEFAULT_STRUCTURE["brain"]["local_path"])
    # only path-shaped tokens; a bare lane name such as "docs" is vocabulary, not a path
    return sorted({token for token in tokens if "/" in token or token.endswith(".md")}, key=len, reverse=True)


def strip_defaults_block(text):
    start = text.index("DEFAULT_STRUCTURE = {")
    end = text.index("\n}\n", start) + 3
    return text[:start] + text[end:]


class LanePathTokenTests(unittest.TestCase):
    def test_default_lane_paths_appear_nowhere_but_the_defaults_object(self):
        for path in sorted(LIB.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if path.name == "hook_io.py":
                text = strip_defaults_block(text)
            with self.subTest(path=path.name):
                for token in lane_tokens():
                    assert token not in text, "%s hardcodes lane path %r" % (path.name, token)

    def test_only_harness_paths_are_named_literally(self):
        for path in sorted(LIB.glob("*.py")):
            with self.subTest(path=path.name):
                for value in string_constants(path):
                    if not PLAIN_PATH.match(value):
                        continue
                    if path.name == "hook_io.py" and value in lane_tokens():
                        continue
                    assert value.startswith("harness/"), "%s names a host path literally: %r" % (path.name, value)

    def test_no_absolute_paths_in_any_hook_file(self):
        pattern = re.compile(r"(?m)(?<![\w:])(?:[A-Za-z]:\\|/home/|/Users/)")
        for path in sorted(TESTS.parent.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".sh", ".ps1", ".md"}:
                continue
            if "fixtures" in path.parts or "expected" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            with self.subTest(path=str(path.relative_to(TESTS.parent))):
                for match in pattern.finditer(text):
                    context = text[max(0, match.start() - 40): match.end() + 40]
                    # regex character classes and the PowerShell root example are allowed shapes
                    if "[A-Za-z]" in context or "Remove-Item" in context or "Program Files" in context:
                        continue
                    raise AssertionError("absolute path in %s: %r" % (path.name, context))


class StdlibOnlyTests(unittest.TestCase):
    def test_every_lib_imports_only_stdlib_or_sibling_modules(self):
        stdlib = set(getattr(sys, "stdlib_module_names", ()))
        assert stdlib, "sys.stdlib_module_names requires Python 3.10+"
        for path in sorted(LIB.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            with self.subTest(path=path.name):
                for node in ast.walk(tree):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [alias.name.split(".")[0] for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        assert node.level == 0, "relative import in %s" % path.name
                        names = [(node.module or "").split(".")[0]]
                    for name in names:
                        assert name in stdlib or name in LOCAL_MODULES, "%s imports %r" % (path.name, name)
                        assert name not in ("harness", "tools"), "%s imports from harness/tools" % path.name

    def test_hook_io_imports_nothing_from_harness_tools(self):
        tree = ast.parse((LIB / "hook_io.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
        assert not any("harness_registry" in name or name.startswith("tools") for name in imported), imported
        assert not any(name in LOCAL_MODULES for name in imported), "hook_io must not import sibling hook modules"

    def test_repo_root_is_derived_from_file_location(self):
        text = (LIB / "hook_io.py").read_text(encoding="utf-8")
        assert "REPO_ROOT = Path(__file__).resolve().parents[3]" in text
        assert hook_io.REPO_ROOT == LIB.parents[2]


if __name__ == "__main__":
    unittest.main()
