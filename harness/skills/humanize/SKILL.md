---
name: humanize
description: >
  Strip AI-writing tells from authored prose and rebuild what a human would actually put there. Runs a 33-pattern audit (inflated significance, promotional language, copula avoidance, negative parallelism, rule of three, elegant variation, false ranges, filler, hedging, signposting, diff-anchored writing, aphorism formulas, and more), then a draft -> audit -> final loop that checks its own rewrite for remaining tells AND for invented facts. Enforces floors as well as ceilings: specific detail, named tension, varied rhythm. WHEN: /humanize, "does this sound AI", "de-slop this", "make this sound human", "this reads like a chatbot wrote it", "clean up this copy", before an artifact goes out for an external reader (email, job description, brief, deck narrative, marketing copy, published page), and as the mechanical pass inside another prose workflow such as /review --prose. Use it even when the user only says "polish this" and the text is destined for an external reader. WHEN NOT: an agent's own conversational replies (the runtime's interaction rules govern those); visual or design slop in a spec (use /review --design-audit); rewriting the substance or the factual argument (settle that first, then run this pass); translating or summarizing (a different job).
metadata:
  packs: [core]
  triggers:
    - "does this sound AI"
    - "de-slop this"
    - "make this sound human"
    - "this reads like a chatbot wrote it"
    - "clean up this copy"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# Humanize

## Purpose

LLMs pick statistically likely continuations, which produces a distinctive and consistent signature: inflated significance, hedged everything, triads everywhere, and a copula phobia. Readers register that signature as "a machine wrote this" long before they can name why, and for anything going out for an external reader that is a credibility tax.

This skill removes the signature. It does not invent substance and it does not supply a personal voice: settle the argument first, then use `/humanize` as the prose pass.

## Scope

This skill applies to authored prose intended for a reader: an email, a job description, a brief, a deck narrative, marketing copy, a published page, a design doc someone else will read. It does not apply to an agent's own conversational replies, which the runtime's interaction rules govern. A writing sample supplied by the author outranks every rule here, including the dash ban in `harness/rules/output-quality.md`; match the sample.

Repository-internal prose (specs, decisions, READMEs) already carries the twelve mechanical tells in `harness/rules/output-quality.md` section 2 as an always-on rule. Run the full skill on such files only on request; pattern 30 (diff-anchored writing) is the high-yield catch there.

## Modes

| Mode | Trigger | Behavior |
|---|---|---|
| **Audit** | `/humanize --report` | Scan and report the clusters found, with line anchors. Change nothing. |
| **Loop** | `/humanize` plus pasted text, `/humanize <path>`, or a call from another skill | Run the draft -> audit -> final loop below. Pasted text shows every step; a file path runs the loop internally and rewrites in place; an embedded call (for example `/review --prose` with authorized `--apply`) returns the final text only, with no intermediate text, audit, or summary. |

`--report` takes precedence over every other input: with it, a file path is read and never written.

## The loop

1. **Scan.** Walk [patterns.md](./references/patterns.md), all 33, and mark every instance with its line. Then walk [false-positives.md](./references/false-positives.md) and strike anything that is a lone signal rather than part of a cluster. A single "honestly" or one curly quote is not evidence.
2. **Draft.** Rewrite for natural reading: varied sentence length, specific detail, register matched to the audience. Preserve information over phrasing. Depth need not be uniform, so compress the dull parts and dwell where a human would actually linger.
3. **Audit.** Answer both questions explicitly, in writing:
   - *What still sounds AI-generated?*
   - *Does the rewrite invent any facts?* This one matters more. De-slopping is exactly when a model replaces a vague claim with a confident fabricated specific. Every number, date, name, path, and citation in the rewrite must trace to the source text or be cut.
4. **Final.** Revise. The output carries no em or en dashes and no invented facts.

The reference files are read from this skill's folder. On a runtime that materializes only `SKILL.md` (the generated Codex wrapper), read them from the repository path `harness/skills/humanize/references/`.

## Floors

Ceilings alone produce clean, empty prose. A rewrite is not done until it also has:

- **Specific, hard-to-fabricate detail** carrying each general claim: a number, a date, a name, a path. A sentence that could be pasted into an unrelated document is carrying nothing.
- **Named tension** where it exists. Real writing leaves trade-offs visible; AI writing resolves everything into consensus.
- **Varied sentence length.** After the 33 patterns are gone, uniform rhythm is the loudest remaining tell.
- **A stated editorial choice** where a judgment was made, not a neutral survey.
- **An ending that stops**, on the last concrete fact or the actual decision. Not a summary of what was just said.

If the source text is too thin to support these, say so and ask for the missing specifics. Do not invent them. That failure mode is worse than slop.

## Output

**Pasted text:** the draft, the two audit answers as bullets, the final rewrite in a fenced block for clean copying, then one line naming the pattern families that fired and the count.

**File path:** rewrite in place, then report the changed-line count, the pattern families that fired, and anything the skill refused to rewrite because it would have required inventing a fact.

**Embedded call:** final text only.

**Audit (`--report`):** the clusters found with line anchors and the pattern family for each, or "no cluster found". Nothing is written.

## Failure modes

- **Text is a quotation, transcript, or third-party excerpt.** Do not rewrite. Secondhand text keeps its own voice. Flag tells if asked, change nothing.
- **Source too thin to meet the floors.** Name the missing specifics and ask. Never fabricate detail to satisfy a floor.
- **Author supplied a writing sample.** The sample outranks every rule here, including the dash ban (`harness/rules/output-quality.md` section 2, Precedence).
- **Clustering absent.** One tell in isolation is not AI writing. Perfect grammar, formal vocabulary, and bland prose are not evidence. Report "no cluster found" rather than manufacturing a rewrite.

## Memory and paths

This skill declares no lane. It reads the text it is given or the file path the user names, and writes back only to that file, only in loop mode. It keeps no durable state of its own.

## Attribution

The pattern catalogue in `./references/patterns.md` is adapted from the humanizer project (MIT), https://github.com/blader/humanizer, itself derived from Wikipedia's WikiProject AI Cleanup "Signs of AI writing". The Status column and the floors are local rulings, not upstream's.
