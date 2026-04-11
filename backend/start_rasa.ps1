param(
    [switch]$Clean,
    [switch]$TrainOnly,
    [switch]$RunOnly,
    [int]$Port = 5005
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$backendDir = $PSScriptRoot
$tempDir = "D:\rasa_tmp"

Write-Host "[INFO] Project root: $projectRoot"
Write-Host "[INFO] Backend dir : $backendDir"

if (-not (Test-Path $tempDir)) {
    New-Item -ItemType Directory -Path $tempDir | Out-Null
}

$env:TEMP = $tempDir
$env:TMP = $tempDir
$env:TMPDIR = $tempDir

Write-Host "[INFO] TEMP/TMP set to $tempDir"

Set-Location $backendDir

if ($Clean) {
    Write-Host "[INFO] Cleaning temp and old models..."
    Remove-Item -Recurse -Force "$tempDir\*" -ErrorAction SilentlyContinue
    Remove-Item -Force ".\models\*.tar.gz" -ErrorAction SilentlyContinue
}

if (-not $RunOnly) {
    Write-Host "[INFO] Running: rasa train"
    rasa train
}

if (-not $TrainOnly) {
    Write-Host "[WARN] Forms / custom actions need Action Server on 5055. In another terminal: .\start_actions.ps1"
    Write-Host "[INFO] Running: python rasa_windows.py run ..."
    python "$PSScriptRoot\rasa_windows.py" run --enable-api --cors "*" --port $Port
}
