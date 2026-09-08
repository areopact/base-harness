---
title: Shared memory lane
access: internal
---

# brain/shared/

The shared half of the identity and knowledge lanes. Everything here is repository content: tracked, read by every cloner, and exported at the internal tier by default. Folders are created on first write; a fresh clone holds this page only; `python harness/tools/init.py --brain` places `IDENTITY.md` and the `knowledge/` marker.

## Contents

| Path | Lane | Holds |
|---|---|---|
| `IDENTITY.md` | identity | The agent's role, scope, voice, values, and anti-patterns for this repository. Optional; when absent the identity lane still resolves to the local operator profile. Edited only through an explicit approval with the operator. |
| `knowledge/` | knowledge | Standing beliefs another session, task, or runtime would act differently for knowing. One page per belief, stable undated slug. |
| `archive/` | knowledge | Promoted and superseded pages kept for audit, each carrying its pointer field. Created on first archive. |

## Page shape for a knowledge page

```
---
title: <belief, under 60 characters, not a sentence>
type: knowledge
maturity: standing
access: internal
---

## Compiled truth

The belief as currently held, its scope, and the condition that triggers reassessment.

## Evidence

Links to the records or docs that support it. A belief with no evidence link is working at best.

## Timeline

Dated entries for changes and contradictions. Dates live here, never in the filename.
```

`maturity:` takes `working`, `standing`, `promoted`, or `superseded`; the memory module page (`brain/README.md`) defines each. Working pages normally start in the local lane and reach `shared/` by promotion, which is why the shared default is standing; a working page may live here when a team needs to see the open question.

## Boundary

The shared lane's boundary is repository access. Before a page enters it, its `access:` label must be safe for everyone who can clone. Pages that name third parties default to `confidential` under the access policy, and a `confidential` page in a repository whose collaborators are not all at that tier belongs in the local lane instead. The frontmatter guard checks the label vocabulary on every write; `python harness/tools/export.py --tier internal --out <dir>` shows exactly what the lane exposes.

## Identity budget

`IDENTITY.md` is delivered at session start by `load_identity`, which caps the whole identity lane at the runtime's `identity_context_limit` from `harness/registry/runtimes.json` and truncates deterministically past it with a visible note. Keep the file under the smallest limit among the runtimes in use; `python harness/tools/lint.py` enforces the budget (check L2).
