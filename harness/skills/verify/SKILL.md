---
name: verify
description: >
  Prove a change actually works by exercising it end to end before claiming
  done, and report the rung reached with evidence. WHEN: user invokes /verify,
  says "prove this works", "verify this change", "did this actually work", or
  "evidence before done"; before completing any nontrivial change. WHEN NOT:
  docs-only or test-only diffs with no runtime surface; checking that the
  harness itself is wired (/doctor); committing the verified change (/commit).
metadata:
  packs: [maintain]
  triggers:
    - "prove this works"
    - "verify this change"
    - "did this actually work"
    - "evidence before done"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# verify

Evidence over assertion. "The code looks right" and "the tests pass" are both weaker claims than "I ran it and watched it do the thing."

## The ladder (climb as high as the change allows)

1. **Static**: build, typecheck, and lint pass. Necessary, never sufficient.
2. **Tests**: the relevant test suite passes, including a test that would have failed before the change (if none exists, write one or say why not).
3. **Exercised**: the actual affected flow was driven end to end: the CLI was invoked, the endpoint was called, the page was loaded, the migration was run against a scratch database. Capture the real command and its real output.
4. **Negative case**: the error path or guard you added actually fires when provoked.

## Reporting

State what was verified at which rung, with the evidence (command plus observed output), and name explicitly anything NOT verified ("untested on POSIX", "not run against production-shaped data"). An honest gap beats a confident guess. The close-the-loop checklist in `harness/rules/close-the-loop.md` already requires this honesty as its first step; this skill is that step made explicit.

## Anti-patterns

- Claiming done from rung 1.
- Running only the new unit test and skipping the integration path the change actually sits on.
- Verifying the happy path of a change whose whole point was error handling.
