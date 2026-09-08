# Shared Python interpreter discovery (PowerShell).
#
# Dot-sourced (`. _find_python.ps1`) by every harness/hooks/*/*.ps1 wrapper
# and by codex-dispatch.ps1. Sets $Python to the full path of the first
# candidate that both resolves on PATH and actually runs, or to $null when
# none does. Every wrapper treats $null as silence and exits 0.
#
# Each candidate is execute-probed, not merely resolved: a platform may expose
# a stub named python or python3 that Get-Command resolves but that exits
# non-zero without running any code. Trusting the resolve alone would hand
# that stub the hook payload and turn its failure into a false verdict.

$Python = $null
$_previousPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
foreach ($_candidate in @("python3", "python", "py")) {
    $_command = Get-Command $_candidate -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $_command -or -not $_command.Source) { continue }
    # An app-execution alias under WindowsApps may block on an interactive
    # install instead of failing; skip it without running it.
    if ($_command.Source -like "*\WindowsApps\*") { continue }
    try {
        $null = & $_command.Source -c "pass" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $Python = $_command.Source
            break
        }
    } catch {
        continue
    }
}
$ErrorActionPreference = $_previousPreference

Remove-Variable _candidate, _command, _previousPreference -ErrorAction SilentlyContinue
