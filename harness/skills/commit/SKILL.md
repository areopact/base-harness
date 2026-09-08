---
name: commit
description: >
  Create a conventional commit that respects the repository's declared git
  mode, stages explicit paths, and runs the close-the-loop checklist. WHEN:
  user invokes /commit, says "commit this", "save my work", "make a commit",
  or "stage and commit"; at the end of a session with a dirty tree. WHEN NOT:
  proving the change works first (/verify); pushing, merging, or rebasing
  (the host's git workflow, on request only); read-only sessions with nothing
  to commit.
metadata:
  packs: [maintain]
  triggers:
    - "commit this"
    - "save my work"
    - "make a commit"
    - "stage and commit"
  requires: [lane:decisions, lane:knowledge]
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# commit

One logical change per commit, staged deliberately, on the branch the repository's git mode expects. The rule this skill applies is `harness/rules/git-workflow.md`; the closing checklist is `harness/rules/close-the-loop.md`.

## Steps

1. **Read the git mode.** Read `git.mode` from `harness/registry/structure.json`. The shipped value is `main-only`; the other value is `branches`. The mode decides step 3; everything else applies in both.

2. **Review what is being committed.** Run `git status` and `git diff` first. Other sessions or tools may share the working tree, so read the whole status, not just the files you remember touching. Stage explicit paths only; never `git add -A` or `git add .` when unrelated changes are present. Changes you do not recognize stay unstaged, and the concurrent activity is noted in the commit body.

3. **Verify the branch immediately before committing.** Run `git branch --show-current`.
   - In `main-only` mode the branch must be the repository's default branch. If it is not, stop and surface it: another session switched the branch or a stray branch exists. Never create a branch or a worktree to work around it, and never switch branches on the operator's behalf.
   - In `branches` mode commit on the current working branch and leave merge, review, and landing policy to the host.
   Do not hardcode a branch name; the default branch is whatever the repository declares.

4. **Run close-the-loop** (`harness/rules/close-the-loop.md`). The change was verified (`/verify` names the rung and the evidence). Decisions taken this session go to the decisions lane and cross-session learnings to the knowledge lane; both lanes resolve through `harness/registry/structure.json` at run time. When a lane is `null` that step is skipped and reported as skipped in your summary, never improvised into a folder. No orphan TODOs.

5. **Write the message.** Subject `type(scope): message`, imperative mood, at most 50 characters. Types: `feat` | `fix` | `docs` | `refactor` | `chore` | `test`. Body only when the diff does not explain the why; wrap body lines at 72 characters.

6. **Stage and commit atomically.** `git add <explicit paths>` immediately followed by `git commit` in the same step. Never leave changes staged across turns. The pre-commit scan in `.githooks/pre-commit` runs automatically; if it blocks, treat the finding as real until proven otherwise (a committed secret is a compromised secret). Fix the cause and re-stage; do not bypass the hook.

7. **Do not push** unless asked. Never force-push a shared branch; where hooks are supported the dangerous-operations guard denies the literal shapes, and the rule holds regardless.

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

After committing, report: the commit hash and subject, the paths staged, the branch verified, the git mode applied, and the close-the-loop outcome per lane (written, skipped because the lane is unset, or nothing to record).
