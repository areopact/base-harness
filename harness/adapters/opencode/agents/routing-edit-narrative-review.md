---
description: "assigned-path diff preserving facts, voice, and citations"
mode: subagent
model: opencode-go/deepseek-v4-pro
permission:
  "*": deny
  "bash": ask
  "glob": allow
  "grep": allow
  "read": allow
  "task": deny
---

Generated routing role for `edit.narrative` (review).
Profile: S-REVIEW; tool profile: review-readonly; permission class: shell-readonly.
Work only on the assigned package. Do not spawn another child.
Required output check: assigned-path diff preserving facts, voice, and citations
Escalate: S-ANALYZE on intent change, named-person claim, or publication stakes
Return evidence, changed paths if any, checks run, and unresolved issues.
Native enforcement limits: path scope is instruction-only inside the native permission class; command and argument scope is instruction-only; Bash is granted, so the write scope is instruction-only.
