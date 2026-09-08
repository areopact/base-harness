<!-- Lens reference for /review (--eng). Not a standalone skill. -->

# Engineering review

## Purpose

Apply engineering-manager judgment to a plan **before** code is written. The goal: find every load-bearing assumption that turns into pain at 2am six months from now. The lens is opinionated: boring tech, reversibility, systems over heroes, smallest blast radius.

## Eleven principles (the lens)

These principles shape every section of the review. Reference them when you flag a finding.

1. **State diagnosis**: every team or system is in one of four states: **falling behind** (debt > velocity), **treading water** (velocity = debt), **repaying debt** (velocity < debt, temporarily and deliberately), **innovating** (capacity-rich). Each demands a different intervention. Do not prescribe "innovate" to a team falling behind.
2. **Boring by default**: every system gets about 3 innovation tokens. Everything else should be proven tech. Spend tokens on the actual differentiator, never the supporting cast (databases, queues, deploy pipelines). [Choose Boring Technology, McKinley]
3. **DRY aggressively**, but not prematurely. Three similar lines is fine. The same logic in three places that diverges over time is a bug factory.
4. **Systems over heroes**: if "the only person who can fix this is X," the system is the problem.
5. **Reversibility (Bezos two-way doors)**: most decisions are reversible; move fast on those. Slow down only on the one-way doors. Tag every accepted plan choice as one-way or two-way explicitly.
6. **Two-week smell test**: if a competent engineer joining today cannot ship a small feature in two weeks, the onboarding or architecture has a problem worth surfacing.
7. **Blast radius**: for each change, what breaks if it goes wrong? A smaller blast radius is almost always worth more than less code.
8. **Explicit over clever**: clever code is a debugging tax. Explicit code is a maintainability dividend.
9. **Minimal diff**: the change should be the smallest patch that achieves the outcome. Drive-by refactors are a separate PR.
10. **Failure as info**: every error path is a UX. Treat error messages, retries, and recovery as features, not exception handling.
11. **DX is product quality**: internal developer experience compounds. If it takes 3 commands to test locally, that friction shows up in bug count.

## Inputs

- Path to the spec being reviewed.
- Optional: scope: `architecture` / `tests` / `performance` / `all` (default `all`).

## Behavior

### Step 0: read and frame

1. Read the spec end to end, including any prior `## CEO Review` section if `/review --ceo` already ran.
2. Memory-first: are there relevant prior architecture decisions in the `decisions` lane or in any active design docs? Surface them. When the lane is unset, say "no lane configured" and continue.
3. Diagnose state: for the team or unit this lives in, are we falling, treading, repaying, or innovating? Note it in the review header.

### Step 1: scope challenge (light)

Engineering review is HOLD SCOPE by default. If `/review --ceo` did not run, ask once: "Has the scope been pressure-tested? If not, consider `/review --ceo` first." Do not insist; sometimes the user knows. But surface it.

### Step 2: run the sections (output goes back into the spec when authorized)

Run **all** sections relevant to the spec. Each emits findings as: **Observation -> Risk -> Suggested fix -> Reversibility class -> Principle reference**.

#### Section 1: architecture

- Is the data flow drawn or describable in 3 sentences? If not, flag.
- Are the boundaries (modules, services, functions) named, and do they own clear responsibilities?
- Is an innovation token being spent here? Is it spent on the actual differentiator, or on plumbing? (Principle 2)
- One-way doors named? (Principle 5)

#### Section 2: error and rescue map

For each failure mode the spec implies:

- What does the user see?
- What does the system do (retry, fallback, surface)?
- What does the operator see (logs, alerts)?
- Can the user recover unaided, or is human intervention required?

If the spec does not address a failure mode for an obvious risk (network, auth, partial data, race), name it.

#### Section 3: security and threat model

- Auth boundary: who can call what? What is the abuse case?
- Data exposure: what gets logged, what gets shipped externally, what crosses a tier boundary (see `harness/rules/access-policy.md`).
- Injection surfaces: SQL, shell, prompt injection if an LLM is in the loop, XSS if HTML output.
- Secrets: anywhere a key or token is hardcoded or interpolated into config? (See `harness/rules/secrets.md`.)

#### Section 4: data flow and edge cases

- What if the input is empty, malformed, oversized, duplicate, in the wrong order?
- What if two clients act concurrently (race condition)?
- What if a downstream is unavailable for 10s? 10min? 10h?

#### Section 5: code quality stance

- DRY violations? Be aggressive (Principle 3), but do not flag three similar lines as a violation.
- Naming: does the spec name things clearly enough that an outside engineer could implement without asking?
- Dependency choices: boring or novel? Justified? (Principle 2)

#### Section 6: test strategy

- What tests would catch the obvious regression? Specify them; do not just say "add tests."
- Is there an end-to-end path worth automating, or is unit plus manual enough?
- **REGRESSION RULE:** if a bug fix is in scope, the spec must specify the regression test that fails without the fix and passes with it. No regression test means the bug is not really fixed.

#### Section 7: performance

- Where is the hottest path? What is the cost per call?
- N+1 patterns? Implicit O(n^2) where n grows?
- Caching strategy if any: what is the invalidation rule?

#### Section 8: observability

- When this breaks in production, what signal surfaces it?
- Are the logs structured? Do they include the IDs needed to debug?
- Metrics: what is the SLI, and what is the SLO?

#### Section 9: deployment and rollout

- Feature flag, canary, big-bang? Default to the smallest blast radius (Principle 7).
- Rollback plan: what does "undo this" look like at hour 1, day 1, week 1?

#### Section 10: long-term trajectory

- In 2 years, what becomes painful? Name the technical debt being created now, deliberately.

### Step 3: write back to the spec

When write-back is authorized, append a `## Engineering Review: <date>` section; otherwise report in conversation. Include:

- State diagnosis (one line)
- Findings per section, each tied to a principle and a reversibility class
- A **Test Plan** subsection: concrete tests to write, in priority order
- A **Failure Modes Registry** subsection: every failure mode named, with the rescue path
- A **One-way doors** subsection: an explicit list with rationale
- Open questions surfaced

### Step 4: suggest next step

- `/review --design` if UI has not been reviewed and there is UI scope.
- `/review --all` if the full pipeline is desired.
- "implement now" if scope, design, and engineering are all locked.

## Failure modes

- **Spec is too thin to engineer-review.** Push back: "I cannot review architecture if there is no architecture described. Outline the data flow first, or run `/review --ceo` to surface the missing structure."
- **User wants a yes/no.** Push back: this lens produces findings plus a test plan. "Approve / reject" is the user's call, not the skill's.
- **Spec is a hotfix with no real architecture.** Use a slimmed pass: Sections 4 (edge cases), 6 (regression test rule), 9 (rollout). Skip the rest.

## Notes

The eleven principles are adopted from the gstack `/plan-eng-review` skill (MIT). The "boring by default" plus "innovation tokens" framing is McKinley's *Choose Boring Technology*. State diagnosis is from Will Larson's *An Elegant Puzzle*. Brooks's question ("which problem are you really solving?") underlies the premise-challenge habit. [Source: gstack `/plan-eng-review` SKILL.md, fetched 2026-05-17]
