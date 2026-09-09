# Skills

A skill is a folder `harness/skills/<name>/` whose body is `SKILL.md` (agentskills.io format). Supporting files (templates, references, scripts) may sit beside it. Only selected skills are materialized into a runtime's skill path; the rest stay here as source.

## Layout

```
harness/skills/
  README.md            this file
  RESOLVER.md          GENERATED: intent to skill routing, target and neighbor per row
  <name>/SKILL.md      one skill per folder
  _vendor/<source>/<name>/   skills adapted from other projects (listed in harness/registry/sources.json)
```

## SKILL.md frontmatter

```yaml
---
name: brainstorm
description: >
  One paragraph. WHEN: the phrases and situations that should route here.
  WHEN NOT: the neighbors that should not, and where they go instead.
metadata:
  packs: [core]                  # kebab-case pack slugs; a skill may belong to several
  triggers:                      # phrases the generated resolver routes from
    - "explore options"
    - "think through alternatives"
  neighbor: review               # optional; a skill name or none; overrides the neighbor derived from WHEN NOT
  requires: []                   # capability ids from capabilities.json and lane:<name> lanes from structure.json, if any
  distribution: native           # native | vendored | runtime-provided
  status: spec-only              # implemented | spec-only | stub
  license: MIT                   # MIT | Apache-2.0 | BSD-3-Clause | source-available | none
  notice: null                   # required text for vendored assets, else null
---
```

Rules the lint enforces (`python harness/tools/lint.py`, check L4):

- `name` and `description` are required; `description` contains `WHEN:`. Runtimes read only these two keys plus the body; every harness-only key nests under `metadata:` so runtime loaders tolerate it (a VERIFICATION row records the loader tolerance per runtime version).
- `metadata.packs`, `metadata.triggers`, `metadata.status`, `metadata.distribution`, and `metadata.license` are required. `metadata.requires`, `metadata.neighbor`, and `metadata.notice` are optional.
- `metadata.requires` holds three vocabularies, all validated on every skill whatever its distribution: a bare id names a row in `harness/registry/capabilities.json`; `lane:<name>` names a lane key in `harness/registry/structure.json` (`identity`, `knowledge`, `decisions`, `records`, `docs`) that the skill reads or writes, resolved at run time and never spelled as a path; `fact:<key>` names a host fact from a closed set (`host.profile`, `git.mode`, `contract.mode`, `brain.local_tracked`, `delegation.mandatory`, `selection_scope`) that the skill's body relies on. Anything else is a lint error. A `SKILL.md` body that names `host.profile` must declare `fact:host.profile` in `metadata.requires`. The generated skill index carries the list per skill, so a host can enumerate which skills need which lane or fact.
- `metadata.neighbor` is the skill named in the resolver's `Neighbor` column: a skill name, or `none` to suppress the derivation. When absent, the first skill named in the `WHEN NOT` clause is used.
- `status` is one of `implemented` (live-verified, with a VERIFICATION row), `spec-only` (complete workflow, not yet live-verified), `stub` (incomplete). Pull requests land as `spec-only`; promotion is a separate change with evidence.
- `distribution` is `native` (authored here), `vendored` (adapted from another project; `license` and `notice` must match the row in `harness/registry/sources.json`), or `runtime-provided` (depends on a runtime tool or connector; must name a capability id in `metadata.requires` that exists in `capabilities.json`, and the body must state the fallback when the capability is absent). A `native` skill may carry adapted third-party reference files, provided every such file is listed in `harness/registry/sources.json` and rendered into `THIRD-PARTY.md`; `review` and `humanize` do.
- Packs never mix licenses.
- A trigger that routes to a `stub` skill is a lint warning; a trigger that routes to a missing skill is an error.

## Status ladder

`stub` -> `spec-only` -> `implemented`. Moving up requires evidence a maintainer can observe: for `implemented`, a dated `docs/VERIFICATION.md` row with a scope token and reproduction steps. Moving down happens when a runtime change breaks the recorded behavior; the row flips to `pending` and the skill to `spec-only` in the same change.

## Selection

`harness/registry/selection.json` holds `packs`, `include`, and `exclude`. The effective set is the union of skills whose `metadata.packs` intersects `packs` with `include`, minus `exclude`. `python harness/tools/selector.py` edits the file (flags or interactive) and re-runs bootstrap's materialization, which creates links or generated trees for selected skills and prunes the ones that were deselected. Shipped default: `["core", "maintain"]`.

Per runtime: Claude Code gets one link per selected skill under `.claude/skills/<name>`; Codex gets a generated `.agents/skills/<name>/` tree; OpenCode gets a generated `harness/.selected/skills/<name>` tree linked as `.opencode/skills` plus generated `.opencode/commands`. The doctors count selection from those materialized artifacts and reconcile the count to `selection.json`; a mismatch is a doctor FAIL.

## The generated resolver

`RESOLVER.md` is written by `python harness/tools/gen_manifest.py` from every skill's `metadata.triggers`. Each row carries the trigger phrase, the target skill, and a neighbor (the first skill named in the skill's `WHEN NOT`, or none; `metadata.neighbor` overrides it). The neighbor is a routing boundary, where an adjacent intent goes when it is not the target's job. It is not a fallback: when a target is deselected or its runtime-provided capability is absent, the skill body and the capability's `unready_behavior` govern. Never edit the resolver by hand: change the skill's `metadata.triggers` and regenerate. `python harness/tools/resolver_lint.py` checks that every row's target exists, flags stub targets, and prints a note for every target outside the effective selection.

## Adding a skill

Owner-first: repair an existing skill, then add a mode, then add a skill only with a distinct intent, output, and routing boundary. Full procedure and the contributor gate: `docs/ADDING-A-SKILL.md` and `CONTRIBUTING.md`.
