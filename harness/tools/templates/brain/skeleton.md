---
title: Memory module skeleton
access: internal
---

Template: this file is a listing, not content. It names every path the reference memory module may contain, which lane each path serves, whether it is tracked by default, and which tool creates it. Copy nothing from it by hand; `python harness/tools/init.py --brain` places the scaffold and the rest is created on first write.

# Memory module skeleton

```
brain/
  README.md                 memory contract           tracked    init --brain
  shared/                   shared half               tracked
    README.md               folder guide              tracked    shape ships beside this file (see note)
    IDENTITY.md             identity lane (optional)  tracked    init --brain, from harness/tools/templates/IDENTITY.md
    knowledge/              knowledge lane, standing  tracked    init --brain places .gitkeep
      <stable-slug>.md      one belief per page       tracked    first write
    archive/                promoted or superseded    tracked    first archive
  local/                    per-user half             ignored    brain.local_tracked=false by default
    README.md               folder guide              ignored    shape ships beside this file (see note)
    OPERATOR.md             identity lane             ignored    init --brain, from harness/tools/templates/OPERATOR.md
    knowledge/              knowledge lane, working   ignored    first write
    journal/                journal lane              ignored    first write
      YYYY-MM-DD.md         one entry per day         ignored    first write
    archive/                promoted or superseded    ignored    first archive
    HOT.md                  generated digest          ignored    reserved; no generator in this version
```

Lane paths are the shipped defaults in `harness/registry/structure.json`; a host may move any of them. The decisions lane (`docs/decisions/` by default) and the docs lane (`docs/`) are outside `brain/` on purpose: they are shared project material, not memory.

Note on the two folder guides: `init.py --brain` currently places `brain/README.md`, `brain/shared/IDENTITY.md`, `brain/shared/knowledge/.gitkeep`, `brain/local/OPERATOR.md`, and `brain/local/.gitkeep`. The `brain/shared/README.md` and `brain/local/README.md` shapes ship beside this file for a later `init.py` change to place; until then copy them by hand if a scaffolded repository wants them.

## Frontmatter per page type

| Page | Required keys | Optional keys |
|---|---|---|
| `IDENTITY.md`, `OPERATOR.md` | `title`, `access` | none |
| knowledge page | `title`, `type: knowledge`, `maturity`, `access` | `last_assessed`, `promoted_to`, `superseded_by`, `allowed_collaborators` (required only when `access: restricted`) |
| journal entry | `title`, `access` | `kind` |
| README guides | `title`, `access` | none |

`access` is one of `public`, `internal`, `confidential`, `restricted`, `secret`. `maturity` is one of `working`, `standing`, `promoted`, `superseded`.
