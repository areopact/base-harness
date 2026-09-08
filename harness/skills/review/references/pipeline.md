<!-- /review --all pipeline. Adapted from the gstack autoplan skill (MIT); updated 2026-09-07. -->

# Review pipeline

`--all` composes only the relevant lenses: CEO, design when UI is in scope, engineering, and DevEx when there is an API, CLI, or SDK surface. It is an assessment pipeline, not an automatic write-back pipeline.

Use `--scope <ceo,design,eng,devex>` to limit phases, `--ceo-mode <scope-expansion|selective-expansion|hold-scope|scope-reduction>` for CEO, and `--devex-mode <dx-expansion|dx-polish|dx-triage>` for DevEx (a bare `--mode` means CEO in this pipeline). Follow each retained detailed lens reference; do not replace it with this orchestration summary.

1. Freeze and read the source snapshot; identify the applicable lenses and prior decisions. Run a red-team first.
2. Run the selected lenses, then deduplicate by anchored issue. A corroborating finding must add new evidence before it changes confidence; correlated model agreement does not.
3. Classify each recommendation:
   - **AUTO candidate**: mechanical and already within explicit edit authority.
   - **TASTE**: defensible alternatives; recommend but do not silently decide.
   - **USER CHALLENGE**: materially contests stated direction, scope, or a one-way door; surface with alternatives and rationale.
4. Report coverage, conflicts, dissent, evidence versus opinion, and unresolved questions. Reviewers remain read-only. The main loop may make AUTO-candidate edits only in already-authorized scope; supplied conversational text need not be saved.

If a user explicitly requests write-back, append one dated review section only to a file they authorized. Do not create a decision record automatically. `--report` performs no source, durable-output, or external mutation regardless of other defaults; temporary inspection outputs follow the parent skill. Thin artifacts should be strengthened through `/brainstorm` or `/brainstorm --venture` (business ideas), not padded by the review process.
