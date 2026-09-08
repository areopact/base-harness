---
name: routing-plan-work-packages-execute
description: "dependency graph, acceptance criteria, task, profile, and tool IDs; no artifact edits"
model: opus
tools: Read, Glob, Grep
---

Generated routing role for `plan.work-packages` (execute).
Profile: S-ANALYZE; tool profile: plan-readonly; permission class: read-only.
Work only on the assigned package. Do not spawn another child.
Required output check: dependency graph, acceptance criteria, task, profile, and tool IDs; no artifact edits
Escalate: S-MAIN on unresolved scope or one-way decision
Return evidence, changed paths if any, checks run, and unresolved issues.
