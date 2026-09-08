# Lanes

A lane is a named place where one kind of information lives. The harness fixes six lane names and lets the host choose the paths, or leave a lane unset. Every hook and tool that needs a host fact reads the lanes from `harness/registry/structure.json`; nothing in the kernel names a folder directly (lint L13, `harness/hooks/tests/test_structure_parameterization.py`). Which lane a piece of information belongs in is the memory-routing rule (`harness/rules/memory-routing.md`); which order to consult them in is the memory-first rule (`harness/rules/memory-first.md`). This page describes the lanes as the built code treats them.

## The six lanes

| Lane | Question it answers | Shape of the value | Shipped default | Tier default |
|---|---|---|---|---|
| identity | Who is the agent, and how does the operator work | files (one page each) | `brain/shared/IDENTITY.md`, `brain/local/OPERATOR.md` | internal |
| knowledge | What is believed now, and how firmly | folders | `brain/shared/knowledge`, `brain/local/knowledge` | internal |
| journal | What was noted and not yet routed | folders | `brain/local/journal` | internal |
| decisions | What was chosen, and what was given up | folders | `docs/decisions` | internal |
| records | What happened, with a date | folders | `null` (unset) | internal |
| docs | What governs or can be reused now | folders | `docs` | public |

A lane value is a non-empty list of repository-relative POSIX paths (no leading slash, no `..`, no drive letter) or `null`. A lane may list several paths; the identity lane lists two in the default so a shared agent identity and a per-user operator profile can be delivered together. Lane folders are created on first write: `init.py --lanes` writes the configuration and states that no folder was created.

## Consumers

Each lane is read by a specific set of kernel files. The table names them so a host knows what changes when a lane is set or unset.

| Lane | Consumer | What it does with the lane |
|---|---|---|
| identity | `harness/hooks/lib/load_identity.py` (SessionStart) | reads every file in declared order, strips frontmatter, skips a file labeled `secret`, and emits one context block capped at the runtime's `identity_context_limit` (9000 on Claude Code, 3200 on Codex and OpenCode); sections are kept whole until the budget is spent and the block ends with a visible truncation note |
| identity | `harness/hooks/lib/dispatch.py` (SessionStart on Codex and OpenCode) | budgets the identity block at weight 40 against the other lanes and never tail-truncates |
| identity | `harness/tools/lint.py` L2 | every identity file must fit the smallest tier-1 `identity_context_limit`; an absent file is a note, not an error |
| knowledge, decisions, docs, records | `harness/hooks/lib/memory_first.py` (PreToolUse on web tools) | tokenizes the query and matches filename stems and directory names under each lane path, three levels deep, at most 4000 entries; content is never read |
| every configured lane | `harness/hooks/lib/frontmatter_guard.py` (PostToolUse on Write and Edit) | checks a Markdown file under any lane path: block closed, `access:` in the five labels, `allowed_collaborators` present exactly when `restricted` and every id in `collaborators.yaml`, ISO dates in `created`, `updated`, `date`, `last_assessed`, `archived` |
| every configured lane; decisions and journal as evidence | `harness/hooks/lib/close_the_loop.py` (Stop) | attributes each dirty path from `git status --porcelain` to its lane and names the lanes with changes that have no companion entry in the decisions or journal lane; lists Markdown files whose `updated:` is not today |
| every lane | `harness/tools/export.py` | the deepest lane a path falls under supplies the default tier from `tiers.lane_defaults` when the file has no `access:` field |
| decisions, docs | `harness/tools/adopt.py` | detects an existing `docs/` folder and an existing `docs/decisions/` or `decisions/` folder and sets those two lanes; every other lane is written as `null` |
| all six | `harness/tools/init.py --lanes` | prompts per lane, validates each path, refuses to write an invalid structure |
| all six | the doctors | print the host shape on the `configured` layer |

The runtime's own memory features are outside this table. The harness does not read or write a runtime's auto-memory; a host that uses one keeps it separate from the lanes.

## Configuring lanes in structure.json

Edit the file directly or run `python harness/tools/init.py --lanes`, which shows each lane's current value and accepts a comma- or space-separated list of paths, the literal `none` for an unset lane, or an empty line to keep the value. The result must pass `harness_registry.validate_structure`; the tool refuses to write otherwise. `python harness/tools/init.py` with no flags prints the current host shape. Five example shapes, each a complete `structure.json` object, live in `harness/tools/templates/lanes.example.json`; `docs/HOST-SHAPES.md` walks through three of them.

Two loaders read the file and must produce identical results: `harness/tools/harness_registry.py` (validating; raises `StructureError` on a malformed file) and `harness/hooks/lib/hook_io.py` (standalone and stdlib-only; a malformed file yields the defaults plus one stderr note and never a deny). A missing file yields the shipped default object verbatim; a present file merges key by key over it; a present-but-null lane stays null.

## Unset lanes

A lane set to `null` is "not configured", which is different from "configured and empty". The contract instructs the agent to say "no lane configured" rather than "no record" and never to invent a folder for an unset lane. The consumers behave as follows when a lane is unset:

| Consumer | Behavior with the lane unset |
|---|---|
| `load_identity` | emits nothing; the doctor can therefore tell "not configured" from "configured, delivery unproven" |
| `memory_first` | skips the lane; silent when all four zone lanes are unset |
| `frontmatter_guard` | a file outside every configured lane is ignored; with no lane configured the hook is silent |
| `close_the_loop` | the lane is not attributed; silent when no lane is configured at all |
| `export.py` | a path in no lane takes `tiers.unlisted_path`: `internal` includes it at internal, `exclude` drops it |
| lint L2 | the identity budget check is skipped with a note |
| `adopt.py` | writes `null` for every lane it cannot detect, so an adopted repository assumes no folder it does not have |

Unready behavior is therefore silence or an explicit "not configured", never a guess and never a created folder.

## Identity lane and delivery limits per runtime

Identity delivery is not runtime parity. `runtimes.json` declares `identity_context_limit` 9000 for Claude Code and 3200 for Codex and OpenCode; `load_identity` reads the value for the runtime named by `--runtime` or `HARNESS_RUNTIME`, falls back to the smallest tier-1 value, and to a fixed 9000 without the registry. Truncation is deterministic: level-two sections are kept whole in document order, the first section that does not fit is cut at a paragraph boundary, and the block ends with `[identity truncated at <n> chars; read <path> on demand]`. Keep the whole identity lane under 3200 characters when all three runtimes are in use; lint L2 enforces the smallest tier-1 limit per file.

Delivery surfaces differ too: Claude Code runs the wrapper as a SessionStart hook; Codex runs the dispatcher on `startup|resume|clear|compact` with `additionalContextLimit` 3200; OpenCode delivers it through the plugin's experimental system-prompt transform. Whether each runtime actually shows the block to the model is a `fired` observation recorded in `docs/VERIFICATION.md`; in this build every such row is pending.

## The brain module: shared and local

`brain/` is the reference provider for the identity, knowledge, and journal lanes. `brain/shared/` is repository content, tracked and exported at internal by default; it holds `IDENTITY.md` (optional; a shape with no persona) and `knowledge/` for standing beliefs. `brain/local/` is one user on one machine: `OPERATOR.md`, working `knowledge/`, `journal/`, and a reserved `HOT.md` that nothing generates in this version. The local lane is untracked by default (`.gitignore` carries `/brain/local/`, `structure.json` `brain.local_tracked` is `false`). `python harness/tools/init.py --brain` scaffolds the module from `harness/tools/templates/brain/` without overwriting an existing file; `--track-local` is the only supported way to track the local lane and prints the consequence before writing.

In branches mode the design places the local lane outside the repository and resolves the operator profile per git user. The current kernel does not implement that: the structure validator accepts repository-relative `local_path` values only, `adopt.py` reports the rejection and keeps the in-repository path, and `load_identity` reads the identity lane paths verbatim. Until it lands, a branches-mode host keeps the local lane untracked inside each contributor's own clone. `brain/README.md` and `brain/local/README.md` carry the detail.

## Maturity, authority, and promotion

A knowledge page carries `maturity:` with one of `working` (a material validation gap remains; the open question is stated), `standing` (may be relied on within a stated scope), `promoted` (`promoted_to:` names the destination), or `superseded` (`superseded_by:` names the successor). Evidence quality, contradiction handling, and scope decide maturity; a fixed observation count never does.

Storage (a lane path), tier (an `access:` label), and authority are three separate facts. Memory has evidence authority only: a page in any memory lane records what was observed, believed, or chosen and never binds behavior by itself. Instruction authority belongs to the contract, the rules, and the docs lane; a memory page becomes binding only by promotion into one of those, which leaves a pointer behind. Promotion moves content up that ladder (local to shared, working to standing, knowledge to a rule or docs page) by writing the content at the destination in the destination's shape, setting `maturity: promoted` on the source, and linking forward from the records that fed it. The procedure is in `brain/README.md`.

## Reclassification

Reclassification changes a page's `access:` label without moving it. Raising a label is a plain edit. Lowering a label is a reviewed change, recorded in the decisions lane when one is configured, preceded by an export at the new label into a scratch directory so the page can be read as its new audience would read it. `restricted` requires a non-empty `allowed_collaborators` list whose ids exist in `harness/registry/collaborators.yaml`. An identity-lane page cannot be `secret`: `load_identity` skips a `secret` file, so the agent would boot without it.

## Solo-to-team migration

A solo repository that gains collaborators changes five things, in order: set `git.mode` to `branches`; set `selection_scope` to `user`; review every page under `brain/shared/` against the new audience and raise labels before the first collaborator clones; run `python harness/tools/export.py --tier internal --out <scratch dir>` and read the result as a collaborator would; keep `brain.local_tracked` false. Then run `python harness/tools/lint.py --strict` and the three doctors. The full procedure with its rationale is in `brain/README.md`.
