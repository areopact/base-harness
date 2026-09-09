# Close the Loop

Run this checklist before stopping any session that created, modified, or moved files. Skip it for read-only lookups. Every step names a memory lane from `harness/registry/structure.json`; a lane that is `null` is not configured, and its step is skipped with that fact stated, never improvised into a folder.

## Why

Work that ends without a closing pass leaves three kinds of debt. Context drifts: the next session reads a status document that no longer describes reality and acts on it. Evidence scatters: what happened, what was decided, and what was learned stay in a transcript nobody will reread, so the same discovery is made again next month. Links rot: a new file that nothing points to is invisible to graph traversal and to the memory-first lookup, which means it is as good as unwritten. A Stop hook surfaces this checklist where the runtime supports hooks; elsewhere this page is the enforcement.

## Application

1. **Verify.** The change was exercised end to end (test run, build, manual invocation). Evidence over assertion; if verification was skipped, say so explicitly. See [agent-discipline](agent-discipline.md).

2. **Commit or park, on the branch and etiquette the host declares.** Work is committed with a conventional message per [git-workflow](git-workflow.md), or explicitly parked with a note on where it stands. No silent dirty trees. `git.mode` decides the branch: `main-only` commits to the default branch or parks the work; `branches` commits on a task branch, never the default branch. `host.profile` decides the social part on top of that: `team` opens a pull request only when asked, on top of whichever branch discipline `git.mode` set; `solo` adds nothing, since no pull request applies.

3. **Docs lane: update the nearest context document.** If the session changed the state of something the docs lane describes (a status page, a plan, a current-priorities section), update the nearest such document: its current section and its updated date. If the docs lane is null, state that no context document exists to update.

4. **Records lane: file dated captures.** Meeting notes, session notes, research runs, and other dated material from the session go to the records lane as dated entries, append-only after the event. If the records lane is null, the capture stays in the reply or in the runtime's native memory and the summary says so.

5. **Decisions lane: log commitments.** Any one-way door taken this session (an architecture choice, a dependency, an API contract, a process change) is logged to the decisions lane with context, the decision, options considered, and risks accepted. A wrong decision is superseded by a newer entry that links back, never deleted. If the decisions lane is null, name the decision in the summary so the operator can record it elsewhere.

6. **Knowledge lane: synthesize only what crosses contexts.** Write a cross-session belief to the knowledge lane only when a future session on a different task or in a different runtime would act differently for knowing it. Facts the code, tests, or docs already state go nowhere; fix the source instead. Current work state never goes to the knowledge lane. Routing test and maturity vocabulary: [memory-routing](memory-routing.md).

7. **Graph hygiene.** Every new file is linked from at least one existing file, and every link written this session resolves. No orphans, no dangling references after a move.

8. **No orphan promises.** Anything promised in conversation ("I'll also...") is either done, committed as a TODO in the code, or written to the lane it belongs in.

### Verification

- `git status` clean, or the dirty state is intentional and explained.
- Dated entries in the records and decisions lanes follow `YYYY-MM-DD-topic.md`.
- Any context document touched carries today's date in its updated field.
- New lane files actually say something a future session needs; delete noise.
