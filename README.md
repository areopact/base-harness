# base-harness

One agent harness for three runtimes. A template repository that gives Claude Code, OpenAI Codex CLI, and OpenCode the same skills, rules, hooks, and optional memory lanes, defined once under `harness/` and materialized into each runtime's expected paths by a bootstrap script.

Audience: developers and technical professionals who also do knowledge work in the same repository.

## Status

| Runtime | Status | Evidence |
|---|---|---|
| Claude Code | verified live on the author's host (2026-09-08): contract loaded through the `CLAUDE.md` pointer, a selected skill invoked with `/doctor`, a rule auto-loaded, and a PreToolUse deny honored (a forced push refused with its `command-sha256`). SessionStart identity, PostToolUse advisory, and Stop rows still pending | `docs/VERIFICATION.md` |
| Codex CLI | verified live on the author's host (2026-09-08): contract loaded in a trusted session and a selected skill invoked with `$doctor` through the generated wrapper. Hook enforcement pending: Codex asks for interactive per-hook hash approval before a hook fires, which a headless run cannot grant; implicit routing is off by design until a skill is promoted past `spec-only` | `docs/VERIFICATION.md` |
| OpenCode | verified live on the author's host (2026-09-08) through the launcher: contract loaded, the generated `/doctor` command invoked, and a PreToolUse deny honored through the plugin bridge. Identity boot pending (no identity lane configured in this build) | `docs/VERIFICATION.md` |
| Skills | 12 skill folders ship as source under `harness/skills/`, all `spec-only`: core (6) and maintain (3) are selected by default and materialized per runtime (every catalog reads `9 selected of 12 available`); decks (2) and delegation (1) stay on disk until selected. The doctor skill has been invoked live on all three runtimes; its `metadata:` block loaded without a loader warning on Claude Code and OpenCode, and the generated Codex wrapper (name and description only) loaded on Codex | `docs/PACKS.md` |

Wording is deliberate. "Configured" means the files have the shape the runtime documents. "Verified" means someone ran it and watched the outcome, and the row in `docs/VERIFICATION.md` names the date, the scope, and how you reproduce it in your own clone. Nothing in this README claims more than that file does.

**No SLA.** This is a maintained side project. Issues and pull requests are read when the maintainer has time; there is no response window, no support channel, and no compatibility promise across runtime versions. Runtime hook, trust, and sandbox semantics change under us. If you need something you can rely on for a team, read `docs/VERIFICATION.md` and pin the runtime versions it names.

## Quickstart: new repository

1. Click **Use this template** on GitHub (clean history), or clone your copy. Then `cd` into it.
2. Run the bootstrap for your platform (below). It creates the runtime-facing links and generated trees, renders `AGENTS.md`, and points `core.hooksPath` at `.githooks/`.
3. Run the doctor for the runtime you use (below). It prints per-layer evidence: `configured`, `loaded`, `trusted`, `fired`, `enforced`, `outcome-proven`. A layer with no evidence prints `UNKNOWN`, never green.
4. Or run the `doctor` skill from inside a session once bootstrap has materialized the `maintain` pack: `/doctor` in Claude Code, `$doctor` in Codex CLI, or the generated `/doctor` command in OpenCode. It runs the same three doctors and reports per runtime. On a clone that has not been bootstrapped, nothing is materialized yet, so run the commands directly: `bash harness/bootstrap/doctor.sh`, `python harness/bootstrap/doctor_codex.py --offline`, `python harness/bootstrap/doctor_opencode.py --offline`.
5. Optional: `python harness/tools/init.py --lanes` to configure memory lanes, `python harness/tools/init.py --brain` to add the reference memory module, `python harness/tools/selector.py` to change which skill packs are materialized.

## Quickstart: existing repository (adopt)

1. From your repository root: `python /path/to/base-harness/harness/tools/adopt.py .` (or `python harness/tools/init.py --adopt <repo>` from inside the template).
2. Adopt copies the kernel (`harness/`, `.githooks/`, contract files) into your repository, never overwrites your README, merges host rules into `harness/rules/` by reserved-name rule, writes `harness/registry/structure.json` with every lane unset so nothing assumes a folder you do not have, and stages the executable bit on the landed scripts and hook so your own commit carries it forward.
3. Run the bootstrap and a doctor as in the new-repository path.
4. Commit the result on a branch and review the diff before merging; adopt is additive and reversible by deleting what it added.

## Requirements

- **git** on PATH.
- **bash** reachable by the runtime that runs hooks. Git for Windows installs `git` but does not put `bash` on PATH by default (it lives under `Git\bin`); check with `bash --version`. Without it, the hook wrappers cannot run and only the contract text governs.
- **Python 3.11+** (real CPython) for hooks, bootstrap, doctors, lint, and tools. Everything is stdlib-only; no installs. Hooks fail open without Python; bootstrap refuses to run without it. The floor is 3.11 because `tomllib` (Codex config and agent-role TOML parsing) is stdlib-only from that version; below it, `doctor_codex.py` fails closed with one clear line rather than silently skipping the checks.
- **NTFS** on Windows for junctions. On other filesystems, or when links misbehave, use copy mode (below).
- At least one of Claude Code, Codex CLI, or OpenCode.
- Optional: `pytest`. Tests also run under `python -m unittest discover -s harness -p "test_*.py"`.

## Bootstrap

macOS / Linux:

```sh
bash harness/bootstrap/bootstrap.sh            # materialize
bash harness/bootstrap/bootstrap.sh --check    # exit 1 on drift
bash harness/bootstrap/bootstrap.sh --copy     # recursive copies instead of links
bash harness/bootstrap/bootstrap.sh --force    # replace existing destinations
```

Windows (PowerShell), the Windows entry point. The `-ExecutionPolicy Bypass` avoids the default "running scripts is disabled" block. `bootstrap.sh` under Git Bash also works on Windows (both scripts delegate to `materialize.py`, which makes real NTFS junctions on Windows either way); use `bootstrap.ps1` unless you already have a Git Bash workflow:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\bootstrap.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\bootstrap.ps1 -Check
powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\bootstrap.ps1 -Copy
powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\bootstrap.ps1 -Force
```

Doctors (offline; they never call a runtime CLI or the network):

```sh
bash harness/bootstrap/doctor.sh                          # Claude Code
python harness/bootstrap/doctor_codex.py --offline        # Codex CLI
python harness/bootstrap/doctor_opencode.py --offline     # OpenCode
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness\bootstrap\doctor.ps1
```

Lint and regeneration (CI runs the same commands; see `.github/workflows/offline-conformance.yml`):

```sh
python harness/tools/lint.py --strict
python harness/tools/resolver_lint.py
python harness/tools/gen_manifest.py --check
python harness/bootstrap/build_codex_adapter.py --check
python harness/bootstrap/build_opencode_adapter.py --check
python -m pytest harness -q -p no:cacheprovider
```

## What is inside

| Layer | Where | Purpose |
|---|---|---|
| Contract | `AGENTS.md` (generated from `harness/CONTRACT.md` + `harness/CONTRACT.host.md`); `CLAUDE.md` is `@AGENTS.md` | operating principles every runtime loads |
| Skills | `harness/skills/<name>/SKILL.md`, materialized per selection | reusable workflows; packs and triggers in `metadata:` |
| Resolver | `harness/skills/RESOLVER.md` (generated from `metadata.triggers`) | intent to skill routing with target and neighbor |
| Rules | `harness/rules/` (`index.json` marks always-on vs path-scoped) | the detailed versions of the contract's principles |
| Hooks | `harness/hooks/lib/*.py` + `<event>/*.{sh,ps1}` wrappers + `codex-dispatch` | one Python implementation per hook, wrapped per runtime |
| Adapters | `harness/adapters/{claude,codex,opencode}/` | runtime-native config, generated from the registries |
| Registries | `harness/registry/*.json` | runtimes, structure (lanes, git mode, tiers), selection, capabilities, sources, environment |
| Memory | `brain/shared/` and `brain/local/` (optional module) | lanes declared in `structure.json`; the harness owns no memory content |
| Floor | `.githooks/pre-commit` | narrow secret scan, gitlink rejection, size floor; active once bootstrap sets `core.hooksPath` |
| CI | `.github/workflows/offline-conformance.yml` | file shape and determinism on three OSes; never runtime behavior |

The degradation ladder, per hook event and runtime: native hook where the runtime supports it, contract text in `AGENTS.md` where it does not, git pre-commit as the floor. `harness/registry/runtimes.json` declares the rung; the doctors print it.

The guards are seatbelts, not locks. `SECURITY.md` lists what each one does not catch.

## Traps (each one was hit for real)

1. **PowerShell execution policy.** A default Windows install refuses to run `.ps1` files. Use the `-ExecutionPolicy Bypass` form above, or set the policy once for your user.
2. **bash not on PATH.** Hook wrappers invoke `bash`. Git for Windows does not add it to PATH by default; without it the runtime reports the hook as failed or silent and only the contract text governs. Add `Git\bin` to PATH or install bash another way.
3. **Windows Store Python alias.** `python` and `python3` may resolve to a Microsoft Store stub that exits without running anything. Every wrapper and bootstrap probes candidates by executing them and skips the stub. If `python` misbehaves in your own shell, use `py` or install real Python.
4. **Non-NTFS filesystems and `--copy`.** Junctions need NTFS; symlinks need a filesystem and a git configuration that support them. On anything else (FAT, exFAT, some network shares, some containers) run bootstrap in copy mode and rerun it after every change to `harness/`, because copies do not track the source.
5. **OneDrive, Dropbox, and other synced folders.** Sync clients rewrite files on save and follow junctions, which breaks links and can double-upload the linked trees. Keep the repository outside synced folders, or use copy mode and accept the drift.
6. **Codex trust and per-hook hash approval.** Codex loads project config and hooks only for a trusted project, and approves each hook by the hash of its definition, so any edit to a hook definition needs re-approval before it fires again. Headless `codex exec` before trusting hangs on the interactive trust prompt. Trust the project interactively on first run, or add a project-scoped table to `~/.codex/config.toml` (a bare top-level `trust_level` does nothing):

   ```toml
   [projects."/abs/path/to/your/repo"]
   trust_level = "trusted"
   ```

   Also: `codex exec "<prompt>"` reads stdin and hangs on "Reading additional input from stdin" unless stdin is closed. Use `codex exec "<prompt>" < /dev/null` (or `< NUL` in cmd, `$null |` in PowerShell).

## Documentation

- `docs/ARCHITECTURE.md`: layers, registries, the degradation ladder.
- `docs/VERIFICATION.md`: per-runtime evidence rows, last live test date, scope, how to reproduce.
- `docs/PACKS.md`: the skill catalog by pack and status.
- `docs/LANES.md`: memory lanes and the brain module.
- `docs/HOST-SHAPES.md`: solo repository, adopted repository, private source.
- `docs/ADDING-A-SKILL.md`: the owner-first rule and the frontmatter contract.
- `docs/ROUTING-TASKS.md`: the opt-in delegation engine and its task IDs.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `ROADMAP.md`.

## License and attribution

MIT. See `LICENSE`. Third-party notices are generated into `THIRD-PARTY.md` from `harness/registry/sources.json`.

Built by Clawford at Areopact.
