---
name: deck-render
description: >
  Render an approved outline as an interactive HTML presentation with --web. The deck behaves like fixed 16:9 slides in a browser, with page-by-page wheel and keyboard navigation, compact current-slide chrome, reusable motion, image-led layouts, and mechanical QA. WHEN: user invokes /deck-render --web, asks to render an approved outline as a web presentation, HTML slide deck, browser-based deck, or animated slides. WHEN NOT: unresolved narrative or evidence work (use /deck-outline first); PowerPoint, PPTX, or Google Slides delivery (unavailable); deployment without an explicit publishing request; an ordinary scrolling website.
metadata:
  packs: [decks]
  triggers:
    - "render this outline as a web presentation"
    - "build an HTML slide deck"
    - "browser slide deck from an approved outline"
    - "animate these slides"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# deck-render

## Purpose

Turn approved content into a projection-ready web deck. The output is a small static bundle that opens in any modern browser and keeps true slide semantics on every viewport. The stage is always 16:9; the space outside it is calm letterboxing, never extra content.

This skill owns the browser show layer. `deck-outline` and `eli5 --deck` hand an approved slide map to it for implementation.

## Format boundary

Invoke as `/deck-render --web <outline>`. `--web` is the only supported format. `--pptx` is unavailable because no PPTX renderer dependency is implemented. Do not offer, emulate, or claim PowerPoint output.

## Load only what the job needs

- Read [design-system.md](./references/design-system.md) before building or revising any deck. It defines stage, type, motion, image, navigation, and accessibility invariants.
- Read [layout-catalog.md](./references/layout-catalog.md) when selecting or changing slide compositions.
- Read [motion-and-data.md](./references/motion-and-data.md) when the deck contains animated text, charts, tables, diagrams, or a data story spanning several slides.
- Read [investment-web.md](./references/investment-web.md) only for an investment-mode outline.
- Start from [the starter bundle](./assets/starter/) for a new deck. Keep its runtime intact unless the requested behavior requires a deliberate change.

The references, starter, and scripts are read from this skill's folder. On a runtime that materializes only `SKILL.md` (the generated Codex wrapper), read them from the repository paths `harness/skills/deck-render/references/`, `harness/skills/deck-render/assets/starter/`, and `harness/skills/deck-render/scripts/`.

## Workflow

1. **Confirm the content is build-ready.** Establish audience, setting, duration, source material, and the one point each slide must land. An outline approved in the current session does not need another approval; confirm only that its evidence and content have not materially changed. If narrative or evidence is unresolved, return the affected slides to `deck-outline` before styling them.
2. **Map the deck.** For every slide, record the message, chapter, density mode, catalog layout and variant, visual proof, and animation primitive. Use `inspire`, `default`, `dense`, or `research` deliberately; a smaller mode never excuses an unclear argument. Decks longer than 20 slides get a detailed grouped contents list after the cover and stable `data-section` chapter labels.
3. **Choose one visual system.** Define the palette, type pairing, ambient background, image treatment, radii, and motion tempo once. A deck may vary composition while keeping these tokens stable.
4. **Build from the starter.** Copy the entire starter bundle to the requested output folder. Author one `<section class="slide">` per page, declare a catalog `data-layout`, and preserve the runtime hooks and compact page indicator.
5. **Use images as evidence or atmosphere.** Prefer supplied or owned assets. Use generated editorial imagery only when it cannot be mistaken for product, people, traction, or other factual proof. Choose a declared hero, split, pair, triptych, quad, mosaic, filmstrip, portrait, screenshot, or document slot; do not improvise image confetti.
6. **Apply the motion vocabulary.** Slide transitions, text reveals, chart paths, rings, bars, counters, tables, and flow nodes use the provided primitives. Motion must be interruptible, replayable on revisit, and disposable under `prefers-reduced-motion`. A motion-catalog slide may use the dedicated slow demonstration loop with a 500ms final-state dwell; ordinary slide content never loops.
7. **Run mechanical QA.** Execute `python harness/skills/deck-render/scripts/check_deck.py <deck-index.html>` and clear its warnings as well as its errors, including any character-based measure cap it reports on display type. Then open `?qa=1`, inspect the returned result at common 16:9, 16:10, ultrawide, and portrait viewports, and exercise wheel, arrow, Page Up/Down, Space, Home/End, and touch navigation where available.
8. **Run visual QA.** Review every slide at fit-to-window and at full-screen projection scale. Fix overflow, weak hierarchy, tiny images, crop mistakes, layout repetition, and animation timing. A passing script is not a visual sign-off.

## Non-negotiable output contract

- The deck stage remains exactly 16:9 on every screen, including phones. Content never reflows into a scrolling article.
- The surrounding viewport uses a low-contrast solid, gradient, or subtle texture that cannot compete with the slide.
- Wheel and keyboard input move exactly one page at a time. Rapid wheel events are thresholded and locked so one gesture cannot skip several slides.
- The only required visible navigation chrome is a bottom-right number such as `07`. It never includes the word "slide", a total, fraction, dot rail, or progress bar unless the user explicitly asks for one. Accessible slide labels may include position and set size for assistive technology.
- A deck longer than 20 slides includes an interactive, grouped contents list detailed enough to name the individual pages, plus a hidden chapter map. The bottom-right number opens the map, `M` toggles it, and `Escape` closes it. The closed state adds no persistent chrome.
- Typography uses one of four complete token packs: `.density-inspire`, `.density-default`, `.density-dense`, or `.density-research`. Do not shrink isolated elements outside the selected pack.
- Research density comes from structured evidence, columns, and tighter rhythm, not sub-legible type or empty panels stretched to a fill target.
- Slide transitions and object animations come from the established primitives. No autoplay loops, parallax, scrolljacking stacks, or motion-only meaning.
- Images use declared slots, focal points, and crop families. Comparison grids use equal geometry; editorial mosaics may vary geometry but preserve an obvious reading order.
- Data graphics use the chart grammar, factual labels, and final-state-first DOM. A related data story may continue across several adjacent slides when one chart would be overloaded.
- A finished deck includes a purposeful closing slide. Supporting evidence that would interrupt the main narrative moves to clearly marked appendix slides using the same runtime and numbering.
- Content is vertically centred in the stage unless a layout class or `.content-top` says otherwise, and no slide leaves a dead band under its content while the composition sits pinned to the top edge.
- Titles wrap because their container is full, never because a character cap decided it. Display measure is bound to the container or to container units; `ch` caps belong to running text only, since one `ch` is the element's own glyph width and shifts with typeface, size, and case. Derive any cap from a render at the target viewport and record its basis.
- Short compositions occupy the vertical center of the safe area instead of clustering against the top. Dense appendix examples span at least 80% of the safe-area height; a research example spans at least 90% and uses the matching `data-fill-target` QA hook.
- Interactive slides use native buttons, ranges, selects, and outputs with visible focus, explicit labels, deterministic reset behavior, and a useful static final state. Interaction never blocks ordinary slide navigation when focus leaves the control.
- All slide content exists in the DOM before animation. JavaScript failure leaves a readable deck.
- Every deck honors reduced motion, keyboard access, visible focus, and print-safe final states.

## Output and publishing

Write the bundle where the user names it. Otherwise use the docs lane resolved through `harness/registry/structure.json` when that lane is configured; otherwise write to a scratch path (the runtime's session scratch directory, or `.tmp/decks/<slug>/` in the repository) and print that path in the output. Never use a temporary folder silently. Keep source assets next to the deck when they are needed to revise it.

Publishing is a separate external write. Deploy only when the user explicitly requests a live URL, then verify the real path after deployment. Never read or embed secrets; deployment tools consume credential environment variables by name. When a host needs one self-contained document, fold the bundle with `python harness/skills/deck-render/scripts/inline_bundle.py <deck-dir> <out.html>`.

## Failure modes

- **Responsive article behavior:** changing to vertical cards on phones breaks the requested medium. Scale the stage as one object.
- **Decorated emptiness:** anti-slop rules without a visual floor produce clean but weak slides. Content slides need an argument-carrying image, chart, diagram, or composition.
- **Image confetti:** several tiny unrelated images are worse than one image large enough to read.
- **Dense by default:** shrinking every font to save a slide hides an outline problem.
- **Motion invention:** new easing, duration, and entrance behavior on each page destroys rhythm.
- **Permanent navigation furniture:** a visible rail or thumbnail strip competes with the slide. Keep the chapter map hidden until the page number, `M`, or a contents link opens it.
- **Button-shaped non-controls:** pills and raised boxes invite clicks. Data-story markers and labels stay typographic unless they actually perform an action.
- **Browser-only success claim:** source inspection cannot catch bad crops or projection-scale hierarchy. Render and inspect.
