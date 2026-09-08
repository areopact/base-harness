# Changelog

All notable changes to this repository. Format follows Keep a Changelog; versions follow semantic versioning. Dates are ISO 8601.

## [0.1.0] - Unreleased

Initial public template.

### Added

- Kernel: registry-driven bootstrap (`--check`, `--copy`, `--force`), contract composition (`harness/CONTRACT.md` + `harness/CONTRACT.host.md` rendered to `AGENTS.md`), offline doctors for Claude Code, Codex CLI, and OpenCode with six evidence layers, hook library with one Python implementation per hook and per-runtime wrappers, `.githooks/pre-commit` floor, strict runtime JSON schemas, kernel manifest.
- Registries: `runtimes.json`, `structure.json` (lanes, git mode, tiers, brain, delegation flag), `selection.json`, `capabilities.json`, `sources.json`, `environment.json`.
- Selector: `selector.py` with materialize-and-prune; packs declared in skill `metadata.packs`; shipped default `core` plus `maintain`.
- Skills, v0.1.0 catalog: core (brainstorm, prompt, capture, eli5, research, review, humanize), maintain (doctor, verify, commit, skillify), delegation module (workflow, opt-in). Shipped on disk but not selected by default: decks (deck-outline, deck-render --web) and memory (daily); `--pack` replaces the current pack list rather than adding to it, so select them on top of the shipped default with `selector.py --pack core --pack maintain --pack decks` or `--pack core --pack maintain --pack memory`.
- Memory lanes and the optional reference memory module (`brain/shared`, `brain/local`).
- Classification and export: five labels, `export.py` copy mode with its own fuzz suite, `frontmatter_guard`.
- `adopt.py` and `init.py` for existing repositories.
- Docs: ARCHITECTURE, VERIFICATION, PACKS, LANES, HOST-SHAPES, ADDING-A-SKILL, ROUTING-TASKS.
- CI: offline conformance on ubuntu, windows, and macos; fresh-template job; permission-posture assertion; de-identification lint.

### Security

- Guards documented as seatbelts, not locks, with named bypass fixtures (see `SECURITY.md`).

### Changed

- Publication history: the pre-publication working history on the private remote was squashed into one signed, signed-off initial commit before the visibility flip, so the public history starts from a tree that passes the release gate (structural and private-vocabulary de-identification over the full history, both clean).

### Fixed

- `dangerous_ops_guard`: widened caught shapes (bundled short force flags, `--mirror` and `--all --force`, command substitution and backtick reads including nested substitution, `..`-relative recursive-delete targets including `./../` and PowerShell's `..\` form, unquoted Windows-style paths, quoted refs and unquoted list joins on a push, remote branch deletion, a bare force push under main-only git mode, and the `.npmrc`/`.netrc`/`.pgpass`/`.pypirc`/`.git-credentials`/`*.ppk`/`*.keystore`/`*.tfvars` credential shapes plus a `$HOME/`-prefixed credential path, the AWS credentials file and `credentials*` wildcard inside `.aws`, gcloud's application-default-credentials file, and SSH private key filenames), with `--dry-run` and quoted-prose passes preserved and a recorded-pass fixture for every named gap including aliases, functions, `eval`, and other shells.
- OpenCode: `.opencode/lib` now materializes alongside `.opencode/plugins` in both link and copy mode, so the plugin bridge's `../lib/harness-bridge-internal.js` import resolves under `--copy` instead of failing `ERR_MODULE_NOT_FOUND` with every guard silently absent; `doctor_opencode.py` now checks the materialized plugin's resolved imports, not just its source; the copy-mode CI job runs the plugin export/import test.
- `native_routing.py`: the "Bash is still granted" permission caveat now also renders for the `shell-readonly` class (previously `shell` only), with runtime-aware wording (Claude Code and OpenCode name Bash directly; Codex names `sandbox_mode` read-only).
- `deidentify_lint.py` D7: now catches a space inside a path segment, a one-segment drive root in backslash form, mixed backslash/forward-slash separators, and JSON-escaped doubled backslashes; the test/fixture directory filter is segment-exact instead of substring, so `docs/contest/` and a `latest/` directory are scanned again; a `<placeholder>` segment (`C:/<repo>/harness`, `/home/<user>/repo`) is exempt.
- `deidentify_lint.py` self-exemption: the `DEFAULT_TERMS_RELATIVE` exemption is now anchored to the actual assignment statement's AST position, not to any line that merely mentions the identifier, so a probe term left in a comment naming it is reported.
- `release_check.py`: an explicit `--no-terms` now wins over the `RELEASE_TERMS` environment variable; `--no-terms` conflicts with an explicit `--terms` and now refuses with exit 2 and one line instead of silently running the terms layer.
- POSIX executable bits: every tracked `*.sh` and `.githooks/pre-commit` was mode 644 (a Windows export with `core.filemode` off), so `core.hooksPath` silently skipped the pre-commit floor on Linux and macOS; all 20 files are 755 now, lint L18 fails on a lost bit, bootstrap chmods them on POSIX, and CI proves refusal through a real commit.
- Python floor: corrected from the documented 3.10 to 3.11 everywhere (tests and the Codex doctor already required `tomllib`); the Codex doctor fails closed below it and CI runs the ubuntu job on 3.11.
- Codex generated agent roles: role-shape correction so every `.codex/agents/*.toml` file carries the fields Codex expects.
- OpenCode plugin bridge: export shape correction so the bridge declares only the surfaces it implements.
- Path-scoped rules: documented that `paths:` frontmatter is honored by Claude Code only, the one runtime that materializes `harness/rules/` at all; Codex and OpenCode read a rule page on demand through the rendered contract's lookup section, with `paths:` frontmatter carried along as inert text.
- UserPromptSubmit degradation rung corrected to `contract-text` on all three runtimes; no implementation exists for it.
- `.githooks/pre-commit`: fails closed on a malformed secret-pattern file instead of scanning nothing; added `.mcp.json` to the filename block.
- Deny-list alignment: the Claude and OpenCode deny lists, `.gitignore`, the pre-commit filename block, and the guard's credential-shape list now draw from one shared list.
- Adopted-host scoping: on an adopted host, lint and the de-identification lint scan only the template's own files by default; `--all` restores the whole-tree scan.
- Release gate: added `harness/tools/release_check.py`, the ship-gate chain named in `ROADMAP.md`'s v0.1.0 gate.
- Docs corrections: removed the false Git Bash `ln -s` copy claim (`bootstrap.sh` delegates to `materialize.py`, which makes real NTFS junctions on Windows too); corrected stale skill-metadata, model-map, dispatcher-count, and pack-flag ("`--pack` replaces, not adds") claims across `README.md`, `docs/VERIFICATION.md`, `docs/ARCHITECTURE.md`, `docs/ROUTING-TASKS.md`, `docs/PACKS.md`, `CONTRIBUTING.md`, `brain/README.md`, and the doctor, research, and skillify skills.
- `adopt.py`: a Windows adopter's own commit recorded mode 644 for the landed `harness/*.sh` scripts and `.githooks/pre-commit` (`core.filemode` is false there, so the working tree carries no executable bit for git to read at commit time), which then failed the template's own lint L18 on the adopter's POSIX CI; adopt now stages the executable bit for those files in the target's git index on apply, chmods them on disk where POSIX supports it, and warns with the manual command when git is unavailable.
- `python -m pytest harness`: adopt also lands the test suite, and several guard, frontmatter, and structure-default tests assumed the template's own shipped `structure.json` or its own `README.md`/`docs/` prose; `HARNESS_STRUCTURE_FILE` now pins the affected fixture runs to the template's fixed default, and the tests that assert this checkout's own state skip with a stated reason when `structure.json` says `host.adopted` is true, so the suite is a valid, deterministic check on an adopted host.

## [0.1.1] - Planned

- decks and memory packs join the default selection once each is live-verified in a runtime; skills promoted past `spec-only` as evidence lands.
