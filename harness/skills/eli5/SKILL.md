---
name: eli5
description: >
  Ephemeral visual explainer: turn one topic into a big-pictures-few-words HTML page, written to scratch and delivered to the reader, never into a durable location by default. WHEN: user invokes /eli5 <topic>, says "explain X like I am five", "explain this simply", "dead-simple explainer", "picture explainer", "show me how X works", or wants a visual walkthrough of an unfamiliar mechanism (a protocol, a financial instrument, a legal structure); with --deck when the explainer is for an audience ("slides to explain X to my team", "quick explainer deck on X"), the same pedagogy handed to /deck-render --web as a slide map. WHEN NOT: a plain terminal answer suffices (just answer); a full teaching outline with research, speaker cues, and demo placement (/deck-outline in the decks pack); durable reference content someone will cite later (write it to the docs lane directly); a branded artifact for an external reader (the owning project's own design system and docs).
metadata:
  packs: [core]
  triggers:
    - "explain this simply"
    - "explain it like I am five"
    - "picture explainer"
    - "show me how this works"
    - "visual walkthrough of a mechanism"
    - "quick explainer deck"
  requires: [user-file-delivery]
  distribution: runtime-provided
  status: spec-only
  license: MIT
  notice: null
---

# /eli5

## Purpose

Answer "how does X actually work" with a picture instead of an essay. Two things separate this skill from a one-line prompt: a lifecycle (the file is scaffolding, not a record; it lives in scratch and is gone when the session is) and an encoded visual floor (the quality comes from rules, not model luck). Persistence is opt-in, never the default. That inversion is the whole point: the failure mode of explainer skills is a durable folder full of one-view HTML litter.

## Inputs

| Parameter | Description |
|-----------|-------------|
| `topic` | Required. The thing to explain. Free-form. |
| `--kid` | Optional. Genuinely toddler-register: one analogy carried all the way through, no numbers. Default audience is a smart adult who knows nothing about this domain: simple structure, real substance. |
| `--deck [target]` | Optional. The explainer is for an audience, not for the person at the keyboard: eli5 keeps the pedagogy and produces the slide map (message, density mode, layout, visual proof per slide), then hands it to `/deck-render --web` for the show layer (starter bundle, motion, mechanical and visual QA). Opens in the browser, not inline: a 16:9 paged stage is built for a window. Naming a target (`--deck acme-widgets`) sets where "keep it" files the bundle. |

## Capability and fallback

This skill declares `user-file-delivery` (`harness/registry/capabilities.json`): a runtime tool that hands a file to the reader and renders it in place. The row marks it provided on Claude Code and absent on Codex and OpenCode.

- Provided: send the file with the delivery tool in render mode so it opens in the side panel immediately, with no path for the reader to hunt down.
- Absent: write the HTML to the scratch path and print the absolute path for the user to open in a browser. This is the row's `unready_behavior` and it is the complete fallback; the skill never stops for lack of the tool.

Either way the one-line output says which happened.

## Behavior

1. Write `eli5-<topic-slug>.html` to scratch: the runtime's session scratch directory when it provides one, otherwise `.tmp/eli5/` in the repository (ignored by git). Never a durable location by default, and never a configured memory lane.
2. Build to the visual floor (below). Self-contained file: inline CSS, inline SVG, no external fetches.
3. Deliver it per the capability section above.
4. Default fate: nothing. No commit, no link from any page, no durable write, no close-the-loop obligation. The file evaporates with the session scratch.
5. Keep, on explicit request only ("keep it", "save that one"): move it into the docs lane resolved through `harness/registry/structure.json`, or a path the user names, with a real filename and a link from an existing page. From that moment it is a normal page and every normal rule applies. When the docs lane is unset and no path was named, ask for a path; never invent a folder.
6. Never publish to a hosted, shareable page unless the user explicitly asks for a shareable version. Explainers routinely touch confidential mechanics (cap tables, deal structures), and local render covers the actual need.
7. With `--deck`: build the slide map first (one idea per slide, analogy-first opener, what -> how -> why -> where it breaks, closing slide), then invoke `/deck-render --web` with it. Never hand-roll a second slide runtime. The bundle lands in scratch (the user opens `index.html` in a browser) and follows the same default fate as everything else here. "Keep it" promotes the whole bundle to the docs lane or the named target path, with a link from an existing page. Without `--deck`, deck-render is never involved: the inline scrolling page is the point.

`deck-render` lives in the `decks` pack and may be deselected. When it is not selected, produce the slide map as Markdown at the scratch path, print that path, and say in the output line that the renderer is not selected. Do not substitute a hand-built slide runtime.

## Visual floor

The craft is encoded here so any executor tier hits the same bar (preferred model, not required model):

- One idea per screen-height section; the reader scrolls through a sequence, never scans a wall.
- Diagram-first: every section leads with an inline SVG (boxes, arrows, flows, proportions) and the words annotate the picture, not the reverse. Labels stay under about ten words.
- Open with the one-sentence version and a single analogy from everyday life; deepen section by section (what -> how -> why it matters -> where it breaks).
- Concrete beats abstract: use the real numbers, names, and failure cases of the topic where they exist.
- Jargon is allowed only after its picture: introduce the term in the diagram that defines it.
- Big type, generous spacing, few words. If a section needs a paragraph, it needs a better diagram. Where the runtime provides a chart-craft skill (dataviz) or a frontend-design skill, they are optional floor references for chart-shaped content and broader visual craft; the rules in this list bind without them.
- Under `--deck`, the visual floor is deck-render's design system (its own `references` folder): eli5 owns what each slide must land, deck-render owns how it looks and moves. The pedagogy rules above still bind the slide map.

## Output

The rendered explainer in the side panel (or the printed scratch path), plus one terminal line naming the file and topic. Do not restate the content in the terminal: the page is the answer. Under `--deck`: the bundle path plus deck-render's QA verdict in one line, or the Markdown slide-map path plus "renderer not selected".

## Failure modes

- Client cannot render inline -> write the file to the scratch path and print the absolute path so the reader can open it in a browser.
- Topic already has a strong page in a configured lane (a concept, a design page) -> still build the visual, but cite that page in a footer line so the deeper record is one click away.

## Neighbors

- `deck-render` (decks pack): the web show layer `--deck` hands off to.
- `deck-outline` (decks pack): full teaching outlines with research, speaker cues, and demo placement.
- Runtime-provided chart and frontend craft skills, where present: optional references, never a dependency.
