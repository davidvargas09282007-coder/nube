# ============================================================================
# Sincroniza nube\jarvis_server con server\jarvis_server (fuente de verdad).
#
#   .\scripts\sync.ps1          copia (espejo) el codigo
#   .\scripts\sync.ps1 -Check   solo comprueba diferencias; exit 1 si hay drift
# ============================================================================
[CmdletBinding()]
param(
    [switch]$Check
)

$ErrorActionPreference = "Stop"

$nubeRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $nubeRoot
$source = Join-Path $repoRoot "server\jarvis_server"
$target = Join-Path $nubeRoot "jarvis_server"

if (-not (Test-Path $source)) {
    throw "No existe el origen: $source"
}

function Get-TreeHashes {
    param([string]$Root)

    if (-not (Test-Path $Root)) {
        return @{}
    }

    $prefix = (Resolve-Path $Root).Path.TrimEnd('\') + '\'
    $result = @{}
    Get-ChildItem -Path $Root -Recurse -File |
        Where-Object {
            $_.FullName -notlike '*\__pycache__\*' -and
            $_.Extension -ne '.pyc'
        } |
        ForEach-Object {
            $relative = $_.FullName.Substring($prefix.Length)
            $result[$relative] = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash
        }
    return $result
}

if ($Check) {
    $sourceHashes = Get-TreeHashes -Root $source
    $targetHashes = Get-TreeHashes -Root $target

    $problems = @()
    foreach ($key in $sourceHashes.Keys) {
        if (-not $targetHashes.ContainsKey($key)) {
            $problems += "FALTA   $key"
        } elseif ($sourceHashes[$key] -ne $targetHashes[$key]) {
            $problems += "DISTINTO $key"
        }
    }
    foreach ($key in $targetHashes.Keys) {
        if (-not $sourceHashes.ContainsKey($key)) {
            $problems += "SOBRA   $key"
        }
    }

    if ($problems.Count -gt 0) {
        $problems | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
        Write-Host "DRIFT: ejecuta .\scripts\sync.ps1 para actualizar nube\jarvis_server" -ForegroundColor Red
        exit 1
    }

    Write-Host "OK: nube\jarvis_server esta sincronizado con server\jarvis_server" -ForegroundColor Green
    exit 0
}

New-Item -ItemType Directory -Force -Path $target | Out-Null
& robocopy $source $target /MIR /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "robocopy fallo con codigo $LASTEXITCODE"
}

Write-Host "Sincronizado: server\jarvis_server -> nube\jarvis_server" -ForegroundColor Green
