# Outcome cases

Each case is one run of the skill against a task with a known right answer. Replace the case below, then add one per kind of output the skill governs. Trigger selection is checked in `triggers.tsv`, so a case prompt names the skill it measures.

## Case 1: short name for the output

**Input:** the exact prompt for the run, naming this skill, plus any fixture files the run starts from.

**Acceptance checks:**

1. Each floor in the skill is met, checked by counting or looking.
2. No ceiling in the skill is broken. A run passes only when every check holds.

**Without the skill:** what a paired run of the same input produces when the skill is absent, so the case shows which floors or ceilings the skill enforces.
