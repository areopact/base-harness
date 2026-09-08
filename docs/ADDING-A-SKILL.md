# Adding a skill

Most "new skill" ideas are a repair to an existing owner. This page is the procedure for the cases that survive that test, plus the frontmatter contract every skill must satisfy and the regeneration steps that keep the catalogs honest. The contributor gate in `CONTRIBUTING.md` applies on top.

## The owner-first rule

Work down the ladder and stop at the first rung that fits.

1. **Repair an existing owner.** If a skill already covers the intent and produces the wrong result, fix that skill. The resolver (`harness/skills/RESOLVER.md`) shows which skill owns a phrase today.
2. **Add a mode or a reference file to an existing skill** when the intent is shared and only a flag, an output shape, or a reference differs. Modes are documented in the skill body and, when they need routing, as extra `metadata.triggers` on the same skill.
3. **New skill** only when the intent, the output, and the routing boundary are all distinct from every existing skill. Name the boundary in the pull request: which trigger phrases route here, and which stay with the neighbor named in `WHEN NOT`.
4. **New hook** only when there is a supported runtime-native decision point for it: an event in `harness/registry/runtimes.json` with `support` other than `unsupported` on at least one tier-1 runtime. A hook starts at the advisory rung and moves to deny only with false-positive and recovery fixtures (`harness/rules/hook-design.md`, `harness/hooks/README.md`).

## Frontmatter contract

A skill is `harness/skills/<name>/SKILL.md` in the agentskills.io format: YAML frontmatter, then the body. Supporting files (templates, references, scripts) sit beside it. Runtimes read only `name`, `description`, and the body; every harness-only key nests under `metadata:` so runtime loaders tolerate it.

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

What lint L4 enforces (`python harness/tools/lint.py`):

| Key | Rule |
|---|---|
| `name` | required; the folder name |
| `description` | required; contains `WHEN:`. Codex reads this text for discovery and, once a skill is `implemented`, for implicit routing (a `spec-only` wrapper is generated explicit-only), so the trigger phrases belong here as well as in `metadata.triggers`. |
| `metadata.packs` | required; every slug kebab-case |
| `metadata.triggers` | required; the list the resolver is generated from |
| `metadata.neighbor` | optional; a skill name or `none`; overrides the neighbor derived from the first skill named in `WHEN NOT` |
| `metadata.status` | required; `implemented`, `spec-only`, or `stub` |
| `metadata.distribution` | required; `native`, `vendored`, or `runtime-provided` |
| `metadata.license` | required; packs never mix values |
| `metadata.requires` | optional; every entry is validated on every skill: a bare id must exist in `capabilities.json`, `lane:<name>` must name a lane in `structure.json`; a `runtime-provided` skill names at least one capability id |
| `metadata.notice` | optional; must match the `sources.json` row for a vendored asset |

`harness/bootstrap/validate_skills.py` reads the same frontmatter with the documented YAML subset and, with `--catalog` or when `.agents/skills` exists, checks that the generated Codex catalog matches the selection exactly.

## Triggers and the generated resolver

`metadata.triggers` is the list of intent phrases a user would actually type or say. Author them from the skill's `WHEN:` sentence: short imperative or noun phrases (`explore options`, `red-team this`, `does this sound AI`), flags the skill accepts (`--deck`, `--hats`), and the verbs the neighbor does not own. Each phrase becomes one row in `harness/skills/RESOLVER.md` with a target (this skill) and a neighbor (the first skill named in `WHEN NOT`, or `none`; set `metadata.neighbor` to name it explicitly, or to `none` to suppress the derivation). The neighbor is a routing boundary: where an adjacent intent goes when it is not this skill's job. It is not a fallback. When the target is deselected or its runtime-provided capability is absent, the skill body and the capability's `unready_behavior` govern, and `resolver_lint.py` prints a note for every target outside the effective selection so a dead phrase is visible.

`python harness/tools/gen_manifest.py` writes the resolver and the untracked skill index; `--check` exits 1 when either would change. `python harness/tools/resolver_lint.py` checks that every row's target exists; a row that routes to a `stub` skill is a warning (lint L5), a row that routes to a missing skill is an error. Never edit `RESOLVER.md` by hand: it carries a generator banner and `--check` reverts a hand edit to drift.

On an adopted host, `lint.py --strict` (and `deidentify_lint.py --structural`) default their scan to the template's own files, recorded in `harness/registry/adopted-files.json` (see `harness/registry/README.md`) plus `harness/kernel-manifest.json`, so a new skill under `harness/skills/<name>/` is only checked automatically when it lands through `adopt.py` on that host; `--all` scans the whole tree.

## Distribution: native, vendored, runtime-provided

- `native`: authored in this repository. The default.
- `vendored`: adapted from another project under `harness/skills/_vendor/<source>/<name>/`. `license` and `notice` must match the row in `harness/registry/sources.json`, and a modified Apache-2.0 asset carries a change-notice line in its body. `gen_manifest.py --licenses` produces the NOTICE and THIRD-PARTY lines.
- `runtime-provided`: depends on a runtime tool or connector. `metadata.requires` names a capability id from `capabilities.json`; that row states per runtime whether the capability is `provided`, `absent`, or `unknown`, an offline probe (`none`, `file-exists`, or `command`), and one `unready_behavior` sentence. The skill body must state the fallback it takes when the capability is absent. The doctors probe only `file-exists` and `command`; `unknown` stays UNKNOWN and never reads as OK.

## Tests, neighbors, and recovery

A skill has no fixture harness of its own; its evidence is a VERIFICATION row. A hook does: every new or changed hook ships with a fixture that fails without the change, a legitimate-neighbor fixture that still passes, and a recovery sentence in any deny reason. Fixtures live under `harness/hooks/tests/fixtures/<group>/` with the verdict in the name (`bypass-` or `deny-` for a deny, `advise-` for an advisory, `allow-` for silence) and their expected stdout under `tests/expected/<group>/`. `bash harness/hooks/tests/run.sh` (or `run.ps1`) pipes every fixture through the native wrapper and diffs byte for byte; in this build that is 54 fixtures plus a dispatcher smoke.

For a skill, the equivalent discipline is: name the neighbor it must not steal from (in `WHEN NOT` and in the pull request), and add the neighbor's own trigger phrases to the resolver check by running `resolver_lint.py` after regeneration.

## Regenerate and lint

After adding or changing a skill, in this order:

```sh
python harness/tools/gen_manifest.py            # RESOLVER.md and the skill index
python harness/tools/resolver_lint.py           # every row's target exists; stub targets warn; deselected targets are noted
python harness/bootstrap/validate_skills.py     # frontmatter shape, plus the generated Codex catalog when it exists
python harness/bootstrap/build_codex_adapter.py     # regenerate the Codex wrappers for the new selection
python harness/bootstrap/build_opencode_adapter.py  # regenerate the OpenCode commands for the new selection
python harness/tools/lint.py --strict           # L4 frontmatter, L5 resolver, L11 generated drift, and the rest
python -m pytest harness -q -p no:cacheprovider # the full suite
bash harness/bootstrap/bootstrap.sh             # materialize the selected set (bootstrap.ps1 on Windows)
bash harness/bootstrap/bootstrap.sh --check     # exit 0 means the tree matches its sources
```

`python harness/bootstrap/build_codex_adapter.py --check` and `python harness/bootstrap/build_opencode_adapter.py --check` are run by lint L11 and by bootstrap; they compare the generated Codex wrappers and OpenCode commands to what the selection would produce. There is no per-runtime registration step: bootstrap materializes whatever is selected, and a skill not in a selected pack is on disk as source only.

## Promotion from spec-only to implemented

The status ladder is `stub` to `spec-only` to `implemented`. Pull requests land as `spec-only` (a complete workflow, not yet live-verified). Promotion to `implemented` is a separate change that adds a row to `docs/VERIFICATION.md` with status `verified`, the date of the live run, a scope token, and the reproduction steps, and flips `metadata.status` in the same commit. Demotion is the reverse: when a runtime change breaks the recorded behavior, the row flips to `pending` and the skill to `spec-only` together. `python harness/tools/skill_usage.py --log <transcripts>` counts invocations in a caller-supplied transcript log to inform that decision; it is local to each adopter and its output is never committed.
