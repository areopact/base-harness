# Output Quality

Every fact cites its source, every link is built from data rather than guessed, and prose carries no mechanical tells. Provenance: the filing and output rules descend from the `gbrain` source in `harness/registry/sources.json`; the mechanical-tell catalogue in section 2 descends from the `humanizer` source there. Both are modified.

## Why

An agent's output is only as trustworthy as its weakest habit. A plausible-looking link that resolves nowhere costs more than an honest TODO, because the reader trusts it once. A cited fact with a hedge attached teaches the reader to doubt the citations. A paragraph that opens with a compliment and closes with "the future looks bright" is recognized as machine output on sight, and everything between those lines is discounted with it. Mechanical tells need no judgment to remove, so they are law everywhere; taste-level choices belong to a skill, scoped per surface.

## Application

### 1. Deterministic links

Build every URL and relative link from structured data; never guess or infer a path. If a rule is stored as `git-workflow.md` in this folder, the link is `[git-workflow](git-workflow.md)`, not an approximation of it. If the target page does not yet exist, leave a TODO rather than fabricating a plausible-sounding link. Broken-but-honest beats confident-but-wrong.

### 2. No slop

Twelve mechanical tells. These need no judgment, so they are law everywhere: replies, repository prose, and outbound artifacts alike. Anything requiring taste (staccato rhythm, rhetorical openers, boldface density) is not here; it belongs to the humanize skill and is scoped per surface.

| # | Tell | Fix |
|---|---|---|
| 1 | LLM preamble, sycophancy ("Great question!", "Certainly!") | Delete. Open on the answer. |
| 2 | Placeholder values (`TBD`, `YYYY-MM-DD`) in committed output | Fill the real value or omit the field |
| 3 | Hedging on a cited fact, or stacked qualifiers ("could potentially possibly") | State it plainly; one qualifier maximum |
| 4 | Em-dashes and en-dashes | Comma, colon, parentheses, or two sentences (spaced " - " if genuinely needed) |
| 5 | Filler phrases: "in order to", "due to the fact that", "at this point in time", "has the ability to" | "to", "because", "now", "can" |
| 6 | Copula avoidance: "serves as", "boasts", "features", "stands as a testament to" | "is", "has" |
| 7 | Signposting: "Let's dive in", "Here's what you need to know", "without further ado" | Delete the announcement, deliver the thing |
| 8 | Negative parallelism: "Not only X but also Y", trailing "no guessing" | One clause, stated positively |
| 9 | Forced rule of three ("innovation, inspiration, and industry insights") | Use the real count, whatever it is |
| 10 | False ranges: "from X to Y" where the endpoints share no scale | A plain list |
| 11 | Elegant variation (synonym cycling: protagonist / figure / hero for one person) | Pick one term and repeat it |
| 12 | Generic positive conclusion ("The future looks bright") | Cut it; end on the last concrete fact |

Two more that bite hardest in repository prose specifically:

- **AI vocabulary.** `delve`, `crucial`, `tapestry`, `testament`, `interplay`, `pivotal`, and `landscape` in the abstract sense. Substitute the plain word.
- **Diff-anchored writing.** Describe the thing as it currently is, not as a narrative of what changed ("was added to replace...", "moved in the second pass"). Change history belongs in a timeline section or the commit, not in the body of a page a fresh session has to read.

This governs output going forward; it is not a mandate to scrub existing files.

#### Floors

A blacklist alone yields prose that is clean and empty. Every piece of authored prose must also carry:

- **Specific, hard-to-fabricate detail** where a general claim would fit: a number, a date, a name, a path. If a sentence would survive being pasted into an unrelated document, it is not carrying anything.
- **Named tension** where it exists. Unresolved trade-offs stay visible rather than getting smoothed into consensus.
- **Varied sentence length.** Uniform rhythm is the loudest remaining tell after the twelve above are gone.
- **A stated editorial choice** wherever a judgment was made ("I'd do X because Y"), not a neutral survey of options.

#### Precedence

A writing sample supplied by the author outranks every style rule in this section, including the em-dash ban. Match the sample. Absent a sample, this section governs.

### 3. Exact phrasing preservation

When quoting a person, use their verbatim words inside a blockquote or inline quote marks. When creating a slug or page title for a concept the person named, use their terminology, not a paraphrase. If a founder calls their product "the mesh," the note title is `the-mesh`, not `distributed-infrastructure-layer`.

### 4. Title quality

Titles must be:

- Descriptive and specific (the reader knows the content before opening)
- Under 60 characters
- Not a full sentence (no terminal period, no verb phrase)
- Not generic (`notes`, `meeting`, `update` are banned as standalone titles)

Good: `Series A terms, second quarter`
Bad: `Notes from the meeting we had about the funding round`

### 5. Soft-wrap prose

Prose paragraphs are one logical line each: no manual line breaks inside a paragraph, a bullet's text, or a blockquote line. Let the editor soft-wrap. Line structure that is syntax keeps its lines: tables, code blocks, frontmatter, headings, and list-item boundaries. Commit message bodies still wrap at 72 characters (git convention).

Why: a hard break splits phrases across lines, which silently defeats the exact-phrase grep that memory-first retrieval depends on; a one-word edit reflows a whole paragraph into multi-line diff noise; and most Markdown renderers collapse single newlines in reading view, so hard wrapping buys nothing where the page is actually read.

Existing hard-wrapped pages reflow on touch: when substantively editing a page, reflow the paragraphs being edited. No mass sweep; reflowing untouched files is diff churn without content change.
