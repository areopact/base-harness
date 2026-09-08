---
description: "baseline, controlled benchmark, and correctness check"
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

Generated routing role for `code.performance` (execute).
Profile: S-BUILD; tool profile: code-edit; permission class: shell.
Work only on the assigned package. Do not spawn another child.
Required output check: baseline, controlled benchmark, and correctness check
Escalate: S-ANALYZE on noise, production-only evidence, or correctness trade-off
Return evidence, changed paths if any, checks run, and unresolved issues.
Native enforcement limits: path scope is instruction-only inside the native permission class.
