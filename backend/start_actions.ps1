param(
    [int]$Port = 5055
)

$ErrorActionPreference = "Stop"

$backendDir = $PSScriptRoot
$tempDir = "D:\rasa_tmp"

Write-Host "[INFO] Backend dir : $backendDir"

if (-not (Test-Path $tempDir)) {
    New-Item -ItemType Directory -Path $tempDir | Out-Null
}

$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:TMPDIR = $tempDir

Write-Host "[INFO] TEMP/TMP set to $tempDir"

Set-Location $backendDir

Write-Host "[INFO] Running: rasa run actions --port $Port"
rasa run actions --port $Port
