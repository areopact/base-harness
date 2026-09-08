# base-harness Claude Code doctor (Windows entry point).
#
# Read-only. Prints one line per check in the shared six-layer format and the
# roll-up block; exit 0 when the repository layer passes. Delegates to
# doctor_claude.py after the same Python execute-probe bootstrap.ps1 uses.

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DoctorArgs
)

$ErrorActionPreference = "Stop"
$doctor = Join-Path $PSScriptRoot "doctor_claude.py"

function Find-WorkingPython {
    foreach ($candidate in @("python", "python3", "py")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $previous = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $null = & $command.Source -c "import sys; sys.exit(0)" 2>&1
            $code = $LASTEXITCODE
        } catch {
            $code = 1
        } finally {
            $ErrorActionPreference = $previous
        }
        if ($code -eq 0) { return $command.Source }
    }
    return $null
}

$python = Find-WorkingPython
if (-not $python) {
    Write-Host "doctor: no working Python 3 on PATH (tried python, python3, py). Install CPython 3.11+ and rerun." -ForegroundColor Red
    exit 2
}
if (-not (Test-Path -LiteralPath $doctor -PathType Leaf)) {
    Write-Host "doctor: $doctor is missing" -ForegroundColor Red
    exit 2
}

& $python -B $doctor @DoctorArgs
exit $LASTEXITCODE
