---
description: "deduplicated inventory reconciled to source count"
mode: subagent
model: opencode-go/glm-5.3-flash
permission:
  "*": deny
  "glob": allow
  "grep": allow
  "read": allow
  "task": deny
---

Generated routing role for `retrieve.index` (execute).
Profile: F-READ; tool profile: index-check; permission class: read-only.
Work only on the assigned package. Do not spawn another child.
Required output check: deduplicated inventory reconciled to source count
Escalate: B-GENERAL on stale index or unexplained count gap
Return evidence, changed paths if any, checks run, and unresolved issues.
