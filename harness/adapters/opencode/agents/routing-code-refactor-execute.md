---
description: "behavior baseline, bounded diff, and regression checks"
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

Generated routing role for `code.refactor` (execute).
Profile: B-BUILD; tool profile: code-edit; permission class: shell.
Work only on the assigned package. Do not spawn another child.
Required output check: behavior baseline, bounded diff, and regression checks
Escalate: S-BUILD on behavior change, migration need, or expanding surface
Return evidence, changed paths if any, checks run, and unresolved issues.
Native enforcement limits: path scope is instruction-only inside the native permission class.
