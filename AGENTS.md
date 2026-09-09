# Agent Contract

This repository uses **base-harness**: one canonical set of skills, rules, hooks, and optional memory lanes under `harness/`, materialized by a bootstrap script into the paths Claude Code, OpenAI Codex CLI, and OpenCode each expect. This file is the contract every runtime loads. It is self-contained by design (Codex reads it natively with no imports and a 32 KiB cap). Detail lives in `harness/rules/`; read those files on demand, never assume they are already in context.

Verified-status note: see `docs/VERIFICATION.md` before assuming a mechanism works in your runtime. "Configured" means the file shape matches the runtime's documentation; "verified" means someone ran it and recorded the date, scope, and reproduction steps in that file. This contract does not claim more.

## Operating principles

**1. Plan first, sized to the task.** Before acting, tier the task:

- **T0 Act**: trivial and reversible (a lookup, a one-file mechanical edit, an answer). Do it.
- **T1 Frame**: small, clear, known pattern. State one line ("goal X, assuming Y, done = Z"), then proceed without waiting.
- **T2 Gate**: multi-file, novel approach, ambiguous requirements, an external write, or hard to reverse. Present a short plan (recommended shape, steps or files, the decisions that need the operator, what is out of scope) and wait for approval before executing. With the delegation module enabled (`harness/registry/structure.json` `delegation.mandatory`), T2 also means a delegated plan, a substantive worker, and an independent review; see `harness/rules/base-routing.md`.
- **T3** exists for architecture, strategy, one-way doors, and high stakes: a written design, independent analysis, separate verification, and strong review. Name it when you see it; do not silently treat it as T2.

If a T0 or T1 task reveals bigger stakes mid-flight, stop and re-tier. Full ladder: `harness/rules/base-routing.md`.

**2. State assumptions, touch only what the goal needs, verify before claiming done.** Say what you are assuming when the goal is ambiguous. Do not improve adjacent code, docs, or formatting while doing the task. Before saying "done", run the actual check (the test, the link, the hook) and report evidence, not intent. Detail: `harness/rules/agent-discipline.md`.

**3. Close the loop before ending a session.** If you created or modified files: verification run (evidence, not intent), work committed or explicitly parked, one-way-door decisions logged to the decisions lane when one is configured, durable learnings to the knowledge lane when one is configured, no new file left unlinked from anything. Checklist: `harness/rules/close-the-loop.md`. A Stop hook reminds you where the runtime supports hooks; elsewhere this text is the enforcement.

**4. Safety lines (never cross without explicit operator instruction):**

- No force-push to a protected branch. No history rewrites on shared branches. In `main-only` git mode (see `structure.json` `git.mode`), never create a branch or a worktree; in `branches` mode, follow the host's branch rules.
- No recursive delete outside the repository working tree; never at the filesystem root or home.
- No secrets in tracked files. Everything secret lives in gitignored local stores (`.env` and siblings). A committed secret is a compromised secret: rotate immediately. Never read a credential file into a session.
- No destructive database statements against anything but a local development instance.
- Never overwrite formatted spreadsheet files with a library that rewrites their styling (`harness/rules/openpyxl-hands-off.md`).

A PreToolUse hook denies the literal shapes of these where the runtime supports hooks; the git pre-commit hook in `.githooks/` is the floor that fires everywhere once bootstrap has set `core.hooksPath`. The guards are seatbelts, not locks: `SECURITY.md` lists what they do not catch.

**5. Memory-first through lanes.** Memory is personal; global truths become rules; shared project knowledge is docs. Before an external lookup, exhaust the configured lanes in `harness/registry/structure.json` (identity, knowledge, decisions, records, docs). A lane set to `null` is not configured: do not invent a folder for it, and say "no lane configured" instead of "no record". Where information goes: `harness/rules/memory-routing.md`. Lookup order: `harness/rules/memory-first.md`.

**6. Output quality.** Lead with the answer or the outcome. Cite the source of every fact that came from a file or a page. ASCII punctuation; no em-dashes or en-dashes. No preamble, no filler, no generic closing. Detail: `harness/rules/output-quality.md` and `harness/rules/cli-interaction.md`.

**7. Data classification.** Files may carry `access:` with one of `public`, `internal`, `confidential`, `restricted`, `secret`. The labels govern export (`harness/tools/export.py`) and, on Claude Code only, an optional read-deny hook for `secret`. On other runtimes they are documentation. Respect them as if they were enforced. Detail: `harness/rules/access-policy.md`.

## Skills

Reusable workflows live in `harness/skills/<name>/SKILL.md` (agentskills.io format). Only the skills selected in `harness/registry/selection.json` are materialized into your runtime's skill path; `python harness/tools/selector.py` changes the selection and re-materializes. The routing table `harness/skills/RESOLVER.md` is generated from each skill's `metadata.triggers` and carries a target and a fallback per row. When a request matches a resolver trigger, use that skill instead of improvising. When a skill declares `metadata.distribution: runtime-provided`, its capability may be absent on your runtime; the skill body names the fallback.

Invocation syntax: Claude Code uses `/skill-name`; Codex uses `$skill-name`; OpenCode uses generated `/skill-name` commands. Natural-language requests that match a trigger work on all three.

## Delegation (opt-in)

`harness/rules/base-routing.md` carries an authored routing policy: task IDs, model-family profiles, tool profiles, and planning floors. It is advisory unless `structure.json` sets `delegation.mandatory` to true, in which case T2 and above require the delegated sequence and the `workflow` skill executes plans. Runtime-native agent definitions under `harness/agents/` are generated from the policy; there are no personas.

## Per-runtime notes

- **Claude Code** (configured; see `docs/VERIFICATION.md` for the live-proof row): reads this contract through `CLAUDE.md` (`@AGENTS.md`), skills through per-skill links under `.claude/skills/`, rules through `.claude/rules/`, hooks registered in `.claude/settings.json`. `.claude/settings.local.json` is the per-user overlay and is ignored.
- **Codex CLI** (configured): reads `AGENTS.md` natively; skills through the generated `.agents/skills/` tree; hooks and project config load only after the project is trusted, and each hook definition is approved by hash, so an edited hook needs re-approval before it fires. Headless `codex exec` hangs on the trust prompt in an untrusted project and hangs on stdin unless stdin is closed (`< /dev/null`).
- **OpenCode** (configured; identity boot experimental): reads `AGENTS.md` natively; skills through `.opencode/skills` linked to the generated `harness/.selected/skills` tree; commands generated under `.opencode/commands`; hooks bridged by a plugin that calls the shared dispatcher.
- Fresh clone? Run `harness/bootstrap/bootstrap.ps1` (Windows) or `bootstrap.sh` (POSIX) once; verify anytime with `--check`; diagnose with the doctors or the `doctor` skill.

## Adopting into an existing repository

`python harness/tools/adopt.py <repo>` copies the kernel, leaves the host README untouched, merges host rules by reserved-name rule, and writes a `structure.json` with every lane unset. Configure lanes with `python harness/tools/init.py --lanes`, then bootstrap. The host block below this contract (`harness/CONTRACT.host.md`) is where the host describes its own layout; the template never edits it.

## Adding a skill

Owner-first: repair an existing skill before adding a mode, add a mode before adding a skill, add a skill only with a distinct intent, output, and routing boundary. Then: `harness/skills/<name>/SKILL.md` with the frontmatter in `harness/skills/README.md`, `python harness/tools/gen_manifest.py` to regenerate the resolver and catalogs, `python harness/tools/lint.py --strict`. No per-runtime registration; bootstrap materializes selected skills. Detail: `docs/ADDING-A-SKILL.md`.

# Host notes

<!-- This block is owned by the host repository. The template never edits it; adopt.py preserves it; bootstrap appends it after harness/CONTRACT.md when rendering AGENTS.md. Describe your repository's layout, lanes, conventions, and anything an agent must know that the template cannot. Keep AGENTS.md under 32 KiB in total (the lint checks). -->

No host-specific notes yet. Run `python harness/tools/init.py --lanes` to configure memory lanes, then describe your layout here.
