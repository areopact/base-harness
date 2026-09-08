# Contributing

Thank you for reading this before opening a pull request. The rules below are short because each one closes a failure that actually happened.

## Sign-off (DCO)

Contributions are accepted under the Developer Certificate of Origin 1.1 (https://developercertificate.org/). No CLA. A `Signed-off-by:` line (`git commit -s`) is requested on every commit, stating that you wrote the change or have the right to submit it under the MIT license of this repository; sign-off is checked in review rather than enforced by CI.

## Before adding a skill or a hook: the owner-first rule

Most "new skill" ideas are a repair to an existing owner. Work down this ladder and stop at the first rung that fits:

1. **Repair an existing owner.** If a skill already covers the intent and produces the wrong result, fix that skill.
2. **Add a mode or a reference file to an existing skill** when the intent is shared and only the output shape or a flag differs.
3. **New skill** only when the intent, the output, and the routing boundary are all distinct from every existing skill. Name the boundary in the PR: which trigger phrases route here and which stay with the neighbor.
4. **New hook** only when there is a supported runtime-native decision point for it (an event in `harness/registry/runtimes.json` with `support` other than `unsupported` on at least one tier-1 runtime). A hook starts at the advisory rung; it moves to deny only after false-positive and recovery tests exist under `harness/hooks/tests/`.

Every new or changed skill or hook ships with: a failing test that the change fixes, a legitimate-neighbor case that still passes, a recovery sentence in any deny message, regenerated catalogs (`python harness/tools/gen_manifest.py`), and a clean `python harness/tools/resolver_lint.py`.

Pull requests land with `status: spec-only` unless the PR includes evidence the maintainer can observe (a VERIFICATION row with a date, scope token, and reproduction steps). Promotion to `implemented` is a separate change.

## Review policy

- **Hook, bootstrap, and tool PRs are reviewed on the diff only.** The reviewer does not run contributor code from a fork; CI runs the repository's own scripts, including `sh .githooks/pre-commit`, on `pull_request` with a read-only token and no secrets. Keep the diff small and self-explanatory.
- Skills and docs PRs are read as prose plus the lint output.
- Generated files (`AGENTS.md`, `harness/skills/RESOLVER.md`, `harness/kernel-manifest.json`, `THIRD-PARTY.md`, the generated adapter trees) are never hand-edited in a PR; change the source and regenerate. `python harness/tools/lint.py --strict` catches the drift.

## Style

- ASCII punctuation. No em-dashes or en-dashes; use commas, colons, or two sentences.
- LF line endings everywhere (`.gitattributes` enforces it; the lint rejects CR).
- Python is stdlib-only. Tests are plain pytest style (bare asserts, `tmp_path` and `monkeypatch` only) and must also pass under `python -m unittest discover -s harness -p "test_*.py"`.
- Shell scripts are POSIX `sh` unless the shebang says `bash`. Every hook wrapper and bootstrap entry has a `.sh` and a `.ps1` sibling.
- Comments state the invariant, never the incident. "Scan the whole index, not the diff, so a blob staged by another session cannot ride into this commit" is fine; a dated story about who did what is not.
- No private vocabulary. `python harness/tools/deidentify_lint.py .` runs in CI.

## Reproducing Linux behavior from Windows

The pattern that works, in this order:

1. Write the script you want to run to a file (heredocs typed into an interactive Git Bash often pick up CR characters).
2. Strip carriage returns: `sed -i 's/\r$//' script.sh` (or `python -c "import sys;p=sys.argv[1];data=open(p,'rb').read();open(p,'wb').write(data.replace(b'\r\n',b'\n'))" script.sh`).
3. Run it with `bash script.sh` from Git Bash or WSL.

## Running the checks locally

```sh
python harness/tools/lint.py --strict
python harness/tools/resolver_lint.py
python harness/tools/gen_manifest.py --check
python harness/bootstrap/build_codex_adapter.py --check
python harness/bootstrap/build_opencode_adapter.py --check
python -m pytest harness/bootstrap/tests harness/hooks/tests harness/tools/tests -q -p no:cacheprovider
```

If `pytest` is not installed: `python -m unittest discover -s harness -p "test_*.py"`.

The full ship gate, including the de-identification lint over the whole history, is `python harness/tools/release_check.py`; see `ROADMAP.md` for the v0.1.0 gate this backs.
