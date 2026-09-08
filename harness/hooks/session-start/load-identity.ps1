# load-identity (SessionStart wrapper, PowerShell)
#
# Event: SessionStart. Matcher: (none).
# Decision: advisory (additionalContext carrying the identity lane) or silence when the lane is null.
# Delegates to harness/hooks/lib/load_identity.py, which reads the JSON envelope on stdin and
# prints zero or one JSON line. Exits 0 unconditionally: a missing lib file
# or a missing Python is silence (fail open), and the decision lives in the
# JSON, never in the exit code.

$ErrorActionPreference = "Continue"
try {
    $LIB = Join-Path (Split-Path -Parent $PSScriptRoot) "lib"
    $PY = Join-Path $LIB "load_identity.py"
    if (-not (Test-Path -LiteralPath $PY)) { exit 0 }
    . (Join-Path $LIB "_find_python.ps1")
    if (-not $Python) { exit 0 }
    . (Join-Path $LIB "_invoke_python.ps1")
    Invoke-PythonWithStdin -Python $Python -Script $PY -Arguments $args
} catch {
    [Console]::Error.WriteLine("load-identity: wrapper malfunction: " + $_.Exception.Message)
}
exit 0
