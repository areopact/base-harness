---
name: new-skill
description: >
  Does one specific job in the third person, stated in under 100 characters.
  WHEN: "natural phrase a user would type", "another way to ask for it".
  WHEN NOT: the near miss that belongs to a neighbor (use the neighbor skill).
metadata:
  form: procedure
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

A procedure tells the agent what to do, in order, and when it is finished. Copy this folder to `harness/skills/<name>/`, set `name` to the folder name, replace every sentence below, and delete the sections the skill does not need. `docs/ADDING-A-SKILL.md` explains each key.

## Goal

One or two sentences: the outcome this skill produces, the authority it acts under, and where it stops.

## Steps

1. Name the first action and the input it reads.
2. Name the next action. Each step is one action with one observable result.
3. Name the last action, including what the reply to the user contains.

## Done when

State the requested outcome, the evidence that is enough to call it reached, and what the reply gives. Use evidence the steps already produced; do not ask for another pass. Describe success only.

## Failure modes

Blocked, partial, and unverified outcomes belong here, each with what the agent says and does instead.
