# Base Routing

The floors on this page bind only when `harness/registry/structure.json` sets `delegation.mandatory` to `true`. The shipped default is `false`, so in a fresh clone every section below is advisory: a description of how substantive work is classified and delegated when the delegation module is switched on, and a vocabulary the main loop may borrow even when it is off.

With the module on, the main loop classifies each request on two independent axes before dispatch: planning depth (T0 to T3) and the capability profile for each assignment. Complex work uses delegated planning, substantive worker execution, and fresh independent review. The main loop owns classification, allocation, escalation, ratification, voice, and live operator dialogue.

This page is the sole authored source for delegation task IDs, compatibility aliases, profile-to-tier allocations, tool profiles, composite floors, and review rules. Profiles name four logical tier labels only: `fast`, `balanced`, `strong`, and `strong-main`. Adapters map the labels to exact provider ids and native syntax in their `model-map.json`; they do not choose allocations. [git-workflow](git-workflow.md), [access-policy](access-policy.md), [secrets](secrets.md), and [hook-design](hook-design.md) retain their authority.

## Why

A request dispatched without classification gets whatever model and tools the runtime hands out by default, and its result is judged by whoever happens to be in the loop. Two independent axes keep the failure modes apart: planning depth decides how much thought precedes action, and the capability profile decides who does the work and with which tools. Naming both up front, from one authored source that every runtime compiles rather than interprets, means a fast reader is never asked to adjudicate a conflict, a reviewer never inherits the writer's blind spots, and no runtime resolves a model implicitly.

## Authored policy

Only the JSON between the two HTML markers is policy input. `harness/tools/routing_policy.py compile` parses that block and nothing else; the generated tables below and the generated manifest are derived views and are excluded from its hash.

<!-- routing-policy:begin -->
```json
{
  "policy_version": "1.0.0",
  "planning": {
    "default_substantive": "T2",
    "tiers": {
      "T0": "Trivial, reversible, one step; main may act directly.",
      "T1": "Small, clear, reversible, bounded; frame briefly and check.",
      "T2": "Substantive, multi-step, multi-file, research-heavy, new artifact, external write, or output under the operator's name; delegated plan, worker, and independent review.",
      "T3": "Architecture, strategy, high stakes, precedent, one-way door, or difficult reconciliation; written design, independent analysis, worker, separate verification, and strong review."
    }
  },
  "scheduling": {"max_concurrent_children":6,"workers_may_spawn":false,"one_canonical_writer":true,"effective_limit":"minimum of policy and tested surface capability"},
  "compatibility_aliases": {
    "explorer":{"task_id":"retrieve.local","profile":"F-READ","tool_profile":"repo-read"},
    "worker":{"task_id":"code.scaffold","profile":"B-BUILD","tool_profile":"code-edit"},
    "reviewer":{"task_id":"review.adversarial","profile":"S-REVIEW","tool_profile":"review-readonly"}
  },
  "profiles": {
    "F-READ": {"tier":"Fast","role":"child","work_kind":"read","purpose":"bounded retrieval, extraction, and deterministic checks","families":{"claude":"fast","codex":"fast","opencode":"fast"},"effort":{"claude":"low","codex":"low","opencode":"lowest-supported"},"fallbacks":{"claude":["balanced"],"codex":["balanced"],"opencode":["balanced"]}},
    "B-GENERAL": {"tier":"Balanced","role":"child","work_kind":"general","purpose":"research, synthesis, and reversible document work","families":{"claude":"balanced","codex":"balanced","opencode":"balanced"},"effort":{"claude":"medium","codex":"medium","opencode":"medium-supported"},"fallbacks":{"claude":["strong"],"codex":["strong"],"opencode":["strong"]}},
    "B-BUILD": {"tier":"Balanced","role":"child","work_kind":"build","purpose":"bounded code, data, and artifact implementation","families":{"claude":"balanced","codex":"balanced","opencode":"balanced"},"effort":{"claude":"medium","codex":"medium","opencode":"high"},"fallbacks":{"claude":["strong"],"codex":["strong"],"opencode":[]}},
    "S-BUILD": {"tier":"Strong","role":"child","work_kind":"build","purpose":"debugging, migration, performance, and security implementation","families":{"claude":"balanced","codex":"strong","opencode":"balanced"},"effort":{"claude":"high","codex":"high","opencode":"max"},"fallbacks":{"claude":["strong"],"codex":[],"opencode":[]}},
    "S-ANALYZE": {"tier":"Strong","role":"child","work_kind":"analyze","purpose":"planning, dense legal or financial reading, and conflict analysis","families":{"claude":"strong","codex":"strong","opencode":"strong"},"effort":{"claude":"high","codex":"high","opencode":"high-supported"},"fallbacks":{"claude":[],"codex":[],"opencode":["balanced"]}},
    "S-REVIEW": {"tier":"Strong","role":"child","work_kind":"review","purpose":"independent verification and adversarial review","families":{"claude":"strong","codex":"strong","opencode":"strong"},"effort":{"claude":"high","codex":"high","opencode":"high-supported"},"fallbacks":{"claude":[],"codex":[],"opencode":[]}},
    "S-MAIN": {"tier":"Strong main","role":"main","work_kind":"main","purpose":"orchestration, ratification, voice, and dialogue","families":{"claude":"strong-main","codex":"strong-main","opencode":"strong-main"},"effort":{"claude":"strong-supported","codex":"high","opencode":"strong-supported"},"fallbacks":{"claude":[],"codex":[],"opencode":[]}},
    "V-OPTIONAL": {"tier":"Balanced","role":"child","work_kind":"visual","purpose":"capability-tested multimodal observation","families":{"claude":"balanced","codex":"balanced","opencode":"balanced"},"effort":{"claude":"medium","codex":"medium","opencode":"tested-supported"},"fallbacks":{"claude":["strong"],"codex":["strong"],"opencode":[]}}
  },
  "runtime_constraints": {
    "claude": {"main_profile":"S-MAIN","main_family":"strong-main","child_families":["fast","balanced","strong"],"explicit_child_overrides":[]},
    "codex": {"main_profile":"S-MAIN","main_family":"strong-main","child_families":["fast","balanced","strong"],"explicit_child_overrides":[]},
    "opencode": {"main_profile":"S-MAIN","main_family":"strong-main","child_families":["fast","balanced","strong"],"explicit_child_overrides":[]}
  },
  "tool_profiles": {
    "repo-read": {"capabilities":["read","glob","grep","bounded-local-search"],"write_scope":"none","gate":"access policy applies"},
    "index-check": {"capabilities":["repo-read","deterministic-enumeration","dedupe"],"write_scope":"scratch only","gate":"reconcile counts before use"},
    "structured-extract": {"capabilities":["read","deterministic-parser","structured-result"],"write_scope":"scratch only","gate":"source remains unchanged"},
    "multimodal-read": {"capabilities":["tested-media-inspection","tested-extraction"],"write_scope":"scratch only","gate":"fail closed without modality support"},
    "evidence-web": {"capabilities":["brain-first-read","web-search","web-fetch","citation-capture"],"write_scope":"none","gate":"source safety and citation rules apply"},
    "plan-readonly": {"capabilities":["read","search","analysis","plan-result"],"write_scope":"none","gate":"no artifact edit, shell mutation, or external write"},
    "document-draft": {"capabilities":["read","edit","write"],"write_scope":"assigned document only","gate":"designated writer required"},
    "data-build": {"capabilities":["data-skill","scripts","formulas","recalculation"],"write_scope":"assigned data artifact and scratch","gate":"styled-file safe path required"},
    "code-edit": {"capabilities":["read","edit","patch","bounded-build","bounded-test","named-shell"],"write_scope":"assigned code paths and scratch","gate":"no deploy or unrelated remediation"},
    "artifact-build": {"capabilities":["matching-artifact-skill","render-tools"],"write_scope":"assigned artifact directory and scratch","gate":"render through matching skill"},
    "artifact-inspect": {"capabilities":["view","render","visual-inspection"],"write_scope":"scratch renders only","gate":"no production fixes; modality must be proven"},
    "image-generate": {"capabilities":["image-generation","image-inspection"],"write_scope":"assigned asset only","gate":"matching skill rules apply"},
    "browser-observe": {"capabilities":["navigate","inspect","capture"],"write_scope":"none","gate":"no form submission"},
    "browser-operate": {"capabilities":["named-click","named-type","upload","download"],"write_scope":"assigned browser session and approved download path","gate":"external writes require existing authorization"},
    "connector-read": {"capabilities":["named-list","named-get","named-search"],"write_scope":"none","gate":"no browser substitution while supported"},
    "connector-write": {"capabilities":["named-create","named-update","named-sync"],"write_scope":"assigned remote object and approved local sync path","gate":"authorization and post-write check required"},
    "git-local": {"capabilities":["git-status","git-diff","assigned-local-git-operation"],"write_scope":"working tree, index, or local ref allowed by git-workflow","gate":"git-workflow retains authority"},
    "ops-check": {"capabilities":["named-lint","named-test","named-render","named-check"],"write_scope":"scratch and cache only","gate":"actual output required"},
    "deploy": {"capabilities":["named-push","named-deploy","health-check","rollback"],"write_scope":"assigned deployment target","gate":"candidate, authorization, and rollback required"},
    "review-readonly": {"capabilities":["read","inspect","bounded-test"],"write_scope":"scratch results only","gate":"independent reviewer; no production fixes"},
    "orchestrate-control": {"capabilities":["dispatch","wait","message","interrupt","controller-receipts"],"write_scope":"scratch: the run's workflow state directory only","gate":"no production artifact edits"},
    "dialogue-none": {"capabilities":["main-loop-response"],"write_scope":"none","gate":"no delegated tool or external side effect"}
  },
  "tasks": {
    "plan.work-packages": {"planning_floor":"T2","executor":"S-ANALYZE","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"plan-readonly","output_check":"dependency graph, acceptance criteria, task, profile, and tool IDs; no artifact edits","escalation":"S-MAIN on unresolved scope or one-way decision"},
    "retrieve.local": {"planning_floor":"T0","executor":"F-READ","reviewer":null,"capability":"Fast","tool_profile":"repo-read","output_check":"exact paths and passages","escalation":"B-GENERAL on miss, broad scope, or ambiguity"},
    "retrieve.index": {"planning_floor":"T1","executor":"F-READ","reviewer":"B-GENERAL","capability":"Fast","tool_profile":"index-check","output_check":"deduplicated inventory reconciled to source count","escalation":"B-GENERAL on stale index or unexplained count gap"},
    "extract.structured": {"planning_floor":"T1","executor":"F-READ","reviewer":"B-GENERAL","capability":"Fast","tool_profile":"structured-extract","output_check":"schema, row count, and missing-field validation","escalation":"B-GENERAL on malformed input or schema/count failure"},
    "extract.ocr": {"planning_floor":"T1","executor":"V-OPTIONAL","reviewer":"B-GENERAL","capability":"Balanced","tool_profile":"multimodal-read","output_check":"page anchors and image sample","escalation":"S-ANALYZE on ambiguity; blocked without tested modality"},
    "extract.transcribe": {"planning_floor":"T1","executor":"V-OPTIONAL","reviewer":"B-GENERAL","capability":"Balanced","tool_profile":"multimodal-read","output_check":"timestamps, speakers, and sampled fidelity","escalation":"S-ANALYZE on speaker ambiguity; blocked without tested modality"},
    "transform.summarize": {"planning_floor":"T1","executor":"B-GENERAL","reviewer":null,"capability":"Balanced","tool_profile":"repo-read","output_check":"source-bounded summary traced to sections","escalation":"S-ANALYZE for dense legal/financial text, contradiction, or lost qualification"},
    "transform.translate": {"planning_floor":"T1","executor":"B-GENERAL","reviewer":"B-GENERAL","capability":"Balanced","tool_profile":"repo-read","output_check":"terms, numbers, and uncertainty preserved","escalation":"S-ANALYZE for legal stakes, ambiguous terminology, or numeric drift"},
    "research.evidence": {"planning_floor":"T2","executor":"B-GENERAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"evidence-web","output_check":"memory-first primary-source packet with gaps","escalation":"S-ANALYZE on conflicting sources, weak authority, or high stakes"},
    "research.citation-verify": {"planning_floor":"T1","executor":"B-GENERAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"evidence-web","output_check":"claim, date, quote, and number opened at source","escalation":"S-ANALYZE when source unavailable, mismatched, or circular"},
    "compare.options": {"planning_floor":"T2","executor":"B-GENERAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"plan-readonly","output_check":"common criteria and evidence matrix","escalation":"S-ANALYZE when criteria require judgment or options are incomparable"},
    "resolve.conflict": {"planning_floor":"T2","executor":"S-ANALYZE","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"plan-readonly","output_check":"independent readings, contradiction map, and adjudication","escalation":"S-MAIN on unresolved primary-source, policy, or legal conflict"},
    "synthesize.evidence": {"planning_floor":"T2","executor":"B-GENERAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"repo-read","output_check":"claim map with provenance and preserved dissent","escalation":"S-ANALYZE for novel decisions, dense evidence, or missing provenance"},
    "edit.narrative": {"planning_floor":"T2","executor":"B-GENERAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"document-draft","output_check":"assigned-path diff preserving facts, voice, and citations","escalation":"S-ANALYZE on intent change, named-person claim, or publication stakes"},
    "data.arithmetic": {"planning_floor":"T1","executor":"B-BUILD","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"data-build","output_check":"units, formulas, and independent recomputation","escalation":"S-ANALYZE on mismatch, unstated assumption, or financial interpretation"},
    "data.clean": {"planning_floor":"T1","executor":"B-BUILD","reviewer":"B-GENERAL","capability":"Balanced","tool_profile":"data-build","output_check":"reversible transform, before/after counts, and exceptions","escalation":"S-ANALYZE on destructive coercion, unexplained loss, or identity merge"},
    "data.statistics": {"planning_floor":"T2","executor":"S-BUILD","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"data-build","output_check":"reproducible method, assumptions, sample size, and sensitivity","escalation":"S-ANALYZE on weak sample, causal claim, or unstable result"},
    "data.financial-model": {"planning_floor":"T2","executor":"S-BUILD","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"data-build","output_check":"formula/recalc checks, scenario bounds, and independent numeric review","escalation":"S-ANALYZE on mismatch, valuation judgment, or styled-file risk"},
    "code.scaffold": {"planning_floor":"T1","executor":"B-BUILD","reviewer":null,"capability":"Balanced","tool_profile":"code-edit","output_check":"assigned-path diff plus build/import check","escalation":"S-BUILD on new architecture, dependency conflict, or multi-module spread"},
    "code.feature": {"planning_floor":"T2","executor":"B-BUILD","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"code-edit","output_check":"one-writer diff, acceptance tests, and relevant suite","escalation":"S-BUILD on scope growth, API ambiguity, or repeated test failure"},
    "code.debug": {"planning_floor":"T2","executor":"S-BUILD","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"code-edit","output_check":"reproduction, isolated cause, regression check, and suite","escalation":"S-ANALYZE after two failed loops, nondeterminism, or cross-system cause"},
    "code.refactor": {"planning_floor":"T2","executor":"B-BUILD","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"code-edit","output_check":"behavior baseline, bounded diff, and regression checks","escalation":"S-BUILD on behavior change, migration need, or expanding surface"},
    "code.migration": {"planning_floor":"T2","executor":"S-BUILD","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"code-edit","output_check":"inventory, reversible sequence, compatibility, and rollback checks","escalation":"S-ANALYZE on data-loss risk, partial state, or unsupported dependency"},
    "code.performance": {"planning_floor":"T2","executor":"S-BUILD","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"code-edit","output_check":"baseline, controlled benchmark, and correctness check","escalation":"S-ANALYZE on noise, production-only evidence, or correctness trade-off"},
    "code.security": {"planning_floor":"T3","executor":"S-BUILD","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"review-readonly","output_check":"threat evidence and independent adversarial review","escalation":"S-MAIN before exploit, secret boundary, or external-target action"},
    "decide.strategy": {"planning_floor":"T3","executor":"S-MAIN","reviewer":"S-REVIEW","capability":"Strong main","tool_profile":"plan-readonly","output_check":"options, assumptions, downside cases, and ratification","escalation":"S-MAIN holds on missing stakeholder facts or one-way commitment"},
    "decide.architecture": {"planning_floor":"T3","executor":"S-ANALYZE","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"document-draft","output_check":"written interfaces, failure modes, and migration path","escalation":"S-MAIN on cross-owner, irreversible dependency, or security boundary"},
    "visual.concept": {"planning_floor":"T2","executor":"B-GENERAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"artifact-build","output_check":"brief, variants, and design rationale","escalation":"S-ANALYZE on brand conflict or unclear audience; blocked without tested modality"},
    "artifact.build": {"planning_floor":"T2","executor":"B-BUILD","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"artifact-build","output_check":"native artifact plus render through matching skill","escalation":"S-BUILD on format loss, complex generation, or external destination"},
    "artifact.render-qa": {"planning_floor":"T1","executor":"V-OPTIONAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"artifact-inspect","output_check":"every relevant view inspected with defect log","escalation":"S-ANALYZE on semantic defect; blocked if modality untested"},
    "artifact.imagegen": {"planning_floor":"T2","executor":"V-OPTIONAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"image-generate","output_check":"prompt provenance and generated-asset inspection","escalation":"S-ANALYZE on identity or brand stakes, or failed visual QA"},
    "browser.observe": {"planning_floor":"T1","executor":"V-OPTIONAL","reviewer":"B-GENERAL","capability":"Balanced","tool_profile":"browser-observe","output_check":"captured state and source URL","escalation":"S-ANALYZE on untrusted instruction; blocked at login or unsupported modality"},
    "browser.operate": {"planning_floor":"T2","executor":"B-GENERAL","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"browser-operate","output_check":"named actions and before/after state","escalation":"S-MAIN before destructive action, external message, or ambiguous-target write"},
    "connector.read": {"planning_floor":"T1","executor":"B-GENERAL","reviewer":null,"capability":"Balanced","tool_profile":"connector-read","output_check":"structured result and source identity","escalation":"S-ANALYZE on schema ambiguity or conflict; blocked if auth absent"},
    "connector.write-sync": {"planning_floor":"T2","executor":"B-BUILD","reviewer":"S-REVIEW","capability":"Balanced","tool_profile":"connector-write","output_check":"authorized preview and post-write fidelity check","escalation":"S-ANALYZE on bidirectional conflict, deletion, or identity ambiguity"},
    "ops.local-git": {"planning_floor":"T1","executor":"F-READ","reviewer":null,"capability":"Fast","tool_profile":"git-local","output_check":"repository/status evidence and expected diff","escalation":"B-BUILD for local mutation; S-ANALYZE before destructive command or conflict"},
    "ops.deploy": {"planning_floor":"T3","executor":"S-BUILD","reviewer":"S-REVIEW","capability":"Strong","tool_profile":"deploy","output_check":"candidate, checks, rollback, and authorization","escalation":"S-MAIN on ambiguity, failed health check, or irreversible step"},
    "verify.deterministic": {"planning_floor":"T1","executor":"F-READ","reviewer":null,"capability":"Fast","tool_profile":"ops-check","output_check":"actual named check output","escalation":"B-GENERAL on flaky or missing check; S-ANALYZE when judgment required"},
    "review.adversarial": {"planning_floor":"T2","executor":"S-REVIEW","reviewer":null,"capability":"Strong","tool_profile":"review-readonly","output_check":"fresh artifact, criteria, evidence, and read-only findings","escalation":"S-MAIN on identity collision, stale artifact, or unresolved critical"},
    "orchestrate.workflow": {"planning_floor":"T2","executor":"S-MAIN","reviewer":"S-REVIEW","capability":"Strong main","tool_profile":"orchestrate-control","output_check":"task graph, explicit profiles, native receipts, and ratification","escalation":"S-MAIN blocks on unknown ID, missing capability, or failed worker/reviewer"},
    "dialogue.user": {"planning_floor":"T0","executor":"S-MAIN","reviewer":null,"capability":"Strong main","tool_profile":"dialogue-none","output_check":"main-loop response, voice, and approval boundary","escalation":"plan.work-packages when request becomes substantive"}
  },
  "floors": {
    "T2": {"required_tasks":["plan.work-packages"],"substantive_worker":true,"independent_review":true,"review_tool_profile":"review-readonly"},
    "T3": {"required_tasks":["plan.work-packages"],"independent_analysis":true,"substantive_worker":true,"separate_verification":true,"strong_review":true,"review_tool_profile":"review-readonly"},
    "numeric_deliverable": {"executor":"B-BUILD","reviewer":"S-REVIEW","independent_recomputation":true},
    "dense_legal_financial": {"reader":"S-ANALYZE"},
    "external_write": {"planning_floor":"T2","executor_tier":"Balanced","requires_matching_skill":true,"requires_authorization":true,"requires_post_write_check":true,"conflict_reviewer":"S-REVIEW"},
    "high_stakes": {"planning_floor":"T3","builder":"S-BUILD","analyst":"S-ANALYZE","reviewer":"S-REVIEW"}
  }
}
```
<!-- routing-policy:end -->

## Generated task view

<!-- gen:routing-tasks -->
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
<!-- /gen:routing-tasks -->

## Generated model profile view

Cells are logical tier labels. The concrete provider id behind each label lives in `harness/adapters/<runtime>/model-map.json`.

<!-- gen:routing-profiles -->
| Profile | Role | Tier | claude | codex | opencode |
|---|---|---|---|---|---|
| `B-BUILD` | child | Balanced | balanced | balanced | balanced |
| `B-GENERAL` | child | Balanced | balanced | balanced | balanced |
| `F-READ` | child | Fast | fast | fast | fast |
| `S-ANALYZE` | child | Strong | strong | strong | strong |
| `S-BUILD` | child | Strong | balanced | strong | balanced |
| `S-MAIN` | main | Strong main | strong-main | strong-main | strong-main |
| `S-REVIEW` | child | Strong | strong | strong | strong |
| `V-OPTIONAL` | child | Balanced | balanced | balanced | balanced |
<!-- /gen:routing-profiles -->

## Generated tool profile view

<!-- gen:routing-tools -->
| Tool profile | Capabilities | Write scope | Gate |
|---|---|---|---|
| `artifact-build` | matching-artifact-skill, render-tools | assigned artifact directory and scratch | render through matching skill |
| `artifact-inspect` | view, render, visual-inspection | scratch renders only | no production fixes; modality must be proven |
| `browser-observe` | navigate, inspect, capture | none | no form submission |
| `browser-operate` | named-click, named-type, upload, download | assigned browser session and approved download path | external writes require existing authorization |
| `code-edit` | read, edit, patch, bounded-build, bounded-test, named-shell | assigned code paths and scratch | no deploy or unrelated remediation |
| `connector-read` | named-list, named-get, named-search | none | no browser substitution while supported |
| `connector-write` | named-create, named-update, named-sync | assigned remote object and approved local sync path | authorization and post-write check required |
| `data-build` | data-skill, scripts, formulas, recalculation | assigned data artifact and scratch | styled-file safe path required |
| `deploy` | named-push, named-deploy, health-check, rollback | assigned deployment target | candidate, authorization, and rollback required |
| `dialogue-none` | main-loop-response | none | no delegated tool or external side effect |
| `document-draft` | read, edit, write | assigned document only | designated writer required |
| `evidence-web` | brain-first-read, web-search, web-fetch, citation-capture | none | source safety and citation rules apply |
| `git-local` | git-status, git-diff, assigned-local-git-operation | working tree, index, or local ref allowed by git-workflow | git-workflow retains authority |
| `image-generate` | image-generation, image-inspection | assigned asset only | matching skill rules apply |
| `index-check` | repo-read, deterministic-enumeration, dedupe | scratch only | reconcile counts before use |
| `multimodal-read` | tested-media-inspection, tested-extraction | scratch only | fail closed without modality support |
| `ops-check` | named-lint, named-test, named-render, named-check | scratch and cache only | actual output required |
| `orchestrate-control` | dispatch, wait, message, interrupt, controller-receipts | scratch: the run's workflow state directory only | no production artifact edits |
| `plan-readonly` | read, search, analysis, plan-result | none | no artifact edit, shell mutation, or external write |
| `repo-read` | read, glob, grep, bounded-local-search | none | access policy applies |
| `review-readonly` | read, inspect, bounded-test | scratch results only | independent reviewer; no production fixes |
| `structured-extract` | read, deterministic-parser, structured-result | scratch only | source remains unchanged |
<!-- /gen:routing-tools -->

## Mandatory sequence and guards

T2 requires three distinct contributions: delegated `plan.work-packages`, a substantive worker, and independent review of the current artifact. T3 also separates verification from strong review. Workers do not spawn workers. Run at most six children concurrently and lower that limit to the tested surface cap. One designated writer owns each shared artifact; an interrupted writer must be confirmed stopped before ownership moves.

Unknown substantive work defaults to T2, but an unknown task ID never resolves or launches. The strictest task, domain, destination, skill, and stakes floor wins. Numeric deliverables require at least a Balanced builder and Strong independent recomputation. Dense legal or financial reading uses S-ANALYZE. External writes require existing authorization, the matching skill, post-write fidelity verification, and S-REVIEW for bidirectional conflict.

Children resolve only to the `fast`, `balanced`, or `strong` labels on every runtime. The `strong-main` label is reserved for the main loop; a child may use it only when a per-run input records an explicit operator instruction, and the shipped `explicit_child_overrides` list is empty on all three runtimes. No runtime may inherit a model implicitly: every dispatch names its label, and the adapter resolves the label to a concrete id.

Every work package records task, planning, profile, resolved label and native model, effort, tool profile, skills, sources, permitted outputs, dependencies, acceptance criteria, retry budget, and result schema. Results record native actor identity where exposed, effective model, actual tools, findings, sources, artifact revision, checks, and unresolved issues. Missing observability is `unknown`, never pass.

Children bail and return on a miss, conflicting sources, ambiguity, unavailable capability, or discovery of a one-way door. The main loop alone may reclassify, upgrade, or substitute a predeclared equal-or-higher fallback. Any artifact change after verification invalidates the affected verification and review.

Hooks remain bounded, read-only, network-free, and stateless. They may report event-visible evidence or issue an advisory; the managed controller owns run state under the `orchestrate-control` write scope and gates completion. New denials enter as advisory and may move to an operator-overridable soft block only after false-positive and recovery tests; see [hook-design](hook-design.md).
