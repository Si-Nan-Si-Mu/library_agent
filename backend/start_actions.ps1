param(
    [int]$Port = 5055
)

$ErrorActionPreference = "Stop"

$backendDir = $PSScriptRoot
$repoRoot = Split-Path $backendDir -Parent

function Import-DotEnvMerged {
    param([string]$RootPath, [string]$BackendPath)
    $merged = @{}
    foreach ($dir in @($RootPath, $BackendPath)) {
        $p = Join-Path $dir ".env"
        if (-not (Test-Path $p)) { continue }
        Get-Content $p -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if ($line -eq "" -or $line.StartsWith("#")) { return }
            $ix = $line.IndexOf("=")
            if ($ix -lt 1) { return }
            $name = $line.Substring(0, $ix).Trim()
            if (-not $name) { return }
            $val = $line.Substring($ix + 1).Trim()
            if (($val.StartsWith('"') -and $val.EndsWith('"')) -or ($val.StartsWith("'") -and $val.EndsWith("'"))) {
                $val = $val.Substring(1, $val.Length - 2)
            }
            $merged[$name] = $val
        }
    }
    foreach ($name in $merged.Keys) {
        $existing = [Environment]::GetEnvironmentVariable($name, "Process")
        if ([string]::IsNullOrEmpty($existing)) {
            [Environment]::SetEnvironmentVariable($name, $merged[$name], "Process")
        }
    }
}

Import-DotEnvMerged -RootPath $repoRoot -BackendPath $backendDir

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
