---
description: "units, formulas, and independent recomputation"
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

Generated routing role for `data.arithmetic` (review).
Profile: S-REVIEW; tool profile: review-readonly; permission class: shell-readonly.
Work only on the assigned package. Do not spawn another child.
Required output check: units, formulas, and independent recomputation
Escalate: S-ANALYZE on mismatch, unstated assumption, or financial interpretation
Return evidence, changed paths if any, checks run, and unresolved issues.
Native enforcement limits: path scope is instruction-only inside the native permission class; command and argument scope is instruction-only; Bash is granted, so the write scope is instruction-only.
