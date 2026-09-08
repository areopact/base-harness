<!-- Lens reference for /review (--ceo). Not a standalone skill. -->

# CEO scope review

## Purpose

Apply CEO or founder thinking to a product spec, a business plan, or a design doc **before** implementation. The job is not to validate the plan. It is to surface where the plan might be quietly small-thinking, where scope is wrong-shaped, and where the **10-star product** is hidden inside the current draft.

Four operating modes; state the selected mode. CLI: `--ceo-mode <scope-expansion|selective-expansion|hold-scope|scope-reduction>`; tokens map to the display labels below.

| Mode | Lens | Output |
|---|---|---|
| **SCOPE EXPANSION** | "You are building a cathedral. Push scope UP." | Multiple expansion proposals, each as an individual opt-in decision |
| **SELECTIVE EXPANSION** | "Hold the baseline; surface expansions to cherry-pick." | Neutral, evocative options; the user picks zero, one, or many |
| **HOLD SCOPE** | "The plan's scope is right. Make it bulletproof." | Rigor pass; no scope changes surfaced |
| **SCOPE REDUCTION** | "Find the minimum viable. Cut everything else." | Stripped-down version that achieves the core outcome |

## Inputs

- Path to an existing spec: the path the user names, or a doc under the `docs` lane.
- Optional: target mode. If omitted, infer an explicit expansion or reduction intent; otherwise default to hold-scope and state it. Ask only when a material scope ambiguity prevents useful review.

## Behavior

### Step 0: memory-first plus premise challenge

1. Read the spec end to end. Note the framing sentence, the named human (from `/brainstorm --venture` question 3), the narrowest wedge (question 4), and the future-fit hypothesis (question 6).
2. Memory-first sweep: search the `knowledge` and `decisions` lanes for prior thinking, related decisions, active design docs, and adjacent owner docs. When a lane is unset, say "no lane configured" and continue.
3. **Premise challenge:** state in one paragraph what you think the underlying premise is. The user reframes if needed. *Do not skip this. Most "bad plans" are actually correct plans for the wrong premise.*

### Step 1: state the mode

Honor an explicit mode or clear user intent. Otherwise select HOLD SCOPE and state it; ask only when a material ambiguity prevents useful review.

| User intent | Mode |
|---|---|
| Expand scope / explore the 10-star version | SCOPE EXPANSION |
| Offer optional expansions to cherry-pick | SELECTIVE EXPANSION |
| Cut scope / find the minimum viable version | SCOPE REDUCTION |
| Hold scope, or no expansion/reduction intent | HOLD SCOPE |

Greenfield status, a feature enhancement, or a long feature list alone does not authorize an expansion or reduction mode. Surface a reason to switch as an option.

### Step 2: mode-specific analysis

#### SCOPE EXPANSION

Generate 3-6 expansion proposals. For **each**:

1. State the 10-star version: "If this product were built to be world-class in [dimension], it would..."
2. Frame the expansion as a numbered prose option with: the proposal, why it raises the ceiling, what it costs in complexity, time, and team, the reversibility class (one-way / two-way), and a one-line recommendation.
3. The user opts in or out **per proposal**. Never batch; every expansion is its own decision.

Posture: "vivid, not promotional." "Makes the product feel 10x more alive" is vivid. "This would 10x your revenue" is over-sell. Cut the over-sell.

#### SELECTIVE EXPANSION

1. Run a HOLD SCOPE pass first (see below) to make sure the baseline is rigorous.
2. Then surface 3-6 expansion opportunities as **neutral options** (no recommended default).
3. The user cherry-picks. Most picks are reasonable; reject anything that creates coupling or breaks the wedge.

#### HOLD SCOPE

Run rigor passes; no scope changes. Sections (only run those relevant to the spec):

1. **Architecture sanity**: is the data flow specified? Are the boundaries clear?
2. **Error and rescue map**: for each failure mode, what happens to the user, the data, the system?
3. **Security and threat model**: auth boundaries, data exposure, prompt injection if an LLM is involved.
4. **Code quality stance**: DRY, naming, dependency choices, boring versus novel.
5. **Test stance**: what tests would prevent the obvious regression?
6. **Observability**: when this breaks in production, how does anyone notice?
7. **Deployment and rollout**: feature flag, canary, big-bang, manual?
8. **Long-term trajectory**: in 2 years, what becomes painful about this design?
9. **Design and UX** (if UI scope): accessibility basics, mobile and desktop, error states.

Each section emits findings as: **Observation -> Risk -> Suggested fix**. When write-back is authorized, findings go into the spec under `## CEO Review (HOLD SCOPE)` as an addition to the summary.

#### SCOPE REDUCTION

1. State the **core outcome** in one sentence. The thing that, if not achieved, makes everything else pointless.
2. List every feature or component the spec proposes. For each: does it serve the core outcome **this week**? Or is it for a future state?
3. Strip everything not serving the core outcome. Write the stripped version as the new summary.
4. Capture the cut items in a separate `## Deferred from CEO reduction` section so they are not lost; a later triage pass can promote them back if the wedge proves out.

### Step 3: temporal interrogation

Run regardless of mode:

- **3-month check:** what does success look like in 3 months? A concrete metric, not vibes.
- **2-year check:** in 2 years, is this still core, or has the world moved past it?
- **One-way door check:** what in this plan, once shipped, cannot be undone? Flag each and identify missing decision evidence; do not create a record automatically.

### Step 4: write back to the spec

When write-back is authorized, append a `## CEO Review: <date>` section to the spec; otherwise report in conversation. It includes:

- Mode used plus why
- Premise (restated)
- Findings or expansions (per mode)
- Accepted versus deferred items
- Open questions surfaced
- Suggested next step (`/review --eng`, `/review --design`, `/review --all`, or just "implement now")

Identify one-way doors and missing decision evidence. Recording a decision requires user intent and the appropriate owner; do not create one automatically.

### Step 5: suggest next step

- `/review --eng` if the scope is now locked and architecture is the next question.
- `/review --design` if UI is core and design needs the same rigor.
- `/review --all` if you want the full pipeline (CEO -> Design -> Eng -> DX), though this lens alone is often enough.

## Failure modes

- **User asks for approval.** Give an evidence-grounded assessment with conditions and unresolved issues. Use HOLD SCOPE absent other intent; do not introduce a routine mode question.
- **User cannot pick a mode.** Default to HOLD SCOPE and offer to switch if the rigor pass surfaces something that begs for expansion or reduction.
- **Spec is too vague to review.** Identify the missing scope. For a business idea, use `/brainstorm --venture`; for other plans, clarify or use `/brainstorm`.

## Notes

The four-mode framework is from the gstack `/plan-ceo-review` skill (MIT). The core distinctions are preserved because the mode-as-lens discipline is what makes the review useful: without explicit mode selection, founders tend to oscillate between "this is amazing" and "this is overbuilt" without ever committing to a direction. [Source: gstack `/plan-ceo-review` SKILL.md, fetched 2026-05-17]

One principle applies especially in SCOPE EXPANSION: when the marginal cost of AI-assisted work is near zero, the expensive-looking complete version (build the whole thing rather than the minimum) is often the right call, because the cost that used to justify cutting scope no longer exists. But not always; the user decides per proposal.
