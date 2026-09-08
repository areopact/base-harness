---
name: daily
description: >
  Append a timestamped line to today's journal entry, creating the entry on first use, or show today's entry when called with no text. WHEN: /daily [text], "log this to today", "add this to the journal", "append to today's entry", "show today's journal entry", or a session note or meeting summary belongs on today's dated page. WHEN NOT: a half-thought with no date structure to park for later triage (use /capture); a meeting or event record of its own (the records lane, in that record's shape); editing an older journal entry by hand (open the file); anything that is not today's entry.
metadata:
  packs: [memory]
  triggers:
    - "log this to today"
    - "add this to the journal"
    - "append to today's entry"
    - "show today's journal entry"
  requires: [lane:journal]
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# Daily

Append to today's journal entry, creating it if it does not exist. With no text, show today's entry.

## Lane

This skill requires the journal lane. Resolve it from `harness/registry/structure.json` (`lanes.journal`; the shipped default is `brain/local/journal`). When the lane lists several paths, the first listed path is where today's entry lives.

**Unready behavior: stop.** When `lanes.journal` is `null`, print exactly one line and do nothing else: `daily: journal lane not configured; run python harness/tools/init.py --lanes to set it`. Do not guess a folder, do not create one, and do not hand the text to /capture on the user's behalf; the user chose a dated entry and can choose the queue themselves.

## Entry path

`$JOURNAL/YYYY/MM/YYYY-MM-DD.md` where `$JOURNAL` is the first journal lane path and the date is today's local date. Parent folders are created on the first write, never earlier.

## Process

### 1. Locate today's entry

Compute the path. If it exists, keep everything in it as it is: existing frontmatter, existing sections, existing lines. Appending never rewrites or backfills.

### 2. Create it when absent

Generate a minimal entry inline:

```markdown
---
date: <today>
---

# <Weekday>, <today>

## Log
```

Use a template only when the host names one (a file the operator points to in the request or in the host's own docs); otherwise the inline shape above is the whole template. Adding `access:` with one of the host's tier labels is optional and follows host policy; the harness does not require it.

### 3. Handle the argument

With text: append one line under `## Log` as `- **HH:MM** <text>`, using the current local time. Keep the user's words; inline markdown passes through unchanged. If `## Log` is missing from an existing entry, add it at the end and append under it.

Without text: print the contents of today's entry, creating it first (step 2) when it does not exist.

### 4. Confirm

Report one line: `appended: <path>` or `created: <path>` (plus the contents when displaying). The path is the resolved file, not the lane name.

## Examples

```
/daily Started the migration plan for the billing service
appended: brain/local/journal/2026/09/2026-09-07.md
   - **14:32** Started the migration plan for the billing service

/daily Sync with the platform team; notes at the decision page: docs/decisions/2026-09-07-queue-backend.md
appended: brain/local/journal/2026/09/2026-09-07.md

/daily
(shows today's entry, creating it first when absent)

/daily anything          (journal lane set to null)
daily: journal lane not configured; run python harness/tools/init.py --lanes to set it
```

The paths above assume the shipped default journal lane; a host that configured a different path sees that path instead.
