# Claude Code adapter

Claude Code reads the shared contract through the root `CLAUDE.md` (`@AGENTS.md`), selected skills through one link per skill under `.claude/skills/`, rules through `.claude/rules/`, and hooks through the project settings file. This directory holds the canonical sources for the Claude-specific pieces; the paths under `.claude/` are bootstrap outputs, never the editing authority.

## Files

| File | Materialized to | Mode | Purpose |
|---|---|---|---|
| `settings.base.json` | `.claude/settings.json` | managed-copy | minimal permission posture plus the hook registrations |
| `model-map.json` | (read by tools, not materialized) | none | tier label to public model alias; permission classes for generated roles |
| `schema.json` | (read by lint and tests) | none | draft-07 schema the generated settings file must satisfy |
| `agents/` | `.claude/agents/` | link | generated routing roles written by `harness/tools/native_routing.py`; `.gitkeep` holds the directory |

## Settings materialization

Bootstrap copies `settings.base.json` byte for byte to `.claude/settings.json`. Editing the copy never changes the source, and `bootstrap --check` reports the drift. Change the source, rerun bootstrap.

`.claude/settings.local.json` is the per-user overlay. Claude Code merges it over the project settings; this repository never ships it, `.gitignore` excludes it, and CI ignores it. Put operator-only allowances there (a wider `permissions.allow`, an MCP server, a model choice), never in `settings.base.json`.

## Permission posture

The shipped posture is minimal: `permissions.allow` lists only the read-shaped tools (`Read`, `Glob`, `Grep`), `permissions.deny` denies the credential shapes in `.gitignore`'s secrets block (dotted environment-file variants, `.envrc`, and `*.pem`/`*.key`/`*.p12`/`*.pfx`) since deny outranks allow, and every other tool goes through the runtime's own prompt. The keys that switch off prompting are forbidden at the top level and inside `permissions`; `schema.json` lists them in its `not` clause and `harness/adapters/tests/test_permission_posture.py` asserts the same list, so a posture regression fails both schema validation and the test suite.

## Hook registrations

Every command string has the shape `bash "${CLAUDE_PROJECT_DIR}/harness/hooks/<event-dir>/<hook-name>.sh"`. The variable is quoted because an unquoted backslash path collapses on Windows, and the path uses forward slashes because Claude Code hands the value to `bash`. The registered set mirrors `harness/registry/runtimes.json` `hook_events`:

| Event | Matcher | Hooks |
|---|---|---|
| SessionStart | (all) | `load-identity`, `pre-bootstrap-detector` |
| PreToolUse | `WebSearch\|WebFetch` | `memory-first` |
| PreToolUse | `Bash` | `dangerous-ops-guard`, `openpyxl-guard` |
| PreToolUse | `Agent\|Workflow` | `delegation-guard` |
| PreToolUse | `Write\|Edit\|NotebookEdit` | `write-deny` (silent until `write_deny.globs` is set in `structure.json`) |
| PostToolUse | `Write\|Edit` | `frontmatter-guard`, `prose-lint` |
| PostToolUse | `Agent\|Workflow` | `delegation-guard` |
| Stop | (all) | `close-the-loop` |

`read-deny` (the optional `secret`-tier read hook) is deliberately not registered. Enabling it is an operator choice made in `settings.local.json`.

Hook exit codes follow the shared envelope in `harness/hooks/README.md`: exit 0 for silence, advisory, and deny (the decision lives in the JSON), any non-zero exit is a malfunction. The doctor reports a non-zero exit as FAIL, never as "enforced".

## Model map

`model-map.json` carries the four family keys (`fast`, `balanced`, `strong`, `strong-main`) mapped to the public Claude Code model aliases. The map never chooses an allocation; `harness/rules/base-routing.md` does. A `null` value means unresolved and the doctor prints it as UNKNOWN. The interactive session's model stays whatever the operator configured.

## Syntax notes

- Skills: `/skill-name`, or natural language matching a resolver trigger.
- Sub-agents: Markdown files with YAML frontmatter under `agents/` (name, description, tools, model); generated, do not hand-edit.
- Verify: `bash harness/bootstrap/doctor.sh` (or `doctor.ps1`) prints the six evidence layers for this runtime.
