"""H10: every wrapper exits 0 for deny, advisory, silence, empty stdin,
malformed stdin, and a missing Python.

POSIX wrappers run through the first bash on PATH wherever one exists; the
PowerShell wrappers run only on Windows. The missing-Python case strips PATH
down to the shell's own directories, then asserts both exit 0 and an empty
stdout: a deny fixture that still produced output would prove the interpreter
was found after all, which fails the case.
"""
import os
import shutil
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TESTS = Path(__file__).resolve().parent
HOOKS = TESTS.parent
ROOT = HOOKS.parents[1]
FIXTURES = TESTS / "fixtures"

WRAPPERS = {
    "session-start/load-identity": None,
    "session-start/pre-bootstrap-detector": None,
    "pre-tool-use/memory-first": None,
    "pre-tool-use/dangerous-ops-guard": FIXTURES / "guard" / "bypass-force-push-main.json",
    "pre-tool-use/openpyxl-guard": FIXTURES / "openpyxl" / "deny-inline-save.json",
    "pre-tool-use/delegation-guard": None,
    "pre-tool-use/read-deny": FIXTURES / "read-deny" / "deny-secret-label.json",
    "post-tool-use/frontmatter-guard": FIXTURES / "frontmatter" / "advise-invalid-access.json",
    "post-tool-use/prose-lint": None,
    "post-tool-use/delegation-guard": None,
    "stop/close-the-loop": None,
}
DISPATCH_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
STDIN_CASES = {"silence": "{}", "empty": "", "malformed": "not json {"}
TIMEOUT = 60

def find_bash():
    """The first bash on PATH, skipping Windows aliases that are not a POSIX shell."""
    found = shutil.which("bash")
    if os.name != "nt":
        return found
    lowered = (found or "").lower()
    if found and "system32" not in lowered and "windowsapps" not in lowered:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        for candidate in (Path(base) / "Git" / "usr" / "bin" / "bash.exe", Path(base) / "Programs" / "Git" / "usr" / "bin" / "bash.exe"):
            if candidate.is_file():
                return str(candidate)
    return None


BASH = find_bash()
POWERSHELL = shutil.which("powershell") if os.name == "nt" else None


def shell_only_path(executable):
    """A PATH with no interpreter on it at all.

    The shell itself is always invoked by absolute path (sh_command,
    ps_command), so it never needs its own directory on PATH; the wrappers
    under test locate themselves with shell builtins only (see their
    comments) and touch nothing else external before the interpreter lookup
    (python3, then python, then py). An empty PATH is therefore both
    sufficient and portable: on a Debian-family POSIX host, bash and every
    python candidate are installed in the same system bin directory, so a
    PATH built from "the shell's own directory" (the prior approach here)
    still finds a candidate and defeats the missing-interpreter case
    entirely.
    """
    del executable  # kept for call-site symmetry; no longer used
    return ""


def run(command, stdin, env_overrides=None, path=None):
    env = dict(os.environ)
    env.pop("HARNESS_HOOK_DEBUG_DIR", None)
    env.pop("HARNESS_READ_DENY", None)
    if env_overrides:
        env.update(env_overrides)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
        env=env,
        timeout=TIMEOUT,
        check=False,
    )


def sh_command(relative):
    return [BASH, str(HOOKS / (relative + ".sh"))]


def ps_command(relative, *extra):
    return [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HOOKS / (relative + ".ps1")), *extra]


def cases(language):
    build = sh_command if language == "sh" else ps_command
    flag_on = {"HARNESS_READ_DENY": "1"}
    for relative, fixture in WRAPPERS.items():
        env = flag_on if relative.endswith("read-deny") else None
        if fixture is not None:
            yield relative + " decision", build(relative), fixture.read_text(encoding="utf-8"), env, None, "decision"
        for name, stdin in STDIN_CASES.items():
            yield relative + " " + name, build(relative), stdin, env, None, None
        stdin = fixture.read_text(encoding="utf-8") if fixture is not None else "{}"
        shell = BASH if language == "sh" else POWERSHELL
        yield relative + " missing-python", build(relative), stdin, env, shell_only_path(shell), "silent"
    for event in DISPATCH_EVENTS:
        if language == "sh":
            command = [BASH, str(HOOKS / "codex-dispatch.sh"), "--runtime", "codex", "--event", event]
        else:
            command = ps_command("codex-dispatch", "-Runtime", "codex", "-Event", event)
        stdin = FIXTURES.joinpath("guard", "bypass-force-push-main.json").read_text(encoding="utf-8") if event == "PreToolUse" else "{}"
        yield "codex-dispatch " + event, command, stdin, None, None, "decision" if event == "PreToolUse" else None
        yield "codex-dispatch " + event + " malformed", command, "not json {", None, None, None
    shell = BASH if language == "sh" else POWERSHELL
    yield "codex-dispatch missing-python", command, stdin, None, shell_only_path(shell), "silent"


def check(case):
    name, command, stdin, env, path, expectation = case
    result = run(command, stdin, env, path)
    problems = []
    if result.returncode != 0:
        problems.append("exit %d, stderr: %s" % (result.returncode, result.stderr.strip()[:300]))
    if expectation == "decision" and "hookSpecificOutput" not in result.stdout and "systemMessage" not in result.stdout:
        problems.append("expected a JSON decision, got %r" % result.stdout[:200])
    if expectation == "silent" and result.stdout.strip():
        problems.append("expected silence without Python, got %r" % result.stdout[:200])
    if result.stdout.strip() and not result.stdout.lstrip().startswith("{"):
        problems.append("stdout is not a JSON line: %r" % result.stdout[:200])
    return name, problems


class ExitCodeTests(unittest.TestCase):
    def run_language(self, language):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(check, cases(language)))
        failures = ["%s: %s" % (name, "; ".join(problems)) for name, problems in results if problems]
        assert not failures, "\n".join(failures)

    @unittest.skipUnless(BASH, "bash not found on PATH")
    def test_posix_wrappers_exit_zero_in_every_case(self):
        self.run_language("sh")

    @unittest.skipUnless(POWERSHELL, "PowerShell wrappers run only on Windows")
    def test_powershell_wrappers_exit_zero_in_every_case(self):
        self.run_language("ps1")

    def test_every_sh_wrapper_has_a_ps1_sibling_and_a_shebang(self):
        shell_files = sorted(path for path in HOOKS.rglob("*.sh") if "tests" not in path.parts)
        assert shell_files
        for path in shell_files:
            with self.subTest(path=path.name):
                assert path.with_suffix(".ps1").is_file(), "missing %s" % path.with_suffix(".ps1").name
                first = path.read_text(encoding="utf-8").splitlines()[0]
                assert first in ("#!/bin/sh", "#!/bin/bash"), first
                text = path.read_text(encoding="utf-8")
                assert text.rstrip().endswith("exit 0") or path.name.startswith("_"), path.name


if __name__ == "__main__":
    unittest.main()
