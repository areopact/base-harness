# Launch OpenCode with the harness-managed skill root.
#
# OpenCode also searches other runtimes' skill directories, so a direct
# `opencode` invocation can see unselected or runtime-specific wrappers. This
# wrapper disables those external roots and refuses to start when the selected
# skill tree has not been materialized, which keeps skill selection enforcing.
# The doctor fails when the OpenCode skill link does not resolve into that tree.
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
$Junctions = Join-Path $Root "harness\bootstrap\junctions.json"

if (-not (Test-Path $Junctions)) {
    Write-Error "opencode-harness: $Junctions is missing; run bootstrap first"
    exit 1
}

try {
    $data = Get-Content -Raw -Encoding UTF8 $Junctions | ConvertFrom-Json
    $selectedDir = [string]$data.per_skill.opencode.dst_dir
} catch {
    Write-Error "opencode-harness: cannot read per_skill.opencode.dst_dir from $Junctions"
    exit 1
}

if (-not $selectedDir) {
    Write-Error "opencode-harness: per_skill.opencode.dst_dir is empty in $Junctions"
    exit 1
}

$selectedPath = Join-Path $Root ($selectedDir -replace "/", "\")
if (-not (Test-Path $selectedPath -PathType Container)) {
    Write-Error "opencode-harness: selected skill tree $selectedDir is not materialized; run bootstrap first"
    exit 1
}

$env:OPENCODE_DISABLE_EXTERNAL_SKILLS = "1"
Set-Location $Root
& opencode @args
exit $LASTEXITCODE
