# Offline hook test driver (PowerShell).
#
# 1. Runs the Python suite (pytest when importable, else unittest discovery).
# 2. Pipes every fixture under tests/fixtures/<group>/ through the PowerShell
#    wrapper that serves that group and diffs the wrapper's stdout against
#    tests/expected/<group>/<name>.expected after trailing newlines are
#    dropped. The wrapper must exit 0 in every case.
# 3. Smokes the Codex/OpenCode dispatcher with one deny fixture.
#
# Hermetic: writes only into the operating system temporary directory,
# performs no network call, and starts no runtime.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Hooks = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Root = (Resolve-Path (Join-Path $Hooks "..\..")).Path

. (Join-Path $Hooks "lib\_find_python.ps1")
if (-not $Python) { Write-Error "no working Python interpreter on PATH"; exit 1 }

Set-Location $Root
& $Python -c "import pytest" 2>$null
if ($LASTEXITCODE -eq 0) {
    & $Python -m pytest $ScriptDir -q -p no:cacheprovider
} else {
    & $Python -m unittest discover -s $ScriptDir -p "test_*.py"
}
if ($LASTEXITCODE -ne 0) { exit 1 }

function Invoke-Wrapper {
    param([string]$Wrapper, [string]$StdinFile, [string[]]$Arguments = @())
    $tmpOut = [System.IO.Path]::GetTempFileName()
    $tmpErr = [System.IO.Path]::GetTempFileName()
    try {
        $argumentList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Wrapper) + $Arguments
        $process = Start-Process -FilePath "powershell.exe" `
            -ArgumentList $argumentList `
            -WorkingDirectory $Root `
            -RedirectStandardInput $StdinFile `
            -RedirectStandardOutput $tmpOut `
            -RedirectStandardError $tmpErr `
            -NoNewWindow -Wait -PassThru
        $stdout = Get-Content -LiteralPath $tmpOut -Raw -Encoding UTF8
        if ($null -eq $stdout) { $stdout = "" }
        return @{ ExitCode = $process.ExitCode; Stdout = $stdout }
    } finally {
        Remove-Item -LiteralPath $tmpOut, $tmpErr -Force -ErrorAction SilentlyContinue
    }
}

$fail = 0
$count = 0
$groups = @(
    @{ Group = "guard"; Wrapper = (Join-Path $Hooks "pre-tool-use\dangerous-ops-guard.ps1") },
    @{ Group = "openpyxl"; Wrapper = (Join-Path $Hooks "pre-tool-use\openpyxl-guard.ps1") },
    @{ Group = "frontmatter"; Wrapper = (Join-Path $Hooks "post-tool-use\frontmatter-guard.ps1") },
    @{ Group = "read-deny"; Wrapper = (Join-Path $Hooks "pre-tool-use\read-deny.ps1") }
)
foreach ($entry in $groups) {
    $fixtures = Get-ChildItem -LiteralPath (Join-Path $ScriptDir ("fixtures\" + $entry.Group)) -Filter *.json | Sort-Object Name
    foreach ($fixture in $fixtures) {
        $name = $fixture.BaseName
        $expectedFile = Join-Path $ScriptDir ("expected\" + $entry.Group + "\" + $name + ".expected")
        $expected = ""
        if (Test-Path -LiteralPath $expectedFile) {
            $expected = Get-Content -LiteralPath $expectedFile -Raw -Encoding UTF8
            if ($null -eq $expected) { $expected = "" }
        }
        $previous = $env:HARNESS_READ_DENY
        if ($entry.Group -eq "read-deny" -and -not $name.EndsWith("-flag-off")) {
            $env:HARNESS_READ_DENY = "1"
        } else {
            Remove-Item Env:HARNESS_READ_DENY -ErrorAction SilentlyContinue
        }
        try {
            $result = Invoke-Wrapper -Wrapper $entry.Wrapper -StdinFile $fixture.FullName
        } finally {
            if ($null -ne $previous) { $env:HARNESS_READ_DENY = $previous } else { Remove-Item Env:HARNESS_READ_DENY -ErrorAction SilentlyContinue }
        }
        $count += 1
        $actualText = $result.Stdout.TrimEnd("`r", "`n")
        $expectedText = $expected.TrimEnd("`r", "`n")
        if ($result.ExitCode -ne 0) {
            Write-Host ("FAIL: {0}/{1}: wrapper exited {2}" -f $entry.Group, $name, $result.ExitCode)
            $fail = 1
        } elseif ($actualText -ne $expectedText) {
            Write-Host ("FAIL: {0}/{1}: stdout differs from expected" -f $entry.Group, $name)
            Write-Host ("  expected: " + $expectedText)
            Write-Host ("  actual:   " + $actualText)
            $fail = 1
        }
    }
}
if ($fail -ne 0) { exit 1 }
Write-Host ("wrapper fixture diff: {0} fixtures PASS" -f $count)

$smoke = Invoke-Wrapper -Wrapper (Join-Path $Hooks "codex-dispatch.ps1") `
    -StdinFile (Join-Path $ScriptDir "fixtures\guard\bypass-force-push-main.json") `
    -Arguments @("-Runtime", "codex", "-Event", "PreToolUse")
if ($smoke.ExitCode -ne 0 -or $smoke.Stdout -notmatch '"permissionDecision"\s*:\s*"deny"') {
    Write-Host "FAIL: PowerShell dispatcher smoke test"
    exit 1
}
Write-Host "PowerShell dispatcher smoke: PASS"
exit 0
