# base-harness OpenCode adapter doctor (Windows wrapper). Offline by default;
# pass --runtime to add version and agent-list probes.

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DoctorArgs
)

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "doctor_opencode.py"

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
    Write-Host "doctor-opencode: no working Python 3 on PATH (tried python, python3, py)." -ForegroundColor Red
    exit 2
}

if (-not $DoctorArgs -or $DoctorArgs.Count -eq 0) { $DoctorArgs = @("--offline") }
& $python -B $script @DoctorArgs
exit $LASTEXITCODE
