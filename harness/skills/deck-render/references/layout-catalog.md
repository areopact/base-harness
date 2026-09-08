# Web deck layout catalog

Every slide declares one `data-layout` value from this catalog. Composition may be customized inside the layout, but a deck should not invent a new page skeleton for every slide.

## Core layouts

| Layout | Structure | Best for | Guardrail |
|---|---|---|---|
| `cover` | title field + optional dominant visual | opening and section cover | one title, one supporting line |
| `statement` | centered or offset proposition | a single transition idea | no body paragraph |
| `split` | 42/58 or 50/50 text and visual | explanation beside image or diagram | image receives at least 45% |
| `image` | 70-100% visual with anchored copy | photographic proof or atmosphere | one focal point, readable overlay |
| `gallery` | one lead image + one or two peers | related artifacts or examples | consistent crop system |
| `grid` | two to four equal modules | parallel ideas or features | each module carries a figure/icon |
| `comparison` | two equal panels | before/after or option A/B | equal geometry; accent only the point |
| `data` | headline metric + supporting chart | a quantitative claim | unit, timeframe, source |
| `timeline` | horizontal sequence or path | three to five stages | connectors draw before nodes reveal |
| `quote` | quote + attribution + quiet visual | testimony or verbal pivot | quote stays under 35 words |
| `document` | contained screenshot/document + annotation | source material or interface | preserve edges; use `contain` |
| `toc` | four to six grouped page lists | decks longer than 20 slides | real jump controls, chapter headings, individual page numbers and titles |
| `interactive` | controls + live visual/output | data exploration, simulation, or a bounded game | native controls, reset path, static fallback |
| `appendix` | dense evidence, table, method, or source note | supporting material after the close or narrative | title as `Appendix: topic`; preserve citations |
| `closing` | callback statement + contact or one next step | final narrative slide | one CTA, contact block, or concluding sentence |

## Rhythm

- Do not repeat the same layout more than twice in sequence.
- Follow a dense informational slide with a visual, statement, or image-led slide.
- Reserve full-bleed `image` and centered `statement` for moments that deserve a tempo change.
- A typical 10-slide deck uses five to seven distinct layouts, not all twelve.

## Image compositions

### Hero

Use `image` with the media covering the stage and a localized scrim behind copy. Keep the text block within 38% of stage width. Place it on the quieter side of the image.

### Split

Use `split` with either `.split-visual-first` or `.split-copy-first`. The visual side stays at 45-60%. A portrait subject gets a taller crop; a landscape scene may use a wider 58% plate.

### Gallery and multi-image variants

The maintained nine-pattern core is Hero, Split, Pair, Triptych, Quad compare, Quad sequence, Mosaic, Filmstrip, and Documents. Hero and Split are defined above; use one of these seven multi-image variants for the rest:

| Variant class | Geometry | Reading logic |
|---|---|---|
| `.gallery-pair` | two equal frames | direct comparison |
| `.gallery-triptych` | three equal frames | sequence or range |
| `.gallery-quad` | equal 2x2 | four-way comparison |
| `.gallery-quad-strip` | four equal vertical columns | stages or categories |
| `.gallery-mosaic` | one dominant plate + three smaller frames | editorial hierarchy |
| `.gallery-filmstrip` | three to five landscape frames with a temporal cadence | time or field sequence |
| `.gallery-screens` | two to four contained pages with visible edges | screenshots or documents |

Equal grids require one crop ratio, caption position, and visual weight. Mosaic layouts may vary frame size, but the lead image must visibly dominate and the supporting order must remain unambiguous. Four or five images are acceptable when the viewer can still inspect each one; otherwise continue the gallery across adjacent slides or move the extra evidence into an appendix.

### Data sequence

One chart does not need to carry an entire analysis. A multi-slide sequence may use:

1. `data` + metric or bars to orient the claim.
2. `data` + line, area, or slope to show change.
3. `data` + donut, stack, or small multiples to decompose the mix.
4. `data` + flowchart/table to explain mechanism or evidence.

Keep the same dataset colors, labels, units, and source line. Use slide transitions as the pan between analytical views; do not add an independent horizontal scroller inside a slide.

Data-story position markers are labels, not controls. Use a rule, numbered step, or editorial breadcrumb rather than a pill, raised box, or hover treatment. If a marker performs navigation, implement it as a real button and style its interactive state explicitly.

### Contents and chapter map

For a deck longer than 20 slides, place `toc` after the cover. Use four to six chapter groups and list each individual page as a numbered jump control; a short chapter description may sit above the list when space permits. The hidden runtime map lists the same pages under the same chapter names. The table of contents is part of the narrative; the map is utility chrome and stays closed by default.

### Interactive pages

Use `interactive` for one bounded question per slide. Suitable patterns include a data explorer, allocation game, assumption simulator, before-and-after reveal, scenario branch, sortable evidence table, or annotated image. Controls occupy a clear control zone, the result occupies a clear output zone, and the slide still communicates its default state in print or without JavaScript.

### Closing and appendix

The closing slide contains a callback, thank-you or question cue, and one compact contact or next-step block. It does not become a navigation menu.

Appendix slides come after the narrative close when the deck is a leave-behind, or before the close when the presentation must literally end on contact information. Mark every appendix title `Appendix: <topic>`. Useful variants include research note, detailed table, source document, methodology, definitions, backup chart, and image evidence grid.

Demonstrate both appendix densities when the deck is documenting the system: dense examples should visibly span at least 80% of the safe-area height, while a research example should span at least 90%. Use `data-fill-target="0.80"` or `"0.90"` on the slide content so browser QA checks the composition span. The span must come from readable content and deliberate spacing; do not satisfy it with oversized empty cards.

## Density modifiers

- `.density-inspire`: very large type, few words, generous rhythm.
- `.density-default`: ordinary presentation scale; also the implicit mode.
- `.density-dense`: compact analytical scale for projected or shared-screen use.
- `.density-research`: paper-like scale for close-screen reading and appendices.

Density modifiers change the complete token pack. They do not permit overflow, arbitrary inline sizes, or shrinking one isolated element below the selected scale. `.density-airy` remains a backwards-compatible alias for inspire spacing but should not be used in new decks.
