---
name: commit
description: >
  Create a conventional commit that respects the repository's declared git
  mode and host profile: verifies before staging (the host's own verify
  command on a team host, the close-the-loop checklist and doctor's
  prove-before-done ladder on a solo host), stages explicit paths, and
  commits on the branch the git mode expects. WHEN: user invokes /commit,
  says "commit this", "save my work", "make a commit", or "stage and
  commit"; at the end of a session with a dirty tree. WHEN NOT: proving a
  change without committing it yet (/doctor); pushing or opening a pull
  request (only on a separate, explicit ask, never as part of "finish this
  up" or "ship it"); merging your own pull request (the host's review path,
  never this skill); read-only sessions with nothing to commit.
metadata:
  packs: [maintain]
  triggers:
    - "commit this"
    - "save my work"
    - "make a commit"
    - "stage and commit"
  requires: [lane:decisions, lane:knowledge, fact:host.profile, fact:git.mode]
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# commit

One logical change per commit, staged deliberately, verified before staging, and landed on the branch the repository's git mode expects. The rule this skill applies is `harness/rules/git-workflow.md`; the closing checklist is `harness/rules/close-the-loop.md`. Two host facts split the steps below: `git.mode` (`main-only` or `branches`) decides branch discipline, a mechanical difference; `host.profile` (`solo` or `team`) decides verification discovery and pull request etiquette, a social difference. Read both from `harness/registry/structure.json` before step 1.

## Proportion

A routine commit is a bounded local git operation. Act directly: a commit request on its own calls for no planning agents, no fresh independent review cycle, no whole-repository lint, and no call to any external service. Requirements on the change itself still apply; this skill does not waive them. Select first, review once, run only the checks still outstanding, then stage and commit in one operation and verify the result once. Reuse a check or review already completed in this session when the content it covered, its dependencies, and its other inputs are unchanged since; after a change or a failed check, recheck the affected results rather than restarting the whole audit. Escalate only on observed ambiguity, mixed ownership, a branch or index race, a failed check, or a host rule that applies. Never optimize or bypass git hooks as part of committing; a slow hook is investigated separately, with measured evidence.

## Steps

1. **Review what is being committed.** Start with two metadata reads, in parallel: `git status --short` and `git diff --cached --name-status`. Other sessions or tools may share the working tree, so read the whole status, not just the files you remember touching. Choose the candidate paths before opening any content, then inspect the staged and unstaged diffs for that selection only, and the selected untracked files separately, since `git diff` omits them. Changes you do not recognize stay unstaged, and the concurrent activity is noted in the commit body; never `git add -A` or `git add .`. If the selection touches the verify command's own definition, `package.json`'s scripts, a Makefile, or the harness hooks, read those changes before running anything. Read recent commit subjects only when a message convention is unclear; the format in step 4 is normally enough. Keep the reviewed selection for the single final recheck in step 5 and do not review it a second time.

2. **Verify, before staging anything.** Run this after the review above and before `git add` touches a single path. When the same verification already ran in this session after the last edit to any selected path, and nothing it depends on changed since, cite that run (the command and its result) instead of running it again; otherwise run it now. After a failed check, fix the cause and rerun that check, not the whole ladder.
   - `host.profile: solo` -> run the doctor's prove-before-done ladder (`harness/skills/doctor/SKILL.md`, "Mode: prove before done") as it already applies to the change.
   - `host.profile: team` -> discover and run the host's own verification first, in this order, first hit wins, and state on the record which source was used and why:
     1. `host.verify_command` in `harness/registry/structure.json`, when it is not `null`. It must match the registry's command shape (`npm run`, `pnpm run`, `yarn`, or `make`, plus a target); anything else is refused with the reason and never run.
     2. `package.json`'s `scripts.verify`, run as `npm run verify`.
     3. A `Makefile` target literally named `verify`, run as `make verify`.
     4. `python harness/tools/lint.py --strict`, when none of the above exist. Say plainly that verification fell to this default; never report a host verification that did not actually run, and never invent a command not found in the host's own files.
   Then, in both profiles, run the close-the-loop checklist's (`harness/rules/close-the-loop.md`) decisions and knowledge lane steps only, limited to the obligations this session created: decisions taken this session go to the decisions lane, cross-session learnings to the knowledge lane, both resolved through `harness/registry/structure.json` at run time. Use the session's own evidence and the closeout work already done first; open a lane file only to resolve a concrete gap, never to audit every lane in a dirty checkout. When a lane is `null` that step is skipped and reported as skipped in your summary, never improvised into a folder. An unfiled learning or stale bookkeeping does not block the commit: report it as outstanding with the result, which does not waive the checklist. No orphan TODOs. The checklist's own "commit or park" step is fulfilled by this skill and is not re-entered.
   The dangerous-operations guard still applies to whichever command runs.

3. **Branch discipline, from `git.mode`.**
   - `main-only` -> commit on the repository's default branch; never switch branches or create one. Run `git branch --show-current` immediately before committing: if the current branch is not the default branch, stop and surface it (another session switched it, or a stray branch exists) rather than committing anywhere or creating a worktree to route around it.
   - `branches` -> commit on a task branch only; never commit directly on the default branch. Run `git branch --show-current` immediately before committing: if the current branch is the default branch, refuse and state the branch-creation command for the task at hand (`git checkout -b <task-branch>` cut from the default branch) instead of committing.
   Do not hardcode a branch name; the default branch is whatever the repository declares.

4. **Write the message.** Subject `type(scope): message`, imperative mood, at most 50 characters. Types: `feat` | `fix` | `docs` | `refactor` | `chore` | `test`. Body only when the diff does not explain the why; wrap body lines at 72 characters, in the host's own conventional-commit style where one is evident from recent history. Always include a `Co-Authored-By` footer for agent-assisted work. Include a `Signed-off-by` footer only when the host's own `CONTRIBUTING.md` (never the harness's own `CONTRIBUTING.harness.md`) affirmatively states that commits carry a DCO sign-off or a `Signed-off-by` trailer. A sentence saying sign-off is not required, an absent file, or an ambiguous mention of `Signed-off-by`, `DCO`, or `sign-off` all mean no sign-off; when the text is ambiguous, say so in the summary and omit the trailer rather than guessing. Never include a session link or session URL.

5. **Stage, verify, and commit in one uninterrupted operation.** Never leave changes staged across turns.
   1. Recheck once: the branch per step 3, no unresolved conflicts, no unrelated staged data in the index, and the selected content unchanged since the review. Stop on a branch or index race or on changed content, without clearing another session's index.
   2. `git add <explicit paths>`, then confirm the staged diff against `HEAD` matches the reviewed selection exactly. This is a drift check, not a second review; stop on a mismatch. A path flagged during the review is never staged.
   3. `git commit` immediately, with a shell-appropriate multiline message: `git commit -F <file>` with a temporary message file on PowerShell, a quoted heredoc in Bash. The pre-commit scan in `.githooks/pre-commit` runs automatically; if it blocks, treat the finding as real until proven otherwise (a committed secret is a compromised secret). Fix the cause and re-stage; do not bypass the hook.
   4. Verify once that the new commit's parent and diff match the expected base and the reviewed selection, then run `git status --short`. Do not rerun unchanged checks or reread unrelated diffs.

6. **Stop after the commit.** Do not push, open a pull request, or merge unless the operator explicitly asks for that specific action in this turn. A general instruction to finish or ship the work ("finish this up", "ship it") is not that ask; it means land the commit and stop. Never force-push a shared branch; where hooks are supported the dangerous-operations guard denies the literal shapes, and the rule holds regardless.
   - `host.profile: solo` -> a pull request does not apply; report the commit as the end of the task.
   - `host.profile: team` -> push and open a pull request only on that separate, explicit ask, and never merge your own pull request; that lands through the host's own review path.

## Splitting

One logical change per commit. If the tree mixes concerns, stage and commit them separately with distinct messages rather than one grab-bag commit. Generated files that the lint byte-checks are regenerated and committed with the source change that produced them, never hand-edited.

## Sample messages

```
feat(parser): accept trailing commas
fix(widget-api): retry on 429
docs(lanes): describe the unset-lane behavior
refactor(select): share the pack filter
chore(lint): pin the ascii check to tracked files
test(materialize): cover the stale-link replacement
```

With a body, when the why is not in the diff:

```
fix(widget-api): retry on 429

The upstream rate limiter returns 429 with a Retry-After header that
the client ignored, so a burst of requests failed permanently instead
of backing off. Honor the header with a capped exponential delay.
```

## Summary shape

After committing, report: the commit hash and subject, the paths staged, the branch verified, the git mode applied, which verification source ran and why (solo checklist and doctor ladder, or the specific team discovery hit, or the earlier run cited and why it still stood), the host profile applied, the close-the-loop outcome per lane (written, skipped because the lane is unset, or nothing to record), and any closeout item left outstanding for the operator.
