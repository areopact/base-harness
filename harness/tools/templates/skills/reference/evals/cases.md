# Outcome cases

Each case is one question the reference should answer correctly. Replace the case below, then add one per kind of fact the skill holds. Trigger selection is checked in `triggers.tsv`, so a case prompt names the skill it measures.

## Case 1: short name for the question

**Input:** the exact question for the run, naming this skill.

**Acceptance checks:**

1. The reply states the fact exactly as the reference holds it.
2. The reply does not add a fact the reference does not hold. A run passes only when every check holds.

**Without the skill:** what a paired run of the same input answers when the skill is absent, so the case shows what the reference adds.
