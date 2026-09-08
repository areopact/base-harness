"""F8: harness/hooks/lib/_find_python.ps1 has its own execute-probe coverage.

_find_python.ps1 is dot-sourced by every harness/hooks/*/*.ps1 wrapper and by
codex-dispatch.ps1, but before this file it had no test of its own: the
matching bash execute-probe tests (B10, harness/bootstrap/tests/
test_bootstrap_shell.py) are unconditionally skipped on win32, the one
platform the PowerShell path actually runs on. Gated on PowerShell being
available, not on platform, so it also runs wherever pwsh is installed.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIND_PYTHON = REPO_ROOT / "harness" / "hooks" / "lib" / "_find_python.ps1"
WRAPPER = REPO_ROOT / "harness" / "hooks" / "session-start" / "pre-bootstrap-detector.ps1"
NULL_MARKER = "<NULL>"


def powershell_executable() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _write_cmd_shim(path: Path, body: str) -> None:
    path.write_text("@echo off\r\n" + body + "\r\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_sh_shim(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _shim_name(name: str) -> str:
    """The candidate's on-disk filename for this host.

    On Windows, PowerShell's Get-Command resolves an Application candidate
    through PATHEXT (.cmd, .exe, ...), so a bare name needs one of those
    suffixes to be found at all. On POSIX, pwsh has no PATHEXT-equivalent
    extension search for Get-Command: it matches the literal candidate name
    against an executable file on PATH, so a ".cmd" file is invisible to it
    and the probe falls through to whatever real python3 sits later on
    PATH. The shim must therefore be a plain, executable, extensionless
    file named exactly like the candidate on POSIX.
    """
    return f"{name}.cmd" if os.name == "nt" else name


def write_broken_shim(directory: Path, name: str) -> Path:
    """A candidate that resolves but exits non-zero without running anything."""
    path = directory / _shim_name(name)
    if os.name == "nt":
        _write_cmd_shim(path, "exit /b 49")
    else:
        _write_sh_shim(path, "exit 49")
    return path


def write_working_shim(directory: Path, name: str) -> Path:
    """A candidate that resolves and actually runs the real interpreter."""
    path = directory / _shim_name(name)
    if os.name == "nt":
        _write_cmd_shim(path, f'"{sys.executable}" %*')
    else:
        _write_sh_shim(path, f'exec "{sys.executable}" "$@"')
    return path


def _run_ps1(script_text: str, path_prefix: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    shell = powershell_executable()
    assert shell, "no PowerShell on this host"
    with tempfile.TemporaryDirectory() as scratch:
        driver = Path(scratch) / "driver.ps1"
        driver.write_text(script_text, encoding="utf-8")
        env = dict(os.environ)
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(driver)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env,
        )


@unittest.skipUnless(powershell_executable(), "no PowerShell on this host")
class FindPythonPs1Tests(unittest.TestCase):
    def test_skips_a_stub_that_exits_nonzero_and_resolves_the_working_candidate(self):
        with tempfile.TemporaryDirectory() as shims:
            shims_dir = Path(shims)
            write_broken_shim(shims_dir, "python")
            write_working_shim(shims_dir, "python3")
            driver = f". '{FIND_PYTHON}'\nif ($Python) {{ Write-Output $Python }} else {{ Write-Output '{NULL_MARKER}' }}\n"
            completed = _run_ps1(driver, shims_dir)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            resolved = completed.stdout.strip().splitlines()[-1]
            assert resolved != NULL_MARKER, completed.stdout + completed.stderr
            resolved_path = Path(resolved)
            assert resolved_path.name.lower() == _shim_name("python3").lower(), resolved
            assert resolved_path.parent.samefile(shims_dir), resolved

    def test_all_broken_candidates_leave_python_null_and_the_wrapper_exits_0_silently(self):
        with tempfile.TemporaryDirectory() as shims:
            shims_dir = Path(shims)
            for name in ("python", "python3", "py"):
                write_broken_shim(shims_dir, name)

            driver = f". '{FIND_PYTHON}'\nif ($Python) {{ Write-Output $Python }} else {{ Write-Output '{NULL_MARKER}' }}\n"
            completed = _run_ps1(driver, shims_dir)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            assert completed.stdout.strip().splitlines()[-1] == NULL_MARKER, completed.stdout + completed.stderr

            shell = powershell_executable()
            env = dict(os.environ)
            env["PATH"] = str(shims_dir)
            wrapper_result = subprocess.run(
                [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)],
                input='{"hook_event_name":"SessionStart"}',
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env,
            )
            assert wrapper_result.returncode == 0, wrapper_result.stdout + wrapper_result.stderr
            assert wrapper_result.stdout.strip() == "", wrapper_result.stdout


if __name__ == "__main__":
    unittest.main()
