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
  form: procedure                # optional; procedure | criteria | reference
  dependencies: [code]           # optional; a list drawn from code | system | agents; omit when none
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
| `metadata.form` | optional; `procedure`, `criteria`, or `reference`. Checked by `validate_skills.py`; see "Form and sections" |
| `metadata.dependencies` | optional; a list drawn from `code`, `system`, `agents`; any other value is rejected. See "Dependencies" |
| `metadata.status` | required; `implemented`, `spec-only`, or `stub` |
| `metadata.distribution` | required; `native`, `vendored`, or `runtime-provided` |
| `metadata.license` | required; packs never mix values |
| `metadata.requires` | optional; every entry is validated on every skill: a bare id must exist in `capabilities.json`, `lane:<name>` must name a lane in `structure.json`; a `runtime-provided` skill names at least one capability id |
| `metadata.notice` | optional; must match the `sources.json` row for a vendored asset |

`harness/bootstrap/validate_skills.py` reads the same frontmatter with the documented YAML subset and, with `--catalog` or when `.agents/skills` exists, checks that the generated Codex catalog matches the selection exactly.

`form`, `dependencies`, and `evals/` are optional: a skill written to the earlier contract passes unchanged, and `validate_skills.py` rejects only a value outside the closed vocabularies or an `evals/` folder whose files have the wrong shape.

## Starting from a skeleton

`harness/tools/templates/skills/` holds one skeleton per form (`procedure`, `criteria`, `reference`), each with complete frontmatter, the sections its form expects, and an `evals/` trio. Copy the folder to `harness/skills/<name>/`, set `name` to the folder name, replace the prose, and delete `evals/` until the skill has real prompts and cases. The skeletons live outside `harness/skills/` because the catalog builders read every `SKILL.md` there.

## Description

The description is the text a runtime loads before it chooses a skill, so it carries the routing.

1. A capability sentence first, in the third person: what the skill does, in under 100 characters.
2. `WHEN:` with the phrases a person would say. Write natural language. A slash command is resolved by name, so it selects nothing a trigger run can observe; the lint checks that the name and resolver row exist.
3. `WHEN NOT:` is optional. Name the neighbor skill or the excluded case and where it goes.
4. Plain wording, under 1,024 characters in all. Do not summarize the steps: a description that outlines the workflow lets an agent follow the outline and skip the body.

## Form and sections

`metadata.form` says what the body tells the agent. It is an author's assertion; the sections are advisory, so a missing one is a WARN and never an error.

| Form | The body tells the agent | Sections checked (WARN when absent) |
|---|---|---|
| `procedure` | what to do, in order, and when it is finished | ordered steps, as a numbered list or numbered headings outside fenced code; a `## Done when` section |
| `criteria` | what a result must and must not be | `## Floors` (countable minimums) and `## Ceilings` (limits and prohibitions) |
| `reference` | what is true | no ordered steps; a table or schema fits |

Headings match by prefix, so `## Floors (what good looks like)` counts. A body with ordered steps is a procedure even if it also lists criteria; a body with criteria and no steps is a criteria skill.

## Dependencies

`metadata.dependencies` records what the skill needs beyond its own text, and the body is written for exactly that:

- `code`: it runs bundled scripts from `scripts/`.
- `system`: it needs one named external system. Name the product once in the description and keep its interface in `references/` or `scripts/`, not in the steps.
- `agents`: its main path needs other agents. State what to do when no delegation is available.

Omit the key when the skill needs none; omission means none.

## The `## Done when` convention

A procedure ends with one section headed exactly `## Done when`, placed after the steps and before the failure-handling section (or after the last procedural section when there is none).

1. It states the requested outcome, the evidence that is enough to call it reached, and what the reply gives. The evidence is whatever the steps already produced; the section never asks for another pass.
2. Every condition is observable in an artifact, a tool result, or the reply. Where the skill already runs a check, name it. Avoid "the user is satisfied" and "verify everything".
3. Prose when there is one outcome. When modes end in different states, a short lead sentence for what they share, then one bullet per mode with the mode name in bold. Only the invoked mode binds. No checkbox syntax.
4. Success only. Blocked, partial, and unverified outcomes stay in the failure-handling section. Do not claim what the steps cannot back: no "nothing else changed", no unqualified "all".
5. Two to five statements, about 80 words, unless a material exception needs more. It adds no obligation and no permission: every condition maps to a step that exists. A condition with no step behind it is a gap in the skill, not a line to write here.
6. One completion statement. If the skill already states completion elsewhere, move only the terminal assertion here and leave the instruction that performs a check where it is.
7. Plain present tense or imperative, one logical line per paragraph or bullet, the skill's own vocabulary.

## Evaluation and maturity

A skill may carry `evals/` with three files. `validate_skills.py` checks their shape when the folder exists; a skill without it is `spec-only`.

| File | Content |
|---|---|
| `triggers.tsv` | tab-separated, header `prompt`, `expect`, `competitor`. `expect` is `select` or `skip`; `competitor` names the skill a near miss belongs to, or is empty. Every prompt is natural language. About ten `select` rows and ten `skip` rows, the `skip` rows sharing words with the skill |
| `cases.md` | at least one outcome case: the input, binary acceptance checks, and what a run without the skill produces |
| `ledger.tsv` | one row per recorded run, with the columns `date`, `harness`, `harness_version`, `model`, `description_rev`, `triggers_rev`, `package_rev`, `cases_rev`, `trigger_result`, `outcome_result`, `notes` |

Protocol:

- **Triggers.** Run each prompt three times; a prompt passes when the skill is selected (or correctly not selected) in at least two of three runs. The set passes at 90 percent of prompts. A run that fails for a harness reason is `unknown` and counts for neither side.
- **Outcomes.** Run each case three times and pass it when the acceptance checks hold in two of three. Pair every case with a run without the skill, so the case shows what the skill adds. An outcome prompt names the skill it measures, because selection is the trigger set's job.
- **Refusal cases.** A case that expects the skill to decline passes when the skill fails safely.
- **External dependencies.** Replace a live system with a stand-in case, so a run needs no credentials or network.
- **Revisions.** The four `*_rev` columns are SHA-256 digests of the description, the trigger file, the package (body plus `scripts/` and `references/`), and the cases file. Use one implementation, normalize CRLF to LF before hashing, and record the harness and model, since rows compare only within one configuration.
- **Staleness.** A description or trigger edit voids trigger evidence only; a body, script, reference, or case edit voids outcome evidence only.
- **Maturity.** A skill is `implemented` when its latest ledger row matches the current revisions and both results are `pass`; otherwise it is `spec-only`. Missing or stale evidence is a warning and never an error.

This template validates the shape of `evals/` and does not ship a runner or a hashing tool. The VERIFICATION row described under "Promotion from spec-only to implemented" stays this repository's promotion gate.

## Triggers and the generated resolver

`metadata.triggers` is the list of intent phrases a user would actually type or say. Author them from the skill's `WHEN:` sentence: short imperative or noun phrases (`explore options`, `red-team this`, `does this sound AI`), flags the skill accepts (`--deck`, `--hats`), and the verbs the neighbor does not own. Each phrase becomes one row in `harness/skills/RESOLVER.md` with a target (this skill) and a neighbor (the first skill named in `WHEN NOT`, or `none`; set `metadata.neighbor` to name it explicitly, or to `none` to suppress the derivation). The neighbor is a routing boundary: where an adjacent intent goes when it is not this skill's job. It is not a fallback. When the target is deselected or its runtime-provided capability is absent, the skill body and the capability's `unready_behavior` govern, and `resolver_lint.py` prints a note for every target outside the effective selection so a dead phrase is visible.

`python harness/tools/gen_manifest.py` writes the resolver and the untracked skill index; `--check` exits 1 when either would change. `python harness/tools/resolver_lint.py` checks that every row's target exists; a row that routes to a `stub` skill is a warning (lint L5), a row that routes to a missing skill is an error. Never edit `RESOLVER.md` by hand: it carries a generator banner and `--check` reverts a hand edit to drift.

On an adopted host, `lint.py --strict` (and `deidentify_lint.py --structural`) default their scan to the template's own files, recorded in `harness/registry/adopted-files.json` (see `harness/registry/README.md`) plus `harness/kernel-manifest.json`, so a new skill under `harness/skills/<name>/` is only checked automatically when it lands through `adopt.py` on that host; `--all` scans the whole tree.

## Distribution: native, vendored, runtime-provided

- `native`: authored in this repository. The default.
- `vendored`: adapted from another project under `harness/skills/_vendor/<source>/<name>/`. `license` and `notice` must match the row in `harness/registry/sources.json`, and a modified Apache-2.0 asset carries a change-notice line in its body. `gen_manifest.py --licenses` produces the NOTICE and THIRD-PARTY lines.
- `runtime-provided`: depends on a runtime tool or connector. `metadata.requires` names a capability id from `capabilities.json`; that row states per runtime whether the capability is `provided`, `absent`, or `unknown`, an offline probe (`none`, `file-exists`, or `command`), and one `unready_behavior` sentence. The skill body must state the fallback it takes when the capability is absent. The doctors probe only `file-exists` and `command`; `unknown` stays UNKNOWN and never reads as OK.

## Tests, neighbors, and recovery

A skill has no fixture harness of its own; its evidence is a VERIFICATION row. A hook does: every new or changed hook ships with a fixture that fails without the change, a legitimate-neighbor fixture that still passes, and a recovery sentence in any deny reason. Fixtures live under `harness/hooks/tests/fixtures/<group>/` with the verdict in the name (`bypass-` or `deny-` for a deny, `advise-` for an advisory, `allow-` for silence) and their expected stdout under `tests/expected/<group>/`. `bash harness/hooks/tests/run.sh` (or `run.ps1`) pipes every fixture through the native wrapper and diffs byte for byte; in this build that is 214 fixtures plus a dispatcher smoke.

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
