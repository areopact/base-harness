# Codex CLI adapter (configured)

Codex reads the root `AGENTS.md` natively (no imports, 32 KiB cap), discovers skills through the generated `.agents/skills/` tree, and loads project configuration and hooks only for a trusted project. This directory holds the canonical Codex-specific sources; everything under `.codex/` and `.agents/` is a bootstrap output.

## Files

| File | Materialized to | Mode | Purpose |
|---|---|---|---|
| `config.toml` | `.codex/config.toml` | managed-copy | environment, hooks feature flag, agent concurrency; no permission controls |
| `hooks.json` | `.codex/hooks.json` | managed-copy | one dispatcher entry per hook event |
| `rules/` (`default.rules`) | `.codex/rules/` | link | Starlark command rules (broad staging denied, force-push denied, hard reset prompts) |
| `agents/` | `.codex/agents/` | link | generated routing roles (TOML) written by `harness/tools/native_routing.py`; `.gitkeep` holds the directory |
| `model-map.json` | (read by tools) | none | tier label to provider id; four ids bound, `null` stays legal |
| `compatibility.json` | (read by the doctor) | none | version floor and the five evidence values |
| `schema.json` | (read by lint and tests) | none | draft-07 schema for the generated hooks file plus the closed key lists for `config.toml` |

Generated skill wrappers under `.agents/skills/<name>/` come from `python harness/bootstrap/build_codex_adapter.py`; bootstrap runs it and `--check` compares the exact file set without writing.

## Trust before anything fires

Codex ignores `.codex/config.toml` and `.codex/hooks.json` in an untrusted project, and it approves each hook definition by the hash of its JSON, so editing a hook entry requires re-approval before that hook fires again. Trust the project interactively on first run, or add a project-scoped table to `~/.codex/config.toml`. The table header is required; a bare top-level `trust_level` does nothing:

```toml
[projects."/abs/path/to/your/repo"]
trust_level = "trusted"
```

Headless runs have a second trap. `codex exec "<prompt>"` reads stdin and hangs on "Reading additional input from stdin" unless stdin is closed:

```sh
codex exec "run the doctor skill" < /dev/null
```

In cmd use `< NUL`; in PowerShell pipe `$null |` into the command. An untrusted project hangs earlier, on the interactive trust prompt, which is fatal in scripts and CI.

## Permission posture

`config.toml` declares environment, hooks, and agents only. It never sets `approval_policy`, `approvals_reviewer`, `sandbox_mode`, `sandbox_workspace_write`, `default_permissions`, or `permissions`; those belong to the operator's global Codex configuration and the effective session. `schema.json` lists the six forbidden keys and the closed set of allowed keys, `doctor_codex.py` asserts their absence, and `harness/adapters/tests/test_permission_posture.py` asserts it again in CI. Bootstrap never grants trust and never touches `~/.codex/`.

## Hook delivery

All five events route through one dispatcher: `bash harness/hooks/codex-dispatch.sh --runtime codex --event <Event>` on POSIX, and the `.ps1` sibling with `-Runtime codex -Event <Event>` on Windows via `commandWindows`. The repository root is resolved with `git rev-parse --show-toplevel` at hook time, so no absolute path lives in the file. The dispatcher reads the shared stdin envelope, runs every implementation registered for the event in `harness/registry/runtimes.json`, prints at most one JSON object, and always exits 0; a deny is `permissionDecision: "deny"` inside that JSON. `additionalContextLimit` values are the per-event caps the dispatcher truncates to.

Hosted web search runs outside the local hook path. The `memory-first` hook can intercept local web tools when Codex exposes them as function calls; for hosted search the contract text is the enforcement, and no doctor claims otherwise.

## Skills

Invoke with `$skill-name` or natural language matching a resolver trigger. Every generated wrapper points back to the canonical `harness/skills/<name>/SKILL.md`; the wrapper carries a compact description that preserves the `WHEN:` trigger text for implicit routing. Only selected skills are generated; the doctor counts them from the `.agents/skills/` tree and reconciles to `harness/registry/selection.json`.

## Model map and roles

`model-map.json` binds all four family labels to provider ids transcribed from a codex-cli 0.153.4 model picker, so `python harness/tools/native_routing.py render` writes a complete role set into `agents/` on a fresh clone. The ids are configured, not verified: provider ids change without notice, so confirm them against your own installation (`codex --version` and the model picker) and rebind as needed. A `null` id stays legal; the doctor prints that family as UNKNOWN, the renderer skips the roles that need it, and nothing defaults silently. After any change, regenerate the roles with the render command. Allocation policy stays in `harness/rules/base-routing.md`; this map only translates.

## Evidence boundary

`compatibility.json` ships with `offline_repository: unproven` and every other evidence value `not-attempted`. Values change only when someone runs the corresponding check in a clone and records the date: the closed vocabulary is `passed`, `unproven`, `not-attempted`, or a sentence beginning `passed:` followed by a date no later than `observed_at`. `python harness/bootstrap/doctor_codex.py --offline` checks file shape only; it never launches Codex.
