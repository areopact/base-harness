<!-- Lens reference for /review (--audience). Not a standalone skill. -->

# Audience review

## Purpose

Applies multiple **audience** personas to a single artifact (a pitch deck, a design doc, a financial model) and produces one structured critique per persona. Exists to surface blind spots before external sharing by simulating how different audiences will read the same content.

Distinct from the `--spec` lens (the `/review` default), which applies **quality** lenses (logic, cross-reference, completeness, red-team) to test whether the doc internally holds together. `--audience` asks "how will the investor, the engineer, the customer react?"; `--spec` asks "does this doc make sense?" Use both when prepping an externally facing artifact: `--spec` first to fix internal issues, `--audience` second to test the audience landing.

## Inputs

- `<file>`: path to the artifact (PDF, Markdown, PPTX, spreadsheet)
- `--audience <persona[,persona...]>`: reviewer personas to apply (default: `vc,engineer,customer,competitor`)
- `--output <inline|separate>`: inline returns one conversational report; separate requests one file per persona at an explicit owner-appropriate destination (default: inline)

## Behavior

1. Read and parse the artifact (delegate to the appropriate reader for the file type).
2. For each persona in `--audience`:
   a. Load the persona prompt for that lens: built-in defaults today (no persona folder exists in this repository; if one is ever added under `harness/personas/`, a `harness/personas/<lens>.md` file takes precedence).
   b. Evaluate the artifact from that persona's perspective: priorities, vocabulary, risk tolerance, success criteria.
   c. Produce a structured critique: Strengths, Concerns, Top 3 Questions, Verdict (1 sentence).
3. For `--output separate`, write only within the requested destination and scope, following the host repository's filing rules. Clarify a missing destination before writing. `--report` overrides separate output and returns all critiques in conversation; temporary inspection renders remain permitted.
4. For `--output inline`, collate all critiques into a single report.
5. Append a synthesis section: common threads across lenses, most urgent issues.

## Output

- One critique block per lens (strengths, concerns, questions, verdict)
- A synthesis section with cross-lens patterns
- Optional explicitly requested files per persona at the owner-appropriate destination

## References

- Use a research skill, when one is selected, for material evidence gaps; this assessment does not publish or send the artifact.
- Persona prompts are inline until a real persona library exists.
- Adapted from the cross-modal-review skill in gbrain (MIT): https://github.com/garrytan/gbrain/tree/0c6fcab/skills/cross-modal-review
