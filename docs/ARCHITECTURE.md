# Architecture

One canonical tree under `harness/` describes how an agent works in this repository; a bootstrap script materializes that tree into the paths Claude Code, Codex CLI, and OpenCode each expect; three offline doctors report what evidence exists per runtime. This page describes the built repository as it is. Where a mechanism is planned but not built, the page says so.

## Behavior versus state

The repository separates what the agent does from what the agent knows, and both from what a runtime reads.

| Concern | Where | Who edits it | Evidence that it is intact |
|---|---|---|---|
| Behavior: contract, rules, skills, hooks, adapters, registries, tools, bootstrap | `harness/` | the template (kernel) and the host (rules merged by adopt, `CONTRACT.host.md`, `structure.json`, `selection.json`) | `python harness/tools/lint.py --strict`, the registry validator, the test suites |
| State: memory lanes and the optional reference memory module | the paths named in `harness/registry/structure.json` `lanes`; by default `brain/shared/`, `brain/local/`, `docs/decisions/`, `docs/` | the operator and the agent, under the memory rules | the frontmatter guard on write, `export.py` at export time, `close_the_loop` at session end |
| Runtime outputs | `.claude/`, `.codex/`, `.agents/`, `.opencode/`, root `opencode.json`, root `AGENTS.md` and `CLAUDE.md`, `harness/.selected/` | nobody by hand; bootstrap creates and repairs them | `bootstrap --check` exits 1 on any drift; the doctors count materialized skills and reconcile to `selection.json` |
| Shared project documentation | `docs/` (the default docs lane) | maintainers | lint L10 on `docs/VERIFICATION.md`; the L9 allowlist permits `docs/**` to name bootstrap paths |

The harness owns no memory content. Every hook and tool reads lane paths from `structure.json` and treats a lane set to `null` as "not configured"; nothing hardcodes a host path (`harness/hooks/tests/test_structure_parameterization.py`, lint L13). Runtime outputs that are links are ignored by git; runtime outputs that are managed copies, generated trees, or the rendered contract are byte-checked against their sources.

## Canonical shape

```text
AGENTS.md                      GENERATED from harness/CONTRACT.md + harness/CONTRACT.host.md
CLAUDE.md                      exactly "@AGENTS.md" plus a newline
.githooks/pre-commit           the git floor: narrow secret scan, filename block, gitlink rejection, size floor
.github/workflows/offline-conformance.yml   file shape and determinism on three operating systems
harness/
  CONTRACT.md                  template block of the contract
  CONTRACT.host.md             host block; the template never edits it
  kernel-manifest.json         every kernel file with state ported | new and its source path
  registry/                    runtimes, structure, selection, capabilities, sources, environment, collaborators
  rules/                       always-on and path-scoped behavior law; index.json is the machine-readable list; a path-scoped rule carries `paths:` frontmatter, which only Claude Code honors (auto-loaded through the `.claude/rules` link; the rule loads only when a matching file is touched). Codex and OpenCode do not materialize harness/rules/ at all: the rendered contract's lookup section points at each rule page, and the agent reads it on demand, with `paths:` frontmatter carried along as inert text
  skills/                      README, generated RESOLVER.md, one folder per skill (14 in this build)
  hooks/                       lib/*.py canonical modules; <event>/*.{sh,ps1} wrappers; codex-dispatch; tests/
  adapters/                    claude/, codex/, opencode/ native configuration sources; model_map.py; tests/
  agents/                      documents the generated-role mechanism; holds no role files
  bootstrap/                   bootstrap.{sh,ps1}, materialize.py, junctions.json, contract_files.py, doctors
  tools/                       lint, resolver_lint, gen_manifest, routing_policy, native_routing, workflow,
                               select, init, adopt, export, deidentify_lint, skill_usage, templates/
brain/                         optional reference memory module: README, shared/, local/ (ignored)
docs/                          this documentation; the default docs lane
```

Fixed points of the shape: the five lane names are fixed and every lane is either a list of repository-relative paths or `null`; the decisions lane defaults to `docs/decisions`; the shipped selection is `core` plus `maintain`; lane folders are created on first write, never pre-created; no tracked file outside `docs/`, `README.md`, and the allowlisted component READMEs may link to a bootstrap-created path (lint L9).

## Registries

`harness/registry/` holds small versioned relationship maps. `python harness/tools/harness_registry.py` validates all of them (nine checks in this build) and exits 1 on any error.

| File | Declares | Read by |
|---|---|---|
| `structure.json` | host facts: the five lanes, `git.mode`, `outbound_globs`, `brain.local_path` and `brain.local_tracked`, `tiers.lane_defaults` and `tiers.unlisted_path`, `delegation.mandatory`, `selection_scope`, `host.profile`, `host.verify_command` | every kernel file that needs a host fact, through `harness_registry.load_structure()` (validating, raises) or `hook_io.load_structure()` (standalone, fails open); the two must agree |
| `structure.schema.json` | JSON Schema for `structure.json`, closed at every level | CI, the doctors, `tests/test_structure_defaults.py` |
| `selection.json` | `packs`, `include`, `exclude` | bootstrap materialization, the two adapter generators, the doctors |
| `runtimes.json` | per runtime: tier, status, adapter and doctor paths, capabilities, `identity_context_limit`, materializations; retired materializations; `hook_events` with support, delivery, context limit, and the degradation rung per runtime | bootstrap, `contract_files.py`, `dispatch.py`, `load_identity.py`, the doctors, lint L2 and L8 |
| `capabilities.json` | runtime-provided capabilities with kind, per-runtime state, offline probe, and the in-skill fallback sentence | lint L4 for every `metadata.requires` entry, the doctors |
| `sources.json` | provenance and license per asset group | `gen_manifest.py --licenses`, lint L4 (packs never mix licenses) |
| `environment.json` | environment policy and, for a host, variable names and symbolic locations; never a value, digest, presence result, or absolute path | the registry validator only; the shipped file carries the policy block and empty maps |
| `collaborators.yaml` | ids and tier ceilings for the `restricted` label; shipped empty | `export.py --tier restricted`, the frontmatter guard |

Three generated caches under `harness/registry/` are untracked and rebuilt on demand: `delegation-policy.json` (from `routing_policy.py compile`), `native-routing-files.json` (from `native_routing.py render`), and `skill-index.json` (from `gen_manifest.py`). Their absence is never drift.

Two host facts in `structure.json` split verification and etiquette from branch discipline: `host.profile` (`solo` or `team`, optional this release, `solo` when absent) decides how the commit skill discovers verification and whether a pull request applies, and how the Stop hook composes its closing clause; `host.verify_command` (`null`, or a shape-restricted `npm run`, `pnpm run`, `yarn`, or `make` invocation) names a team host's own verification command, tried before `package.json`'s `scripts.verify`, a `Makefile` `verify` target, and the harness lint, in that order. `metadata.requires` also accepts the `fact:<key>` shape over a closed set (`host.profile`, `git.mode`, `contract.mode`, `brain.local_tracked`, `delegation.mandatory`, `selection_scope`); lint L19 requires the ship-gate repair when `host.profile` is absent and flags a skill body that names `host.profile` without declaring `fact:host.profile`.

## Contract composition

`AGENTS.md` is `harness/CONTRACT.md`, one blank line, then `harness/CONTRACT.host.md`, normalized to UTF-8 with LF endings and no byte-order mark. `CLAUDE.md` is the bytes `@AGENTS.md` plus a newline, nothing else. There is no `.codex/AGENTS.md` and no `.claude/CLAUDE.md`: Codex and OpenCode read the root file natively, Claude Code follows the pointer, and `contract_files.py check` reports either retired copy as drift. The budget is 32768 bytes for the whole rendered file (lint L2), which is the cap Codex applies to `AGENTS.md`.

The template block carries the seven operating principles, the skills section, the opt-in delegation note, and per-runtime notes. The host block is where an adopting repository describes its own layout; `adopt.py` preserves it and bootstrap appends it on every render.

## Materialization modes

Every runtime-facing path is declared twice, in `harness/bootstrap/junctions.json` and in `harness/registry/runtimes.json` `materializations`, with the same source, destination, and mode; lint L8 fails on any disagreement. The mode vocabulary is closed at four values.

| Mode | Meaning | `--check` behavior |
|---|---|---|
| `link` | directory junction on Windows, symlink on POSIX, from the destination into `harness/`; `--copy` renders a recursive copy | accepts a link that resolves correctly or a content-equal copy |
| `managed-copy` | independent byte-exact file copy, never a hardlink; editing the destination never changes the source | reports any byte difference as drift |
| `generated` | the destination tree is produced by a named generator (`build_codex_adapter.py`, `build_opencode_adapter.py`) from the source tree | compares the exact file set and bytes |
| `contract-render` | the destination is produced by `contract_files.py` | compares to a fresh render |

The engine is `harness/bootstrap/materialize.py`; `bootstrap.sh` and `bootstrap.ps1` are thin entry points that execute-probe Python (a candidate must run `import sys; sys.exit(0)` and exit 0, which skips an app-store alias), warn when `bash` is absent, and delegate. Safety invariants: a destination that is empty, is the repository root, or resolves outside the repository is refused before anything is removed; a real directory without a harness marker is never recursively removed, not even with `--force`; a manifest that fails to parse exits 3 rather than yielding zero entries; the git floor is registered by setting `core.hooksPath` to `.githooks`, recording any prior value in the local key `harness.chainedHooksPath` so `.githooks/pre-commit` can chain to it. Bootstrap also sets `merge.ours.driver` to `true` so the `merge=ours` attribute on generated files is honored in branches mode.

Per-skill materialization follows `junctions.json` `per_skill`: Claude Code gets one link per selected skill under `.claude/skills/<name>`; Codex gets one generated directory per selected skill under `.agents/skills/`; OpenCode gets one link per selected skill under `harness/.selected/skills/`, that tree linked as `.opencode/skills`, and one generated command per selected skill under `.opencode/commands/`. Deselected entries are pruned only when they are harness-managed (a link into `harness/skills` or a tree carrying the generator marker); anything else is left in place and reported.

## Hooks: envelope and dispatch

One Python module per hook under `harness/hooks/lib/`; one `.sh` and one `.ps1` wrapper per hook per event directory; one dispatcher (`harness/hooks/codex-dispatch.{sh,ps1}` around `harness/hooks/lib/dispatch.py`) that Codex and OpenCode call per event. Hooks are bounded, read-only, network-free, and stateless; the only write path is the opt-in tracer behind `HARNESS_HOOK_DEBUG_DIR`, and `tests/test_no_state.py` proves nothing is written without it.

The envelope is fixed on all three runtimes. Stdin is one JSON object (`hook_event_name`, `tool_name`, `tool_input`, `cwd`, `session_id`, `turn_id`; `input` is accepted for `tool_input`; `shell_command` maps to `Bash`; `agent`, `Task`, and `spawn_agent` map to `Agent`). Stdout is silence, one advisory object, or one deny object; deny is valid on `PreToolUse` only and its reason names the hook, the rung, a hash of the command, and one recovery sentence. The exit code is 0 for silence, advisory, and deny alike; 0 when Python or the module is absent (fail open); 2 is reserved and never emitted; any other non-zero exit is a malfunction, which the doctors report as FAIL and never as "enforced".

Shipped hooks and their rungs on the enforcement ladder (advisory, soft-block, hard-block):

| Event | Hook | Rung | Host fact it reads |
|---|---|---|---|
| SessionStart | `load-identity` | context injector | identity lane; `identity_context_limit` per runtime |
| SessionStart | `pre-bootstrap-detector` | advisory | `junctions.json` destinations |
| PreToolUse | `memory-first` | advisory | knowledge, decisions, docs, records lanes (filename stems only) |
| PreToolUse | `dangerous-ops-guard` | hard-block | `outbound_globs` as extra credential paths |
| PreToolUse | `openpyxl-guard` | hard-block | none |
| PreToolUse | `delegation-guard` | advisory, inert unless `delegation.mandatory` | `delegation.mandatory` |
| PreToolUse | `read-deny` | hard-block, shipped off, Claude Code only, needs `HARNESS_READ_DENY=1` | none |
| PostToolUse | `frontmatter-guard` | advisory | every configured lane; `collaborators.yaml` |
| PostToolUse | `prose-lint` | advisory | `outbound_globs` (empty by default, so silent) |
| PostToolUse | `delegation-guard` | advisory, inert unless `delegation.mandatory` | `delegation.mandatory` |
| Stop | `close-the-loop` | advisory | every configured lane; decisions as the evidence lane |

`dispatch.py` caps `additionalContext` at the `context_limit` declared per runtime and event in `runtimes.json` and appends a visible note when it truncates. SessionStart is budgeted per lane by weight (identity 40, knowledge 20, other 5) with a footer naming trimmed and omitted sources; it is never tail-truncated. The regression suite has 54 fixtures across the `guard`, `frontmatter`, `openpyxl`, and `read-deny` groups, each piped through the native wrapper and diffed byte for byte against an expected file.

## The degradation ladder

Each hook event sits on exactly one rung per runtime, declared in `runtimes.json` `hook_events.<Event>.runtimes.<runtime>.rung` and printed by every doctor as `degradation rung for <Event>: <rung>`.

| Rung | Meaning |
|---|---|
| `native-hook` | The runtime invokes the wrapper or dispatcher and consumes the JSON decision. |
| `contract-text` | The runtime has no hook surface for the event; the rule lives in `AGENTS.md` and the model is asked to honor it. |
| `git-floor` | Neither a hook nor the contract applies; only `.githooks/pre-commit` stands between the change and the repository. |

The rungs declared in this build:

| Event | Claude Code | Codex CLI | OpenCode |
|---|---|---|---|
| SessionStart | native-hook (individual wrappers, limit 9000) | native-hook (dispatcher, limit 3200, configured-beta) | native-hook (plugin system-prompt transform, limit 3200, experimental) |
| UserPromptSubmit | contract-text | contract-text | contract-text |
| PreToolUse | native-hook | native-hook (dispatcher, limit 600) | native-hook (plugin `tool.execute.before`; partial: only the two guards are configured, `memory-first`, `delegation-guard`, and `read-deny` unsupported) |
| PostToolUse | native-hook | native-hook (dispatcher, limit 1200) | contract-text |
| Stop | native-hook | native-hook (dispatcher) | contract-text |

A rung names the mechanism, not the evidence. `native-hook` on Codex still requires the project to be trusted and each hook definition approved by hash before anything fires; the `support` value beside the rung (`native`, `configured-beta`, `configured-alpha`, `experimental`, `partial`, `unsupported`) carries the maturity, and `docs/VERIFICATION.md` carries the observations. The git floor fires everywhere once bootstrap has set `core.hooksPath`; it is a narrow scanner and is bypassable by design (`SECURITY.md`).

## Evidence layers

The doctors and `docs/VERIFICATION.md` share one vocabulary, in order: `configured` (the file has the shape the runtime documents), `loaded` (the runtime read it), `trusted` (the runtime's trust or approval gate passed), `fired` (a hook or skill ran inside a session), `enforced` (a deny decision was honored), `outcome-proven` (an artifact-level result was observed). Each doctor line is `  [<layer>] <state> <message>` with the state one of `OK`, `WARN`, `FAIL`, `UNKNOWN`. The roll-up per layer is `FAIL` on any FAIL, `PARTIAL` on any WARN or on UNKNOWN mixed with OK, `UNKNOWN` when only UNKNOWN or when the layer has zero entries, and `PASS` only with at least one OK and nothing else. A layer with zero entries is UNKNOWN, never PASS, never omitted. The final line is `Result: repository PASS|FAIL; runtime evidence PROVEN|INCOMPLETE; n warning(s), m failure(s)`; the exit code is 0 only when the repository is PASS.

Offline doctors populate `configured` only and never launch a runtime, touch the network, or regenerate anything. In this build all three doctors report `repository PASS; runtime evidence INCOMPLETE` with `configured PARTIAL`. The `configured` layer is PARTIAL because each doctor mixes OK checks with UNKNOWN capability declarations: `peer-runtime-cli` and `web-search` on Claude Code; `delegated-execution`, `peer-runtime-cli`, and `web-search` on Codex CLI and OpenCode. Every id in every adapter's `model-map.json` (Claude Code, Codex CLI, OpenCode) is bound to a provider id already, marked `configured, not verified` in that file's own notes rather than left `null`; every other layer beyond `configured` is UNKNOWN. The CI workflow proves file shape and determinism on three operating systems and states in its own header that it never proves runtime behavior.

## Selection and packs

A skill declares its packs in `metadata.packs`; `harness/registry/selection.json` names the selected packs plus explicit `include` and `exclude` lists; the effective set is the union of pack members and includes, minus excludes. `python harness/tools/selector.py` edits the file (flags or an interactive prompt on a terminal), refuses a skill name that does not exist, warns on a pack no shipped skill declares, and then re-runs bootstrap's materialization, which prunes links for deselected skills. `selection_scope` in `structure.json` picks the repository-shared file or a user-local `selection.local.json`. The doctors count selection from the materialized artifacts per runtime and reconcile to the selection file; a mismatch is a `configured` FAIL. This build ships 12 skills on disk, 9 of them selected by default from the `core` and `maintain` packs, so every catalog reads `9 selected of 12 available`; zero skills remains a legal state that bootstrap tolerates (lint reports it as a WARN under `--strict` and an ERROR only under `--release`). The pack catalog and its release plan are in `docs/PACKS.md`.

## Memory lanes and the brain module

Five lanes with fixed names (identity, knowledge, decisions, records, docs) and host-chosen paths in `structure.json`. `brain/` is the optional reference provider for the identity and knowledge lanes, split into a tracked `shared/` half and an untracked `local/` half. Memory carries evidence authority only; instruction authority belongs to the contract, the rules, and the docs lane. Lane semantics, consumers, and unready behavior: `docs/LANES.md`. Maturity, promotion, reclassification, and the solo-to-team migration: `brain/README.md`.

## Classification and export

Five labels with clearance-free semantics (`public`, `internal`, `confidential`, `restricted`, `secret`), a default per lane and a policy for unlisted paths in `structure.json` `tiers`, and an explicit per-file `access:` that always wins. `harness/tools/export.py --tier <label> --out <dir>` copies a history-free tree at the requested level into an empty destination outside the source, never follows links, never enumerates `.git`, fails closed on unparseable frontmatter (exit 1), refuses a `restricted` export without a validated collaborator list (exit 2), and prints counts that reconcile to the input file count. `secret` is excluded from every export; on Claude Code only, the shipped-off `read-deny` hook can deny the native Read tool for a `secret` page. On Codex and OpenCode the labels are documentation. Rule text: `harness/rules/access-policy.md`.

## Delegation module (opt-in)

`harness/rules/base-routing.md` carries the authored routing policy as a JSON block between HTML markers: planning tiers T0 to T3, eight profiles that name only the logical tier labels `fast`, `balanced`, `strong`, and `strong-main`, 22 tool profiles, 41 task ids, and composite floors. `routing_policy.py compile` validates the block and writes the untracked manifest; `native_routing.py render` writes one role per task id and phase into each adapter's `agents/` directory through that adapter's `model-map.json` (a `null` id leaves the role unrendered and the doctor prints UNKNOWN); `workflow.py` is the controller that runs plans as controller-owned child processes and refuses to run unless `delegation.mandatory` is true or `--opt-in` is passed. The shipped default is `false`, so the policy is advisory, the delegation guard is silent, and the generated roles exist for direct invocation only. Detail: `docs/ROUTING-TASKS.md`.

## Kernel manifest and the source relationship

This template was extracted from a private operating repository that remains the source of the kernel. No history, tag, or object from that repository reaches this one; the template starts from its own genesis commit, and de-identification runs both as a structural lint (`deidentify_lint.py --structural`, lint L14) and, at publication, with a private term list and `--history`.

`harness/kernel-manifest.json` records the relationship per file. In this build it lists 303 files: 105 with `state: ported` and a `source` naming the file's path in the source repository (one of them prefixed `basic-harness:` for the predecessor template), and 198 with `state: new` and `source: null`. Lint L6 reconciles the manifest to the tree in both directions: every kernel file on disk (everything under `harness/` except skills, generated roles, `.gitkeep` markers, and the untracked caches, plus `.githooks/` and `.github/`) must be listed, every listed path must exist, and `source` must be non-null exactly when the state is `ported`.

Not built in this version: a per-file `adopted` state with a source commit, a `--check` that reports only on adopted files, and a drift counter with a release-blocking threshold. `ROADMAP.md` lists source updating under v0.2, and an instance mode (the source repository consuming the template's kernel) is deferred to a dated decision after a period without kernel edits and at least one external adopter. Until then the direction is one way: the source repository changes, and a change that belongs in the template is ported by hand with its manifest entry updated.
