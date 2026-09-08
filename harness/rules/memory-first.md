# Memory-First Lookup

Before reaching for web search, web fetch, or any external API, exhaust the configured memory lanes. The lanes in `harness/registry/structure.json` are the authoritative source for this repository's context; re-deriving known facts from outside wastes tokens, introduces drift, and degrades trust in the local record.

## Why

An external lookup that duplicates local knowledge produces two records of the same thing, and they disagree as soon as one is updated. A stale web summary filed beside a curated local page creates triage work that did not need to exist. And a session that reaches outside first never learns what the repository already believes, so it cannot notice when the outside source contradicts it. The local record can only stay authoritative if it is consulted first.

## Application

### Mandatory check sequence

Run these in order before any external lookup. Each step names a lane; a lane set to `null` is skipped, and the reply says "no lane configured" rather than "no record".

1. **Knowledge lane.** Standing and working beliefs. Prefer standing knowledge; label working knowledge as provisional.
2. **Decisions lane.** What was chosen and why. A standing decision outranks a later opinion.
3. **Docs lane.** Current status, plans, architecture, and living reference pages: what governs now.
4. **Records lane.** Dated evidence: what happened. Records answer the past; a time-sensitive question answered only from a record must be reverified.
5. **Journal lane.** Session-level notes and daily entries; the lowest-authority local source, useful for recent context.

Only after these return empty (or clearly stale) is an external call justified.

### Escalation before declaring no record

Grep is the fast path and only finds exact vocabulary. If a lookup misses but the topic plausibly exists under different wording, escalate to a content-level search over the same lanes (parallel read agents where the runtime supports them) before declaring "no record". Declaring an absence after one grep is a retrieval failure, not a finding.

### Lifecycle awareness

Prefer standing knowledge, standing decisions, and current docs. When citing an archived or superseded page, say that the hit is historical and follow its successor pointer when present. Presenting an archived hit as current truth is a retrieval failure. Maturity vocabulary: [memory-routing](memory-routing.md).

### The hook is a reminder, not a gate

The memory-first hook fires before web search and web fetch tool calls where the runtime supports hooks. It matches query tokens against filename stems in the configured lanes only; it never reads file contents, and it always allows the call to proceed. A silent hook does not mean the lanes hold nothing: knowledge inside page bodies is invisible to it. The discipline above is the agent's responsibility; the hook only catches filename-level coincidences.

### Override

If the local record is dated and the question is time-sensitive (current status, recent news, a version number), note the local source and its date, then proceed to the external lookup. Never silently discard the local version; the reply names both and says which one it trusted.
