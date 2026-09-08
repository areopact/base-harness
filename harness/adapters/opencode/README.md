# OpenCode adapter (configured, identity boot experimental)

OpenCode reads the root `AGENTS.md` natively, discovers skills through `.opencode/skills`, loads slash commands from `.opencode/commands`, agents from `.opencode/agents`, and plugins from `.opencode/plugins`. This directory holds the canonical OpenCode-specific sources; everything under `.opencode/` and the root `opencode.json` is a bootstrap output.

## Files

| File | Materialized to | Mode | Purpose |
|---|---|---|---|
| `opencode.json` | `opencode.json` (repository root) | managed-copy | minimal posture: sharing off, credential files denied to the read tool, skills allowed |
| `plugins/` (`harness-bridge.js`) | `.opencode/plugins/` | link | pre-tool denial and identity boot through the shared dispatcher |
| `launch/` (`opencode-harness.sh`, `opencode-harness.ps1`) | (run directly) | none | launcher that makes skill selection enforcing |
| `agents/` | `.opencode/agents/` | link | generated routing roles (Markdown) written by `harness/tools/native_routing.py`; `.gitkeep` holds the directory |
| `model-map.json` | (read by tools) | none | tier label to `provider/model` id; four ids bound to one provider, `null` stays legal |
| `compatibility.json` | (read by the doctor) | none | version floor and the five evidence values |
| `schema.json` | (read by lint and tests) | none | draft-07 schema for the generated `opencode.json` |

Skills and commands are generated: `python harness/bootstrap/build_opencode_adapter.py` writes the selected skill tree under `harness/.selected/skills/` and the command files under `.opencode/commands/`; bootstrap links `.opencode/skills` to that tree. `--check` compares without writing.

## Why the launcher exists

OpenCode also searches the skill roots other runtimes use, so a bare `opencode` in this repository can see Codex wrappers and unselected skills. `opencode-harness.sh` (POSIX) and `opencode-harness.ps1` (Windows) under `launch/` read `per_skill.opencode.dst_dir` from `harness/bootstrap/junctions.json`, refuse to start when that tree is not materialized, set `OPENCODE_DISABLE_EXTERNAL_SKILLS=1`, and exec `opencode` from the repository root. The doctor fails when `.opencode/skills` does not resolve into the selected tree; that failure is how a bypass is caught. Direct invocation is unsupported until upstream duplicate-root behavior is proven deterministic.

## Hook delivery

| Event | Surface | Support |
|---|---|---|
| PreToolUse | `tool.execute.before` in the bridge plugin, calling `harness/hooks/codex-dispatch.sh --runtime opencode --event PreToolUse` (the `.ps1` sibling on Windows when `bash` is absent) | configured; deny throws, advisory has no model-visible surface |
| SessionStart | `experimental.chat.system.transform`, calling the dispatcher with `--event SessionStart` once per process | experimental; needs live proof |
| UserPromptSubmit, PostToolUse, Stop | none | contract fallback |

The bridge reads one JSON line from the dispatcher's stdout and throws an `Error` carrying `permissionDecisionReason` when `permissionDecision` is `"deny"`. A missing shell, missing dispatcher, non-zero exit, or unparseable output fails open. Tool names are normalized to the shared envelope (`bash` to `Bash`, `edit` to `Edit`, `task` to `Agent`, and so on) and OpenCode's camelCase arguments (`filePath`, `patchText`) are mirrored to the snake_case keys the hook library reads.

## Permission posture

`opencode.json` sets `share` to `disabled`, denies the read tool on `.env` files and private-key formats, and allows skills. It sets no `default_agent`, no model, and no `bash` or `edit` decisions; those stay with the runtime's defaults and the operator's own config. `schema.json` closes the top level and rejects underscore-prefixed keys at every level, so a comment key fails validation rather than being ignored.

## Model map and roles

`model-map.json` binds all four family labels to `provider/model` ids on one provider (`opencode-go`, transcribed from an OpenCode 1.18.29 model list) so that `python harness/tools/native_routing.py render` writes a complete role set, including the `workflow` primary, on a fresh clone. This is an editorial default, configured and not verified: OpenCode is provider-neutral and every provider needs its own configuration and consent, so rebind all four ids to the provider you actually use before relying on a generated role. A `null` id stays legal; the doctor prints that family as UNKNOWN and the renderer skips the roles that need it. After any change, regenerate the roles with the render command. Do not run `opencode debug config` inside an agent audit: the resolved view can interpolate environment values.

## Evidence boundary

`compatibility.json` ships with `offline_repository: unproven` and every other value `not-attempted`; values change only with a dated live run recorded in `docs/VERIFICATION.md`. `python harness/bootstrap/doctor_opencode.py --offline` checks file shape, the skill-root resolution, and the selection count; it never launches OpenCode, never prints resolved config, and never inspects an auth store.

Official references: [configuration](https://opencode.ai/docs/config/), [rules](https://opencode.ai/docs/rules/), [skills](https://opencode.ai/docs/skills/), [commands](https://opencode.ai/docs/commands/), [agents](https://opencode.ai/docs/agents/), [plugins](https://opencode.ai/docs/plugins/).
