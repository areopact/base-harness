---
title: Local memory lane
access: internal
---

# brain/local/

The per-user half of the memory module: one operator, one machine. Untracked by default. The shipped `.gitignore` carries `/brain/local/`, and `structure.json` `brain.local_tracked` is `false`, so nothing here reaches the repository history unless the operator opts in. Folders are created on first write; `python harness/tools/init.py --brain` places `OPERATOR.md` and a `.gitkeep` and nothing else.

Because the whole folder is ignored, this guide is itself untracked in a default clone. The tracked copy of its shape lives at `harness/tools/templates/brain/local/README.md`.

## Contents

| Path | Lane | Holds |
|---|---|---|
| `OPERATOR.md` | identity | How the operator prefers to work: style, preferences, communication, corrections stated as the rule that now applies. The template is a shape with no person in it. |
| `knowledge/` | knowledge | Working beliefs with a stated open question. Promotion to `brain/shared/knowledge/` is an explicit edit, never a sync. |
| `journal/` | journal | Daily entries, session notes, half-thoughts awaiting routing. An entry older than two weeks is routed or discarded. |
| `HOT.md` | (generated) | A current-work digest rebuilt from its sources. Reserved for a later release; nothing generates it in this version. |
| `archive/` | knowledge | Local pages that were promoted or superseded. |

## Resolution

Which directory is "the local lane" depends on the host's git mode.

Main-only mode (the shipped default): the lane is the path in `structure.json` `brain.local_path`, resolved against the repository root by `hook_io.load_structure()` and `harness_registry.load_structure()`. One operator, one clone, one lane.

Branches mode (the design): the lane lives outside the repository, in a per-repository directory under the user's home, and the operator profile resolves per `git config user.email` so two contributors sharing a clone never read each other's profile. `adopt.py` proposes that external directory when it detects branches mode. The current kernel does not implement the design: `harness_registry.validate_structure` rejects any `local_path` that is not repository-relative, `adopt.py` reports the rejection and keeps the in-repository path, and `load_identity` reads the identity lane paths verbatim with no substitution by email. The honest state is "documented, not implemented". Until it lands, a branches-mode host keeps the local lane untracked inside each contributor's own clone.

## Tracking the lane

`python harness/tools/init.py --brain --track-local` is the only supported way to set `brain.local_tracked` to `true`. It prints the consequence before writing: every file here is committed, on a public remote that is publication, and the lane then takes the internal tier by default, so every export at internal or above includes it. Plan intent adds a doctor failure when the lane is tracked and the origin remote is public; no doctor performs that check in this version, so the operator carries it.

## What does not belong here

Secrets and credentials (the secrets rule names the only approved stores), another user's notes, and anything a rule or a docs page should state. Working knowledge that has become standing and useful to others is promoted to `brain/shared/knowledge/`, with the pointer left behind.
