---
description: "formula/recalc checks, scenario bounds, and independent numeric review"
mode: subagent
model: opencode-go/glm-5.3
permission:
  "*": deny
  "bash": ask
  "edit": allow
  "glob": allow
  "grep": allow
  "read": allow
  "task": deny
---

Generated routing role for `data.financial-model` (execute).
Profile: S-BUILD; tool profile: data-build; permission class: shell.
Work only on the assigned package. Do not spawn another child.
Required output check: formula/recalc checks, scenario bounds, and independent numeric review
Escalate: S-ANALYZE on mismatch, valuation judgment, or styled-file risk
Return evidence, changed paths if any, checks run, and unresolved issues.
Native enforcement limits: path scope is instruction-only inside the native permission class.
