# Shared Python invocation helper (PowerShell).
#
# Dot-sourced (`. _invoke_python.ps1`) by every harness/hooks/*/*.ps1 wrapper
# that passes stdin through to a Python child. System.Diagnostics.Process
# keeps stdin byte-faithful under a nested Windows PowerShell host without a
# temporary file or an extra cmd.exe hop, and forces UTF-8 on every stream.
#
# The child's stdout is copied verbatim (it carries the one-line JSON decision
# or nothing); its stderr is copied to the wrapper's stderr. A non-zero child
# exit is reported on stderr as a malfunction and never turned into a decision.
#
# Usage:
#   . (Join-Path $LIB "_find_python.ps1")
#   if (-not $Python) { exit 0 }
#   . (Join-Path $LIB "_invoke_python.ps1")
#   Invoke-PythonWithStdin -Python $Python -Script $PY -Arguments @("--runtime", "codex")

function Invoke-PythonWithStdin {
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$Script,
        [string[]]$Arguments = @()
    )

    [Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $inputData = [Console]::In.ReadToEnd()
    if ($null -eq $inputData) { $inputData = "" }

    $quoted = @('"' + ($Script -replace '"', '\"') + '"')
    foreach ($argument in $Arguments) {
        $quoted += '"' + ($argument -replace '"', '\"') + '"'
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Python
    $psi.Arguments = ($quoted -join " ")
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables['PYTHONUTF8'] = '1'
    $psi.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
    $psi.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $psi
    try {
        if (-not $process.Start()) { return }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $inputBytes = [System.Text.Encoding]::UTF8.GetBytes($inputData)
        $process.StandardInput.BaseStream.Write($inputBytes, 0, $inputBytes.Length)
        $process.StandardInput.Close()
        $process.WaitForExit()
        [Console]::Out.Write($stdoutTask.Result)
        [Console]::Error.Write($stderrTask.Result)
        if ($process.ExitCode -ne 0) {
            [Console]::Error.WriteLine("hook-python: child exited {0}; treated as malfunction, not as a decision" -f $process.ExitCode)
        }
    } finally {
        $process.Dispose()
    }
}
