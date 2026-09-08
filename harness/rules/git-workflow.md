# Git Workflow

The repository declares one of two git modes in `harness/registry/structure.json` under `git.mode`: `main-only` or `branches`. The mode decides whether branches and worktrees exist at all; the commit format, the atomic stage-and-commit habit, and the shared-tree etiquette apply in both.

## Why

Git's index and HEAD are per-repository, not per-session. When several sessions or agents share one working tree, one session's `git add -A` sweeps another session's staged files into its commit, and a branch switch moves the tree under a task that is still running. The only defenses that hold are habits that fit in a single step: verify the branch immediately before committing, stage explicit paths, and commit in the same command that staged them. A mode that forbids branches removes an entire class of these collisions; a mode that allows them needs protected-branch rules to contain them.

## Application

### Shared-tree etiquette (both modes)

- Verify the branch immediately before every commit: `git branch --show-current`. If it is not the branch you expect, stop: another session switched it or a stray branch exists. Surface it to the operator before committing anywhere.
- Stage and commit atomically: `git add <explicit paths>` immediately followed by `git commit` in the same step. Never leave changes staged across turns.
- When `git status` shows changes you do not recognize, stage explicit paths only (never `git add -A` or `git add .`), and note the concurrent activity in the commit body.
- Heavy parallel mutation uses a runtime's ephemeral isolated-worktree feature only when that feature exists and the mode allows it. Runtimes whose sub-agents share the filesystem keep them read-only in parallel and serialize writers.

### Mode: main-only

A single-operator repository with no review workflow. All work lands directly on the default branch as a sequence of small commits.

- Never create a branch or a worktree, and never switch off the default branch. Large work lands as many small commits, in order.
- The one exception is a runtime-managed, temporary isolated worktree for a delegated task. It is a tool mechanism, not a workflow branch, and stays allowed where the runtime supports it. Do not emulate it by hand.
- Leftover branches or worktrees (predating this mode, or created by mistake): surface to the operator, merge or discard on their instruction, then delete. Never leave one lying around.
- Committed generated files are byte-checked by the lint; regenerate and commit, never hand-edit.

### Mode: branches

A team repository, or a solo repository that wants review.

- One feature branch per task, named for the task, cut from the default branch. Land it through the host's review path.
- No force-push to a protected branch, ever, and no history rewrite on any shared branch. The dangerous-operations guard denies the literal shapes where hooks are supported; the rule holds regardless.
- Where the remote enforces linear history, land branch content by rebase or cherry-pick, never by a merge commit: a local merge commit passes every local check and is then declined at push time.
- Committed generated files carry `merge=ours` in `.gitattributes`; on conflict, regenerate and diff rather than merging by hand. The attribute is inert until the local `merge.ours` driver exists (`git config merge.ours.driver true`); check it before relying on it.
- The personal memory lane defaults to a location outside the repository in this mode (see `docs/LANES.md`), so a branch never carries one person's working memory into review.

### Size guard (pre-commit)

Binary files over 1 MiB stay out of git. Compressed container formats (office documents, PDFs, archives) never delta-compress, so every re-commit stores a near-full copy forever. The pre-commit hook in `.githooks/` enforces the floor; text formats that delta-compress are exempt at any size. Route an oversized binary to an artifact store outside git, or add a deliberate allowlist entry with a reason.

### Commits

Format: `type(scope): message` (imperative, max 50 characters).

Types: `feat` | `fix` | `docs` | `refactor` | `chore`

Body lines wrap at 72 characters. Include a `Co-Authored-By` footer when an agent assisted.
