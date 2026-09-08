# read-deny (PreToolUse wrapper, PowerShell)
#
# Event: PreToolUse. Matcher: Read (Claude Code only; not registered by default).
# Decision: deny (permissionDecision in the JSON) for a file labeled access: secret, or silence.
# Delegates to harness/hooks/lib/read_deny.py, which reads the JSON envelope on stdin and
# prints zero or one JSON line. Exits 0 unconditionally: a missing lib file
# or a missing Python is silence (fail open), and the decision lives in the
# JSON, never in the exit code.
#
# Shipped OFF: the wrapper returns silence unless the environment variable
# HARNESS_READ_DENY equals 1. On Codex and OpenCode the tier labels are
# documentation and this hook is not registered.
$ErrorActionPreference = "Continue"
try {
    if ($env:HARNESS_READ_DENY -ne "1") { exit 0 }
    $LIB = Join-Path (Split-Path -Parent $PSScriptRoot) "lib"
    $PY = Join-Path $LIB "read_deny.py"
    if (-not (Test-Path -LiteralPath $PY)) { exit 0 }
    . (Join-Path $LIB "_find_python.ps1")
    if (-not $Python) { exit 0 }
    . (Join-Path $LIB "_invoke_python.ps1")
    Invoke-PythonWithStdin -Python $Python -Script $PY -Arguments $args
} catch {
    [Console]::Error.WriteLine("read-deny: wrapper malfunction: " + $_.Exception.Message)
}
exit 0
