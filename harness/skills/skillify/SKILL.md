---
name: skillify
description: >
  Turn a recurring failure pattern into a durable repair, starting with its
  existing owner. WHEN: user observes "this keeps happening", says "fix this
  durably", "turn this recurring failure into a rule", or "make this failure
  structurally impossible", or invokes /skillify; after the same correction
  has appeared three or more times in feedback, journal entries, or
  close-the-loop summaries. WHEN NOT: one-off mistakes; failures the user has
  explicitly accepted as inherent ambiguity; pressure-testing a single
  artifact rather than a pattern (/review).
metadata:
  packs: [maintain]
  triggers:
    - "this keeps happening"
    - "fix this durably"
    - "turn this recurring failure into a rule"
    - "make this failure structurally impossible"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# skillify

## Purpose

When an agent fails the same way repeatedly, diagnose the owner before adding machinery. Most patterns belong in an existing skill, rule, adapter, validator, or reference. Repair that owner first; use a parameter, mode, or reference when the intent is shared. A new skill needs a distinct recurring intent, output, and routing boundary. A new hook needs a distinct observable event or signal and enforcement boundary. In either case, first establish why the existing owner cannot absorb the repair.

This ladder is the repository's contributor gate; `docs/ADDING-A-SKILL.md` and `CONTRIBUTING.md` restate it in the same order:

1. Repair an existing owner.
2. Add a mode or a reference file to an existing skill when the intent is shared.
3. New skill only with a distinct intent, output, and routing boundary.
4. New hook only with a supported runtime-native decision point.

The goal is a durable, evidence-backed reduction in recurrence. A repair can make a bad action unavailable in a supported runtime, detect it reliably, or give the owning workflow a safe path. Do not claim it is impossible unless the relevant runtime-native enforcement has been tested and its limits are documented.

## Inputs

- A pattern name in kebab-case (for example `stale-lockfile-commit`, `wrong-lane-path`, `frontmatter-date-drift`).
- At least three references to past occurrences. References can be session IDs, journal entries, records, decisions, standing knowledge, or owner rule paths.

## Behavior

1. **Read all referenced occurrences.** Extract the common failure shape: the triggering request or action, the responsible owner, the observed symptom, and the correction. Preserve the user's correction language as an acceptance criterion.

2. **Find the existing owner.** Inspect the generated resolver (`harness/skills/RESOLVER.md`), relevant active skills and their references, governing rules under `harness/rules/`, validators under `harness/tools/` and `harness/bootstrap/`, and the applicable runtime adapter under `harness/adapters/`. Identify the narrowest owner that already governs the behavior. If the pattern is a shared variant of that owner's intent, repair it there with a mode, parameter, or reference. Record why a new owner is unnecessary.

3. **Choose the smallest durable repair.** Prefer one existing owner, selecting the mechanism that matches its authority:
   - **Skill, rule, reference, or validator repair**: when the behavior is procedural, policy-bound, or deterministically checkable.
   - **Runtime adapter repair**: when the behavior depends on provider-specific syntax, capabilities, catalog materialization, or permissions.
   - **Hook repair**: only when a supported runtime can observe the action at the required point and a runtime-native decision can enforce the intended boundary. Follow `harness/rules/hook-design.md`: canonical adapter sources and `harness/registry/runtimes.json` determine wiring and support; generated runtime files are outputs.
   - **New skill**: only with a distinct recurring user intent, a distinct output, a non-overlapping resolver boundary, and evidence that no existing owner can absorb it.
   - **New hook**: only with a distinct observable event or signal and enforcement boundary, a supported runtime-native decision point (an event in `harness/registry/runtimes.json` with support other than `unsupported` on at least one tier-1 runtime), and evidence that no existing hook or owner can absorb it. A new hook enters at the advisory rung and moves to deny only with false-positive and recovery fixtures under `harness/hooks/tests/`; the admission and enforcement-rung rules are in `harness/rules/hook-design.md`. A hook does not need its own user-facing skill or command.

   Do not create a new artifact merely to preserve a name from an occurrence.

4. **Draft a bounded change.** State the owner, the corrected behavior, the enforcement limits, and exact paths. Preserve existing authorization: perform changes already authorized by the user; otherwise present a concrete draft and wait for authorization before mutating files. A commit records accepted work; it is not the acceptance mechanism.

5. **Test observable behavior.** Test three cases where applicable: a representative failure that the repair catches or routes safely, a legitimate neighboring case that remains allowed, and recovery after the repair reports or denies. Use the relevant runtime or deterministic check; a mental replay is not sufficient. If a hook is involved, test its native payload and supported-runtime behavior rather than inferring enforcement from a script exit code.

6. **Wire and verify canonically.** The resolver is generated; change a skill's `metadata.triggers` or its `WHEN NOT` neighbor only when an authorized routing boundary changes, never the resolver file itself. For new or changed skills, run in this order and fix until clean:

   ```
   python harness/tools/gen_manifest.py
   python harness/tools/resolver_lint.py
   python harness/bootstrap/validate_skills.py
   python harness/bootstrap/build_codex_adapter.py
   python harness/bootstrap/build_opencode_adapter.py
   python harness/tools/lint.py --strict
   python -m pytest harness -q -p no:cacheprovider
   bash harness/bootstrap/bootstrap.sh      # bootstrap.ps1 on Windows
   ```

   For hooks, edit the adapter source, materialize through bootstrap, run the hook fixtures (`bash harness/hooks/tests/run.sh` or `run.ps1`), and verify the registered event against `harness/registry/runtimes.json`. Then run the focused checks that exercise the repair.

## Output

A structured result containing: pattern summary, occurrence evidence, existing-owner analysis, selected repair and its limits, changed paths or a concrete draft, failure, legitimate-neighbor, and recovery test evidence, and the canonical wiring and generated-catalog checks that were run with their results.

## Failure modes

If the failure is too varied to assign to one owner, record the evidence and defer a durable control until more occurrences establish a stable boundary. Use the knowledge lane only when that cross-session belief is useful; a binding rule or runtime control still requires a clear enforceable behavior and the appropriate authorization.

## Worked example

The `stale-lockfile-commit` pattern is a useful shape: a dependency manifest is edited, the lockfile is not regenerated, and the commit lands with the two out of step, so the next clean install resolves different versions than the ones the change was tested against.

Find the owner first. The commit skill's review step already says to read the whole `git status` before staging, and the pre-commit floor in `.githooks/pre-commit` is the deterministic check that runs on every commit. Both exist; neither names this case. Repair in place: the commit skill's review step gains one line (a staged manifest without its lockfile is a split-brain change, stage both or neither), and if the floor is extended, its message names the missing file and the regenerate command. A separate `lockfile-guard` skill would be justified only if it had a distinct recurring user workflow and a distinct output, which it does not: the intent is "commit this" and the output is a commit.

Test the three cases. Failure: stage the manifest alone and confirm the commit is reported or refused with a message that names the lockfile. Neighbor: stage a lockfile-only version bump, and a manifest change in a project that has no lockfile at all; both must commit unchanged. Recovery: regenerate the lockfile, stage both files, commit, and confirm the check is silent. If the check is a floor extension, run it through the real `git commit` in a scratch clone rather than reading its exit code in isolation; report the platforms it was exercised on rather than claiming universal prevention.
