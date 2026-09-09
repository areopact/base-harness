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

## Steps

1. **Verify, before staging anything.** Run this before `git add` touches a single path.
   - `host.profile: solo` -> run the close-the-loop checklist (`harness/rules/close-the-loop.md`) and the doctor's prove-before-done ladder (`harness/skills/doctor/SKILL.md`, "Mode: prove before done") as they already apply to the change.
   - `host.profile: team` -> discover and run the host's own verification first, in this order, first hit wins, and state on the record which source was used and why:
     1. `host.verify_command` in `harness/registry/structure.json`, when it is not `null`. It must match the registry's command shape (`npm run`, `pnpm run`, `yarn`, or `make`, plus a target); anything else is refused with the reason and never run.
     2. `package.json`'s `scripts.verify`, run as `npm run verify`.
     3. A `Makefile` target literally named `verify`, run as `make verify`.
     4. `python harness/tools/lint.py --strict`, when none of the above exist. Say plainly that verification fell to this default; never report a host verification that did not actually run, and never invent a command not found in the host's own files.
     Then run the close-the-loop checklist as well.
   In both profiles the checklist writes decisions taken this session to the decisions lane and cross-session learnings to the knowledge lane, both resolved through `harness/registry/structure.json` at run time; when a lane is `null` that step is skipped and reported as skipped in your summary, never improvised into a folder. No orphan TODOs.
   The dangerous-operations guard still applies to whichever command runs.

2. **Review what is being committed.** Run `git status` and `git diff`. Other sessions or tools may share the working tree, so read the whole status, not just the files you remember touching. Stage explicit paths only; never `git add -A` or `git add .` when unrelated changes are present. Changes you do not recognize stay unstaged, and the concurrent activity is noted in the commit body.

3. **Branch discipline, from `git.mode`.**
   - `main-only` -> commit on the repository's default branch; never switch branches or create one. Run `git branch --show-current` immediately before committing: if the current branch is not the default branch, stop and surface it (another session switched it, or a stray branch exists) rather than committing anywhere or creating a worktree to route around it.
   - `branches` -> commit on a task branch only; never commit directly on the default branch. Run `git branch --show-current` immediately before committing: if the current branch is the default branch, refuse and state the branch-creation command for the task at hand (`git checkout -b <task-branch>` cut from the default branch) instead of committing.
   Do not hardcode a branch name; the default branch is whatever the repository declares.

4. **Write the message.** Subject `type(scope): message`, imperative mood, at most 50 characters. Types: `feat` | `fix` | `docs` | `refactor` | `chore` | `test`. Body only when the diff does not explain the why; wrap body lines at 72 characters, in the host's own conventional-commit style where one is evident from recent history. Always include a `Co-Authored-By` footer for agent-assisted work. Include a `Signed-off-by` footer only when the host's own `CONTRIBUTING.md` (never the harness's own `CONTRIBUTING.harness.md`) mentions `Signed-off-by`, `DCO`, or `sign-off`, case-insensitive; otherwise omit it. Never include a session link or session URL.

5. **Stage and commit atomically.** `git add <explicit paths>` immediately followed by `git commit` in the same step. Never leave changes staged across turns. The pre-commit scan in `.githooks/pre-commit` runs automatically; if it blocks, treat the finding as real until proven otherwise (a committed secret is a compromised secret). Fix the cause and re-stage; do not bypass the hook.

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

After committing, report: the commit hash and subject, the paths staged, the branch verified, the git mode applied, which verification source ran and why (solo checklist and doctor ladder, or the specific team discovery hit), the host profile applied, and the close-the-loop outcome per lane (written, skipped because the lane is unset, or nothing to record).
