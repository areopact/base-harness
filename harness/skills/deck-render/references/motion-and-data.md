# Web deck motion and data grammar

Read this reference when a deck uses animated text, charts, tables, diagrams, or a data story across several slides. The starter runtime implements these attributes without external dependencies.

## Motion principles

Motion answers one of four questions: what entered, what changed, what connects, or what deserves attention. If an animation answers none of them, remove it.

- Use one primary object primitive per slide and no more than two supporting primitives.
- Keep peer staggering at `50-90ms`; keep the normal total entrance sequence under `500ms`.
- `data-delay="N"` sets the delay. `data-duration="N"` may override the default between `160-1600ms`.
- Every target begins as readable DOM content. QA, print, no-JavaScript, and reduced-motion modes show the final state.
- Do not autoplay the next slide, loop ordinary slide content, or require animation to understand a value.

### Motion-catalog demonstration loop

A slide whose purpose is to compare motion primitives may declare `data-demo-loop="500"`. The value is the final-state dwell in milliseconds: use `800-1100ms` object durations, let the longest stagger finish, hold for 500ms, then replay. The runtime pauses the loop as soon as the slide becomes inactive. Reduced-motion, QA, capture, print, and no-JavaScript modes show the final state without looping. Do not reuse this attribute on narrative, data, appendix, or closing slides.

## Slide transitions

Set the deck default on `.deck[data-transition]`; override an individual page with the same attribute on `.slide`.

| Value | Use | Default |
|---|---|---:|
| `fade` | calm continuity, research, appendix | `420ms` |
| `push` | narrative or data-story progression | `520ms` |
| `rise` | section opening or reveal | `500ms` |
| `scale` | image, quote, or reflective beat | `480ms` |

## Text primitives

| Attribute | Behavior | Best use |
|---|---|---|
| `data-animate="fade"` | opacity | captions and quiet support |
| `data-animate="rise"` | short vertical entrance | ordinary titles and body blocks |
| `data-animate="scale"` | subtle scale from `0.96` | media or one emphasized phrase |
| `data-animate="pop"` | scale from `0.72` | chips, nodes, or single numerals |
| `data-animate="wipe"` | left-to-right clip reveal | short headline or section label |
| `data-animate="mask"` | bottom-to-top clipped reveal | one line inside `.text-mask` |
| `data-animate="focus"` | blur resolves to sharp | reflective statement; one per slide |
| `data-animate="tracking"` | wide tracking settles | eyebrow or short all-caps phrase |
| `data-animate="highlight"` | accent underline grows | one load-bearing phrase |

For word-by-word motion, wrap words in spans and stagger them explicitly. Do not split text with JavaScript or recreate a typewriter by deleting the accessible sentence.

Mask and wipe primitives need typographic bleed in their final clip boundary. Leave enough negative inset for italic overhangs, accents, and descenders such as `g`, `p`, and `y`; a visually complete animation may still clip glyph ink when it ends at an exact zero inset.

## Data primitives

| Attribute | Final state | Typical mark |
|---|---|---|
| `data-count="420"` | formatted target number | headline metric |
| `data-value="72"` | 0-100% scale | bar or progress mark |
| `data-ring="68"` | 0-100 ring sweep | donut or completion ring |
| `data-draw` | full SVG stroke | line, area boundary, connector, arrow |
| `data-animate="pop"` | full-size point or node | scatter point, milestone, flow node |
| `data-animate="rise"` | visible row/group | table row, legend, annotation |

The source values live in text or attributes before animation. Use `pathLength="100"` for ring circles so `data-ring` maps directly to a percentage.

## Chart selection

| Question | Preferred template | Avoid |
|---|---|---|
| How much? | metric, bar, dot plot | decorative gauge |
| How did it change? | line, area, slope | smoothed line that invents peaks |
| What is the mix? | stacked bar, donut with few categories | crowded pie |
| How do items relate? | scatter, matrix, small multiples | dual-axis chart without strong need |
| How does it move? | flowchart, process, Sankey-like bands | unlabeled spaghetti lines |
| What is the evidence? | comparison table, research table, heatmap | cell-by-cell animation |

Line slopes encode rate of change. If a smoothed path is used, choose a monotone curve or a hand-authored path that does not introduce extrema absent from the data. [Source: https://vega.github.io/vega/examples/line-chart/]

Pie and donut marks encode part-to-whole values through angular extent and area. Keep the category count small, label directly, and use a bar when precise comparison matters more than the whole. [Source: https://vega.github.io/vega-lite/examples/arc_pie.html]

## Multi-slide data story

Use adjacent slides as analytical camera moves:

1. **Orient:** headline value, unit, timeframe, source.
2. **Trend:** line, area, slope, or waterfall; annotate the inflection.
3. **Decompose:** mix, category, cohort, or small multiples.
4. **Explain:** flowchart, process, detailed table, or source evidence.

Keep the same category colors and stable chart geometry when possible. A pushed slide transition creates the sense of panning through one analysis without adding an internal scroll surface.

## Tables

- Use a real `<table>` with column headers and a caption or nearby title.
- Default mode carries roughly five rows by four columns; dense carries eight by six; research may carry twelve by eight when labels remain legible.
- Reveal whole rows or grouped sections. Keep one highlighted row/column and one accent meaning.
- Align text left, comparable numbers right, and units in headers rather than repeated in every cell.
- Put source and method beneath the table, not inside the page number area.

## Flowcharts and diagrams

Build nodes in HTML or SVG and connectors in SVG. Draw connectors before nodes reveal when the route is the message; reveal nodes before connectors when the actors are the message. Every node and connector needs a readable final state and accessible text outside purely decorative SVG paths.

## Accessibility

The visible page indicator remains current-number only. Each slide should still expose `role="group"`, `aria-roledescription="slide"`, and a useful accessible name. WAI's carousel guidance permits position and set size inside that accessible name even when the visible chrome is minimal. [Source: https://www.w3.org/WAI/ARIA/apg/patterns/carousel/]

All navigation stays keyboard-operable and focus remains predictable. [Source: https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/]

## Interactive slide contract

- Prefer native `button`, `input`, `select`, and `output` elements.
- Label every control in visible text; use `aria-live="polite"` only for the compact result that changes.
- Keep a deterministic reset or default state so revisiting the slide does not create an unexplained result.
- Pause slide-level wheel and keyboard navigation while focus is inside a control, then resume when focus leaves it.
- Make the printed and no-JavaScript state useful: controls may become inert, but the default values and result remain visible.
- Use interaction to test a decision or reveal a relationship, not to turn navigation into a puzzle.
