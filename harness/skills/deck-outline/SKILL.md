---
name: deck-outline
description: >
  Create an evidence-grounded Markdown slide outline in education, investment, or introduction mode. Produces the argument or teaching arc, one message per slide, citations and gaps, visual suggestions, timing, and speaker cues. WHEN: user invokes /deck-outline <education|investment|introduction>, asks to outline a teaching deck, investor deck, or introductory presentation, or wants the narrative settled before rendering. WHEN NOT: HTML or PowerPoint production, visual rendering, or deployment (use /deck-render --web once the outline is approved); one-off slide edits; review of an already rendered deck.
metadata:
  packs: [decks]
  triggers:
    - "outline a teaching deck"
    - "outline an investor deck"
    - "outline an intro deck"
    - "settle the deck narrative before slides"
    - "structure this training presentation"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# deck-outline

Turn source material into an approved Markdown outline or slide map. This skill owns content structure only. It does not create HTML, PPTX, a builder, rendered slides, or a deployment.

## Invocation

`/deck-outline <education|investment|introduction> <subject> [--audience <audience>] [--duration <minutes>]`

Choose one mode from the user's objective. Ask only for missing inputs that materially change the arc. Load the matching reference and no other mode reference:

- education: [education.md](./references/education.md)
- investment: [investment.md](./references/investment.md)
- introduction: [introduction.md](./references/introduction.md)

The reference files are read from this skill's folder. On a runtime that materializes only `SKILL.md` (the generated Codex wrapper), read them from the repository path `harness/skills/deck-outline/references/`.

## Shared method

1. Lock audience, objective, desired next action, duration, and source scope.
2. Sweep local material first: the sources the user supplies, plus the knowledge and docs lanes when `harness/registry/structure.json` configures them. Verify time-sensitive external claims only when the task requires them and record sources near the claims.
3. Separate supported claims from gaps. Never turn a gap into plausible copy or an invented metric.
4. Draft the arc, then a slide map with one assertion or teaching message per slide.
5. Walk the user through the arc and slide messages. Iterate until approved before handing it to a renderer.

## Output contract

Return or save Markdown containing:

- brief: subject, mode, audience, objective, duration, and desired next action
- arc: the argument, teaching sequence, or introduction flow
- slide map: slide number, working title, one message, supported claims with cited sources, evidence gaps and owners, visual suggestion, timing, and speaker cues
- appendix or optional cuts when the duration requires them
- approval state, and the approval date in ISO form once the user approves the outline

Claims cite deterministic local paths or external sources. Gaps stay visible. Visual suggestions describe what must carry the message; they do not fabricate product screens, people, traction, or data.

## Output destination

Return the Markdown in the reply by default. When the user asks for a file, write it to the docs lane resolved through `harness/registry/structure.json` when that lane is configured, otherwise to a path the user names. No lane is mandatory for this skill: when the docs lane is unset and no path was named, ask for a path rather than inventing a folder.

## Handoff

After the outline is approved, `/deck-render --web <outline>` may build it. The renderer confirms currency and format, but does not force a second approval of an outline already approved in the current session. A material content or evidence change reopens only the affected outline slides.

`--pptx` is unavailable. Do not imply that PowerPoint output exists.
