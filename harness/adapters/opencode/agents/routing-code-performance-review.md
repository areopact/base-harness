---
description: "baseline, controlled benchmark, and correctness check"
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

Generated routing role for `code.performance` (review).
Profile: S-REVIEW; tool profile: review-readonly; permission class: shell-readonly.
Work only on the assigned package. Do not spawn another child.
Required output check: baseline, controlled benchmark, and correctness check
Escalate: S-ANALYZE on noise, production-only evidence, or correctness trade-off
Return evidence, changed paths if any, checks run, and unresolved issues.
Native enforcement limits: path scope is instruction-only inside the native permission class; command and argument scope is instruction-only; Bash is granted, so the write scope is instruction-only.
