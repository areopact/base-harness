# pre-bootstrap-detector (SessionStart wrapper, PowerShell)
#
# Event: SessionStart. Matcher: (none).
# Decision: advisory naming the bootstrap command for this platform, or silence when every destination is materialized.
# Delegates to harness/hooks/lib/pre_bootstrap_detector.py, which reads the JSON envelope on stdin and
# prints zero or one JSON line. Exits 0 unconditionally: a missing lib file
# or a missing Python is silence (fail open), and the decision lives in the
# JSON, never in the exit code.

$ErrorActionPreference = "Continue"
try {
    $LIB = Join-Path (Split-Path -Parent $PSScriptRoot) "lib"
    $PY = Join-Path $LIB "pre_bootstrap_detector.py"
    if (-not (Test-Path -LiteralPath $PY)) { exit 0 }
    . (Join-Path $LIB "_find_python.ps1")
    if (-not $Python) { exit 0 }
    . (Join-Path $LIB "_invoke_python.ps1")
    Invoke-PythonWithStdin -Python $Python -Script $PY -Arguments $args
} catch {
    [Console]::Error.WriteLine("pre-bootstrap-detector: wrapper malfunction: " + $_.Exception.Message)
}
exit 0
