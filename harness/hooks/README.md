# Hooks

Event-driven checks shared by Claude Code, Codex, and the supported part of
OpenCode. The Python modules under `harness/hooks/lib/` are canonical; the
`.sh` and `.ps1` files beside each event directory are thin wrappers that find
an interpreter, pass stdin through, and exit 0. Codex and OpenCode reach the
same modules through one dispatcher per event (`codex-dispatch.{sh,ps1}` and
`harness/hooks/lib/dispatch.py`).

Hooks are bounded, read-only, network-free, and stateless. A hook reads its
stdin envelope, a bounded set of repository files, and the registries under
`harness/registry/`; it never pulls, fetches, writes a cache, appends a log,
or mutates the tree. The single exception is the opt-in tracer: when the
environment variable `HARNESS_HOOK_DEBUG_DIR` names a directory,
`harness/hooks/lib/_debug.py` appends one line per invocation to
`hooks-debug.log` there. Without the variable nothing is written anywhere
(`tests/test_no_state.py` proves it).

## I/O envelope

| Direction | Shape |
|---|---|
| stdin | One JSON object: `hook_event_name`, `tool_name`, `tool_input`, `cwd`, `session_id`, `turn_id`. The reader accepts `input` as an alias for `tool_input` and maps `shell_command` to `Bash` and `agent`, `Task`, `spawn_agent` to `Agent`. Empty, unparseable, or non-object stdin is silence; nothing ever raises. |
| stdout, silence | Nothing printed. |
| stdout, advisory | `{"hookSpecificOutput": {"hookEventName": "<event>", "additionalContext": "<text>"}}`, or `{"systemMessage": "<text>"}` when the payload is a Claude `Write`/`Edit` shape or the event is `Stop`. `hook_io.advisory_for` picks. |
| stdout, deny | `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<hook> [<tier>]: <reason>. [command-sha256:<hex>] <recovery>"}}`. Valid on `PreToolUse` only. |
| exit code | Always 0 for silence, advisory, and deny; the decision lives in the JSON, never in the code. 0 when Python is missing or the lib file is absent (fail open). 2 is reserved and never emitted. Any other non-zero exit is a malfunction, never a decision; a doctor reports it as FAIL, not as "enforced". |

The dispatcher caps `additionalContext` at the `context_limit` declared for
the runtime and event in `harness/registry/runtimes.json` and appends
`[hook context capped; read the named source files on demand]`. `SessionStart`
is budgeted per lane (identity 40, knowledge 20, journal 10, other 5) with a
footer naming trimmed and omitted sources; it is never tail-truncated.

## Event and hook matrix

| Event | Matcher (Claude) | Wrapper | Module | Rung | Decision |
|---|---|---|---|---|---|
| `SessionStart` | (none) | `session-start/load-identity` | `load_identity` | context injector | identity lane, bounded per runtime |
| `SessionStart` | (none) | `session-start/pre-bootstrap-detector` | `pre_bootstrap_detector` | advisory | bootstrap command when a destination is missing |
| `PreToolUse` | `WebSearch\|WebFetch` | `pre-tool-use/memory-first` | `memory_first` | advisory | local filename matches in the knowledge, decisions, docs, records lanes |
| `PreToolUse` | `Bash` | `pre-tool-use/dangerous-ops-guard` | `dangerous_ops_guard` | hard-block | deny: system-destroy, git-protected-branch, git-history-rewrite, data-destroy, secret-exposure |
| `PreToolUse` | `Bash` | `pre-tool-use/openpyxl-guard` | `openpyxl_guard` | hard-block | deny: openpyxl write to an existing workbook |
| `PreToolUse` | `Agent\|Workflow` | `pre-tool-use/delegation-guard` | `delegation_guard` | advisory | only when `structure.json` `delegation.mandatory` is true |
| `PreToolUse` | `Read` (Claude only, not registered by default) | `pre-tool-use/read-deny` | `read_deny` | hard-block, shipped off | deny when the file carries `access: secret`; active only with `HARNESS_READ_DENY=1` |
| `PostToolUse` | `Write\|Edit` | `post-tool-use/frontmatter-guard` | `frontmatter_guard` | advisory | tier label, collaborator list, closed block, ISO dates under any lane |
| `PostToolUse` | `Write\|Edit` | `post-tool-use/prose-lint` | `prose_lint` | advisory | mechanical writing tells in files matched by `outbound_globs` (empty by default) |
| `PostToolUse` | `Agent\|Workflow` | `post-tool-use/delegation-guard` | `delegation_guard` | advisory | as above, result-side |
| `Stop` | (none) | `stop/close-the-loop` | `close_the_loop` | advisory | lanes with uncommitted changes and no decisions or journal entry |

Codex routes every event through `codex-dispatch.{sh,ps1} --runtime codex
--event <Event>`; `harness/hooks/lib/dispatch.py` selects the modules above from the
payload's tool name and applies first-deny precedence. OpenCode's plugin
bridge calls the same dispatcher with `--runtime opencode` for `PreToolUse`
(throws on a deny) and `SessionStart` (system prompt transform); the other
events have no OpenCode surface and fall to the contract text.

Every host fact reaches a hook through `harness/registry/structure.json`
(`hook_io.load_structure`, `hook_io.lane_paths`): lane paths, outbound
globs, and the delegation flag. No lib hardcodes a lane path
(`tests/test_structure_parameterization.py`).

## Degradation ladder

Each event on each runtime sits on one rung, declared in
`harness/registry/runtimes.json` `hook_events.<Event>.runtimes.<runtime>.rung`
and printed by the doctors:

| Rung | Meaning |
|---|---|
| `native-hook` | The runtime invokes the wrapper or dispatcher and consumes the JSON decision. |
| `contract-text` | The runtime has no hook surface for the event; the rule lives in `AGENTS.md` and the model is asked to honor it. |
| `git-floor` | Neither a hook nor the contract applies; only `.githooks/pre-commit` stands between the change and the repository. |

A guard on the `native-hook` rung is still a seatbelt: it models literal
shapes and is bypassable by shapes it does not model. `SECURITY.md` names the
classes with their fixtures.

## Enforcement rungs and how to add a hook

New checks enter at **advisory** and move one rung at a time, only after
running long enough to show a near-zero false-positive rate. **Hard-block** is
reserved for actions that cannot be undone next turn. To add a hook:

1. Put the behavior in `harness/hooks/lib/<name>.py` with a `decide(data, ...)` function
   that returns the JSON string or `None`, and a `main()` that reads stdin,
   prints at most one line, and exits 0. Import only the standard library and
   sibling modules; read host facts through `hook_io`.
2. Add both wrappers, `<event>/<name>.sh` and `<event>/<name>.ps1`, from an
   existing pair. Each states the event, the matcher, and the decision it can
   return, and exits 0 unconditionally.
3. Route it in `harness/hooks/lib/dispatch.py` `modules_for` and register it for the
   runtimes that support it (`harness/adapters/`) and in
   `harness/registry/runtimes.json` `hook_events`.
4. Add fixtures under `tests/fixtures/<group>/` with the verdict in the name
   (`bypass-`/`deny-` for a deny, `advise-` for an advisory, `allow-` for
   silence) and their expected stdout under `tests/expected/<group>/`.
5. Run both drivers below until green.

## Tests

```text
bash harness/hooks/tests/run.sh
powershell -NoProfile -ExecutionPolicy Bypass -File harness/hooks/tests/run.ps1
python -m pytest harness/hooks/tests -q -p no:cacheprovider
```

Each driver runs the Python suite, then pipes every fixture through the
native wrapper for its group and diffs stdout against the expected bytes,
then smokes the dispatcher with one deny fixture. Fixture groups: `guard`
(dangerous-ops), `openpyxl`, `frontmatter`, `read-deny`. The expected file
for a fixture is the exact stdout of its lib with a trailing newline, or an
empty file for silence; regenerate one by piping the fixture into the wrapper
and confirming the verdict by hand before saving it.

Every fixture's expected bytes are written against the template's shipped
`structure.json` (main-only git mode, populated lanes). `hook_io.load_structure()`
normally reads this checkout's own `harness/registry/structure.json`, so on an
adopted host (a different git mode, unset lanes) a fixture's verdict can
change. `HARNESS_STRUCTURE_FILE` (an absolute path to a structure JSON)
overrides that lookup whenever `load_structure()` is called with no explicit
root, or with a root that resolves to this checkout's own root; an explicit,
different root (a test's own `tmp_path`) always ignores it. Both `run.sh` and
`run.ps1` set it to `harness/tools/templates/structure.default.json` before
replaying fixtures against the native wrappers, and `test_guard_regressions.py`,
`test_dispatch.py`, and `test_exit_codes.py` set it for their own module's
tests. This is a test-only mechanism: no production hook or wrapper sets this
variable, and setting it outside a test run has no defined behavior.

The suite is hermetic: it writes only under the operating system temporary
directory, starts no runtime, and never touches the network. Passing it is
file-shape and in-process evidence ("configured"); whether a runtime actually
invokes a wrapper and honors its decision is recorded per runtime in
`docs/VERIFICATION.md` after someone watches it happen.
