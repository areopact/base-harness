# False positives: what NOT to flag

Read this before reporting anything. A pattern scanner with no restraint is worse than no scanner: it trains the operator to ignore it, and it rewrites good human prose into different, blander prose.

**The unit of evidence is a cluster, not a hit.** One tell is noise. Four tells in three paragraphs is a signature. Upstream's core insight is statistical: LLMs produce distinctive *co-occurrence*, not distinctive individual words. A human can write "crucial" without a machine's help.

## Never evidence on its own

| Signal | Why it is not evidence |
|---|---|
| Perfect grammar and spelling | Copy editors exist. So do careful writers. |
| Formal or academic vocabulary | Register, not origin. |
| Bland or dry prose | Most functional writing is dull. Dullness is not a machine tell. |
| Mixed registers in one document | Multiple human authors, or one author across sessions. |
| Letter-style openings and closings | Genre convention. |
| A common transition word in isolation ("however", "moreover", "furthermore") | Only meaningful in density. |
| Curly quotation marks | Every word processor inserts them by default. |
| A single short sentence | Rhythm. Only sequences of them signal pattern 31. |
| A standalone "honestly" or "look" | Only a tell when it opens an ordinary point to manufacture candour. |
| An unsourced claim | A citation problem, not an AI problem. Route it to the `[Source: ...]` rule instead. |
| Correct or consistent formatting | Templates and linters exist. This repository has both. |

## Never rewrite

- **Quotations.** Verbatim words inside quote marks or a blockquote stay verbatim. `harness/rules/output-quality.md` section 3 is explicit and outranks this skill.
- **Transcripts and captured records.** A dated record is an append-only capture of what was actually said. De-slopping it destroys the record.
- **Third-party excerpts and examples.** Text quoted *as* an example of something keeps its original form, including its tells.
- **Someone else's writing sample.** If the operator supplied it to calibrate voice, it is input, not target.
- **Deliberate house format.** Inline-header lists in rule files and READMEs are this repository's convention, not pattern 16.

## Out of scope by design

This skill applies to authored prose intended for a reader, not to an agent's own replies. Flagging patterns 15, 16, 18, 31, or 33 in an agent's conversational output is not a false positive so much as a category error: it reads the runtime's interaction rules as a defect.

## When the scan finds nothing

Say so. "No cluster found; the text reads as human" is a complete and useful answer. Manufacturing a rewrite to justify having been invoked is the failure this file exists to prevent.
