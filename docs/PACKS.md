# Packs

A pack is a label a skill declares in `metadata.packs`; selection names packs, and bootstrap materializes only the skills in the selected packs (plus explicit includes, minus excludes). This page lists the catalog by pack with each skill's release and status. The built state matters more than the plan: this build ships twelve skill folders under `harness/skills/`, the generated resolver carries one row per trigger phrase, and every runtime catalog reads `9 selected of 12 available` (core and maintain selected; decks and delegation on disk as source). Every skill's status stays `spec-only` in this catalog: promotion to `implemented` is a separate change, not automatic from a live observation. The doctor skill has been invoked live on all three runtimes (`docs/VERIFICATION.md`); every other skill still waits on its first observed run, and `docs/VERIFICATION.md` holds the pending rows.

## How packs work

- A skill folder is `harness/skills/<name>/` with `SKILL.md`; adapted skills live under `harness/skills/_vendor/<source>/<name>/` and are listed in `harness/registry/sources.json`.
- `harness/registry/selection.json` holds `packs`, `include`, `exclude`. Effective set = union(skills whose `metadata.packs` intersects `packs`, `include`) minus `exclude`. Shipped default: `["core", "maintain"]`.
- `python harness/tools/selector.py --list` prints packs, skills, and the effective set; `--pack X --skill Y --without Z` edits the file; with no flags on a terminal it prompts. After a write it re-runs bootstrap's materialization, which prunes deselected harness-managed entries. A skill name that does not exist is refused; a pack no shipped skill declares is a warning. `--pack` is repeatable but **replaces** the current pack list rather than adding to it (the flag's own help text says so): to add a pack on top of the shipped default, name every pack you want, for example `--pack core --pack maintain --pack decks`, not `--pack decks` alone.
- Per runtime: Claude Code gets one link per selected skill under `.claude/skills/`; Codex a generated wrapper directory per selected skill under `.agents/skills/` whose compact `SKILL.md` carries a summary truncated at a word boundary (never inside a quoted phrase) plus the `WHEN:` text, for discovery; the wrapper's generated `openai.yaml` metadata sets `allow_implicit_invocation` from the status ladder (`implemented` only), so every skill in this build is explicit-only on Codex (`$name`) until promoted, and nothing routes implicitly there yet (`docs/VERIFICATION.md` carries the pending row); OpenCode a link per selected skill under `harness/.selected/skills/` (linked as `.opencode/skills`) plus a generated command under `.opencode/commands/`. The OpenCode launcher (`harness/adapters/opencode/launch/`) refuses to start until that tree exists and disables the runtime's external skill roots, which is what makes selection enforcing there.
- The doctors count selection from the materialized artifacts and reconcile to the selection file; a mismatch is a `configured` FAIL.
- A pack never mixes licenses (lint L4). Every `metadata.requires` entry is validated on every skill: a bare id names a row in `harness/registry/capabilities.json`, `lane:<name>` names a lane in `harness/registry/structure.json`. A `runtime-provided` skill names at least one capability id; its degraded path lives in the skill body and in the capability's `unready_behavior`, never in the resolver, whose `Neighbor` column is the routing boundary named in `WHEN NOT` and not a fallback.

## core

Selected by default. Skills for thinking and writing work that any technical professional does in a repository.

| Skill | Intent | Notes | Status at landing |
|---|---|---|---|
| brainstorm | explore options, think through alternatives, compare approaches; `--hats` for perspectives, `--peers` degrades to one seat | port | spec-only |
| prompt | improve or clarify a prompt; `--rewrite-only` | port | spec-only |
| eli5 | explain a topic simply with a picture explainer; `--deck` hands the result to a deck renderer | declares `distribution: runtime-provided` against the `user-file-delivery` capability (provided on Claude Code, absent on Codex and OpenCode); fallback: write the file to the repository and print its path | spec-only |
| research | quick cited answer, `deep` and `ingest` modes | rewritten without the source repository's machine-specific tier filter; declares `distribution: runtime-provided` against `web-search` and `delegated-execution`; when delegated execution is absent, deep mode runs its stages sequentially in the main loop and says so | spec-only |
| review | red-team or pressure-test an artifact; all lenses, `--hats`, `--peers` | port | spec-only |
| humanize | audit prose for mechanical tells and rewrite; no operator-voice mode | rewritten | spec-only |

## maintain

Selected by default. Skills that keep the harness itself healthy.

| Skill | Intent | Notes | Status at landing |
|---|---|---|---|
| doctor | run the three doctors from inside a session and report per runtime; also carries the close-the-loop verification checklist as its "prove before done" mode | ported from the predecessor template's diagnostic skill and wired to `doctor.sh`, `doctor_codex.py --offline`, `doctor_opencode.py --offline` | spec-only |
| commit | a conventional commit that respects `git.mode` and stages explicit paths | rewritten from the predecessor plus the source conventions | spec-only |
| skillify | "this keeps happening, fix it durably": the owner-first repair doctrine | port | spec-only |

## decks

Shipped as source, not selected by default: `python harness/tools/selector.py --pack core --pack maintain --pack decks` selects it on top of the shipped default and re-materializes.

| Skill | Intent | Notes | Status at landing |
|---|---|---|---|
| deck-outline | outline a teaching, investor, or intro deck | port, four files | spec-only |
| deck-render | render an outline as a web presentation (`--web`) with pure-Python checks (`harness/skills/deck-render/scripts/check_deck.py` and `inline_bundle.py` beside it) | port, ten files | spec-only |

## delegation module (opt-in)

Shipped as source, not selected by default (`python harness/tools/selector.py --pack core --pack maintain --pack delegation`). The skill declares `distribution: runtime-provided` against the `delegated-execution` capability.

| Skill | Intent | Notes | Status at landing |
|---|---|---|---|
| workflow | execute a ratified plan through the delegated sequence | the skill fronts `harness/tools/workflow.py`, which refuses to run unless `structure.json` `delegation.mandatory` is true or `--opt-in` is passed; the compiler (`routing_policy.py`) and the role generator (`native_routing.py`) are in the kernel regardless. Detail: `docs/ROUTING-TASKS.md` | spec-only |

## Document skills are Claude-only

The four document skills from the public Anthropic skill set (Word, PDF, slide deck, and spreadsheet handling) are not in this catalog and are not in `harness/registry/sources.json`. Two facts keep them out of a shared pack:

1. License. They are published under a source-available license while the rest of that set is Apache-2.0. A pack never mixes licenses, and an MIT template cannot vendor a source-available asset into a pack alongside MIT or Apache-2.0 skills. If they are ever carried, they form their own pack with `metadata.license: source-available` and a `notice` that matches their `sources.json` row.
2. Runtime dependency. They rely on tooling that Claude Code provides and Codex and OpenCode do not. A carried version would declare `distribution: runtime-provided` against a capability that `capabilities.json` marks `provided` on `claude` and `absent` elsewhere, and the skill body would name the fallback (produce the file with a local script and print its path). No such capability row exists in this build.

Until both are in place, a Claude Code user who wants those skills installs them from their upstream source outside the harness selection; the doctor reports such an entry under `.claude/skills/` as `unmanaged, left in place` and never prunes it.

## Licensing per pack

Every skill carries `metadata.license` (one of `MIT`, `Apache-2.0`, `BSD-3-Clause`, `source-available`, `none`) and, for vendored assets, a `notice` that must match its row in `harness/registry/sources.json`. `python harness/tools/gen_manifest.py --licenses` prints the NOTICE and THIRD-PARTY lines from that file. The shipped `sources.json` lists `base-harness-internal` (MIT, no notice, no assets) plus the adapted-text rows `gbrain`, `gstack`, and `humanizer` (all MIT, modified, each naming the rule or skill reference files it covers). A modified vendored Apache-2.0 skill carries a change-notice line in its body. Contributions arrive under the DCO (`CONTRIBUTING.md`).

## Planned (v0.2)

From `ROADMAP.md`: an engineering pack (debug, code-review, write-safety with its freeze hook); reports and youtube skills; connectors under a connection standard with capability rows reserved in `capabilities.json`, plus focus; a marketplace channel after a spike proves that a pack directory installs as a plugin on at least one runtime. None of these is a commitment.
