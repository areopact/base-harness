# Changelog

All notable changes to this repository. Format follows Keep a Changelog; versions follow semantic versioning. Dates are ISO 8601.

## [0.1.1] - 2026-09-11

### Added

- `write-deny`: a PreToolUse guard that denies an agent write (Write, Edit, NotebookEdit, apply_patch) to any path matched by `structure.json` `write_deny.globs` and not by `write_deny.except`. Shipped off (empty globs); a host switches it on by naming the paths it reserves for human authors. Registered under `Write|Edit|NotebookEdit` on Claude Code; Codex and OpenCode reach it through the dispatcher. Fixture group `write-deny`, unit tests in `test_write_deny.py`.
- `structure.json` gains `write_deny` (`globs`, `except`) in both loaders, the schema, and the shipped defaults. The key is additive and forward-only: a 0.1.0 structure without it validates, a structure that sets it fails the validating loader on a 0.1.0 kernel.
- Upgrading an adopted host: re-run the bootstrap (or its `--check`) after taking the kernel, so the new `Write|Edit|NotebookEdit` registration lands in `.claude/settings.json`; without it the wrapper is present and Claude Code never calls it.

## [0.1.0] - 2026-09-10

Initial public template.

### Added

- Kernel: registry-driven bootstrap (`--check`, `--copy`, `--force`), contract composition (`harness/CONTRACT.md` + `harness/CONTRACT.host.md` rendered to `AGENTS.md`), offline doctors for Claude Code, Codex CLI, and OpenCode with six evidence layers, hook library with one Python implementation per hook and per-runtime wrappers, `.githooks/pre-commit` floor, strict runtime JSON schemas, kernel manifest.
- Registries: `runtimes.json`, `structure.json` (five lanes, git mode, tiers, brain, delegation flag, `host.profile` and `host.verify_command`), `selection.json`, `capabilities.json`, `sources.json`, `environment.json`.
- `init.py --profile`: a four-question interview (who works here, how work lands, where personal notes live, whether to set the five lanes now) behind a `solo` or `team` preset, or `--profile <solo|team> --yes` for the non-interactive form; sets `host.profile`, `git.mode`, `brain.local_path`, and the derived `contract.mode` in one pass.
- Selector: `selector.py` with materialize-and-prune; packs declared in skill `metadata.packs`; shipped default `core` plus `maintain`.
- Skills, v0.1.0 catalog: core (brainstorm, prompt, eli5, research, review, humanize), maintain (doctor, commit, skillify), delegation module (workflow, opt-in). Shipped on disk but not selected by default: decks (deck-outline, deck-render --web); `--pack` replaces the current pack list rather than adding to it, so select it on top of the shipped default with `selector.py --pack core --pack maintain --pack decks`.
- Memory lanes and the optional reference memory module (`brain/shared`, `brain/local`).
- Classification and export: five labels, `export.py` copy mode with its own fuzz suite, `frontmatter_guard`.
- `adopt.py` and `init.py` for existing repositories.
- lint L19: `host.profile` absent is a ship-gate note with the repair command; a value outside `solo`/`team`, or a `host.verify_command` that is not `null` and does not match the `npm run`, `pnpm run`, `yarn`, or `make` shape, is an error.
- `metadata.requires` gains the `fact:<key>` shape over a closed set (`host.profile`, `git.mode`, `contract.mode`, `brain.local_tracked`, `delegation.mandatory`, `selection_scope`); a `SKILL.md` body that names `host.profile` must declare `fact:host.profile`.
- The Stop hook's closing clause is composed from `git.mode` and `host.profile` together.
- Docs: ARCHITECTURE, VERIFICATION, PACKS, LANES, HOST-SHAPES, ADDING-A-SKILL, ROUTING-TASKS.
- CI: offline conformance on ubuntu, windows, and macos; fresh-template job; permission-posture assertion; de-identification lint.
- `commit` skill and `git-workflow.md`: a commit message never includes a session link or session URL; that identifier stays in the agent's own audit trail, never in a record the host's contributors will read.

### Removed

- Skills: the verify skill; its prove-before-done mode lives in doctor.
- Skills: the daily and capture skills; the template ships no triage cadence, so a journal and an inbox have no reader, memory stays pages, and the journal lane is removed with them.
- Migration: hosts that pulled a pre-profile kernel run `python harness/tools/init.py --profile <solo|team> --yes`, which removes the retired `journal` key from `lanes` and `tiers.lane_defaults` and prints that it does; every other command refuses the file and names the keys to delete.

### Deprecated

- `host.profile` is optional in this release's schema (absent defaults to `solo`); it becomes required in the next minor release.

### Security

- Guards documented as seatbelts, not locks, with named bypass fixtures (see `SECURITY.md`).

### Changed

- `verify` folds into `doctor` as its "prove before done" mode, carrying the four trigger phrases and the evidence ladder that used to live in the standalone skill.
- `adopt.py` writes `host.profile: team` on every new adoption, regardless of the detected `git.mode`, and prints the command a solo adopter runs to switch.
- The `commit` skill reads `git.mode` and `host.profile` apart: `git.mode` decides branch discipline; `host.profile` decides verification discovery (a team host's own `host.verify_command`, then `package.json`'s `scripts.verify`, then a `Makefile` `verify` target, then the harness lint, said plainly) and pull request etiquette.
- `commit` skill and `git-workflow.md`: a `Signed-off-by` footer is added only when the host's own `CONTRIBUTING.md` affirmatively states that commits carry a DCO sign-off or a `Signed-off-by` trailer; a sentence saying sign-off is not required, an absent file, or an ambiguous mention no longer trigger the footer, and an ambiguous case is named in the summary rather than guessed.
- Publication history: the pre-publication working history on the private remote was squashed into one signed, signed-off initial commit before the visibility flip, so the public history starts from a tree that passes the release gate (structural and private-vocabulary de-identification over the full history, both clean).
- On a configured host, `init.py --profile <solo|team> --yes` changes `host.profile` only and prints what it kept.

### Fixed

- `init.py --adopt <target> --yes`: `--yes` is a global flag on `init.py`'s own parser, so it never reached `adopt.py`, which has no `--yes` flag (only `-y`/`--apply`), and the adoption silently ran as a dry run; `init.py` now translates `--yes` to `--apply` before forwarding to `adopt.py`.
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
- `adopt.py`: the branches-mode external `brain.local_path` was named after the adopting checkout's own folder (`~/.harness-local/<folder-name>`), so a one-off clone name landed in the host's committed `structure.json` for every future editor; the name now derives from the target's git `origin` remote (https or ssh form, `.git` stripped, sanitized to `[A-Za-z0-9._-]`), falling back to the folder name only when there is no usable origin, and the chosen name and its source print in adopt's output.
- `init.py --brain`: the scaffold placed `brain/README.md`, `brain/shared/IDENTITY.md`, and the local lane's `OPERATOR.md` but never `brain/shared/README.md` or `brain/local/README.md`, both listed in `harness/kernel-manifest.json` and required by lint L6 as soon as any lane points into `brain/`; a clean scaffold on an adopted host failed L6 twice with no file to place them by hand. The scaffold now places every manifest-listed `brain/` file.
- `harness/registry/tests/test_harness_registry.py::test_selection_validates_and_rejects_overlap`: asserted the template's own shipped `selection.json` packs (`["core", "maintain"]`), which no adopted host that changes its selection can satisfy; the packs assertion now lives in its own `test_shipped_selection_packs`, skipped on an adopted host with the same `_host_adopted()` idiom already used in `test_structure_defaults.py`, and the overlap-rejection assertions stay unconditional.

## [0.1.1] - Planned

- decks and memory packs join the default selection once each is live-verified in a runtime; skills promoted past `spec-only` as evidence lands.
