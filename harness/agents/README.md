# harness/agents/

Runtime agent roles are generated, not authored. `harness/tools/native_routing.py` reads the compiled routing policy (`python harness/tools/routing_policy.py compile`, sourced from `harness/rules/base-routing.md`) together with each adapter's `model-map.json` and writes one role per task id and phase into the adapter's `agents/` directory. This directory documents that mechanism; it holds no role files.

## What a role carries

Name, scope (the task id and phase, execute or review), tools (from the tool profile), permission class (`read-only`, `edit`, or `shell`), and model family (`fast`, `balanced`, `strong`, or `strong-main`) translated through the adapter's model map. Nothing else. There is no persona: no character name, no voice, no backstory. A role is an isolated context with bounded tools; the skill being run supplies the procedure and the routing policy supplies the allocation.

## Where roles land

| Runtime | Generated into | Format | Materialized to |
|---|---|---|---|
| Claude Code | `harness/adapters/claude/agents/` | Markdown with YAML frontmatter | `.claude/agents/` (link) |
| Codex CLI | `harness/adapters/codex/agents/` | TOML | `.codex/agents/` (link) |
| OpenCode | `harness/adapters/opencode/agents/` | Markdown with YAML frontmatter | `.opencode/agents/` (link) |

Each `agents/` directory ships with a `.gitkeep` so the link target exists before the first render. A family whose provider id is `null` in the model map cannot be rendered for that runtime; the renderer reports it and the doctor prints UNKNOWN rather than inventing an id.

## Regenerate, never hand-edit

`python harness/tools/native_routing.py render` writes the roles; `python harness/tools/native_routing.py render --check` compares the tree to what the policy would produce and exits non-zero on any difference. A hand edit to a generated role is drift, caught by that check in CI and in `python harness/tools/lint.py --strict`. To change a role, change the policy in `harness/rules/base-routing.md` or the binding in the adapter's `model-map.json`, then render.

## Delegation is opt-in

The routing policy is advisory unless `harness/registry/structure.json` sets `delegation.mandatory` to `true`. With it on, T2 work requires a delegated plan, a substantive worker, and an independent review, and the `workflow` skill executes plans through these roles. With it off, the roles still exist for anyone who invokes them directly. Detail: `docs/ROUTING-TASKS.md`.
