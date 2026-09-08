# harness/bootstrap/

Turns a fresh clone into a working Claude Code, Codex CLI, and OpenCode environment by materializing runtime paths (`.claude/`, `.codex/`, `.agents/`, `.opencode/`, the root `opencode.json`, and the rendered `AGENTS.md`) from the canonical `harness/` tree. Run once per clone and again after changing an adapter, the registry, the skill selection, the junction manifest, or the contract. Verify anytime with `--check`; diagnose with the doctors.

## Commands

| Command | What it does |
|---|---|
| `bash harness/bootstrap/bootstrap.sh [--check\|--copy\|--force]` | POSIX and Git Bash entry point |
| `powershell -File harness/bootstrap/bootstrap.ps1 [-Check\|-Copy\|-Force]` | Windows entry point (add `-NoProfile -ExecutionPolicy Bypass` when the policy blocks scripts) |
| `bash harness/bootstrap/doctor.sh` / `powershell -File harness/bootstrap/doctor.ps1` | Claude Code doctor (offline) |
| `python harness/bootstrap/doctor_codex.py --offline` | Codex doctor; `--runtime`, `--network`, `--auth`, `--probe-skill-loading` opt into probes |
| `python harness/bootstrap/doctor_opencode.py --offline` | OpenCode doctor; `--runtime` adds version and agent-list probes |
| `python harness/bootstrap/build_codex_adapter.py [--check] [--output DIR]` | generate or verify the Codex skill catalog |
| `python harness/bootstrap/build_opencode_adapter.py [--check] [--output DIR]` | generate or verify the OpenCode commands |
| `python harness/bootstrap/contract_files.py render\|check\|repair` | compose or verify `AGENTS.md` and the `CLAUDE.md` pointer |
| `python harness/bootstrap/validate_skills.py [--catalog DIR] [--require-codex-catalog]` | skill frontmatter and exact catalog check |

Exit codes for bootstrap: `0` clean, `1` drift or an unresolved conflict, `2` a missing prerequisite (no working Python, no engine), `3` a manifest that fails to parse. `--check` never changes anything and exits `1` on any drift. Outside a git repository (or without git on PATH) the pre-commit floor cannot be registered; bootstrap and the doctors report that as a warning, not drift, so copy mode in a plain directory still exits `0`.

## Files

| File | Role |
|---|---|
| `bootstrap.sh`, `bootstrap.ps1` | Thin entry points. Each runs an execute-probe for Python (a candidate must run `import sys; sys.exit(0)` with exit 0, so an app-store alias or a broken shim is skipped), warns when `bash` is absent (hook wrappers will not run; the contract text still governs), then delegates to the engine. Both cannot diverge because neither carries materialization logic. |
| `materialize.py` | The engine: `plan(root, mode)`, `apply(root, mode, check, force, copy)`, `prune(root, selected)`. Reads `junctions.json` and `harness/registry/selection.json`, renders the contract, creates or repairs every destination, materializes selected skills per runtime, prunes deselected harness-managed entries, runs `extensions/`, and registers the git floor. |
| `junctions.json` | The materialization manifest: `junctions` (src, dst, mode, runtime, description), `retired_destinations`, and `per_skill` (per-runtime skill directories). Every row mirrors `harness/registry/runtimes.json` materializations; the registry validator and the lint fail on any disagreement. |
| `contract_files.py` | Contract composition: `AGENTS.md` is `harness/CONTRACT.md`, one blank line, `harness/CONTRACT.host.md`, normalized to UTF-8 LF with no BOM. `CLAUDE.md` is exactly `@AGENTS.md` plus a newline. `.codex/AGENTS.md` and `.claude/CLAUDE.md` are retired copies: `check` reports them and `repair` removes them. `check` prints the first differing byte offset. |
| `skill_catalog.py` | Frontmatter reader (the documented YAML subset) and the selection rule: union of skills whose `metadata.packs` intersects the selected packs with `include`, minus `exclude`. Vendored skills under `_vendor/<source>/<name>/` are read too. |
| `build_codex_adapter.py` | Generates `.agents/skills/<name>/` (a compact `SKILL.md` wrapper plus an `openai.yaml` interface file under `agents`) for selected, non-stub skills. Every generated directory carries a `.generated-by` marker; the root carries `.catalog.json`. |
| `build_opencode_adapter.py` | Generates `.opencode/commands/<name>.md` for selected, non-stub skills, each carrying a generator marker comment. |
| `doctor_claude.py`, `doctor_codex.py`, `doctor_opencode.py` | Offline doctors, one per runtime. `doctor_common.py` holds the shared `Audit` model and the shared repository checks; `schema_check.py` is the stdlib JSON Schema subset validator the doctors use on every generated runtime JSON file. |
| `doctor.sh`, `doctor.ps1`, `doctor-codex.{sh,ps1}`, `doctor-opencode.{sh,ps1}` | Wrappers with the same execute-probe; the Codex and OpenCode wrappers pass `--offline` when given no arguments. |
| `validate_skills.py` | Frontmatter validation for every skill and, with `--catalog` or when `.agents/skills` exists, exact catalog equality. |
| `extensions/` | Optional host extension point, shipped absent. When present, every file in it runs in sorted order (`.py`, `.sh`, `.ps1`, or an executable), receives `--check` in check mode, and a non-zero exit counts as drift. |
| `tests/` | The regression suite (see below). |

## The four materialization modes

| Mode | Meaning |
|---|---|
| `link` | directory junction (Windows) or symlink (POSIX) from the destination to the source; `--copy` renders it as a recursive copy, and `--check` accepts a content-equal copy |
| `managed-copy` | independent byte-exact file copy, never a hardlink or symlink; editing the destination never changes the source, and `--check` reports the drift |
| `generated` | the destination tree is produced by a named generator from the source tree; `--check` compares the exact file set and bytes |
| `contract-render` | the destination is produced by `contract_files.py`; every contract-render row is served by the root `AGENTS.md` render, and a second rendered copy elsewhere is kept absent so a runtime that reads the root pointer never loads the contract twice |

## Per-skill materialization and prune

The selected set comes from `harness/registry/selection.json` plus each skill's `metadata.packs`. Per runtime:

- Claude Code: one link per selected skill at `.claude/skills/<name>`.
- Codex: one generated directory per selected skill under `.agents/skills/`.
- OpenCode: one link per selected skill under `harness/.selected/skills/`, that tree linked as `.opencode/skills`, and one generated command per selected skill under `.opencode/commands/`.

An entry under those directories whose name is not selected is pruned only when it is harness-managed: a link that resolves into `harness/skills`, or a directory or file carrying the generator marker. Anything else is left in place and reported as `unmanaged, left in place`. Zero skills on disk is legal: bootstrap reports `0 selected of 0 available` and succeeds.

## Safety invariants

- A destination that is empty, resolves to the repository root, or resolves outside it is refused with `ABORT refusing dangerous or empty destination` before anything is removed, and counts as drift.
- A real directory without a harness marker is never recursively removed, not even with `--force`; move it aside or run `--copy` to resync it in place. Reparse points and symlinks are unlinked non-recursively, so a link's target is never touched.
- A manifest that fails to parse aborts with exit 3; it never yields zero entries silently.
- Managed copies are independent files; a hardlinked or symlinked destination is reported as drift and replaced.
- The git floor: `core.hooksPath` is set to `.githooks`. When it was already set to something else, the prior value is recorded in the local key `harness.chainedHooksPath` first, and `.githooks/pre-commit` chains to it after its own checks. Bootstrap never writes into `.githooks/`.

## Doctor output

Each check prints `  [<layer>] <state> <message>` with the layer padded to 14 characters and the state to 7. Layers are `configured`, `loaded`, `trusted`, `fired`, `enforced`, `outcome-proven`; states are `OK`, `WARN`, `FAIL`, `UNKNOWN`. The roll-up block prints one line per layer (`PASS`, `PARTIAL`, `UNKNOWN`, `FAIL`), and the last line is `Result: repository PASS|FAIL; runtime evidence PROVEN|INCOMPLETE; n warning(s), m failure(s)`. A layer with no evidence prints `UNKNOWN`, never `PASS`. Offline doctors populate only `configured`; the other layers stay `UNKNOWN` with an explicit reason until a live run is recorded in `docs/VERIFICATION.md`. Every doctor prints the degradation rung per hook event from `harness/registry/runtimes.json` and reconciles the selected-skill count from the materialized artifacts to `selection.json`; a mismatch is a `configured` FAIL.

## Recovery sweep

Run this top to bottom when a runtime will not start, links point at the wrong targets, hooks stay silent, or a doctor reports drift; most failures share one root cause the bootstrap already fixes.

1. Stop the running session first; repairs under an active session with open file locks are harder to diagnose.
2. Run the doctor for your runtime. It names the failing layer and a remedy per line.
3. Run the bootstrap. It is idempotent: links, managed copies, generated catalogs, the contract, and the git floor are re-checked and repaired.
4. Run `--check`. Exit 0 means the tree matches its sources byte for byte.
5. If a link is reported as a real directory with different content, move that directory aside and rerun; bootstrap never deletes it for you.
6. If bootstrap exits 2, install CPython 3.11+ so that `python3 -c "import sys; sys.exit(0)"` succeeds (an app-store alias does not count).
7. If the repository moved on disk, rerun bootstrap from the new location; junctions carry absolute targets.
8. Restart the runtime from the repository root.

## Tests

`python -m pytest harness/bootstrap/tests -q -p no:cacheprovider` (plain pytest style; every file also imports under `python -m unittest discover -s harness -p "test_*.py"`). The suite covers the data-loss canary (empty, root, and escaping destinations), the real-directory refusal, `--check` drift detection, copy mode plus the three doctors, managed-copy independence, contract composition, per-skill materialization and prune, zero skills, the shell execute-probe (POSIX), hooksPath chaining, the doctor output format, the stale-link replacement hazard, and strict runtime JSON with a seeded underscore key. Windows and POSIX both run the shell entry-point tests through the host's bash and PowerShell when present.
