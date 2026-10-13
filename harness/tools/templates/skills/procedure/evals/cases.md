# Outcome cases

Each case is one run of the skill against a task with a known right answer. Replace the case below, then add one per outcome the skill promises. Trigger selection is checked in `triggers.tsv`, so a case prompt names the skill it measures.

## Case 1: short name for the outcome

**Input:** the exact prompt for the run, naming this skill, plus any fixture files the run starts from.

**Acceptance checks:**

1. A binary condition that can be seen in the reply, a file, or a tool result.
2. A second binary condition. A run passes only when every check holds.

**Without the skill:** what a paired run of the same input produces when the skill is absent, so the case shows what the skill adds.
