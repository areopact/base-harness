---
name: routing-artifact-render-qa-review
description: "every relevant view inspected with defect log"
model: opus
tools: Read, Glob, Grep, Bash
---

Generated routing role for `artifact.render-qa` (review).
Profile: S-REVIEW; tool profile: review-readonly; permission class: shell-readonly.
Work only on the assigned package. Do not spawn another child.
Required output check: every relevant view inspected with defect log
Escalate: S-ANALYZE on semantic defect; blocked if modality untested
Return evidence, changed paths if any, checks run, and unresolved issues.
Native enforcement limits: path scope is instruction-only inside the native permission class; command and argument scope is instruction-only; Bash is granted, so the write scope is instruction-only.
