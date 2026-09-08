---
name: doctor
description: >
  Harness diagnostic from inside a session: run the three offline doctors and
  report per runtime whether the harness is wired, without ever turning an
  unproven layer green. WHEN: user invokes /doctor, says "test the harness",
  "is the harness wired correctly", "run the doctors", "diagnose the harness",
  or "check bootstrap state"; after a fresh clone, a bootstrap run, or a change
  to an adapter, the registry, or the skill selection. WHEN NOT: proving that a
  code change works (/verify); committing (/commit); repairing a hook or a
  skill (edit its source, then run bootstrap and this skill again).
metadata:
  packs: [maintain]
  triggers:
    - "test the harness"
    - "is the harness wired correctly"
    - "run the doctors"
    - "diagnose the harness"
    - "check bootstrap state"
  requires: []
  distribution: native
  status: spec-only
  license: MIT
  notice: null
---

# doctor

A diagnostic, not a greeting. When invoked, actually run the checks and report what they print, so a broken bootstrap is visible rather than hidden. Everything here is offline and dependency-free: file reads and local git config reads only, no network, no installs, no regeneration.

## 1. Pre-bootstrap state (before reading any doctor output)

State three facts from your own vantage point:

1. **Which runtime.** Name the agent CLI the session is running in (Claude Code, Codex CLI, or OpenCode).
2. **Which skills path this file was read through.** `.claude/skills` on Claude Code, `.agents/skills` on Codex, `.opencode/skills` on OpenCode. If you read it straight from `harness/skills/doctor/SKILL.md` and none of those paths holds a `doctor` entry, say so: the skill is on disk as source only and nothing is materialized.
3. **Whether the repository looks bootstrapped at all.** `CLAUDE.md`, `.agents/`, and `.opencode/commands` are tracked in every clone, so their presence alone does not prove bootstrap ran; a fresh, un-bootstrapped clone instead has no `.claude/skills` link (or the runtime's own materialized skills path) and no `core.hooksPath` set. Check `git config core.hooksPath` and for at least one entry under the skills path for this runtime; the doctors then report the absence rather than failing to run.

If the repository is not bootstrapped, print the bootstrap command for both platforms and still run the doctors (their output is the evidence):

```
bash harness/bootstrap/bootstrap.sh
powershell -NoProfile -ExecutionPolicy Bypass -File harness/bootstrap/bootstrap.ps1
```

## 2. Run all three doctors

Run each from the repository root and capture the full output:

```
bash harness/bootstrap/doctor.sh                       # Claude Code
python harness/bootstrap/doctor_codex.py --offline     # Codex CLI
python harness/bootstrap/doctor_opencode.py --offline  # OpenCode
```

On Windows without a POSIX shell, the Claude Code doctor is `powershell -NoProfile -ExecutionPolicy Bypass -File harness/bootstrap/doctor.ps1`; it delegates to the same `doctor_claude.py` and prints the same lines. The Codex and OpenCode doctors are Python entry points on every platform. Run all three even when the session is in only one runtime: the report is per runtime, and a host that has not bootstrapped the other two should see that stated, not omitted.

## 3. Report in the doctors' own vocabulary

Every doctor prints one line per check as `[<layer>] <state> <message>`, an `Evidence tiers:` block with one roll-up line per layer, and a final `Result:` line. The layers, in order, are `configured`, `loaded`, `trusted`, `fired`, `enforced`, `outcome-proven`; the states are `OK`, `WARN`, `FAIL`, `UNKNOWN`; the roll-up per layer is `PASS`, `PARTIAL`, `UNKNOWN`, or `FAIL`.

Rules for the summary:

- Quote the `Evidence tiers:` roll-up per layer as the doctor printed it. **Never turn an `UNKNOWN` layer green.** Offline doctors populate only `configured`; `loaded`, `trusted`, `fired`, `enforced`, and `outcome-proven` stay `UNKNOWN` until a live run is recorded in `docs/VERIFICATION.md`. Report them as `UNKNOWN` together with the doctor's stated reason (for example `hook execution not observed offline`), not as pass, not as "fine".
- Quote every `FAIL` and `WARN` line verbatim with its remedy text; the doctors name a remedy per line.
- Quote the `Result:` line per runtime verbatim: `Result: repository PASS|FAIL; runtime evidence PROVEN|INCOMPLETE; n warning(s), m failure(s)`.
- The exit code is 0 only when the repository layer passes; report a non-zero exit as a failure, never as "the doctor did not apply".

## 4. Output shape

One compact block: one pre-bootstrap line, one line per runtime, then the exact command to fix whatever is not OK.

```
harness diagnostic:
  session:   <runtime> via <skills path> | source only (nothing materialized)
  bootstrap: CLAUDE.md present, skills materialized | NOT BOOTSTRAPPED
  claude:    repository PASS|FAIL; configured <roll-up>; other layers UNKNOWN (<reason>); n warn, m fail
  codex:     repository PASS|FAIL; configured <roll-up>; other layers UNKNOWN (<reason>); n warn, m fail
  opencode:  repository PASS|FAIL; configured <roll-up>; other layers UNKNOWN (<reason>); n warn, m fail
  fix:       <exact command> | none needed
```

Below the block, list the quoted `FAIL` and `WARN` lines per runtime, if any.

## 5. Fix and re-run

If any line is not OK, run the bootstrap for the platform, then run `/doctor` again and compare:

```
bash harness/bootstrap/bootstrap.sh && bash harness/bootstrap/bootstrap.sh --check
powershell -NoProfile -ExecutionPolicy Bypass -File harness/bootstrap/bootstrap.ps1 -Check
```

`--check` exits 0 only when the materialized tree matches its sources byte for byte. A `FAIL` that survives a bootstrap is a source problem (a wrong adapter file, a registry mismatch, a real directory sitting where a link belongs); name the failing line and stop rather than editing generated output by hand. The recovery sweep in `harness/bootstrap/README.md` covers the remaining cases.
