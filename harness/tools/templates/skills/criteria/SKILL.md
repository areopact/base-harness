---
name: new-skill
description: >
  Sets the quality bar for one kind of output in the third person, under 100 characters.
  WHEN: "natural phrase a user would type", "another way to ask for it".
  WHEN NOT: the near miss that belongs to a neighbor (use the neighbor skill).
metadata:
  form: criteria
  packs: [core]
  triggers:
    - "natural phrase a user would type"
    - "another way to ask for it"
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# new-skill

Criteria tell the agent what a result must and must not be. Copy this folder to `harness/skills/<name>/`, set `name` to the folder name, replace every sentence below, and delete what the skill does not need. `docs/ADDING-A-SKILL.md` explains each key.

## Goal

One or two sentences: the kind of output this skill governs and who reads it.

## Floors

Countable minimums. Each line can be checked by counting or looking.

- A minimum that can be counted, such as a number of cited sources.
- A required element that is either present or absent.

## Ceilings

Limits and prohibitions. Each line can be checked the same way.

- A maximum, such as a length or a count.
- A thing the output never contains.
