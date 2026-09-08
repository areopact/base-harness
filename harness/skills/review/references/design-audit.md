<!-- Lens reference for /review (--design-audit). Not a standalone skill. -->

# Design audit

## Purpose

Audit a design spec for visual coherence, AI-slop patterns, and accessibility using the source and any available rendered evidence. Most design rot at the spec stage is detectable from prose: generic adjectives ("clean, modern, intuitive"), missing accessibility specs, uniform border-radius vibes, fonts unspecified.

This lens produces an A-F grade per category, an independent AI-Slop grade, and a Goodwill Reservoir trace through the implied user flow.

## When to use which design lens

- `/review --design`: plan-stage 0-10 rating *with fix-to-10 actions*. Runs before any visual work exists. Forward-looking.
- `/review --design-audit` (this lens): post-spec consistency audit on what has actually been written. Looks back. Catches drift from `DESIGN.md` if it exists.
- For rendered artifacts or live sites, use the available matching artifact or browser skill to inspect them. If unavailable, disclose the limit; do not install a toolchain or claim visual verification from prose alone.

## The ten categories (each graded A-F)

| Category | What is audited |
|---|---|
| **1. Visual hierarchy** | First, second, third element by visual weight. Does the eye know where to go? |
| **2. Typography** | Font specified by name. Type scale defined. Body text at least 16px. Line-height and tracking opinionated. |
| **3. Color and contrast** | Palette named (not "various blues"). Contrast ratios specified for body and large text. |
| **4. Spacing and layout** | Spacing scale defined (4/8/12/16/24/32 or similar). Layout grid named. |
| **5. Interaction states** | Loading, empty, error, success, partial: each specified per interactive element. |
| **6. Responsive** | Breakpoints named. Mobile is not "stacked"; it is an intentional layout. |
| **7. Motion** | Easing curves, durations, what animates and why. Or explicitly: "no motion." |
| **8. Content and microcopy** | Voice specified. Error message structure named. CTAs concrete, not "Submit." |
| **9. AI Slop** | See the checklist below; graded independently *and* as 5% of overall. |
| **10. Performance as design** | Page weight target. LCP target. Image strategy. "Loading is part of UX." |

## AI Slop blacklist (graded as its own headline)

These patterns scream "AI-generated"; auto-flag each:

1. Three-column feature grid as the first impression
2. Uniform bubbly border-radius across everything (use a small intentional system: 2/4/8/12/16)
3. Decorative gradient blobs or "abstract shapes" with no functional purpose
4. `system-ui` / `-apple-system` as the **primary** display or body font: the "I gave up on typography" signal. *A tertiary fallback is fine; primary is not.*
5. Body text below 16px or contrast ratio below 4.5:1
6. Hero with a stock-photo-shaped image plus a generic value-prop headline
7. "Modern, clean, intuitive" as the entirety of the design direction
8. Generic SaaS card grid pattern
9. Repeated identical-looking sections separated only by alternating background colors
10. Emoji used as decoration to compensate for missing typographic personality

## Goodwill Reservoir tracking

Trace the implied user flow described in the spec. Every user starts with about 70/100 goodwill. Walk the flow and adjust:

**Subtract for:**
- Hidden info ("learn more" requiring extra clicks)
- Format punishment (rejecting credit card numbers with spaces, and the like)
- Interstitials between the user and the goal
- Sloppy appearance (uniform border-radius, system-ui)
- Ambiguous choices (3 CTAs equally weighted)

**Add for:**
- An obvious primary action
- Cost transparency (price visible without scroll or click)
- Saved steps (autocomplete, defaults)
- Graceful error recovery (state preserved, clear fix)
- Magical moments (a small surprise that delights)

The end-of-flow goodwill score is part of the report.

## Inputs

- Path to the design spec: the path the user names, a doc under the `docs` lane, or a `DESIGN.md` reference doc.
- Optional: `--scope <category-list>` to limit categories.

## Behavior

### Step 0: read and frame

1. Read the spec end to end.
2. Memory-first: does a `DESIGN.md` exist for this product? If yes, read it; categories 1-8 should align.
3. Identify the implied user flow: even if not drawn, what is the sequence of states or screens the user moves through?

### Step 1: run the ten categories

For each category, grade A-F based on the spec's content:

- **A**: specific, opinionated, world-class for this category
- **B**: specific, complete, no obvious gaps
- **C**: specified but generic or with small gaps
- **D**: mostly unspecified or relying on vibes
- **F**: not addressed at all

For each non-A grade, name **one concrete fix** the spec could adopt to reach A.

### Step 2: AI Slop blacklist scan

Walk the 10 patterns above. For each match, quote the relevant spec line and propose a specific replacement (not "be more intentional" but "replace `system-ui` with a named font; suggested: Inter for UI, Source Serif for body").

The AI-Slop grade is computed standalone (count of slop patterns triggered) AND folds in as 5% of the overall design grade.

### Step 3: Goodwill Reservoir trace

Walk the user flow. At each step, name the goodwill impact. The final score is the running total.

### Step 4: compute overall grade

Weighted average of categories 1-10:

| Category | Weight |
|---|---|
| Visual hierarchy | 15% |
| Typography | 15% |
| Color and contrast | 10% |
| Spacing and layout | 10% |
| Interaction states | 12% |
| Responsive | 10% |
| Motion | 5% |
| Content and microcopy | 8% |
| AI Slop | 5% |
| Performance as design | 10% |

Overall grade rounded to A, B, C, D, or F.

### Step 5: report

Report in conversation by default. When write-back is authorized, append a `## Design Review: <date>` section to the spec with:

- Per-category grade with a one-line rationale plus a one-line fix-to-A
- AI Slop standalone grade with quoted offenders
- Goodwill Reservoir trace with the running score
- Overall grade with a one-paragraph summary
- A list of high-impact fixes, sorted by leverage

## Failure modes

- **Spec has no design content.** Tell the user; use `/review --design` for an existing design plan or `/brainstorm` to establish UI needs.
- **Visual assets are unavailable.** Report the inspection limit. Use accessible images or rendered artifacts through the matching tool when available; never imply prose-only inspection verified appearance.
- **The spec is intentionally minimal (an MVP, say).** Adjust grading: a D in "motion" for an MVP is fine; a D in "interaction states" is not.

## Notes

The ten categories, the AI Slop blacklist, and the Goodwill Reservoir are adopted from the gstack `/design-review` skill (MIT). The discipline of grading AI Slop independently is the most useful idea: it makes the failure visible as a headline number rather than buried in a general design score. [Source: gstack `/design-review` SKILL.md, fetched 2026-05-17]
