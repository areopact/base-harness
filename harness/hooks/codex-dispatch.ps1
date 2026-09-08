# Single-process hook dispatcher entry (PowerShell) for Codex and OpenCode.
#
# Event: any of SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop.
# Matcher: set by the runtime registration (harness/adapters/codex/hooks.json,
# harness/adapters/opencode/plugins/harness-bridge.js). Decision: whatever the
# routed lib modules return, merged by harness/hooks/lib/dispatch.py into one JSON line:
# silence, an advisory, or (PreToolUse only) a deny. This wrapper exits 0
# unconditionally; the decision lives in the JSON, never in the exit code.
#
# Parameters: -Runtime <codex|opencode> -Event <Event>. An unknown event or
# runtime, a missing Python, or a missing dispatcher is silence.

param(
    [string]$Event = "",
    [string]$Runtime = "codex"
)

$ErrorActionPreference = "Continue"
try {
    if (@("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop") -notcontains $Event) { exit 0 }
    if (@("codex", "opencode") -notcontains $Runtime) { exit 0 }
    $LIB = Join-Path $PSScriptRoot "lib"
    $PY = Join-Path $LIB "dispatch.py"
    if (-not (Test-Path -LiteralPath $PY)) { exit 0 }
    . (Join-Path $LIB "_find_python.ps1")
    if (-not $Python) { exit 0 }
    . (Join-Path $LIB "_invoke_python.ps1")
    Invoke-PythonWithStdin -Python $Python -Script $PY -Arguments @("--event", $Event, "--runtime", $Runtime)
} catch {
    [Console]::Error.WriteLine("codex-dispatch: wrapper malfunction: " + $_.Exception.Message)
}
exit 0
