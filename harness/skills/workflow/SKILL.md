---
name: workflow
description: >
  Run a managed T2 or T3 workflow with delegated planning, bounded native workers, artifact-bound verification, and independent review, fronting the controller in harness/tools/workflow.py. WHEN: user invokes /workflow, says "execute this plan", "run the delegated workflow", "run this as a managed multi-step job", or "resume the workflow run", or substantive complex work is classified T2 or T3 by base-routing. WHEN NOT: T0 or T1 requests (act directly); reviewing an artifact without executing anything (use /review); exploring an approach before there is a plan (use /brainstorm).
metadata:
  packs: [delegation]
  triggers:
    - "execute this plan"
    - "run the delegated workflow"
    - "run this as a managed multi-step job"
    - "resume the workflow run"
  requires: [delegated-execution]
  distribution: runtime-provided
  status: spec-only
  license: MIT
  notice: null
---

# Managed workflow

Use the canonical task IDs and floors in `harness/rules/base-routing.md`. Load the operating skill appropriate to each artifact or external system before preparing its package. This skill supplies orchestration; it does not replace document, spreadsheet, presentation, connector, browser, git, or deployment rules.

## Capability and fallback

This skill declares `delegated-execution` (`harness/registry/capabilities.json`): a runtime facility that can launch, await, and receive receipts from bounded native worker processes on the controller's behalf. Where the facility is absent, the skill does not fake a run. It reports the gate (which capability is missing and on which runtime), offers to execute the packages sequentially in the main loop, and labels any result produced that way as `undelegated`: no planner, verifier, or reviewer receipt exists, so the result never counts as managed-workflow completion.

A runtime's own bounded helper (a saved command, a native sub-agent, a background task) is never managed-workflow completion evidence on its own. Only a run the controller launched and awaited produces receipts.

## Opt-in gate

The controller is opt-in. It exits 2 with a one-line reason when `harness/registry/structure.json` sets `delegation.mandatory` to `false` and `--opt-in` is absent. Pass `--opt-in` for a single run, or set `delegation.mandatory` to `true` in `structure.json` to make managed execution the default on this host. Do not work around the gate by editing run state.

## Prepare the spec

Prepare a JSON spec under `.tmp/` containing the runtime, T2 or T3 depth, original requirements, acceptance criteria, source-evidence references, explicit artifact files, dependency-aware worker packages, and main-loop ratification. Use `floor_flags` on a package when numeric, dense legal or financial, external-write, bidirectional-conflict, or high-stakes floors apply. Record an explicit child-model override only when the user actually instructed it for that run.

For complex read-only analysis, assign one text `result_artifact`; the controller captures the native worker's final response to that file atomically. The controller executes dependency-ready packages serially. The policy concurrency value remains a capacity ceiling, not claimed utilization.

## Commands

```text
python harness/tools/workflow.py [--opt-in] plan <spec.json>
python harness/tools/workflow.py [--opt-in] start <spec.json> [--run-id ID]
python harness/tools/workflow.py [--opt-in] run|resume|status|cancel <run-id>
```

`plan` validates the spec and prints the task graph; `start` seeds the run and returns its ID. The controller inserts `plan.work-packages`, the required verification stage, and `review.adversarial`; do not add or impersonate those packages in the spec. Run the returned ID with `run`, then use `status`, `resume`, or `cancel` on that same ID. `/workflow`, `$workflow`, and the generated OpenCode workflow command all follow this controller procedure.

## Modes and telemetry

Use managed mode when native execution is proven but a runtime does not expose effective-model or permission telemetry. Report those fields as `unknown`, never as pass. Use strict mode only when completion must fail on any such evidence gap.

## Integrity rules

- Never edit workflow state or import receipts to manufacture completion. A worker or reviewer result counts only when the controller directly launched and awaited the native process.
- One designated writer owns each shared artifact. An interrupted writer retains ownership until the controller confirms its process stopped.
- A changed artifact invalidates its verification and review; both rerun before the run can complete.
- If a runtime, model, tool, permission, artifact, or authorization is unsupported, leave the run blocked and report the exact gate.
