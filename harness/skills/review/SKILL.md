---
name: review
description: >
  Review specs, plans, decks, memos, decision docs, supplied plan text, and inspectable non-Markdown artifacts with the fitting lens: spec quality (default), CEO scope, engineering, design plan, design audit, developer experience, audience reception, prose tells, or the full pipeline. Read-first and adversarial; reviewers do not edit; --report never writes. WHEN: /review, "review this spec", "red-team this", "pressure-test this plan", "does this hold together", "rethink the scope", "lock the architecture", "score the UX", "run a design audit", "run a DX audit", "how will this reader receive it", "run all the reviews"; --hats and --peers add perspectives and independent seats. WHEN NOT: idea exploration with no artifact yet (use /brainstorm); code diffs and pull requests (no skill in this repository owns them yet; use the runtime's own code review path); rewriting prose rather than auditing it (use /humanize directly).
metadata:
  packs: [core]
  triggers:
    - "review this spec"
    - "red-team this"
    - "pressure-test this plan"
    - "does this hold together"
    - "rethink the scope"
    - "lock the architecture"
    - "score the UX"
    - "run a design audit"
    - "run a DX audit"
    - "how will this reader receive it"
    - "run all the reviews"
  requires: [peer-runtime-cli, web-search]
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# Review

Review is a read-first, adversarial assessment of an artifact that already exists. It does not rewrite artifact toolchains and it never claims visual inspection unless it actually renders and inspects the artifact through a matching available skill. `--report` never modifies source files, durable artifacts, dated records, or external state. Matching tools may create temporary inspection or render outputs in scratch storage; treat them as non-deliverables and clean them up when no longer needed. Do not force a file or a write-back for a conversationally supplied plan: cite its current snapshot and anchors in the response.

## Memory and paths

This skill declares no lane of its own. It reads the artifact the user names and writes back, when authorized, only to that artifact. The memory-first sweep inside each lens consults the `knowledge` and `decisions` lanes when `harness/registry/structure.json` configures them; when a lane is unset the sweep says "no lane configured" and continues without it. Lens references that name the `docs` or `records` lanes resolve them the same way; a skill never hardcodes a host path.

## Lenses

| Flag | Question | Reference |
|---|---|---|
| `--spec` (default) | Does it hold together? | [spec-quality.md](./references/spec-quality.md) |
| `--ceo` | Is the scope right? | [ceo.md](./references/ceo.md) |
| `--eng` | Will it survive reality? | [eng.md](./references/eng.md) |
| `--design` / `--design-audit` | Is UX planned / is the design coherent? | [design-plan.md](./references/design-plan.md) / [design-audit.md](./references/design-audit.md) |
| `--devex` | Would developers love it? | [devex.md](./references/devex.md) |
| `--audience <persona[,persona...]>` | How will this reader receive it? | [audience.md](./references/audience.md) |
| `--prose` | Does the writing show machine tells? | `/humanize --report` (audit only); with authorized `--apply`, `/humanize` runs embedded and returns final text only |
| `--all` | The applicable CEO -> design -> eng -> devex pipeline | [pipeline.md](./references/pipeline.md) |

The reference files are read from this skill's folder. On a runtime that materializes only `SKILL.md` (the generated Codex wrapper), read them from the repository path `harness/skills/review/references/`.

`--hats <all|list>` and `--peers [N|runtime[,runtime...]]` optionally add selected perspectives and independent adversarial seats. Use the shared method in [perspectives.md](../brainstorm/references/perspectives.md); when the brainstorm skill is deselected the file is still readable at `harness/skills/brainstorm/references/perspectives.md`. Hats are not seats; the active main runtime chairs; seats are read-only; peer completion is conditional and must be reported honestly. No council recursion and no worker dispatch by a seat.

The authorization and input rules on this page override any write-back wording in an individual lens reference. Preserve `--scope <lens-list>`, `--apply` (authorized mechanical fixes), and `--verbose` where the selected reference supports them. Use `--ceo-mode <scope-expansion|selective-expansion|hold-scope|scope-reduction>` and `--devex-mode <dx-expansion|dx-polish|dx-triage>`. A bare `--mode` aliases the selected lens mode when unambiguous; with `--all` it means CEO mode. Reject mismatched values. `--report` takes precedence over every write flag.

For an existing business thesis, use the shared [venture questions](../brainstorm/references/venture.md) as evidence checks where relevant (also readable at `harness/skills/brainstorm/references/venture.md`). Do not launch a new brainstorm interview or ask again for facts already in the artifact.

## Routing

- A code diff or pull request: no skill in this repository owns code review in this release. Say so, and route to the runtime's own code review path.
- No artifact yet, only an idea: `/brainstorm`.
- A prose rewrite rather than an audit: `/humanize`.
- Otherwise choose the narrowest fitting lens and state it.

## Runtime capabilities and fallbacks

`--peers` depends on a second runtime CLI (`peer-runtime-cli` in `metadata.requires`). A single-seat review is fully local and needs nothing beyond the active runtime, which is why this skill stays `native`. When no eligible second CLI is installed, authenticated, and allowed:

- `--peers` degrades to one seat: the chair's own red-team, with the requested hats.
- The roster line says so explicitly, for example `peers: requested 2, effective 1 (no eligible peer runtime CLI)`.
- Same-model hats are never labeled as independent input, and the result carries no claim that a peer ran. Report actual completion, error, or unknown telemetry per seat.

The DevEx lens's competitive benchmark step uses web search when the runtime provides it (`web-search`); without it, the lens falls back to the reference anchors listed in its file and says the benchmark was not refreshed.

## Shared confidence calibration

All lenses use the same issue-confidence scale: 9-10 strongly supported, 7-8 supported with limited uncertainty, 5-6 plausible but unresolved, 3-4 weak, 1-2 speculative. Confidence measures evidence, not severity or visual quality. State the support and the counterevidence; agreement without new evidence never raises the score. Lead with consequential, supported findings, label uncertainty, and preserve material dissent. Lens-specific UX and DX grades remain separate from confidence.

## Procedure

1. Route: code diff or PR -> the runtime's own code review path; no artifact yet -> `/brainstorm`; otherwise choose the narrowest fitting lens and state it. Read the whole current source snapshot, the relevant local context, and any prior reviews before judging.
2. For Markdown, use the lens rubric. For a supplied plan, assess the supplied text directly. For a non-Markdown artifact, use the matching artifact skill or renderer if one is available; if rendering cannot occur, review only the inspectable content and say that visual claims were not verified.
3. Run an independent red-team first for substantive work, then the other selected lenses, hats, and seats. Deduplicate findings, anchor them to the source, distinguish evidence from opinion, and state substantive disagreement rather than averaging it away.
4. Classify findings under the pipeline rules (AUTO candidate, TASTE, USER CHALLENGE). Reviewers do not edit. The main loop may apply mechanical fixes only where the user has already authorized the scope; otherwise report the proposed edits. `--report` forbids write-back; only the temporary inspection outputs described above are allowed.
5. Report findings by severity and confidence, with evidence and anchors, the counterargument, the recommended action, dissent, coverage and peer telemetry, and open questions. A file write-back is optional and must stay within the user-authorized scope; never create a decision record merely because the review found a one-way door.

## Attribution

The lens method is adapted from the review family in gstack (MIT): the review, plan-ceo-review, plan-eng-review, plan-design-review, design-review, plan-devex-review, and autoplan skills. The audience lens is adapted from the cross-modal-review skill in gbrain (MIT). Each reference file names its own upstream.
