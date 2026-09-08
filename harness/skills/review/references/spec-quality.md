<!-- Lens reference for /review (--spec, the default). Not a standalone skill. -->

# Spec quality

## Purpose

Pressure-test a written artifact (spec, decision, memo, concept page, product spec) before it lands or gets published. Adapted from the gstack `/review` code-review skill (MIT): the specialist-dispatch architecture and the confidence-calibration framework apply as well to prose as to code.

A prose repository has different failure modes than a codebase:

- Unattributed claims (no `[Source: ...]`)
- Stale facts past their `last_assessed` window
- Internal contradictions (the summary says X, the timeline says Y)
- Missing back-links (a mentioned entity has a page; the page is not linked)
- Over-confident framing on low-confidence content
- Hidden one-way doors in a decision page
- Loose threads: questions raised but not addressed

This lens catches those without the reader having to read the whole doc three times.

## Specialist lenses

Each lens runs as a focused pass with its own checklist. By default, run **all four** for substantive work; the user can pass `--scope <lens-list>` to limit.

| Lens | What it looks for |
|---|---|
| **Logic** | Internal contradictions, premises that do not support conclusions, scope creep within the doc, claims that contradict the timeline section |
| **Cross-reference** | Missing links, broken internal references (including wikilinks where the host uses that syntax), mentioned-but-not-linked entities, links that point to drafted-but-not-existing pages |
| **Completeness** | Required frontmatter fields missing or stale, sections the page type expects that are empty, `[Source: ...]` citations missing on substantive claims |
| **Red-team** | What is the adversarial read of this doc? What would a hostile reader use to dismiss it? What is the unstated assumption? Where would a competent skeptic push? |

For decision pages specifically, add a fifth lens:

| Lens | What it looks for |
|---|---|
| **One-way doors** | Decisions in the doc that, once executed, cannot be undone. Are they named? Justified? Recorded under the appropriate decision owner when warranted? |

## Inputs

- Path to the file under review: typically an active design doc, a knowledge or decision page, an owner doc, or a memo.
- Optional: `--scope <logic,cross-ref,completeness,red-team,one-way>` to limit lenses.
- Optional: `--apply` to auto-apply AUTO-FIX findings without asking each time (default: report; existing explicit edit authorization is honored).

## Behavior

### Step 0: read and frame

1. Read the file end to end including frontmatter.
2. Identify the page type: a living summary with a timeline, a principle page (summary only), or a dated record (append-only capture).
3. Memory-first: are there prior reviews of this doc or related decisions in the `knowledge` and `decisions` lanes? Surface them. When a lane is unset, say "no lane configured" and continue.
4. Build the entity index from frontmatter `related:` and a link scan; this is the cross-reference baseline.

### Step 1: run lenses (in parallel via delegated readers where the file is long)

For short or light work, run lenses inline. For substantive work, lead with an independent red-team. The main loop owns any dispatch under `harness/rules/base-routing.md`; use the shared [perspectives procedure](../../brainstorm/references/perspectives.md) for bounded hats and peers (also readable at `harness/skills/brainstorm/references/perspectives.md` when brainstorm is deselected). Reviewers are read-only.

#### Logic lens

- Read the summary and timeline sections separately. Do they agree?
- For each substantive claim, ask: does the doc itself support this, or is it asserted?
- Scope check: does the doc stay on its stated topic?
- Premise check: is the central premise stated explicitly? If not, flag.

#### Cross-reference lens

- For every mentioned entity (person, firm, unit slug, concept), search the repository for a corresponding page. If one exists and is not linked from this doc, flag.
- For every link in the doc, verify the target exists. Flag broken links.
- Check frontmatter `related:` is non-empty when the doc has more than two page-worthy mentions.

#### Completeness lens

- Frontmatter completeness for the doc's page type, per whatever frontmatter rule the host repository declares.
- `[Source: ...]` citation on every substantive claim in the summary (per `harness/rules/output-quality.md`).
- `last_assessed:` date: flag if older than 90 days for active topics.
- Page-type specifics: a living summary needs both a summary and a timeline; a principle page should not have a timeline section; a record should not have a summary section.

#### Red-team lens

- What is the strongest counter-argument to the doc's core claim?
- Where could a skeptic say "the author is being optimistic"?
- What is missing that someone with the opposite stance would have included?
- Are there unstated assumptions a reader from a different background would not share?

#### One-way doors lens (decision pages only)

- For each commitment, decision, or recommended action: is it reversible? At what cost?
- Are one-way doors named explicitly with the rationale?
- Is there an appropriate owner-scoped decision record where one is warranted? Do not create one automatically.

### Step 2: confidence scoring

Apply the parent skill's shared evidence-based calibration; these display bands do not replace it.

Each finding from each lens gets a confidence score 1-10:

| Score | Treatment |
|---|---|
| 9-10 | Display prominently; auto-fix candidate if mechanical |
| 7-8 | Display normally |
| 5-6 | Display with hedge ("possible issue:") |
| 3-4 | Move to appendix; surface only on `--verbose` |
| 1-2 | Suppress (likely false positive) |

Agreement alone does not raise confidence. Increase confidence only when a pass adds new, relevant evidence; preserve conflicting evidence and explain the judgment.

### Step 3: fingerprint and dedupe

Each finding has a fingerprint: `<file>:<line-range>:<category>`. Two findings with the same fingerprint merge into one (with evidence-based confidence and preserved dissent).

### Step 4: fix-first classification

For each finding with confidence 5 or above, classify:

- **AUTO-FIX**: a mechanical correction with no judgment call. Examples: missing frontmatter field, broken link with an obvious target, stale `last_assessed` date when the doc was clearly recently revised. The main loop applies these only within already-authorized edit scope, including an explicit `--apply` request. Never invent missing values or sources. `--report` overrides all write behavior.
- **ASK**: a judgment call. Examples: a red-team finding ("you might be too confident here"), scope creep ("this paragraph is off-topic"), a missing citation when the source is not obvious. Batch-ask in numbered prose at the end of the review.

### Step 5: report

Report in conversation by default. If write-back is requested, append a `## Spec Review: <date>` section to the authorized living document with:

- Lenses run plus scope signals
- Findings list, grouped by lens, sorted by confidence
- AUTO-FIXES applied (with a diff summary)
- ASK items resolved with user choices
- Open issues not addressed in this pass

If the doc is a design doc and the review surfaced material new content, recommend a `last_assessed:` bump and an `updated:` field refresh.

## Output

A conversational report, plus an optional authorized `## Spec Review` section: lenses run, findings count by confidence band, AUTO-FIX count, ASK count, remaining-open count.

## Failure modes

- **Source is missing or not Markdown.** Ask for a missing source; review supplied plan text directly. Use an available matching artifact skill or renderer for other formats and disclose inspection limits. Never claim visual review without rendering and inspecting.
- **File is a dated record under the records lane.** Review read-only using the applicable conventions; do not append a spec-review section or rewrite the historical record.
- **File is a principle page.** Summary-only model; skip the timeline-versus-summary check; otherwise run normally.
- **User wants a yes/no.** Push back. This lens produces findings plus fixes, not verdicts.

## Notes

The specialist-dispatch and confidence-calibration architecture is adopted from the gstack `/review` skill (MIT). Prioritize actionable findings. Confidence depends on supporting evidence rather than a mechanical agreement bonus. [Source: gstack `/review` SKILL.md, fetched 2026-05-17]

Optional hats and independent runtime seats use `/review --hats all --peers` and the shared perspectives procedure. The parent review skill governs authorization, conversational inputs, and artifact inspection for every lens.
