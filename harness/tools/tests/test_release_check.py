"""release_check: the ordered ship-gate chain, terms handling, and --help."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

from ._repo import ROOT, install_bridge  # noqa: F401

import release_check as rc


class FakeCompleted:
    __slots__ = ("returncode",)

    def __init__(self, returncode: int):
        self.returncode = returncode


class FakeRunner:
    """Records every argv it was called with; never spawns a process.
    Returns 0 by default, or the code named in `codes` for a call index."""

    def __init__(self, codes: dict | None = None, default: int = 0):
        self.calls = []
        self.codes = codes or {}
        self.default = default

    def __call__(self, argv, cwd=None):
        index = len(self.calls)
        self.calls.append((argv, cwd))
        return FakeCompleted(self.codes.get(index, self.default))


@contextlib.contextmanager
def _env(**overrides):
    """Sets or removes environment variables for the block; restores after.
    A value of None removes the key (delenv); any other value sets it."""
    sentinel = object()
    saved = {key: os.environ.get(key, sentinel) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, prior in saved.items():
            if prior is sentinel:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior


def _run(argv: list[str], runner) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = rc.run(argv, runner=runner)
    return code, out.getvalue()


def test_plan_order_with_terms_layer(tmp_path):
    steps = rc.plan(tmp_path, str(tmp_path / "terms.txt"), 3, True, False)
    names = [step.name for step in steps]
    assert names == [
        "lint --release",
        "gen_manifest --check",
        "resolver_lint",
        "build_codex_adapter --check",
        "build_opencode_adapter --check",
        "native_routing render --check",
        "deidentify_lint structural+history",
        "deidentify_lint terms+history",
    ]


def test_plan_without_terms_layer_omits_the_terms_step(tmp_path):
    steps = rc.plan(tmp_path, None, 3, False, False)
    names = [step.name for step in steps]
    assert "deidentify_lint terms+history" not in names
    assert len(names) == 7


def test_plan_with_tests_flag_adds_a_pytest_step(tmp_path):
    steps = rc.plan(tmp_path, str(tmp_path / "terms.txt"), 3, True, True)
    assert steps[-1].name == "pytest"
    assert steps[-1].argv[1:4] == ["-m", "pytest", "harness"]


def test_require_terms_is_forwarded_to_the_terms_step(tmp_path):
    steps = rc.plan(tmp_path, str(tmp_path / "terms.txt"), 7, True, False)
    terms_step = [s for s in steps if s.name == "deidentify_lint terms+history"][0]
    assert "--require-terms" in terms_step.argv
    assert terms_step.argv[terms_step.argv.index("--require-terms") + 1] == "7"


def test_run_without_terms_and_without_env_refuses(tmp_path):
    with _env(RELEASE_TERMS=None):
        runner = FakeRunner()
        code, out = _run(["--root", str(tmp_path)], runner)
    assert code == 2
    assert "refused" in out
    assert runner.calls == []


def test_run_no_terms_flag_warns_and_runs_every_other_step(tmp_path):
    with _env(RELEASE_TERMS=None):
        runner = FakeRunner()
        code, out = _run(["--root", str(tmp_path), "--no-terms"], runner)
    assert code == 0
    assert "WARN" in out and "private-vocabulary layer did not run" in out
    assert len(runner.calls) == 7
    assert not any("--terms" in argv for argv, _ in runner.calls)
    assert "release check: PASS" in out


def test_run_env_var_terms_is_used_when_no_flag(tmp_path):
    with _env(RELEASE_TERMS=str(tmp_path / "env-terms.txt")):
        runner = FakeRunner()
        code, out = _run(["--root", str(tmp_path)], runner)
    assert code == 0
    assert len(runner.calls) == 8
    terms_call = runner.calls[-1][0]
    assert str(tmp_path / "env-terms.txt") in terms_call


def test_run_explicit_terms_flag_wins_over_env(tmp_path):
    with _env(RELEASE_TERMS=str(tmp_path / "env-terms.txt")):
        runner = FakeRunner()
        code, out = _run(["--root", str(tmp_path), "--terms", str(tmp_path / "flag-terms.txt")], runner)
    assert code == 0
    terms_call = runner.calls[-1][0]
    assert str(tmp_path / "flag-terms.txt") in terms_call
    assert str(tmp_path / "env-terms.txt") not in terms_call


def test_run_no_terms_flag_wins_over_release_terms_env(tmp_path):
    """--no-terms must win over RELEASE_TERMS: the layer is skipped even
    when the environment variable happens to be set."""
    with _env(RELEASE_TERMS=str(tmp_path / "env-terms.txt")):
        runner = FakeRunner()
        code, out = _run(["--root", str(tmp_path), "--no-terms"], runner)
    assert code == 0
    assert "WARN" in out and "private-vocabulary layer did not run" in out
    assert len(runner.calls) == 7
    assert not any("--terms" in argv for argv, _ in runner.calls)
    assert not any(str(tmp_path / "env-terms.txt") in argv for argv, _ in runner.calls)


def test_run_no_terms_conflicts_with_explicit_terms_flag(tmp_path):
    with _env(RELEASE_TERMS=None):
        runner = FakeRunner()
        code, out = _run(
            ["--root", str(tmp_path), "--no-terms", "--terms", str(tmp_path / "flag-terms.txt")],
            runner,
        )
    assert code == 2
    assert "refused" in out and "--no-terms" in out and "--terms" in out
    assert runner.calls == []


def test_run_prints_each_step_exit_code(tmp_path):
    with _env(RELEASE_TERMS=None):
        runner = FakeRunner(codes={2: 1})  # the third step (resolver_lint) fails
        code, out = _run(["--root", str(tmp_path), "--terms", str(tmp_path / "t.txt")], runner)
    assert code == 1
    assert "resolver_lint: exit 1 (FAIL)" in out
    assert "lint --release: exit 0 (PASS)" in out
    assert "release check: FAIL" in out
    # every step still ran despite the earlier failure
    assert len(runner.calls) == 8


def test_run_all_steps_pass_prints_release_check_pass(tmp_path):
    with _env(RELEASE_TERMS=None):
        runner = FakeRunner()
        code, out = _run(["--root", str(tmp_path), "--terms", str(tmp_path / "t.txt")], runner)
    assert code == 0
    assert "release check: PASS" in out


def test_help_exits_zero():
    result = subprocess.run(
        [sys.executable, str(ROOT / "harness" / "tools" / "release_check.py"), "--help"],
        capture_output=True,
    )
    assert result.returncode == 0


install_bridge(globals(), "ReleaseCheckBridge")
