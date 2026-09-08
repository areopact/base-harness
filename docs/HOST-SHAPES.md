# Host shapes

The same kernel serves three kinds of repository. What differs is `harness/registry/structure.json`, the state of the runtime-facing paths before bootstrap runs, and what the host's own validators have to ignore. The complete `structure.json` object for each shape is in `harness/tools/templates/lanes.example.json`; copy the inner `structure` object, never the outer wrapper.

## Solo repository (template)

Created with "Use this template" or by cloning a copy. One operator, one clone, all six lanes served by the memory module where it provides them.

Structure: the shipped default. Identity `brain/shared/IDENTITY.md` plus `brain/local/OPERATOR.md`; knowledge `brain/shared/knowledge` plus `brain/local/knowledge`; journal `brain/local/journal`; decisions `docs/decisions`; records `null` until the operator has dated events to file; docs `docs`. `git.mode` is `main-only`, `selection_scope` is `repo`, `brain.local_tracked` is `false`, `tiers.unlisted_path` is `internal`, `delegation.mandatory` is `false`.

Steps, in order: bootstrap for the platform; the doctor for the runtime in use; optionally `python harness/tools/init.py --brain` to place `IDENTITY.md`, `OPERATOR.md`, and the `knowledge/` marker; optionally `python harness/tools/selector.py` to change the packs. In main-only mode committed generated files (`AGENTS.md`, `harness/skills/RESOLVER.md`) are byte-checked by the lint: regenerate and commit, never hand-edit.

## Existing repository (adopt)

`python harness/tools/adopt.py <repo>` installs the kernel into a repository that already has a history, a README, and its own conventions. The default is a dry run that prints every action and writes nothing; `-y` or `--apply` performs them. `python harness/tools/init.py --adopt <repo>` delegates to the same script.

Refusals (exit 2): the target is not a git repository or not its root, has uncommitted changes, is the template itself, or already carries a kernel (`harness/kernel-manifest.json` or `harness/tools/adopt.py` present).

What adopt writes:

- `harness/` file by file. An existing target file is never overwritten: under `harness/rules/` the incoming file lands as `<slug>.harness.md` (the reserved-name merge), elsewhere as `<name>.harness<suffix>`, and each case is reported.
- The scaffold-owned root files (`README.md`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `NOTICE`, `THIRD-PARTY.md`, `.gitignore`, `.gitattributes`), the `.githooks/` and `docs/` trees, and the conformance workflow, each only when absent. The host README is never overwritten; an existing file keeps its place and the template version lands as a `.harness.md` sibling.
- `harness/registry/structure.json`, written for the target rather than copied: every lane `null` except docs (when `docs/` exists) and decisions (when `docs/decisions/` or `decisions/` exists); `git.mode` is `branches` when the target has more than one remote branch or a branch-protection marker (a `CODEOWNERS` file or `.github/rulesets/`), otherwise `main-only`. `contract.mode` is `host-owned` when the target already has a root `AGENTS.md` (the common case for an adopted repository), otherwise `rendered`. In `host-owned` mode `host.adopted` is `true`, `host.roots` records the target's own top-level tracked directories at adoption time, and `host.harness_owned` records the paths under `harness/` that already existed before adoption (a target that ships its own `harness/` tree of rules, schemas, or scripts).
- The run ends with a numbered checklist: review the diff, merge or delete every `.harness.md` sibling, fill `harness/CONTRACT.host.md`, set the lanes you use, run `git check-ignore -v` on every bootstrap-managed copy once any `.gitignore.harness.md` sibling is merged, bootstrap, run the doctors. Adopt is additive; deleting what it added reverses it.

### Per-runtime state before bootstrap

Adopt does not bootstrap. Between adopt and the first bootstrap run, each runtime sees the following.

| Runtime | What it reads before bootstrap | Hooks before bootstrap |
|---|---|---|
| Claude Code | root `CLAUDE.md` pointing at `AGENTS.md` (both copied by adopt when absent); no `.claude/settings.json`, no `.claude/skills`, no `.claude/rules`, no `.claude/agents` | none registered; on the first session after bootstrap the `pre-bootstrap-detector` SessionStart hook names the bootstrap command whenever a declared destination is missing |
| Codex CLI | root `AGENTS.md`; no `.codex/config.toml`, no `.codex/hooks.json`, no `.agents/skills` | none; even after bootstrap nothing loads until the project is trusted and each hook definition is approved by hash |
| OpenCode | root `AGENTS.md`; no root `opencode.json`, no `.opencode/` tree | none; the plugin bridge is a bootstrap output, and the launcher refuses to start until the selected skill tree is materialized |
| every runtime | `.githooks/pre-commit` is present but inert: `core.hooksPath` is set by bootstrap, not by adopt | git floor inactive |

The contract text is the only mechanism that governs before bootstrap, and only where the runtime reads the root contract natively. When the target had no `AGENTS.md` (`contract.mode` stays `rendered`), the copied `AGENTS.md` carries the template's host block, and the first bootstrap re-renders it from `harness/CONTRACT.md` plus the host's own `harness/CONTRACT.host.md`. When the target already had an `AGENTS.md` (`contract.mode` is `host-owned`), adopt keeps it in place and lands the template contract as `AGENTS.harness.md` instead; bootstrap never writes the host's `AGENTS.md`, and it renders and repairs `AGENTS.harness.md` from the same two sources. Add a line to the host's `AGENTS.md` that references `AGENTS.harness.md` (or merge its content in directly) so runtimes actually load the harness block; the doctors warn once when that reference is missing and stay silent once it is added.

### What a host validator must exclude

An adopted repository usually has its own lint, formatter, or link checker. Those must ignore, or be told about, the following.

| Path or pattern | Why |
|---|---|
| `.claude/skills/`, `.claude/agents/`, `.claude/rules/`, `.claude/hooks/`, `.codex/agents/`, `.codex/rules/`, `.codex/hooks/`, `.opencode/skills/`, `.opencode/agents/`, `.opencode/plugins/`, `harness/.selected/` | links into `harness/`; a link-following walker sees the tree twice, and git on Windows would track a junction's contents. The shipped `.gitignore` excludes them. |
| `.agents/skills/`, `.opencode/commands/`, `.claude/settings.json`, `.codex/config.toml`, `.codex/hooks.json`, root `opencode.json` | generated trees and managed copies; `bootstrap --check` owns their drift, and a host formatter that rewrites them causes exactly that drift |
| `AGENTS.md`, `CLAUDE.md`, `harness/skills/RESOLVER.md`, `THIRD-PARTY.md`, `NOTICE` | rendered or generated; edit the sources (`harness/CONTRACT.md`, `harness/CONTRACT.host.md`, skill frontmatter, `harness/registry/sources.json`) and regenerate. In `contract.mode: host-owned`, `AGENTS.md` is the host's own file (not template output); `AGENTS.harness.md` is the rendered one |
| `brain/local/` | the untracked personal lane |
| `*.harness.md` and `*.harness<suffix>` siblings | adopt's non-overwrite landing spots, expected to be merged or deleted and gone after the checklist |
| `harness/registry/delegation-policy.json`, `harness/registry/native-routing-files.json`, `harness/registry/skill-index.json` | untracked generated caches |
| Markdown links into any of the link or generated paths | lint L9 forbids them outside `docs/`, `README.md`, and the allowlisted component READMEs; a host link checker should treat them the same way |

The harness lint scans only `harness/`, `docs/`, and `brain/` for punctuation and line endings (L3) and the tracked tree for the other checks; it does not impose its style on the host's own code.

### Adopted-host day one

What the shipped checks actually report right after adopt, merge, and bootstrap on a repository that already had its own `AGENTS.md`, its own top-level content directories, and its own `harness/` tree:

- **Doctors** (`doctor.sh`/`doctor.ps1`, `doctor_codex.py --offline`, `doctor_opencode.py --offline`): the contract line reads `contract: host-owned (AGENTS.md is the host's; template block at AGENTS.harness.md)` instead of the rendered-file message, and stays `OK` (not `DRIFT`/`FAIL`). A `WARN` fires once, naming the exact line to add, if the host's `AGENTS.md` does not yet reference `AGENTS.harness.md`; it clears silently once that line is added. A second `WARN` fires per bootstrap-managed copy (`.claude/settings.json`, `.codex/config.toml`, `.codex/hooks.json`, `opencode.json`, ...) that a pre-existing host `.gitignore` rule hides, naming the rule; it never blocks the doctor's PASS.
- **Scope, both checks below**: `adopt.py` records the exact paths it created or wrote in `harness/registry/adopted-files.json`. When `structure.json`'s `host.adopted` is true, `lint.py` and `deidentify_lint.py` default their scan to the union of that file, every path in `harness/kernel-manifest.json`, and `structure.json` itself: the template's own files, not the host's. Each prints one line naming the mode and file count (`lint: scope adopted-host (42 file(s) scanned)`); `--all` restores the whole-tree scan on either tool. A non-adopted host (the template repository itself) is unaffected: its scope is always the whole tree.
- **`lint.py --strict`**: on the default adopted-host scope, `L6` never even sees the host's own pre-existing or newly-added `harness/` files (they are outside the scan set), so it reports them once as an `INFO` count (`N host-owned file(s) under harness/ not judged`) rather than individually, and never as an error; template-owned kernel files (in the adopted scope or `structure.json`'s `host.harness_owned`) are still checked in full. `L12` (rules-index) does the same for a host's own `harness/rules/*.md` file that carries no `harness/rules/index.json` entry. `--all` restores the prior whole-tree behavior for both: an unlisted `harness/` file not in `host.harness_owned`, or an unlisted rule file, is an error again. L6 also no longer requires `brain/README.md`, `brain/local/README.md`, or `brain/shared/README.md` to exist when no lane points into `brain/`.
- **`deidentify_lint.py --structural`**: on the default adopted-host scope, D3 and D5 never scan the host's own content (docs, other host top-level directories, host-owned `harness/` files), so a relative path in the host's own prose or the host's own attribution string is not a finding; `--all` scans the whole tree, where D3 still treats the host's own top-level directories (`structure.json`'s `host.roots`) as allowed. D6's carriage-return check reads the git index blob for a tracked file before flagging a worktree CR, so a Windows checkout with `core.autocrlf` or a normalizing `.gitattributes` entry does not report CR noise the host never committed; an untracked file with real CR bytes is still flagged.
- **The .codex ignore trade-off (D3 checklist item)**: if the host's own `.gitignore` already has a broad rule like `.codex/` before adoption, it can hide a bootstrap-managed copy under that path from git even though the file exists on disk and the doctor sees it. The doctor's `WARN` names the hiding rule; the operator chooses between narrowing the rule to the harness's own link subpaths (so the managed copy is tracked like every other repository) or accepting that runtime's config as bootstrap-local per clone (untracked, regenerated by every `bootstrap` run, and excluded from code review).
- **The host's own validator** (a repository-wide link checker, secret scanner, or formatter run by `npm run verify` or equivalent) sees every file adopt landed, including the template's `docs/` tree, `README.harness.md` and similar siblings, and the skill catalog under `harness/skills/`. Nothing in this template changes that validator; a false positive it raises against template-owned prose (a link inside a fenced code example, an examples-only path that looks secret-shaped) is a template defect to fix at the source, not a host-side suppression to add.

### Branches mode

When adopt detects branches mode, the checklist adds a line about the local memory lane. The design places that lane outside the repository under a per-repository directory in the user's home and resolves the operator profile per git user, so no personal note can ride into a pull request. The current validator accepts repository-relative paths only, so the lane stays in-repository and untracked, and each contributor keeps a separate clone. Generated files carry `merge=ours` in `.gitattributes`, honored once bootstrap sets `merge.ours.driver` locally: on conflict, regenerate and diff rather than merging by hand.

## Private source repository (mirrored structure, private content)

The shape of the repository the kernel was extracted from, described generically. It mirrors the harness structure and lint but keeps every lane's content private, and it is not a template consumer in this version (see `docs/ARCHITECTURE.md`, "Kernel manifest and the source relationship").

Structure, from the `private-instance-host` example: a flat memory folder instead of shared and local halves (identity and knowledge, journal, and decisions all under one memory root with `brain.local_tracked` true and `brain.local_path` pointing at that root); a records lane for dated events; every memory lane at the `confidential` tier; docs at `internal`; `tiers.unlisted_path` set to `exclude`; `delegation.mandatory` true so substantive work takes the delegated plan, worker, and review sequence; `git.mode` main-only; repository-shared selection. Nothing in this shape is exported below `confidential`, and an export at `internal` carries only the docs lane. The lane paths in the example are illustrative; a private host names its own.

What such a host runs that a template consumer does not: the de-identification lint with a private term list and `--history` before anything leaves the repository; a per-file export policy through `export.py` rather than a public remote; and, when the source-updating tooling lands, the drift check between its kernel and the template's manifest.

## Git modes: main-only and branches

`git.mode` selects the branch discipline in `harness/rules/git-workflow.md`. `main-only`: never create a branch or a worktree; all work lands as small commits on the default branch; committed generated files are byte-checked. `branches`: one feature branch per task; no force-push to a protected branch and no history rewrite on a shared branch; generated files regenerate-and-diff under `merge=ours`; the personal lane stays out of review. The dangerous-operations guard denies the literal force-push and history-rewrite shapes in both modes; the rule holds regardless of the hook.

## Selection scope: repository or user

`selection_scope` decides which file `selector.py` writes. `repo` writes `harness/registry/selection.json`, shared by every clone. `user` writes `harness/registry/selection.local.json`, which `adopt.py` skips when copying and which a host must add to its `.gitignore` (the shipped `.gitignore` does not list it). The doctors reconcile the materialized skill count to whichever file the scope names.

## Tracked and untracked local memory

`brain.local_tracked` is `false` by default and the shipped `.gitignore` excludes `/brain/local/`. `python harness/tools/init.py --brain --track-local` is the only supported way to flip it: the tool prints the consequence (every file under the lane is committed; on a public or shared remote that is publication; reversing it needs a history rewrite), then sets the flag and removes the ignore entry together. A tracked local lane takes the internal tier by default and is included in every export at internal or above. The plan adds a doctor failure when the lane is tracked and the origin remote is public; no doctor performs that check in this version, so the operator carries it.
