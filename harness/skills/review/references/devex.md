<!-- Lens reference for /review (--devex). Not a standalone skill. -->

# Developer experience review

## Purpose

Apply developer-experience judgment to a plan **before** the API, CLI, or SDK gets built. Audit how a real developer would experience the product across eight dimensions. Catch friction at the plan stage, when fixing it is cheap.

## Benchmark tiers

Each pass is scored against four tiers:

| Tier | Definition | Example |
|---|---|---|
| **Hall of Fame** | World-class for this dimension. Often imitated. | Stripe API docs, Rust error messages, Vercel deploy flow |
| **Excellent** | Strong, polished. Closes most friction. | A well-maintained mid-size OSS lib |
| **Adequate** | Works. Not embarrassing. | Most enterprise SaaS APIs |
| **Findable** | Information exists, but discovery is hard. | Older OSS libs with sparse docs |
| **Not addressed** | Dimension simply not in the plan. | none |

Score range: 0 (not addressed) to 10 (Hall of Fame).

## Three modes

CLI: `--devex-mode <dx-expansion|dx-polish|dx-triage>`; tokens map to the display labels below.

| Mode | Lens |
|---|---|
| **DX EXPANSION** | "How can DX be the competitive moat?" Push past Adequate, into Hall of Fame |
| **DX POLISH** | "Bulletproof every touchpoint." Get every dimension to Excellent |
| **DX TRIAGE** | "What is actively broken or missing?" Focus on dimensions below Adequate |

Default mode: **DX POLISH** unless the spec is for a competitive-DX product (then EXPANSION) or a hotfix-shape change (then TRIAGE).

## Inputs

- Path to the spec.
- Optional: target persona: `experienced` / `mid-level` / `student`. Default `mid-level`.
- Optional: `--devex-mode` override; `--mode` is an alias only when DevEx is the sole selected mode-bearing lens.

## Behavior

### Step 0: detect product type

Is this a developer-facing product? Signals: the spec mentions API endpoints, CLI commands, SDK methods, library functions, plugin interfaces, webhooks, OAuth flows. If no, stop and tell the user this lens does not apply.

### Step 0A: persona interrogation

Quick prose question: who is the primary developer for this?

- **Experienced**: knows the domain, expects power and unobtrusive defaults
- **Mid-level**: competent but new to this specific space; needs clear error messages and good docs
- **Student**: learning to code; needs hand-holding, lots of examples, gentle error messages

The persona shapes the scoring: what counts as "Hall of Fame" for a student is different from "Hall of Fame" for an experienced dev.

### Step 0B: competitive benchmark

Memory-first, then web search when the runtime provides it (the `web-search` capability): "[product category] developer experience best practices" and "[closest competitor] getting started." Record 3-5 reference time-to-hello-world (TTHW) figures. Without web search, use the reference anchors below and state that the benchmark was not refreshed:

- Stripe: about 30 seconds
- Vercel: about 2 minutes
- Firebase: about 3 minutes
- Docker: about 5 minutes

Use these as anchors for Pass 1.

### Step 0C: magical moment design

Ask: what is the moment in the first 5 minutes where the developer says "oh, this is great"? If the plan does not have one, that is a finding before any pass runs.

### Step 1: run the eight passes

#### Pass 1: getting started (zero friction)

*Rate 0-10.* TTHW measurement: count the steps in the plan's getting-started flow. Estimate minutes per step.

**Fix to 10:** write the ideal getting-started sequence step by step. Specify exact commands. Compare TTHW to the competitive benchmark from 0B. Flag every step that adds friction beyond what is strictly necessary.

#### Pass 2: API, CLI, or SDK design (usable plus useful)

*Rate 0-10:* are the names guessable without docs? Are the defaults sane? Does the surface area match the use case (not bloated, not anemic)?

**Fix to 10:** name the actual API, CLI, or SDK surface. Show example invocations. Test guessability: could the persona find the right method without reading docs?

#### Pass 3: error messages and debugging (fight uncertainty)

*Rate 0-10:* do error messages tell the developer (a) what went wrong, (b) why, (c) how to fix it, (d) where to learn more?

**Fix to 10:** for each error path identified in the engineering review's Section 2, write the actual error message. Apply the pattern Elm, Rust, and Stripe share: problem plus cause plus fix plus docs link.

#### Pass 4: documentation and learning (findable plus learn by doing)

*Rate 0-10:* is documentation structured (reference, how-to, tutorial, and explanation per Diataxis)? Is search good? Are code examples copy-pasteable? Is there a language switcher?

**Fix to 10:** map the planned docs to the Diataxis quadrants; if a quadrant is missing, flag it. Specify whether docs ship with the product or come later. Name a search strategy (built-in, a hosted search service, and so on).

#### Pass 5: upgrade and migration path (credible)

*Rate 0-10:* does the plan think about v2? Is there a CHANGELOG strategy, a migration guide pattern, a deprecation warning convention?

**Fix to 10:** specify the upgrade story. Even at v0.1, name the conventions: semver, deprecation warnings with N versions of notice, CHANGELOG format.

#### Pass 6: developer environment and tooling (valuable plus accessible)

*Rate 0-10:* is local setup specified end to end? Is CI specified? Are types or contracts published? Are test fixtures provided?

**Fix to 10:** walk through "clone repo -> run hello world" as if you were the persona. Time it. Specify every prerequisite explicitly.

#### Pass 7: community and ecosystem (findable plus desirable)

*Rate 0-10:* is there a planned community surface (chat, discussions, a message board)? An issue-response SLA? A contributing guide?

**Fix to 10:** specify the community channel, the moderation discipline, the contributing guide structure, and the issue-triage cadence.

#### Pass 8: DX measurement and feedback loops (implement plus refine)

*Rate 0-10:* can DX be measured? Is TTHW instrumented? Is there an NPS or feedback collection point?

**Fix to 10:** name the metrics, the collection method, the review cadence.

### Step 2: write back to the spec

When write-back is authorized, append a `## DevEx Review: <date>` section; otherwise report in conversation. Include:

- Persona used
- Mode used (EXPANSION / POLISH / TRIAGE)
- Per-pass scores against the benchmark tier (for example, "Pass 1, Getting Started: 6/10, Adequate, target Excellent")
- Magical moment specification (if surfaced in Step 0C)
- Competitive benchmark table (TTHW comparison)
- A **DX Implementation Checklist** subsection: concrete items to ship
- Open questions

### Step 3: suggest next step

- `/review --eng` if the architecture review has not run.
- `/review --all` for the full pipeline.
- "implement now" if all reviews look clean.
- Recommend a post-shipping `/review --devex` as a boomerang once shipped: TTHW target versus reality.

## TTHW priority order

If you have to triage, fix in this order:

1. Magical moment design (the differentiator)
2. TTHW (the gate to everything else)
3. Error message quality (the source of dropoff)
4. Getting started (the funnel)
5. API/CLI ergonomics
6. Everything else

## Failure modes

- **Plan has no developer surface.** Stop. Do not fabricate a DX review for a consumer-app feature.
- **User wants you to validate that the plan is "developer-friendly."** Push back. The lens produces scores plus concrete fixes. "Developer-friendly" is the user's takeaway after seeing the scorecard, not the skill's verdict.
- **No competitor exists, or no web search is available.** Skip the live benchmark from 0B; use the reference TTHWs (Stripe, Vercel, Firebase, Docker) as the anchors and say so.

## Notes

The eight passes, the TTHW framework, and the tier-based scoring are adopted from the gstack `/plan-devex-review` skill (MIT). The TTHW reference anchors are gstack's; they are useful because they are widely recognized in the DX community. The magical-moment-design framing is also gstack's. [Source: gstack `/plan-devex-review` SKILL.md, fetched 2026-05-17]
