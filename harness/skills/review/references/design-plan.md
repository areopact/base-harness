<!-- Lens reference for /review (--design). Not a standalone skill. -->

# Design plan review

## Purpose

Apply designer judgment to a plan **before** UI gets built. Rate each design dimension 0-10. If it is not a 10, explain what would make it a 10, then write the fixes into the spec when authorized. Catches AI-slop patterns (generic feature grids, system-ui fonts, blob decorations) before they ship.

This is the **plan-stage** design review. For rendered or live-site visual audits, use the available matching artifact or browser skill. Disclose inspection limits if unavailable; do not install another toolchain as part of this review.

## Operating posture

- **Specificity over vibes.** "Clean, modern UI" is not a design decision. Name the font. Name the spacing scale. Name the interaction pattern.
- **Accessibility is not optional.** Keyboard navigation, screen readers, contrast, touch targets: specify them in the plan or they will not exist.
- **Goodwill reservoir.** Every user starts with about 70/100 goodwill. Hidden info, format punishment, interstitials, sloppy appearance, and ambiguous choices subtract. An obvious primary action, cost transparency, saved steps, and graceful error recovery add. Most products bleed goodwill from a thousand small choices.

## The 0-10 rating method

Each pass below produces a score 0-10. If not 10, the lens names what would make it a 10, then writes those fixes back into the spec when authorized. No section is "good enough": either it is 10 or there is an explicit fix list.

| Score | Meaning |
|---|---|
| 10 | World-class for this dimension. Nothing to improve. |
| 7-9 | Solid. Specific named gaps. |
| 4-6 | Has structure but multiple concrete problems. |
| 1-3 | Generic, AI-slop, or unspecified. |
| 0 | Not addressed at all. |

## Inputs

- Path to the spec.
- Optional: focus areas, which restrict which passes run (default: all 7 passes).

## Behavior

### Step 0: detect UI scope

If the spec has no UI/UX components, stop and tell the user. Do not fabricate a design review for backend work.

### Step 0A: initial rating

Rate the spec's overall design completeness 0-10 before any pass. This is the baseline for the boomerang at the end.

### Step 0B: design system check

Does a `DESIGN.md`, brand guide, or design system reference exist for this product? If yes, read it; every pass should align. If no, flag it ("no design system defined; every choice becomes a one-off") but do not refuse.

### Step 1: run the seven passes

#### Pass 1: information architecture

*Rate 0-10:* does the plan specify what the user sees first, second, third? Is the hierarchy explicit?

**Fix to 10:** write the actual visual hierarchy: primary headline, secondary CTAs, tertiary navigation, supporting body. Specify which element wins the eye on first load.

#### Pass 2: interaction state coverage

*Rate 0-10:* does the plan specify loading, empty, error, success, and partial states?

**Fix to 10:** for each interactive element, name all five states. Do not just say "show an error"; write what the error says, what action it offers, what the recovery looks like.

#### Pass 3: user journey and emotional arc

*Rate 0-10:* does the plan consider how the user feels at each step? Where is the magical moment? Where might they bounce?

**Fix to 10:** trace the user's first five minutes step by step. Mark the high-friction beats. Specify one magical moment that surprises them positively.

#### Pass 4: AI-slop risk

*Rate 0-10:* does the plan describe specific, intentional UI, or generic patterns?

**Slop signals (auto-flag each):**

- Three-column feature grid with uniform card styling
- Bubbly uniform border-radius across all elements
- Decorative gradient blobs or "abstract shapes"
- `system-ui` / `-apple-system` as the primary display or body font (the "I gave up on typography" signal)
- Body text below 16px or contrast ratio below 4.5:1
- Hero with a stock-photo-shaped image plus a generic value-prop headline
- "Modern" / "clean" / "intuitive" as the entirety of the design direction

**Fix to 10:** replace each slop signal with a specific intentional choice. Name the font. Name the spacing scale (4/8/12/16/24/32...). Specify the interaction pattern (modal versus inline versus drawer). State *why* this choice fits this product.

#### Pass 5: design system alignment

*Rate 0-10:* does the plan align with `DESIGN.md` if one exists? Are the typography, color, and spacing choices consistent?

**Fix to 10:** either align with the existing system, or explicitly document why this is a deliberate exception.

#### Pass 6: responsive and accessibility

*Rate 0-10:* does the plan specify mobile and desktop layouts? Keyboard navigation? Screen reader behavior?

**Fix to 10:** per breakpoint, name the layout shift (not "stacked on mobile"; name the intentional change). Specify keyboard nav order. Name ARIA landmarks. Touch targets at least 44px. Contrast at least 4.5:1 for body, at least 3:1 for large text.

#### Pass 7: unresolved design decisions

*Rate 0-10:* does the plan name the design decisions that are still open? Or does it pretend everything is decided?

**Fix to 10:** surface the actual open decisions as numbered prose questions with the options inline. Capture each user choice in the spec.

### Step 2: write back to the spec

When write-back is authorized, append a `## Design Review: <date>` section; otherwise report in conversation. Include:

- Initial rating (0-10 from Step 0A)
- Per-pass scores with concrete fixes applied
- Slop signals caught (if any)
- Final rating after fixes
- A **Design Decisions** subsection: every user choice from Pass 7 captured
- Open questions

### Step 3: suggest next step

- `/review --eng` if architecture has not been pressure-tested.
- `/review --all` for the full pipeline.
- "implement now" if all three reviews look clean.

## Design hard rules (auto-flag in any pass)

- system-ui as primary display or body font
- Body text below 16px
- Contrast ratio below 4.5:1 on body text
- Uniform border-radius across all elements (use a small system: 2/4/8/12/16)
- "Modern, clean, intuitive" as the entire design direction
- No accessibility section at all
- No mobile-specific layout decisions

Hard-rule violations get auto-fix proposals; the user can accept or override per item.

## Failure modes

- **Spec has no design content.** Stop. Tell the user there is nothing to review. Use `/brainstorm` to establish UI needs; skip this lens when UI is irrelevant.
- **User wants a yes/no.** Push back: this lens produces 0-10 scores with concrete fixes, not approvals.
- **Spec is for a code-only feature (no UI).** Skip entirely; flag for the user that this lens was inapplicable.

## Notes

The 0-10 rating method, the seven passes, and the AI-slop detection are adopted from the gstack `/plan-design-review` skill (MIT). The Goodwill Reservoir concept is gstack's framing too. The hard-rule list distills patterns common in AI-generated UI that signal a lack of typographic intent. [Source: gstack `/plan-design-review` SKILL.md, fetched 2026-05-17]
