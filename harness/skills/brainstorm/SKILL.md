---
name: brainstorm
description: >
  Explore consequential ideas, designs, strategies, and trade-offs before commitment: credible options, their strongest objections, and what would change the answer. WHEN: /brainstorm, "brainstorm", "explore options", "think through alternatives", "compare approaches", "how should we approach this", "triangulate approaches", "ask another model about these options", "develop a business idea", "pressure-test an idea before committing"; --venture develops a business idea through six forcing questions; --hats and --peers add perspectives and independently produced input without creating a council. WHEN NOT: pressure-testing an existing plan, spec, memo, deck, or decision (use /review); understanding a document (answer directly); recording a decision or implementing anything (hand off to the skill that owns the destination, and only after the user asks).
metadata:
  packs: [core]
  triggers:
    - "explore options"
    - "think through alternatives"
    - "compare approaches"
    - "how should we approach this"
    - "triangulate approaches"
    - "ask another model about these options"
    - "develop a business idea"
    - "pressure-test an idea before committing"
  requires: [peer-runtime-cli]
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# Brainstorm

Brainstorm is discussion and analysis, not a commitment or an implementation engine. It helps the user see credible options, their strongest objections, and what would change the answer. Do not manufacture a durable decision, edit an artifact, or start implementation unless the user separately asks.

This skill writes nothing and declares no lane. If the user asks to record the result, hand off to the skill that owns the destination (a decision, a document) rather than writing from here.

The reference files are read from this skill's folder. On a runtime that materializes only `SKILL.md` (the generated Codex wrapper), read them from the repository path `harness/skills/brainstorm/`.

## Intake and modes

Read relevant local context first. Ask only material questions that local context cannot answer: objective, decision horizon, hard constraints, affected people, or the success/failure boundary. Do not re-ask facts the user supplied.

- **Quick Explore** is the default for a simple, reversible request: state 2 to 3 credible options, the trade-off, a tentative recommendation, and its strongest caveat. Keep it light; no compulsory six-hat ceremony.
- **Full Explore** is for uncertainty, high stakes, novelty, or a one-way door: use all relevant hats from [LENSES.md](LENSES.md), map critical assumptions, make at least two genuine options, and preserve material dissent.
- **Venture exploration** (`--venture <idea-or-entity>`) develops a business idea through the six forcing questions in [venture.md](./references/venture.md): demand, status quo, specific customer, wedge, observation, and future-fit. Load only for this mode; reuse existing answers.
- **Artifact pressure-test** is not brainstorm: route an existing plan, spec, memo, deck, or decision to `/review` with the suitable lens.

Natural-language intent works. Examples: `brainstorm the launch choices`, `brainstorm --hats risks,alternatives`, and `brainstorm --peers 2 --hats all whether to launch in one region first`.

An existing business thesis brought for critique goes to `/review`; an idea brought for development uses `--venture`. A request to understand a document can be answered directly without invoking either skill.

## Controls

`--hats <all|comma-separated hats>` selects the thinking perspectives from the six-hat reference. Hats are structured viewpoints within one analysis; they never count as independently produced model input.

`--peers [N|runtime[,runtime...]]` defaults to one eligible opposite-runtime seat when no value is given; otherwise requests up to the stated number of eligible independent peer seats, or named peer runtimes. It is optional and conditional: the active main runtime chairs; it asks the main loop to resolve `compare.options` through `harness/rules/base-routing.md` and the selected runtime adapters. No model IDs, allocation policy, worker children, recursive council, install or login steps, permission bypass, or cross-runtime capability claim belongs here. If a requested opposite CLI is installed, authenticated, and allowed, prefer it; otherwise label the available fallback accurately. Same-model hats are not peer independence.

Use [perspectives.md](./references/perspectives.md) for the shared, bounded procedure. The main loop owns dispatch and must report actual completion, error, or unknown telemetry; never imply a peer ran when it did not.

### Peer runtime capability and fallback

`--peers` depends on a second runtime CLI (`peer-runtime-cli` in `metadata.requires`). Single-seat exploration is fully local and needs nothing beyond the active runtime, which is why this skill stays `native`. When no eligible second CLI is installed, authenticated, and allowed:

- `--peers` degrades to one seat: the chair's own analysis, with the requested hats.
- The roster line says so explicitly, for example `peers: requested 2, effective 1 (no eligible peer runtime CLI)`.
- Same-model hats are never labeled as independent input, and the result carries no claim that a peer ran.

## Full Explore method

1. Frame the question, snapshot the local evidence, and state known facts versus assumptions. Give every peer the same bounded snapshot, question, constraints, role, and requested output.
2. Work the selected hats. Treat them as perspectives, not votes. Generate options that truly differ in what they optimize and sacrifice; include status quo when credible.
3. For each option, identify decisive assumptions, evidence gaps, downside, and the strongest counterargument. Invite independent peer seats to challenge the frame or options, not merely agree.
4. Synthesize by reasons and evidence, not seat count. State a provisional recommendation only when warranted, what would reverse it, and any substantive dissent or unresolved question.

If the user has asked to record or execute a direction, follow that authorization through the appropriate skill or workflow; otherwise leave the result as discussion. A brainstorm output alone is not a decision record or authorization.

Adapted in part from the office-hours method in gstack (MIT), https://github.com/garrytan/gstack/blob/026751e/office-hours/SKILL.md; the venture forcing questions in `./references/venture.md` carry that attribution.
