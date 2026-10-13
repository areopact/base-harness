# Changelog

All notable changes to this repository. Format follows Keep a Changelog; versions follow semantic versioning. Dates are ISO 8601.

## [0.2.0] - Unreleased

### Added

- The v0.2 skill contract, an additive extension of the skill frontmatter. `metadata.form` (`procedure`, `criteria`, or `reference`) says what a skill body tells the agent; `metadata.dependencies` is a list drawn from `code`, `system`, and `agents`, omitted when a skill needs none. Both are optional, and any other value is rejected by `harness/bootstrap/validate_skills.py`.
- An optional `evals/` folder per skill: `triggers.tsv` (header `prompt`, `expect`, `competitor`, with `expect` of `select` or `skip`), `cases.md` (outcome cases with input, acceptance checks, and a without-skill note), and `ledger.tsv` (the eleven-column run ledger). When the folder exists the validator checks each file's shape; a skill without it is unaffected. `metadata.status` and promotion still follow the `docs/VERIFICATION.md` row (`CONTRIBUTING.md`); the ledger is protocol guidance the template does not compute.
- Advisory section checks for a declared form, printed as WARN lines and never changing the exit status: a procedure carries ordered steps (a numbered list or numbered headings, outside fenced code) and a `## Done when` section; a criteria skill carries `## Floors` and `## Ceilings`; a reference skill carries no ordered steps.
- `harness/tools/templates/skills/` with a `procedure`, a `criteria`, and a `reference` skeleton, each with complete frontmatter, the sections its form expects, and an `evals/` trio with a placeholder case to delete or replace.
- `docs/ADDING-A-SKILL.md` documents the forms, dependencies, the description rule, the `## Done when` convention, and the evaluation protocol as guidance. A table now names which tool enforces each frontmatter row (lint L4 or `validate_skills.py`).
- CI runs `python harness/bootstrap/validate_skills.py` after the strict lint step; `CONTRIBUTING.md` lists it among the local checks.

### Compatibility

- A v0.1 skill passes the v0.2 validator unchanged, with no error and no warning, unless it already used `metadata.form`, `metadata.dependencies`, or an `evals/` folder with other meanings. Migration for that case: rename the key or folder, or bring its values and files to the v0.2 shapes. `harness/bootstrap/tests/test_skill_contract.py` proves it on a v0.1 fixture and on this repository's own skills.
- The success line is byte-identical when there are no warnings. No key is removed or renamed, `WHEN:` stays required in descriptions, and `validate_source` keeps its return shape.

### Fixed

- Three current-file uses of the generic private-source term from the seed term list are reworded so the term-list release check no longer reports them: two in `START_HERE.md` (the Obsidian setup prose and step) and one in the `harness/bootstrap/links.py` module docstring. Behavior is unchanged.

### Added

- `harness/tools/deidentify-accepted-history.txt` records accepted historical term findings (full commit SHA, path, term). `deidentify_lint.py --history` suppresses only a TERM finding that matches all three fields, reports an entry that matches nothing as `STALE` (exit 1), exits 2 on a malformed line, and skips the file from every scan. It holds the two findings in published commits that cannot be rewritten. This loosens a release gate and needs independent review.

## [0.1.6] - 2026-10-14

### Fixed

- The openpyxl guard's path scans are linear in the length of the command. Its two unquoted-path patterns retried from every position inside a long run of path characters, so cost grew with the square of the run: a 160 KB command took over 45 seconds, the hook timed out, and the deny for a save against an existing workbook was lost with it. Both scans now walk each run of path characters once and return exactly the lists the patterns returned, so the same command is judged in well under a second. Every extracted path is still probed on disk, so a command that names tens of thousands of distinct paths can still outlast a hook timeout.
- The openpyxl guard sees unquoted drive-qualified paths. The path character class has no colon, so an unquoted script or workbook path that began with a drive letter was extracted without its drive and resolved against whatever drive the process or the payload working directory was on; a script or workbook on another drive was never found and the save was allowed. A second phase, run only when the first allowed, rebuilds the drive-qualified form (one ASCII letter, a colon, a path starting with a slash, not glued to a longer word) and repeats both checks against it. It runs after the first phase has decided, so a probe that stalls on an unreachable drive cannot cost a deny the first phase would have issued, and an error inside it falls through to allow. Still without a candidate: drive-relative paths, extended-length paths, an option glued to the drive letter, file URLs, and paths with spaces or a tilde. On Windows, a Git Bash drive path (a leading slash, the drive letter, a slash) is not mapped to its drive. `harness/hooks/tests/test_openpyxl_guard.py` carries the parity, drive-candidate, timing, host-independent decision and wiring, and cross-drive tests.

## [0.1.5] - 2026-09-27

### Added

- `adopt.py --upgrade <host> [-y] [--source <template>] [--skip GLOB ...]` refreshes an adopted host to the template's committed HEAD, dry run by default. Content is read blob by blob with `git show` from the source's HEAD, never its working tree. It refuses a host that is not adopted, has any uncommitted or untracked change, or has tracked files missing from disk (an incomplete checkout, the state in which a broad staging command commits mass deletions), and refuses when the source is the target or is itself an adopted host. Each candidate is reported as `update`, `new`, `skip` with a reason, or `gone`. Host-owned files (the registry, the host contract, the root files adopt installs and hosts then own), paths the host deleted, untracked or ignored files, unsafe paths (backslash, colon, absolute, `..`), and any path whose destination or parent is a link are never written; nothing is ever deleted. New shell scripts land with the executable bit staged, `adopted-files.json` records the new template version, and a post-apply check fails loudly on any deletion.

### Fixed

- Generated catalogs are no longer locked to the Administrators group when bootstrap runs elevated. Since Python 3.13 on Windows, `tempfile.mkdtemp`'s `0o700` becomes a protected owner-only ACL, and under an elevated token the owner is the Administrators group; the Codex skill catalog staged each skill in such a directory and renamed it into place, so a catalog generated from an elevated shell (the recovery path 0.1.4 recommends for untrusted junctions) became unreadable and undeletable once the shell ran at medium integrity, and git reported every catalog file as deleted. The catalog writer now stages with a plain `mkdir` that inherits the parent's ACL. `harness/bootstrap/tests/test_no_owner_only_staging.py` fails on any `tempfile.mkdtemp` in a production module. Recovery for an already-locked catalog without elevation: move the whole `.agents/skills` directory out of the repository (a rename needs no access to the locked children), then rerun bootstrap.

### Changed

- The directory-link primitives (create, unlink without touching the target, match, and the one-read Redirection Guard probe) move from `materialize.py` into `harness/bootstrap/links.py`, a stdlib-only module with no repository knowledge. `materialize.py` and the doctors import it under the same names. The upstream harness this template is ported from uses the same file byte for byte, and its drift release gate fails when the copies differ, so a link fix lands once for both.

## [0.1.4] - 2026-09-17

### Fixed

- Junctions an elevated process cannot traverse are repaired instead of reported healthy. Windows Redirection Guard stamps a junction with its creator's trust level and refuses to let an elevated process follow one created non-elevated (Win32 448, "untrusted mount point"). A terminal that runs elevated, which some launchers do, then loses every materialized link at once, while `--check` and the doctors still said OK because they compared link targets without traversing them, and bootstrap could not repair anything because its registry preflight died on the first blocked link. The engine now probes one read through each link: check mode reports the block as drift with the remedy; apply mode unlinks and recreates the junction, and that recreation from the elevated process carries a trusted stamp while junctions created by a non-elevated bootstrap stay valid for non-elevated tools; when the registry preflight itself is blocked, the link rows are repaired first and the preflight runs again. The three doctors report a blocked link, or blocked skill links, as a `configured` FAIL naming the remedy. Observed on the author's host after a Windows security update on 2026-09-14.

## [0.1.3] - 2026-09-12

### Changed

- The commit skill commits in proportion. A routine commit is a bounded local git operation: no planning agents, no fresh review cycle, no whole-repository lint, and no external call of its own. The review starts from `git status --short` and `git diff --cached --name-status`, selects paths before reading content, and reads diffs for the selection only; a verification that already ran in the session after the last edit to a selected path is cited rather than rerun, and a failed check is rerun alone; the close-the-loop lane steps cover only what the session created, and an unfiled learning is reported as outstanding instead of blocking the commit; the final race check, explicit staging, the staged-diff drift check, and the commit run as one operation (`git commit -F` with a message file on PowerShell, a quoted heredoc in Bash), verified once afterwards. Branch discipline, verification discovery, the sign-off rule, and the stop-after-commit rule are unchanged.

## [0.1.2] - 2026-09-11

### Fixed

- `adopt.py` wrote `host.adopted: false` and an empty `host.roots` for a target without an `AGENTS.md`, so the lint and the de-identification check scanned the host's whole tree instead of the template's files; every adoption now records `adopted: true` and the detected roots, and `contract.mode` alone records the host-owned contract.
- The de-identification check flagged attribution strings in `harness/CONTRACT.host.md`, the host's own contract notes; that file now speaks in the host's voice.

### Added

- `.githooks/secret-scan-exclude.txt`: a host-declared list of repository-relative paths or globs (one per line, `#` comments) that the pre-commit content and filename scans skip, for evidence trees a host tracks on purpose and never edits. Never shipped; documented in the hook header, `SECURITY.md` and `docs/HOST-SHAPES.md`.

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
