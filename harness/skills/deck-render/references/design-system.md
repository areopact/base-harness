# Web deck design system

Use this reference for every `deck-render --web` build. The starter implements these defaults; change tokens, not the underlying invariants.

## Stage and viewport

- The viewport is a centering frame. The `.deck` stage uses `aspect-ratio: 16 / 9` and the largest width that fits both viewport dimensions.
- Keep a small viewport gutter so non-16:9 screens show intentional letterboxing. Use a calm two- or three-stop gradient, with decorative contrast below the slide's weakest text contrast.
- The stage clips overflow. Split or recompose anything outside its safe area.
- All meaningful sizes use container query units tied to the stage, so the deck scales as one object.
- The stage remains 16:9 on portrait screens. Do not add a mobile reflow mode.

## Typography and density

The stage has four complete type-and-spacing modes. Values are calibrated to a 1280x720 stage and scale with it; word budgets are decision prompts, not permission to fill every available line.

| Token | Inspire | Default | Dense | Research |
|---|---:|---:|---:|---:|
| `--text-display` | `7.20cqw` | `5.15cqw` | `4.30cqw` | `3.65cqw` |
| `--text-title` | `5.15cqw` | `3.65cqw` | `2.85cqw` | `2.50cqw` |
| `--text-lede` | `2.45cqw` | `2.05cqw` | `1.72cqw` | `1.55cqw` |
| `--text-body` | `1.62cqw` | `1.46cqw` | `1.18cqw` | `1.06cqw` |
| `--text-small` | `1.10cqw` | `1.06cqw` | `0.92cqw` | `0.90cqw` |
| `--text-caption` | `0.78cqw` | `0.78cqw` | `0.72cqw` | `0.75cqw` |
| Typical body words | `0-18` | `20-45` | `45-90` | `100-190` |
| Primary setting | keynote beat | projection | analytical screen | close-screen reading |

- `.density-inspire` is for covers, vision statements, section breaks, and emotional callbacks. One phrase should dominate.
- `.density-default` is the ordinary projected slide and the implicit mode when no class is declared.
- `.density-dense` is for analysis, structured comparisons, operating plans, and tables that still need to work on a large screen.
- `.density-research` behaves like a compact paper or evidence appendix. It is denser through columns, structure, and evidence volume, not tiny type. Use two or three columns, visible hierarchy, citations, and close-screen reading. Do not use it for a projected main narrative unless explicitly requested.

Headlines use sentence case, a maximum of two lines, and one emphasis treatment. Body measure stays between 28 and 68 characters of running text where the layout permits; research columns stay narrower. That range is a reading-comfort rule for prose the eye tracks line to line, so it never transfers to headlines, display lines, labels, or captions, which are scanned in one pass. Split an argument before dropping below the selected mode's tokens. Never stretch empty cards to simulate a full research page: enlarge the type, improve the composition, or reduce the content before adding artificial height.

### Measure caps

A character cap is the last resort, not the first instinct, and it is always derived from a render rather than chosen because the number sounds right.

- **`ch` is font-relative, so a cap never travels between type roles.** One `ch` is the advance width of the element's own `0` glyph at its own computed size, so `34ch` on a Didone title at `--text-title` and `34ch` on the body sans are different physical widths on the same slide. Copying a cap from body prose onto a headline silently halves or doubles it.
- **Font size, typeface, and format all move the true limit.** The same sentence occupies different width at each density mode's token, in a display serif against a grotesque, and again once uppercase, letter-spacing, or a heavier weight is applied, so a limit that is correct in one combination is wrong in the next.
- **Derive, then bound.** Set the element loose, render at the target viewport, measure the line the browser actually produces, and add a cap only when the measured line is genuinely too long to read. A cap that forces a wrap while its container still has room is a defect: the stage sits unused and the title reads as broken.
- **Bound headlines by their container, never by a character count.** A title in a split column is limited by the column; a title over a full-width figure is limited by the stage. Both are structural facts the browser already knows.
- **A cap only earns its place when the container is wider than the measure.** A column that is already 40 to 50 characters wide is inside the comfortable range, so capping it again buys nothing and spends the column: the text simply wraps earlier and the block grows taller. Check the container width first, and drop the cap when the container is already doing the job.
- **State the intent in the selector.** Where a cap is genuinely needed, comment the measured basis (the viewport, the type role, and the line count it protects) so the next author can re-derive it instead of inheriting a number with no provenance.

Let text use the available width before forcing a wrap. Do not add a manual `<br>` or constrain a short sentence to manufacture extra lines when it fits legibly on one line. Force a break only when each line is an intentional semantic unit, such as the two-part title on a cover; verify the resulting line count visually at the target viewport. When a title wraps unexpectedly, check for an inherited measure cap before rewriting the words: the cause is more often a stale `ch` value than a headline that is too long.

## Format expansion

Formatting grows from meaning, not decoration. A deck may combine typography, decoration, foreground color, and background highlight, but each treatment keeps one stable job:

- **Weight:** regular carries reading text, medium carries labels, and bold carries claims or values. Do not bold full paragraphs.
- **Posture:** roman is the default; italic marks voice, contrast, titles, or a deliberate tonal change. It is not a substitute for quotation marks or source labels.
- **Underline:** a conventional underline remains reserved for links. A thicker keyline or marker underline may emphasize a phrase when it cannot be confused with interaction.
- **Foreground color:** accent marks the deck's primary emphasis; semantic colors retain positive, warning, danger, and information meaning.
- **Background highlight:** pale accent or semantic washes may hold a phrase, row, or evidence block. Text contrast must survive the highlight.
- **Combination:** use at most two simultaneous emphasis channels on one phrase, such as bold plus color or italic plus marker. Bold, italic, underline, color, and highlight together become noise.

Color remains a role system rather than a collection of isolated hex values. Every deck defines:

- **Foundation:** `--slide-bg`, `--panel`, `--panel-2`, `--ink`, `--muted`, `--line`.
- **Accent ramp:** `--accent-pale`, `--accent-soft`, `--accent`, `--accent-strong`; use one ramp for emphasis depth.
- **Semantic roles:** `--positive`, `--warning`, `--danger`, and `--info`; reserve them for meaning, not decoration.
- **Categorical data:** `--data-1` through `--data-6`; keep the same category-color mapping throughout a data story.

The starter includes `ocean`, `ember`, `forest`, and `mono` palette hooks on `.deck[data-palette]`. A custom palette may replace those tokens, but must preserve contrast and the semantic-role distinction. Prefer an OKLCH or perceptual color-mix ramp so pale, soft, base, and strong values remain visibly related. On any one slide, one accent family dominates; additional data colors appear only when categories require them.

## Spacing and safe area

- Default stage padding: `4.8cqw` horizontally and `2.6cqw` vertically. Because the stage ratio is fixed, width-relative container units remain proportional in every viewport orientation.
- Keep the page indicator outside the content safe area.
- Use the spacing scale already defined in the starter. Avoid per-slide pixel values.
- Align slide titles and primary visual edges to the same grid lines across the deck.

## Navigation

Required inputs:

- Next: wheel down/right, Arrow Down/Right, Page Down, Space.
- Previous: wheel up/left, Arrow Up/Left, Page Up.
- Jump: Home and End.
- Touch: one-axis swipe with a deliberate threshold.

One gesture moves one slide. The wheel accumulator ignores small trackpad noise and applies a short navigation lock after a page change. Keyboard events do not fire while the user is inside an input, textarea, select, button, or editable region.

The bottom-right indicator reads only `NN`, using the current number. It is the sole required visible chrome. Do not add the word "slide", total pages, fractions, dot rails, thumbnails, or persistent instructions. The DOM may expose richer accessible labels such as a title plus position and set size.

For decks longer than 20 slides:

- place an interactive contents slide directly after the cover;
- group the contents by chapter and list the individual page titles with their numbers, rather than showing chapter summaries alone;
- declare `data-section` and a concise `data-nav-title` on every slide;
- make the numeric indicator a real button that opens a hidden chapter map;
- support `M` to toggle the map, `Escape` to close it, and keyboard focus inside it;
- group the map by chapter and mark the current slide without adding a persistent rail;
- use stable slide hashes so contents and map entries can jump directly.

## Motion vocabulary

Use four slide transitions and the maintained object primitives in [motion-and-data.md](./motion-and-data.md). A slide may override the deck default with `data-transition="fade|push|rise|scale"`; use one transition for most pages and a second for deliberate section changes.

Text primitives include fade, rise, scale, pop, wipe, mask, focus, tracking, and highlight. Data primitives include draw, bar growth, ring sweep, count-up, point pop, row reveal, and flow-node sequencing. `data-delay="N"` staggers peers; `data-duration="N"` changes a primitive only when the default rhythm would misrepresent the reading order. `data-demo-loop="500"` is reserved for motion-catalog slides: its value is the final-state dwell in milliseconds, so the runtime waits for the longest animation and then holds for 500ms before replaying. The loop stops when the slide is inactive.

Object animations replay when the viewer returns to a slide. Their final states are identical to print, no-JavaScript, QA, and reduced-motion states. Text never disappears permanently behind a JavaScript-only split or typewriter effect.

## Images

Choose image slots by the visual argument:

| Composition | Images | Geometry | Best for |
|---|---:|---|---|
| Hero | 1 | 60-100% stage | atmosphere or decisive proof |
| Split | 1 | 45/55 or 58/42 | image beside explanation |
| Pair | 2 | equal 1:1 | before/after or direct comparison |
| Triptych | 3 | equal strip or lead + two | sequence, range, or facets |
| Quad compare | 4 | equal 2x2 | four comparable examples |
| Quad split | 4 | equal four-column strip | stages or categories with short labels |
| Mosaic | 4 | one dominant + three support | editorial hierarchy, not comparison |
| Filmstrip | 3-5 | equal wide frames | time, process, or field sequence |
| Portrait set | 3-5 | equal tall frames | people, characters, or vertical artifacts |
| Screenshot/document | 1-4 | contained edges | product, source, or evidence review |

Four-image layouts are valid when all four images carry meaning and remain readable. Equal comparison uses the same crop ratio and visual weight; a mosaic uses unequal geometry only to declare hierarchy. Do not mix these two logics.

Use `object-fit: cover` for photography and set `object-position` from the subject's focal point. Use `contain` for screenshots, diagrams, and documents whose edges matter. Add a source or credit in caption text when the asset is not owned or generated for the deck. Generate or crop assets to the target slot ratio before using extreme CSS crops.

Never present generated imagery as product evidence, a real person, a real location, traction, or a customer outcome. Label illustrative material when a reasonable viewer could mistake it for evidence.

## Data and diagrams

- A number needs unit, timeframe, and source when it is factual.
- Supported templates include metric, horizontal, vertical, or stacked bars, line, area, slope, donut, scatter, small multiples, heatmap, waterfall, timeline, flowchart, process, comparison table, and research table.
- Bars start at zero and use a shared scale. Lines use linear or monotone paths when smoothing could otherwise invent peaks. Donut and pie charts are reserved for a small part-to-whole set.
- Use count-up on one or two headline figures per slide, not every number. Draw lines in reading order, sweep one ring, then reveal labels; avoid simultaneous chart fireworks.
- A data story may span adjacent slides: orient with the headline metric, reveal trend, decompose mix, then explain flow or evidence. Keep category colors, axes, units, and source treatment stable across the sequence.
- Tables reveal by row or group, never cell-by-cell. Highlight one decision-bearing row, column, or variance.
- Animation emphasizes the reading order; it does not alter the final value.
- A conceptual chart or diagram carries an `Illustrative` or `Conceptual` label.

## Accessibility and failure behavior

- Without JavaScript, all slides stack in source order and all content is visible.
- With JavaScript, inactive slides receive `aria-hidden="true"`; the current label is an `aria-live` region.
- Honor `prefers-reduced-motion: reduce` by eliminating transitions, reveals, drawing, counting, and smooth motion.
- Interactive elements have visible focus and a minimum target sized to remain usable when the stage is comfortably visible.
- Chapter maps trap focus while open, close on `Escape`, restore focus to their trigger, and never change slides from a wheel gesture behind the overlay.
- Print renders one 16:9 slide per page with all animation targets in final state and navigation chrome hidden.

## QA contract

The starter exposes `window.webDeckQA()`. A passing result has:

- stage ratio within `0.002` of 16:9;
- stage entirely inside the viewport;
- zero slide overflow in either axis;
- exactly one current-only page indicator;
- no duplicate slide IDs;
- every slide declares a catalog layout;
- all `data-value` values in the 0-100 range.

`?qa=1` displays the same result inside the page and freezes every object in its final animation state for deterministic screenshots. `?capture=1` applies the same deterministic final state without the visible QA panel, which is useful for clean contact sheets and slide exports. Run the static checker before browser QA, then inspect the visual contact surface at the target presentation resolution. Test live animation timing separately without either query.

Vertical centring is the default: a composition with no layout class of its own, including the common pattern of a header above a nested `.layout-*` block, sits in the middle of the stage rather than clustering against the top. Layout classes govern their own alignment, so media frames and galleries still fill the stage. Use `.content-top` for a composition that genuinely starts at the top edge, such as a document facsimile; `.content-center` remains valid and is now a no-op on the default case. Appendix examples may declare `data-fill-target="0.80"` for dense or `data-fill-target="0.90"` for research; browser QA measures the direct-content vertical span against that target.

Decorative elements whose deliberate pseudo-element bleed would create a false bounding-box failure may carry `data-qa-ignore`. Use it only on non-content decoration; never use it to suppress real text, image, chart, or layout overflow.
