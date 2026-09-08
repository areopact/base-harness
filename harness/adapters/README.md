# harness/adapters/

An adapter maps the tool-neutral harness (contract, rules, skills, hooks, routing policy) into one runtime's native configuration. Shared behavior stays in `harness/CONTRACT.md`, `harness/rules/`, `harness/skills/`, and `harness/hooks/`; provider syntax, loader formats, model ids, and capability limits live here. Runtime paths (`.claude/`, `.codex/`, `.agents/`, `.opencode/`, the root `opencode.json`) are bootstrap outputs: edit the adapter source, then run bootstrap.

## The four materialization modes

Every adapter file that reaches a runtime path is declared in `harness/bootstrap/junctions.json` and mirrored in `harness/registry/runtimes.json` with one of exactly four modes:

| Mode | Meaning |
|---|---|
| `link` | directory junction (Windows) or symlink (POSIX) from the runtime path to the source; `--copy` renders it as a recursive copy |
| `managed-copy` | independent byte-exact file copy; never a hardlink; editing the destination never mutates the source, and `bootstrap --check` reports the drift |
| `generated` | the destination tree is produced by a named generator (`build_codex_adapter.py`, `build_opencode_adapter.py`) from the source tree |
| `contract-render` | the destination is rendered by `contract_files.py` from `harness/CONTRACT.md` plus `harness/CONTRACT.host.md` |

A junctions entry without a matching runtimes.json row, or the reverse, is a lint error.

## Adapters translate, they never allocate

`harness/rules/base-routing.md` is the only authored source of task ids, model-family profiles, and tool profiles. Each adapter's `model-map.json` binds the four family keys (`fast`, `balanced`, `strong`, `strong-main`) to that runtime's provider ids and names its permission classes. A `null` id is legal: the doctor reports it as UNKNOWN and nothing substitutes a default. Generated roles under each adapter's `agents/` come from `harness/tools/native_routing.py`; they carry no persona.

## Per-runtime status

Mirror of `harness/registry/runtimes.json` at authoring time; that file is the authority and the doctors print from it.

| Runtime | Directory | Status | Hook delivery | Skill materialization |
|---|---|---|---|---|
| Claude Code | `claude/` | configured; live proof recorded only in `docs/VERIFICATION.md` | individual wrappers registered in the project settings | one link per selected skill |
| Codex CLI | `codex/` | configured-beta; trust and per-hook hash approval required before any hook fires | one dispatcher entry per event | generated wrappers for selected skills |
| OpenCode | `opencode/` | configured-alpha; identity boot experimental | plugin bridge for PreToolUse and SessionStart; other events fall back to contract text | generated selected tree linked as the skill root, enforced by the launcher |

No runtime is reported green on a layer without evidence. The vocabulary is `configured`, `loaded`, `trusted`, `fired`, `enforced`, `outcome-proven`; a layer with no entry prints UNKNOWN.

## Contents

- `claude/`: `settings.base.json` (minimal posture and hook registrations), `model-map.json`, `schema.json`, `agents/`.
- `codex/`: `config.toml`, `hooks.json`, `rules/` (`default.rules`), `model-map.json`, `compatibility.json`, `schema.json`, `agents/`.
- `opencode/`: `opencode.json`, `plugins/` (`harness-bridge.js`), `launch/` (`opencode-harness.sh` and `opencode-harness.ps1`), `model-map.json`, `compatibility.json`, `schema.json`, `agents/`.
- `model_map.py`: the stdlib loader that marks unresolved families as UNKNOWN; doctors and tests import it.
- `tests/`: permission posture, schema validation, hook registrations, model maps, compatibility records, private-vocabulary scan.

Add an adapter only when a runtime cannot consume the canonical format directly. Never duplicate skill procedures or behavioral rules into an adapter.
