# delegation-guard (PostToolUse wrapper, PowerShell)
#
# Event: PostToolUse. Matcher: Agent|Workflow.
# Decision: advisory when structure.json delegation.mandatory is true, otherwise silence.
# Delegates to harness/hooks/lib/delegation_guard.py, which reads the JSON envelope on stdin and
# prints zero or one JSON line. Exits 0 unconditionally: a missing lib file
# or a missing Python is silence (fail open), and the decision lives in the
# JSON, never in the exit code.

$ErrorActionPreference = "Continue"
try {
    $LIB = Join-Path (Split-Path -Parent $PSScriptRoot) "lib"
    $PY = Join-Path $LIB "delegation_guard.py"
    if (-not (Test-Path -LiteralPath $PY)) { exit 0 }
    . (Join-Path $LIB "_find_python.ps1")
    if (-not $Python) { exit 0 }
    . (Join-Path $LIB "_invoke_python.ps1")
    Invoke-PythonWithStdin -Python $Python -Script $PY -Arguments $args
} catch {
    [Console]::Error.WriteLine("delegation-guard: wrapper malfunction: " + $_.Exception.Message)
}
exit 0
