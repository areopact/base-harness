---
name: new-skill
description: >
  Holds the facts about one subject for lookup in the third person, under 100 characters.
  WHEN: "natural phrase a user would type", "another way to ask for it".
  WHEN NOT: the near miss that belongs to a neighbor (use the neighbor skill).
metadata:
  form: reference
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

A reference tells the agent what is true, so it answers from the page instead of from memory. Copy this folder to `harness/skills/<name>/`, set `name` to the folder name, replace every sentence below, and delete what the skill does not need. `docs/ADDING-A-SKILL.md` explains each key.

## Scope

One or two sentences: the subject this page covers and what it leaves out.

## Facts

| Item | What is true | Where it is confirmed |
|---|---|---|
| First item | A statement that can be checked | The file, command, or document that confirms it |
| Second item | A statement that can be checked | The file, command, or document that confirms it |

A long table moves to `references/` with a one-line pointer here that says which question it answers.
