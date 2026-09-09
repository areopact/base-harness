---
title: Memory module
access: internal
---

# Memory module

`brain/` is the reference memory module and the default provider for the memory lanes named in `harness/registry/structure.json`. It is optional: every hook and tool in the harness reads lane paths from that file and treats an unset lane as "not configured", so a repository may delete this folder, point the lanes elsewhere, or keep only the lanes it uses. The harness owns no memory content. What it owns is the contract on this page: which lane answers which question, when a belief may be relied on, what a memory page is allowed to govern, and how a page moves between lanes and tiers.

Scaffold the module with `python harness/tools/init.py --brain`. Lane folders are created on first write; a fresh clone carries three files: this page, `brain/shared/README.md`, and `brain/local/README.md` (the local lane is otherwise gitignored, but its own README is tracked and un-ignored on purpose so the local-lane contract is still readable in a fresh clone); `python harness/tools/init.py --brain` places the rest.

## Lanes

Five lanes, fixed names, host-chosen paths. The shipped defaults place them as follows.

| Lane | Question it answers | Default path | Tracked | Tier default |
|---|---|---|---|---|
| identity | Who is the agent, and how does the operator work | `brain/shared/IDENTITY.md`, `brain/local/OPERATOR.md` | shared yes, local no | internal |
| knowledge | What is believed now, and how firmly | `brain/shared/knowledge/`, `brain/local/knowledge/` | shared yes, local no | internal |
| decisions | What was chosen, and what was given up | `docs/decisions/` | yes | internal |
| records | What happened, with a date | unset | n/a | internal |
| docs | What governs or can be reused now | `docs/` | yes | public |

The routing rule that decides which lane a piece of information enters is `harness/rules/memory-routing.md`. The tier vocabulary is `harness/rules/access-policy.md`. Neither is repeated here.

Two lanes have a shared and a local half. The shared half is repository content that every cloner reads. The local half belongs to one user on one machine and is untracked by default (see "The local lane" below). A lane path is a file when the lane holds one page (identity) and a folder when it holds many.

## Maturity

A knowledge page carries `maturity:` with one of two live values and two terminal values.

| Value | Meaning | What the page must state |
|---|---|---|
| `working` | A material validation gap remains | The open question, and the evidence that would close it |
| `standing` | The belief may be relied on within its stated scope | The scope, and the condition that would trigger reassessment |
| `promoted` | The content now has a canonical home elsewhere | `promoted_to:` naming the destination |
| `superseded` | A successor page replaced it | `superseded_by:` naming the successor |

Maturity is decided by evidence quality, contradiction handling, and scope clarity. A fixed observation count never decides it: one decisive observation can establish a narrow standing rule, and ten correlated anecdotes can still be working. A working page with no open question and no evidence path is malformed; clarify it, promote it to standing, or archive it.

## Authority: evidence versus instruction

Storage, tier, and authority are three separate facts about a page.

- Storage says where the bytes live (a lane path).
- Tier says how far the page may travel (`access:` label, export policy).
- Authority says what the page may govern.

Memory has evidence authority only. A page in any memory lane records what was observed, believed, or chosen; it never binds the agent's behavior by itself. Instruction authority belongs to the contract (`AGENTS.md`), the rules (`harness/rules/`), and the docs lane. A memory page becomes binding only by promotion into one of those, which leaves a pointer behind. The practical test: if an agent reading a knowledge page would act on it as an order rather than as a belief with a stated scope, the page is filed in the wrong lane.

Two consequences follow. First, an identity page is instruction-shaped (voice, anti-patterns, scope) and is therefore edited only through an explicit approval with the operator, never as a side effect of another task. Second, a standing knowledge page may be cited by a rule, but the rule remains the authority; deleting the knowledge page does not unbind the rule.

## Operations

### Promotion

Promotion moves content up the authority ladder: local to shared, working to standing, knowledge to a rule or a docs page.

1. Confirm the destination's own gate. A rule needs a supported enforcement point or a stated advisory rung; a docs page needs a maintainer; standing maturity needs a stated scope.
2. Write the content at the destination in that destination's page shape. Do not copy the memory page verbatim; a belief and a rule are different sentences.
3. On the source page set `maturity: promoted` and `promoted_to: <destination path>`. Leave the page in place for one review cycle, then move it to the lane's `archive/`.
4. Link forward from any record that fed the belief to the promoted destination, so the evidence chain survives the move.

Promotion from local to shared is the same procedure with one added check: the page's `access:` label must be safe for every cloner of the repository, because the shared lane's boundary is repository access.

### Reclassification

Reclassification changes a page's `access:` label without moving it.

- Raising a label (toward `secret`) is a plain edit. Nothing that already excluded the page now includes it.
- Lowering a label (toward `public`) is a reviewed change, recorded in the decisions lane when one is configured, because the next export at the lower tier will carry the page. Before lowering, run `python harness/tools/export.py --tier <new label> --out <scratch dir>` and read the page in the output as its new audience would.
- `restricted` requires a non-empty `allowed_collaborators:` list whose ids exist in `harness/registry/collaborators.yaml`; the frontmatter guard rejects the label without it.
- A page the agent must boot from (identity lane) cannot be `secret`: a `secret` page is stripped from every export and, where the Claude-only read-deny hook is on, from the agent's own view.

### Archiving

A promoted or superseded page moves to `archive/` under its lane's shared or local root, keeping its frontmatter and gaining the pointer field. Archived pages are historical; a retrieval that surfaces one must say so. Records never archive, because a dated event is already historical by construction.

## The local lane

`brain.local_path` names the per-user lane root (default `brain/local`). `brain.local_tracked` is `false` by default and the shipped `.gitignore` excludes the local lane except its `README.md`, so the operator profile and working knowledge never enter the repository history by accident while the lane's own contract page stays readable in a fresh clone.

Setting `brain.local_tracked` to `true` has one consequence that the tooling states before it acts: every file under the local lane is committed, and on a repository with a public remote that is publication. The only supported way to enable it is `python harness/tools/init.py --brain --track-local`, which prints the consequence and then flips the flag and the `.gitignore` entry together. When tracked, the local lane takes the internal tier by default like every other lane, which is the second consequence: a page there is then readable by everyone with repository access and is included in every export at internal or above.

Per-user resolution in branches mode: the design places the local lane outside the repository (`adopt.py` proposes a per-repository directory under the user's home) and resolves the operator profile per `git config user.email`, so two contributors on one clone never read each other's profile. The current tooling does not yet implement either half. `harness_registry.validate_structure` accepts only repository-relative `local_path` values, `adopt.py` reports the rejection and falls back to the in-repository path, and `load_identity` reads exactly the paths listed in the identity lane with no per-user substitution. Until that lands, branches-mode hosts keep the local lane untracked inside the repository and each contributor keeps a separate clone. `brain/local/README.md` carries the per-user detail.

## Solo to team migration

A solo repository that gains collaborators changes five things, in this order.

1. Set `git.mode` to `branches` in `structure.json`. The git-workflow rule switches from main-only to branch-and-pull-request discipline, and generated files fall under regenerate-and-diff (`merge=ours` in `.gitattributes`).
2. Set `selection_scope` to `user` so each contributor materializes only the skills they use; `selector.py` then writes a user-local selection file that the `.gitignore` must exclude.
3. Review every page under `brain/shared/` for its `access:` label against the new audience: anyone who can clone reads internal. Raise labels before the first collaborator clones, not after.
4. Run `python harness/tools/export.py --tier internal --out <scratch dir>` once and read the output as a new collaborator would. Anything that should not be there is either relabeled (reclassification above) or moved to the local lane.
5. Keep `brain.local_tracked` false. If a contributor needs a shared operator convention, that is a docs page or a rule, not a tracked local lane.

Run `python harness/tools/lint.py --strict` and the three doctors after the change; the doctor reports the git mode and the local-lane tracking state on its `configured` layer.

## What never goes here

- Binding behavior: that is a rule in `harness/rules/` or contract text, never a memory page.
- Shared project knowledge, status, plans, and architecture: the docs lane.
- Secrets, tokens, credentials, or the path to a secret store: nowhere in a lane; the secrets rule governs.
- A fact the code, tests, or README already state: fix the source instead of caching it as memory.
- Generated digests as hand-edited pages: a generated file is rebuilt from its sources, never edited in place.
- Another person's private notes: the local lane is per user by construction.
- A persona for the agent to perform: the identity template is a shape (role, scope, voice, values, anti-patterns), and the harness ships no content for it.

## Tooling

| Need | Tool |
|---|---|
| Scaffold the module | `python harness/tools/init.py --brain [--track-local]` |
| See what a tier's export contains | `python harness/tools/export.py --tier <label> --out <dir>` |
| Check frontmatter on write | `harness/hooks/lib/frontmatter_guard.py` (advisory rung; scope is every configured lane path) |
| Deliver the identity lane at session start | `harness/hooks/lib/load_identity.py` (truncates deterministically at the runtime's `identity_context_limit` and says so) |
| Remind the agent to read memory before an external lookup | `harness/hooks/lib/memory_first.py` (advisory; matches filename stems only) |
| Validate `structure.json` | `python harness/tools/harness_registry.py` |

Folder guides: `brain/shared/README.md` and `brain/local/README.md`. Lane semantics for the whole repository: `docs/LANES.md`. Host shapes and their `structure.json` examples: `docs/HOST-SHAPES.md` and `harness/tools/templates/lanes.example.json`.
