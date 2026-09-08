# Shared perspectives procedure

Used by `/brainstorm` for option exploration and `/review` for adversarial review. This is a reusable method, not a peer-runtime promise. Brainstorm owns this file; review links to it and, when brainstorm is deselected, reads it from the repository path `harness/skills/brainstorm/references/perspectives.md`.

## Terms and boundary

- **Hat/perspective**: an assigned viewpoint within an analysis; it may be done by one model and is not independent evidence.
- **Seat**: an independently produced response from an eligible peer runtime.
- **Chair**: the active main runtime, whichever one the session runs in. It frames, dispatches through the main loop, deduplicates, and synthesizes. The chair is a role, not a particular vendor.

The chair resolves exploration seats as `compare.options` and review seats as `review.adversarial` through `harness/rules/base-routing.md` and the selected runtime adapters. Keep policy and native model IDs there. Never create worker children, recurse into council, resume sessions, export full transcripts, install or log in a CLI, bypass permissions, or assert unproven cross-runtime support.

## Peer runtime capability

A seat needs a second runtime CLI (`peer-runtime-cli` in the calling skill's `metadata.requires`). When no eligible second CLI is installed, authenticated, and allowed, the request degrades to one seat: the chair's own analysis with the requested hats. The roster line states the requested and effective seat counts and the reason, and same-model hats are never labeled as independent input.

## Bounded dispatch

1. Freeze one source snapshot: relevant excerpts or a bounded file or stdin packet, with anchors and date. All seats receive the same packet, not the chair's full conversation.
2. Define each seat's role, exact question, constraints, requested output, and read-only boundary. Prefer an installed, authenticated, allowed opposite CLI; label any fallback and do not count hats as model diversity.
3. Main declares a bounded per-seat deadline and at most one justified retry before dispatch, within the limits `harness/rules/base-routing.md` sets for the resolved task. Require a neutral working directory and verified control of ambient hooks, instructions, and integrations; preserving operator policy takes precedence over obtaining a peer. Main dispatches within that budget. The chair records per seat: requested runtime and role, snapshot identity, outcome (completed, error, timeout, or unknown), and any retry. Missing or unavailable seats reduce coverage; they are not silent substitutes.
4. Deduplicate equivalent findings, distinguish cited evidence from opinion, and preserve a material minority view. Synthesis weighs relevance, grounding, and counterarguments, not votes or correlated agreement.

Return a concise roster and telemetry note with the result. The procedure is conditional until a runtime has live evidence; unsupported orchestration remains unsupported.

## Control defaults and reporting

`--peers` alone requests one eligible opposite-runtime seat; a positive count or runtime list narrows that request within base-routing's limits. No flag means no required external peer. Hat names are `facts`, `stakeholders`, `opportunities`, `risks`, `alternatives`, and `intuition`, or `all`; see [LENSES.md](../LENSES.md). Validate unsupported values instead of inventing a runtime or hat.

Record requested and effective model when observable, duration, coverage, and source snapshot identity. Mark absent effective-model telemetry unknown. Distinct same-model agents can supply independently produced reasoning, but are not cross-model diversity; one model rotating hats is neither independent seats nor independent evidence. Keep these distinctions visible in the roster.
