# base-harness bootstrap (Windows entry point).
#
# Materializes the runtime paths declared in harness/bootstrap/junctions.json
# (.claude/, .codex/, .agents/, .opencode/, opencode.json, AGENTS.md) from the
# canonical harness/ tree, materializes the selected skills per runtime,
# prunes deselected harness-managed entries, runs the optional extension
# point, and registers the git pre-commit floor.
#
# All of that logic lives in materialize.py, which creates NTFS junctions
# (no administrator rights needed), validates every destination as strictly
# below the resolved repository root before any removal, unlinks reparse
# points with non-recursive calls so a junction's target is never deleted,
# and never recursively removes a real directory. This script only finds a
# working Python and delegates, so the Windows and POSIX entry points cannot
# diverge.
#
# Modes:
#   .\bootstrap.ps1          create or repair every destination
#   .\bootstrap.ps1 -Check   verify only; exit 1 on drift; changes nothing
#   .\bootstrap.ps1 -Copy    recursive copies instead of junctions
#   .\bootstrap.ps1 -Force   replace a conflicting unmanaged FILE; real directories are never removed
#
# Exit codes: 0 clean, 1 drift or unresolved conflict, 2 missing prerequisite,
# 3 manifest parse failure.

[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$Copy,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$engine = Join-Path $PSScriptRoot "materialize.py"
$manifest = Join-Path $PSScriptRoot "junctions.json"

# Execute-probe for Python. An app-store alias or a broken shim is found by
# Get-Command but exits non-zero without running code; only a candidate that
# executes a trivial program with exit code 0 is accepted.
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
    Write-Host "bootstrap: no working Python 3 on PATH (tried python, python3, py; an alias that only opens an app store does not count). Install CPython 3.11+ and rerun." -ForegroundColor Red
    exit 2
}

# Hook wrappers are bash scripts. Without bash the contract text still
# governs, so this is a warning, not a failure.
if (-not (Get-Command bash -ErrorAction SilentlyContinue)) {
    Write-Host "  WARN     bash is not on PATH: hook wrappers will not run in this environment; the contract text in AGENTS.md still governs" -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath $engine -PathType Leaf)) {
    Write-Host "bootstrap: engine missing at $engine" -ForegroundColor Red
    exit 2
}
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    Write-Host "bootstrap: manifest missing at $manifest (harness/bootstrap/junctions.json)" -ForegroundColor Red
    exit 3
}

Write-Host "bootstrap: python = $python"

$engineArgs = @()
if ($Check) { $engineArgs += "--check" }
if ($Copy) { $engineArgs += "--copy" }
if ($Force) { $engineArgs += "--force" }

# The engine derives the repository root from its own location.
& $python -B $engine @engineArgs
exit $LASTEXITCODE
