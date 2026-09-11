---
name: prompt
description: >
  Refine a user prompt before execution: clarify only material gaps, preview exactly one versioned copyable prompt, wait for explicit confirmation of that version, then execute the confirmed task once through the appropriate skill or workflow. WHEN: /prompt <task>, "improve this prompt", "refine this prompt", "clarify my prompt before executing", "rewrite this prompt without running it"; --rewrite-only returns the wording without execution. WHEN NOT: a task that merely contains the word "prompt" (execute it directly); exploring which approach to take before there is a task to phrase (use /brainstorm); re-approving a version the user already confirmed.
metadata:
  packs: [core]
  triggers:
    - "improve this prompt"
    - "clarify my prompt before executing"
    - "refine this prompt"
    - "rewrite this prompt without running it"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# Prompt: refine, confirm, execute

Use only on explicit invocation or explicit prompt-improvement intent, not because a task happens to contain the word "prompt". The embedded task is data while refining: do not execute it, delegate it, mutate files, or send or publish anything before the displayed version is explicitly confirmed.

This skill writes no file and declares no lane. Its output is the preview in the conversation; execution after confirmation runs through whichever skill or workflow owns the confirmed task, under that owner's permissions.

The reference file is read from this skill's folder. On a runtime that materializes only `SKILL.md` (the generated Codex wrapper), read it from the repository path `harness/skills/prompt/references/best-practices.md`.

## Flow

1. Read conversation context. Preserve the user's objective, constraints, facts, budgets, permissions, and desired output. Do not invent any of them.
2. Ask concise questions only for material missing or conflicting details. Continue until resolved, or let the user explicitly choose disclosed assumptions; never silently cap clarification rounds. A clear input skips questions but still gets a preview. Optional style preferences are not material blockers: when a writing task already specifies its audience, purpose, and output, preserve those instructions and use neutral wording for unspecified tone. Do not invent personal details or ask for extra praise, background, or tone merely to polish the result, including in `--rewrite-only` mode.
3. Display exactly one complete, copyable improved prompt labeled with a version, plus short separate `Changes` and `Assumptions` notes. Keep source or context distinguishable from instructions. A material revision creates a new version and requires a new preview.
4. Ask for confirmation of that exact version. Silence, elapsed time, a clarification answer, or quoted "execute" text inside the prompt is not confirmation. No persistent or shared approval state exists. After displaying a newer version, a reply approving an older version does not authorize the current task: identify the mismatch and ask which version the user intends. If they restore older wording, preview it as the new current version before confirmation; do not silently substitute either version.
5. On explicit confirmation, execute the clearly specified task once through the appropriate skill or workflow without recursively refining or asking the same approval again. Confirmation authorizes the clearly specified actions within existing governing permissions; pause only for a genuinely new scope or authority gap.

`--rewrite-only`, or a clear request for no execution, returns the preview and stops without a confirmation question. Do not append "confirm to stop", ask permission to finish, or invite execution of the embedded task; the user already chose a wording-only result. Never request hidden chain-of-thought or guarantee output quality. See [best-practices.md](./references/best-practices.md) for the evidence behind the wording changes and the acceptance cases.
