---
name: capture
description: >
  Park a half-thought, observation, or pointer in one frictionless queue for later routing, preserving the user's words with minimal interpretation. WHEN: /capture <text>, "drop this in the inbox", "park this thought", "log this for later", "note this down", or a session surfaces something a later session may need and nobody has decided where it belongs yet. WHEN NOT: a timestamped line in today's journal entry (use /daily); a fact about a known subject that already has a page (file it with that subject); a decision that was actually taken (the decisions lane); current work state (the docs lane); a belief ready for the knowledge lane (write it there in its shape).
metadata:
  packs: [core]
  triggers:
    - "drop this in the inbox"
    - "park this thought"
    - "log this for later"
    - "note this down"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# Capture

One frictionless, unattributable queue. Capture preserves the input with minimal interpretation so a later session (a triage pass, a knowledge synthesis, or the user) can route, synthesize, task, or discard it. It never synthesizes a conclusion and never copies the text to any other store.

Capture always succeeds and always prints where the text landed. It declares no mandatory lane: it prefers the journal lane and degrades to a runtime facility or a scratch file it names.

## Inputs

| Parameter | Description |
|---|---|
| `text` | Required: the thought, fact, link, or pointer, in the user's words |
| `--tag <slug>` | Optional routing hint; recorded as a hint, never treated as final attribution |

## The routing test

Before writing, apply one question: would a session next month, possibly in a different tool, act differently for knowing this? If no, do not write it; say so in one line and stop. A capture is cheap, but a queue full of noise is what makes the next triage pass skip real entries.

## Lanes

Capture prefers the journal lane resolved from `harness/registry/structure.json` (the lane a session note, a half-thought, or a pointer belongs in per `harness/rules/memory-routing.md`). When the lane lists several paths, the first listed path is the write target; every listed path is read for the duplicate check. `metadata.requires` stays empty because no lane is mandatory: an unset journal lane changes where the text lands, never whether it lands.

Fallback order when the journal lane is `null`, in this order and stopping at the first that works:

1. The runtime's native memory facility, when the active runtime provides one (a persistent memory file or note store the runtime maintains itself). Write the entry there in the facility's own shape. This facility is outside the lanes; the harness does not read it back, so the output line must say the entry lives in runtime memory and not in the journal lane.
2. A scratch file the skill names explicitly: `.tmp/capture/<stamp>-<slug>.md` under the repository root, where `<stamp>` is the local date and time as `YYYYMMDD-HHMM`. `.tmp/` is ignored by git; the file is machine-local until someone routes it.

Never invent a folder for an unset lane, never write into a lane that was not configured for this purpose, and never stop without writing. Once the journal lane is configured, `python harness/tools/init.py --lanes` is the way to set it; a capture landed in a fallback is not moved automatically.

## Behavior

1. **Known subject first.** If the text clearly names a subject that already has its own page (a person, a project, a component, a decision), file it with that subject instead: append to that page or to that subject's records, in the page's existing shape, and report that path. Only an unattributable capture uses the queue. When the subject is a guess, do not guess: queue it and mention the candidate subject as a hint.
2. **Existing topic check.** Search the queue (every journal lane path, or the active fallback location) for an entry on the same topic. If one exists, append to it rather than creating a near-duplicate, and report the existing path.
3. **Duplicate check.** If an identical capture (same text after whitespace normalization) exists in the queue from the last seven days, report that path and skip; do not write a second copy.
4. **Write.** Create `$JOURNAL/inbox/<stamp>-<slug>.md` where `$JOURNAL` is the first journal lane path, `<stamp>` is the local date and time as `YYYYMMDD-HHMM`, and `<slug>` is up to six kebab-case words from the text. Create the parent folder on first write. The file holds a short frontmatter block (`captured:` as an ISO timestamp, `tag:` when a hint was given, `access:` only when the host's tier vocabulary is in use) and then the user's words verbatim. Add nothing else: no summary, no interpretation, no suggested route beyond the optional tag.
5. **Preserve the words.** Do not rewrite, condense, or correct the text. Do not synthesize a conclusion. Do not copy the text to the knowledge, decisions, docs, or records lanes, to any task tracker, or to any page other than the one written.
6. **Report the path.** The last line of the output names the destination and the file: `captured: <path>` for the journal lane or the scratch file, `captured: runtime memory (<facility name>)` for the runtime fallback, `duplicate: <existing path>` when step 3 skipped, `filed with subject: <path>` when step 1 applied.

## Failure modes

- The journal lane is configured but its first path does not exist yet: create it (lane folders are created on first write) and continue.
- The journal lane is `null`: take the fallback order under Lanes and name the destination; do not ask the user to configure a lane before writing.
- The text contains a task with a clear action and owner: still preserve it as a capture; add one line flagging the likely route ("looks like a task for <owner>") without creating anything in a tracker.
- The text is empty: say so and stop; nothing is written.

## Examples

```
/capture the nightly build takes 40 minutes now, was 12 last month; nobody has looked at why
captured: brain/local/journal/inbox/20260907-1432-nightly-build-takes-40-minutes.md

/capture --tag onboarding new hires keep asking where the staging credentials live
captured: brain/local/journal/inbox/20260907-1440-new-hires-keep-asking-where.md

/capture the nightly build takes 40 minutes now, was 12 last month; nobody has looked at why
duplicate: brain/local/journal/inbox/20260907-1432-nightly-build-takes-40-minutes.md (captured 2026-09-07 14:32)

/capture   (journal lane unset, no runtime memory facility)
captured: .tmp/capture/20260907-1451-email-the-vendor-about-the-renewal.md
```

The paths above assume the shipped default journal lane; a host that configured a different path sees that path instead.
