#!/usr/bin/env python
"""Ship gate for a release: runs the full lint, build, and de-identify chain in
order and prints PASS/FAIL for each step, then one final PASS/FAIL line.

Usage:
    python harness/tools/release_check.py [--root ROOT] [--terms PATH]
        [--require-terms N] [--no-terms] [--tests]

ROADMAP.md names "de-identification lint clean over the full history" as a
v0.1.0 gate; this tool is what runs it, alongside every other ship-blocking
check in the repository.

Steps, always in this order:
    1. lint.py --release
    2. gen_manifest.py --check
    3. resolver_lint.py
    4. build_codex_adapter.py --check
    5. build_opencode_adapter.py --check
    6. native_routing.py render --check
    7. deidentify_lint.py . --structural --history
    8. deidentify_lint.py . --terms <path> --require-terms <n> --history
    9. pytest (only with --tests)

Each step prints its own name and exit code as it runs. The private-
vocabulary layer (step 8) needs a term list that lives outside the published
tree: pass it with --terms, or set RELEASE_TERMS in the environment. Without
one, this tool refuses with exit 2 and one clear line, unless --no-terms is
passed, in which case it prints a WARN that the private-vocabulary layer did
not run and continues with every other step. --no-terms wins over the
RELEASE_TERMS environment variable, but conflicts with an explicit --terms
path: passing both refuses with exit 2 and one clear line before any step
runs. --require-terms N is the floor on the resolved term list itself
(default 3), forwarded to deidentify_lint.py.

The final line is exactly "release check: PASS" or "release check: FAIL",
exit 0 or 1. A usage refusal (no terms, no --no-terms) exits 2 before any
step runs.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_REQUIRE_TERMS = 3


class Step:
    __slots__ = ("name", "argv")

    def __init__(self, name: str, argv: list):
        self.name = name
        self.argv = argv


def _python(root: Path, *args) -> list:
    return [sys.executable, *args]


def plan(root: Path, terms_path, require_terms: int, run_terms_layer: bool, run_tests: bool) -> list:
    """The ordered step list this run will execute. terms_path is ignored
    when run_terms_layer is False (--no-terms was passed)."""
    steps = [
        Step("lint --release", _python(root, str(root / "harness" / "tools" / "lint.py"), "--root", str(root), "--release")),
        Step("gen_manifest --check", _python(root, str(root / "harness" / "tools" / "gen_manifest.py"), "--root", str(root), "--check")),
        Step("resolver_lint", _python(root, str(root / "harness" / "tools" / "resolver_lint.py"), "--root", str(root))),
        Step("build_codex_adapter --check", _python(root, str(root / "harness" / "bootstrap" / "build_codex_adapter.py"), "--root", str(root), "--check")),
        Step("build_opencode_adapter --check", _python(root, str(root / "harness" / "bootstrap" / "build_opencode_adapter.py"), "--root", str(root), "--check")),
        Step("native_routing render --check", _python(root, str(root / "harness" / "tools" / "native_routing.py"), "--root", str(root), "render", "--check")),
        Step(
            "deidentify_lint structural+history",
            _python(root, str(root / "harness" / "tools" / "deidentify_lint.py"), str(root), "--structural", "--history"),
        ),
    ]
    if run_terms_layer:
        steps.append(
            Step(
                "deidentify_lint terms+history",
                _python(
                    root,
                    str(root / "harness" / "tools" / "deidentify_lint.py"),
                    str(root),
                    "--terms", str(terms_path),
                    "--require-terms", str(require_terms),
                    "--history",
                ),
            )
        )
    if run_tests:
        steps.append(Step("pytest", _python(root, "-m", "pytest", "harness", "-q", "-p", "no:cacheprovider")))
    return steps


def run(argv=None, runner=subprocess.run) -> int:
    """Runs the release chain. runner defaults to subprocess.run; tests pass
    a fake to assert the planned command list without running anything."""
    parser = argparse.ArgumentParser(
        prog="release_check.py",
        description="Ship gate: runs the full lint, build, and de-identify chain in order.",
    )
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    parser.add_argument("--terms", default=None, help="private term list; falls back to the RELEASE_TERMS environment variable")
    parser.add_argument("--require-terms", type=int, default=DEFAULT_REQUIRE_TERMS, help="floor on the resolved term list (default 3)")
    parser.add_argument("--no-terms", action="store_true", help="skip the private-vocabulary layer with a WARN instead of refusing; wins over RELEASE_TERMS, but conflicts with an explicit --terms (exit 2)")
    parser.add_argument("--tests", action="store_true", help="also run the pytest suite as a step")
    args = parser.parse_args(argv)

    if args.no_terms and args.terms:
        print("release check: refused: --no-terms conflicts with an explicit --terms path")
        return 2

    run_terms_layer = True
    terms_path = None
    if args.no_terms:
        # Explicit --no-terms wins over RELEASE_TERMS: skip the layer even
        # when the environment variable happens to be set.
        print("WARN: --no-terms passed; the private-vocabulary layer did not run")
        run_terms_layer = False
    else:
        terms_path = args.terms or os.environ.get("RELEASE_TERMS")
        if not terms_path:
            print(
                "release check: refused: no --terms path and RELEASE_TERMS is unset "
                "(pass --terms, set RELEASE_TERMS, or pass --no-terms to proceed without "
                "the private-vocabulary layer)"
            )
            return 2

    steps = plan(args.root, terms_path, args.require_terms, run_terms_layer, args.tests)

    overall_ok = True
    for step in steps:
        result = runner(step.argv, cwd=str(args.root))
        code = result.returncode
        status = "PASS" if code == 0 else "FAIL"
        print(f"{step.name}: exit {code} ({status})")
        if code != 0:
            overall_ok = False

    print(f"release check: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


def main(argv=None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
