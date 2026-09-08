---
paths:
  - "harness/hooks/**"
---

# Hook Design

Every hook is bounded, read-only, network-free, and stateless; it emits one JSON payload or silence, exits 0, and classifies itself on the enforcement ladder. A new hook exists only where a supported runtime has a native decision point for its event. The I/O envelope, exit-code contract, and per-runtime delivery are specified in `harness/hooks/README.md`; this page is the design law those mechanics implement.

## Why

Hooks run on every turn, in every runtime, before the model sees the result. A hook that is slow taxes every interaction; a hook that writes state makes two sessions disagree about the world; a hook that reaches the network makes a local tool depend on a remote one; a hook that raises turns a safety aid into an outage. A guard that blocks too eagerly is bypassed, and once one guard is routinely bypassed the whole enforcement layer loses trust. The ladder exists so that a check earns its rung with evidence rather than intent.

## Application

### Core properties

- **Idempotent.** Running a hook twice produces the same result as running it once.
- **Defensive.** Every hook wraps its logic in a narrow error boundary. Unexpected errors fail open with at most a terse stderr diagnostic; tested safety denials use the runtime's native decision payload. Exit 0 always: the decision lives in the JSON, never in the exit code, and a non-zero exit is a malfunction that the doctors report as a failure, not as enforcement.
- **Stable terse stdout.** One valid JSON payload or silence. Never incidental multi-line noise.
- **No network, no state.** A hook never pulls, fetches, writes caches, appends logs, mutates environment variables, or accumulates session state. Bootstrap, scheduled jobs, and explicit tools own refreshes; a debug flag may emit one timing line to stderr and nothing to disk.
- **Bilingual wrappers.** Every hook has a `.ps1` and a `.sh` wrapper; the shared logic lives in `harness/hooks/lib/` and the wrappers only locate Python and pass stdin through. Wrappers derive the repository root from their own location, never from the working directory, because Stop, PreToolUse, and PostToolUse inherit whatever directory the turn was in.
- **Schema-tolerant stdin.** Events and runtimes send different JSON shapes. Parse only the fields you need, accept the documented aliases, and treat unparseable or empty stdin as silence.
- **Bounded context.** An advisory that injects model-visible text is capped at the runtime's declared context limit in `harness/registry/runtimes.json` and says so when it truncates.

### Speed budgets

Measure hook logic separately from interpreter and shell startup. Budgets are regression tripwires, not performance targets: a non-safety hook that cannot finish within its budget degrades to silence; a safety hook keeps its decision path small enough to finish reliably. A check too slow for its budget is redesigned, not promoted.

### Enforcement ladder

Three rungs; every hook and every future check is explicitly classified:

| Rung | Behavior | Reserved for |
|---|---|---|
| advisory | observe and nudge; model-visible context; always allows | anything recoverable next turn |
| soft-block | native deny decision with reason; the operator can override by changing a declared state | operator-set boundaries |
| hard-block | native deny decision with reason; no override switch | the irreversible: secrets exposure, force-push to a protected branch, mass delete, destructive spreadsheet writes |

- New checks enter at advisory. Promotion moves one rung at a time, and only after the check has shown a near-zero false-positive rate and a demonstrated recovery path (a fixture that proves a legitimate neighbor passes and a blocked action can be redone correctly).
- Hard-block is reserved for actions that cannot be undone next turn. If a mistake is recoverable, the hook's job is to make it visible, not impossible.
- Deny is valid on PreToolUse only. A deny reason names the hook, its rung, the reason, a hash of the offending command, and one recovery sentence.

### Degradation ladder

Each event declares, per runtime, the rung at which it actually fires: a native hook, the contract text, or the git pre-commit floor. The doctors print that rung and never report a layer green without evidence. A hook that a runtime cannot deliver is documented as such in `harness/registry/runtimes.json`; the contract carries the rule in prose so the behavior still binds.

### Adding a hook

A new hook needs, in order: a supported runtime-native decision point for its event; a shared library module under `harness/hooks/lib/` with fixtures under `harness/hooks/tests/` covering the failure it catches, a legitimate neighbor it must allow, and recovery; both wrappers; registration in the adapters; a row in `runtimes.json` per runtime; and a rung. Owner-first applies: repair an existing hook before adding a mode, add a mode before adding a hook.
