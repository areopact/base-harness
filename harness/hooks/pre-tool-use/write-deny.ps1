# write-deny (PreToolUse wrapper, PowerShell)
#
# Event: PreToolUse. Matcher: Write|Edit|NotebookEdit (Claude Code); Codex and
# OpenCode reach the same module through harness/hooks/codex-dispatch.
# Decision: deny (permissionDecision in the JSON) for a target path matched by
# structure.json write_deny.globs and not by write_deny.except, or silence.
# Delegates to harness/hooks/lib/write_deny.py, which reads the JSON envelope on
# stdin and prints zero or one JSON line. Exits 0 unconditionally: a missing
# lib file or a missing Python is silence (fail open), and the decision lives
# in the JSON, never in the exit code.
#
# Shipped OFF: the default write_deny.globs is empty, so the module is silent
# until the host names the paths it reserves for its human authors.
$ErrorActionPreference = "Continue"
try {
    $LIB = Join-Path (Split-Path -Parent $PSScriptRoot) "lib"
    $PY = Join-Path $LIB "write_deny.py"
    if (-not (Test-Path -LiteralPath $PY)) { exit 0 }
    . (Join-Path $LIB "_find_python.ps1")
    if (-not $Python) { exit 0 }
    . (Join-Path $LIB "_invoke_python.ps1")
    Invoke-PythonWithStdin -Python $Python -Script $PY -Arguments $args
} catch {
    [Console]::Error.WriteLine("write-deny: wrapper malfunction: " + $_.Exception.Message)
}
exit 0
