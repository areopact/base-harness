# Routing tasks

The delegation module classifies substantive work on two axes, planning depth and capability profile, and dispatches it through generated runtime roles. It is opt-in: the shipped `harness/registry/structure.json` sets `delegation.mandatory` to `false`, so everything on this page is advisory in a fresh clone. The authored policy is the JSON block between `<!-- routing-policy:begin -->` and `<!-- routing-policy:end -->` in `harness/rules/base-routing.md`; that file is the single source and this page is a reader's view of it at `policy_version` 1.0.0.

## Planning tiers T0 to T3

| Tier | Meaning | With the module on |
|---|---|---|
| T0 | Trivial, reversible, one step; the main loop may act directly. | act |
| T1 | Small, clear, reversible, bounded; frame in one line and check. | frame, then proceed |
| T2 | Substantive, multi-step, multi-file, research-heavy, a new artifact, an external write, or output under the operator's name. | delegated `plan.work-packages`, a substantive worker, and independent review of the current artifact (`review-readonly`) |
| T3 | Architecture, strategy, high stakes, precedent, a one-way door, or difficult reconciliation. | T2 plus independent analysis, separate verification, and strong review |

Unknown substantive work defaults to T2. The strictest applicable floor wins: task floor, domain floor (`numeric_deliverable`, `dense_legal_financial`), destination floor (`external_write`), and stakes floor (`high_stakes`). The contract (`AGENTS.md`, principle 1) carries the same ladder in prose so the tiers bind even when the module is off.

## Task IDs

The 41 task ids, rendered from the authored policy by `routing_policy.render_task_table`. Plan is the planning floor; Executor and Reviewer are profile ids; Capability is the tier label; Tool profile bounds what the assignment may touch. An unknown task id never resolves and never launches.

| Task ID | Plan | Executor | Reviewer | Capability | Tool profile |
|---|---:|---|---|---|---|
| `artifact.build` | T2 | `B-BUILD` | `S-REVIEW` | Balanced | `artifact-build` |
| `artifact.imagegen` | T2 | `V-OPTIONAL` | `S-REVIEW` | Balanced | `image-generate` |
| `artifact.render-qa` | T1 | `V-OPTIONAL` | `S-REVIEW` | Balanced | `artifact-inspect` |
| `browser.observe` | T1 | `V-OPTIONAL` | `B-GENERAL` | Balanced | `browser-observe` |
| `browser.operate` | T2 | `B-GENERAL` | `S-REVIEW` | Balanced | `browser-operate` |
| `code.debug` | T2 | `S-BUILD` | `S-REVIEW` | Strong | `code-edit` |
| `code.feature` | T2 | `B-BUILD` | `S-REVIEW` | Balanced | `code-edit` |
| `code.migration` | T2 | `S-BUILD` | `S-REVIEW` | Strong | `code-edit` |
| `code.performance` | T2 | `S-BUILD` | `S-REVIEW` | Strong | `code-edit` |
| `code.refactor` | T2 | `B-BUILD` | `S-REVIEW` | Balanced | `code-edit` |
| `code.scaffold` | T1 | `B-BUILD` | none | Balanced | `code-edit` |
| `code.security` | T3 | `S-BUILD` | `S-REVIEW` | Strong | `review-readonly` |
| `compare.options` | T2 | `B-GENERAL` | `S-REVIEW` | Balanced | `plan-readonly` |
| `connector.read` | T1 | `B-GENERAL` | none | Balanced | `connector-read` |
| `connector.write-sync` | T2 | `B-BUILD` | `S-REVIEW` | Balanced | `connector-write` |
| `data.arithmetic` | T1 | `B-BUILD` | `S-REVIEW` | Balanced | `data-build` |
| `data.clean` | T1 | `B-BUILD` | `B-GENERAL` | Balanced | `data-build` |
| `data.financial-model` | T2 | `S-BUILD` | `S-REVIEW` | Strong | `data-build` |
| `data.statistics` | T2 | `S-BUILD` | `S-REVIEW` | Strong | `data-build` |
| `decide.architecture` | T3 | `S-ANALYZE` | `S-REVIEW` | Strong | `document-draft` |
| `decide.strategy` | T3 | `S-MAIN` | `S-REVIEW` | Strong main | `plan-readonly` |
| `dialogue.user` | T0 | `S-MAIN` | none | Strong main | `dialogue-none` |
| `edit.narrative` | T2 | `B-GENERAL` | `S-REVIEW` | Balanced | `document-draft` |
| `extract.ocr` | T1 | `V-OPTIONAL` | `B-GENERAL` | Balanced | `multimodal-read` |
| `extract.structured` | T1 | `F-READ` | `B-GENERAL` | Fast | `structured-extract` |
| `extract.transcribe` | T1 | `V-OPTIONAL` | `B-GENERAL` | Balanced | `multimodal-read` |
| `ops.deploy` | T3 | `S-BUILD` | `S-REVIEW` | Strong | `deploy` |
| `ops.local-git` | T1 | `F-READ` | none | Fast | `git-local` |
| `orchestrate.workflow` | T2 | `S-MAIN` | `S-REVIEW` | Strong main | `orchestrate-control` |
| `plan.work-packages` | T2 | `S-ANALYZE` | `S-REVIEW` | Strong | `plan-readonly` |
| `research.citation-verify` | T1 | `B-GENERAL` | `S-REVIEW` | Balanced | `evidence-web` |
| `research.evidence` | T2 | `B-GENERAL` | `S-REVIEW` | Balanced | `evidence-web` |
| `resolve.conflict` | T2 | `S-ANALYZE` | `S-REVIEW` | Strong | `plan-readonly` |
| `retrieve.index` | T1 | `F-READ` | `B-GENERAL` | Fast | `index-check` |
| `retrieve.local` | T0 | `F-READ` | none | Fast | `repo-read` |
| `review.adversarial` | T2 | `S-REVIEW` | none | Strong | `review-readonly` |
| `synthesize.evidence` | T2 | `B-GENERAL` | `S-REVIEW` | Balanced | `repo-read` |
| `transform.summarize` | T1 | `B-GENERAL` | none | Balanced | `repo-read` |
| `transform.translate` | T1 | `B-GENERAL` | `B-GENERAL` | Balanced | `repo-read` |
| `verify.deterministic` | T1 | `F-READ` | none | Fast | `ops-check` |
| `visual.concept` | T2 | `B-GENERAL` | `S-REVIEW` | Balanced | `artifact-build` |

Three compatibility aliases resolve to task ids for callers that still use role names: `explorer` is `retrieve.local` on `F-READ` with `repo-read`; `worker` is `code.scaffold` on `B-BUILD` with `code-edit`; `reviewer` is `review.adversarial` on `S-REVIEW` with `review-readonly`.

How this table is produced. `harness/rules/base-routing.md` carries the same table under "Generated task view" beside the authored block, bounded by `<!-- gen:routing-tasks -->` and `<!-- /gen:routing-tasks -->` markers; `harness/tools/gen_manifest.py` refreshes that table in place between the markers. This page's table is a separate render, not driven by those markers, and its accuracy is checked by the digest below rather than by `gen_manifest.py`. `harness/tools/native_routing.py` does not render tables; it renders role files. The table above was rendered from the policy at digest `55bb27329ef6ac6ca1875569f55429a31d27ea50f63a9ee3e9a5856672751753`; verify with `python harness/tools/routing_policy.py check`. If it disagrees with `base-routing.md`, the rule file wins and this page is stale.

## Profiles and model families

Eight profiles name a role, a tier, and per runtime a logical family label with an effort hint and predeclared fallbacks. The labels are `fast`, `balanced`, `strong`, and `strong-main`; no profile names a provider model.

| Profile | Role | Tier | Claude Code | Codex CLI | OpenCode |
|---|---|---|---|---|---|
| `F-READ` | child | Fast | fast | fast | fast |
| `B-GENERAL` | child | Balanced | balanced | balanced | balanced |
| `B-BUILD` | child | Balanced | balanced | balanced | balanced |
| `S-BUILD` | child | Strong | balanced | strong | balanced |
| `S-ANALYZE` | child | Strong | strong | strong | strong |
| `S-REVIEW` | child | Strong | strong | strong | strong |
| `S-MAIN` | main | Strong main | strong-main | strong-main | strong-main |
| `V-OPTIONAL` | child | Balanced | balanced | balanced | balanced |

Each adapter's `model-map.json` binds the four labels to provider ids. The Claude Code map ships `haiku`, `sonnet`, `opus`, `opus`. The Codex and OpenCode maps each bind all four families too (Codex: `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra`; OpenCode: `opencode-go/glm-5.3-flash`, `opencode-go/glm-5.3`, `opencode-go/deepseek-v4-pro`, `opencode-go/kimi-k3`), but every id on every adapter is `configured, not verified` per its own notes; a `null` value is still legal for an id that has not been transcribed, and the doctor prints an unresolved family as UNKNOWN while `native_routing.py render` reports the roles it could not render, with nothing substituting a default. Children resolve only to `fast`, `balanced`, or `strong`; `strong-main` is reserved for the main loop, and the shipped `explicit_child_overrides` list is empty on all three runtimes.

## Tool profiles

22 tool profiles bound what an assignment may do: a capability list, a write scope, and a gate sentence. The read-only family (`repo-read`, `plan-readonly`, `review-readonly`, `connector-read`, `browser-observe`, `dialogue-none`) has write scope `none` or scratch results only; the build family (`code-edit`, `data-build`, `document-draft`, `artifact-build`, `connector-write`, `deploy`) writes only to an assigned path; `orchestrate-control` writes only under the controller's machine-state run directory. `native_routing.py` translates a tool profile into a permission class (`read-only`, `edit`, `shell`, `shell-readonly`) through the adapter's `model-map.json` `permission_classes`; a profile that carries a shell-shaped capability (`bounded-test`, `render`, and the rest of `SHELL_CAPABILITIES` in `native_routing.py`) but only a non-production write scope (`none`, `scratch`, `.tmp`) renders with `shell-readonly` instead of plain `read-only`, for example `review-readonly` and `artifact-inspect`; `shell-readonly` is Bash without the `Edit` or `Write` tool on Claude Code, a read-only sandbox on Codex, and `bash` without `edit` on OpenCode. The full table is the "Generated tool profile view" in `harness/rules/base-routing.md`.

## Floors and guards

- `T2`: `plan.work-packages` first, a substantive worker, independent review with `review-readonly`.
- `T3`: T2 plus independent analysis, separate verification, and strong review.
- `numeric_deliverable`: at least a `B-BUILD` builder and `S-REVIEW` with independent recomputation.
- `dense_legal_financial`: the reader is `S-ANALYZE`.
- `external_write`: T2, a Balanced executor, the matching skill, existing authorization, a post-write check, and `S-REVIEW` on bidirectional conflict.
- `high_stakes`: T3 with `S-BUILD`, `S-ANALYZE`, and `S-REVIEW`.

Scheduling: at most six concurrent children, lowered to the tested surface cap; workers never spawn workers; one designated writer per shared artifact. Every work package records task, planning tier, profile, resolved label and native model, effort, tool profile, skills, sources, permitted outputs, dependencies, acceptance criteria, retry budget, and result schema; a result with missing observability is `unknown`, never a pass. Any artifact change after verification invalidates the affected verification and review.

## Enabling mandatory delegation

Set `delegation.mandatory` to `true` in `harness/registry/structure.json` (or start from the `private-instance-host` example in `harness/tools/templates/lanes.example.json`). Three things change:

1. `harness/hooks/lib/delegation_guard.py`, registered on `PreToolUse` and `PostToolUse` for `Agent` and `Workflow` dispatches on Claude Code and through the dispatcher on Codex, stops being a no-op and reminds the model that every dispatch resolves through the policy and that a launch id is not completion evidence. It stays advisory.
2. `harness/tools/workflow.py` runs without `--opt-in`. With the flag off it prints a one-line reason and exits 2.
3. The contract's T2 definition (principle 1) applies in its delegated form.

The generated roles exist either way. `python harness/tools/routing_policy.py compile` validates the authored block, writes the untracked manifest `harness/registry/delegation-policy.json`, and prints the digest; `check` exits 1 when the manifest drifted; `resolve --task <id> [--runtime r] [--assignment executor|reviewer] [--profile p]` prints one resolved work package as JSON. `python harness/tools/native_routing.py render` writes one role per task id and phase into `harness/adapters/<runtime>/agents/` (Markdown with frontmatter for Claude Code and OpenCode, TOML for Codex), and `render --check` is part of lint L11. Roles carry name, scope, tools, permission class, and family; no persona.

## The workflow skill

`workflow.py` is the controller: `plan <spec.json>` plans a ratified work-package spec; `start` seeds the mandatory planner, reviewer, and (for T3) analyst and verifier stages and runs each package as a controller-owned native child process; `run`, `resume`, `status`, and `cancel` operate on a run id. Receipts land under the machine-state workflows directory, one folder per run. Nothing in it parses `base-routing.md`; the policy comes through `routing_policy` and native selections through `native_routing`. The `workflow` skill that fronts the controller ships under `harness/skills/workflow/`, part of the delegation module in the catalog (`docs/PACKS.md`); it is not in the default selection, so select it with `--pack core --pack maintain --pack delegation` before it materializes into a runtime. The controller and its tests (`harness/tools/tests/test_workflow.py`) ship regardless of selection.
