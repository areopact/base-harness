---
name: prompt
description: "Refine a user prompt before execution: clarify only material gaps, preview exactly one versioned... WHEN: /prompt <task>, \"improve this prompt\"..."
---

# Codex adapter for `prompt`

Read `harness/skills/prompt/SKILL.md` completely, then follow that canonical
procedure. Translate any `/skill` examples or `$ARGUMENTS` placeholders to the
Codex `$prompt` invocation and the user's supplied arguments. This wrapper only
keeps Codex discovery metadata compact.

Invoke explicitly as `$prompt`. Canonical status: `spec-only`.
