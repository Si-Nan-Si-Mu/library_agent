# 本地 Neo4j 一键配置脚本（拿到 zip 后运行）
# 前提：把下载好的 neo4j-community-*-windows.zip 放到 D:\neo4j-local\neo4j.zip
# 作用：解压 -> 用 JDK21 -> 设初始密码 -> 控制台启动
# 用法：powershell -ExecutionPolicy Bypass -File scripts\setup_local_neo4j.ps1

$ErrorActionPreference = "Stop"
$base = "D:\neo4j-local"
$zip = Join-Path $base "neo4j.zip"
$jdk = "C:\Program Files\Java\jdk-21.0.10"
$initPwd = "libraryagent"

if (-not (Test-Path $zip)) {
    Write-Host "[X] 未找到 $zip ，请先把 Neo4j 社区版 Windows zip 放到该路径。" -ForegroundColor Red
    exit 1
}

# 1. 解压（若尚未解压）
$home = Get-ChildItem $base -Directory -Filter "neo4j-community-*" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $home) {
    Write-Host "[*] 正在解压 $zip ..." -ForegroundColor Cyan
    Expand-Archive -Path $zip -DestinationPath $base -Force
    $home = Get-ChildItem $base -Directory -Filter "neo4j-community-*" | Select-Object -First 1
}
if (-not $home) { Write-Host "[X] 解压后未找到 neo4j-community-* 目录。" -ForegroundColor Red; exit 1 }
$NEO4J_HOME = $home.FullName
Write-Host "[*] NEO4J_HOME = $NEO4J_HOME" -ForegroundColor Green

# 2. 指定 JDK21（仅本会话），避免 Java 22 兼容问题
if (Test-Path $jdk) {
    $env:JAVA_HOME = $jdk
    $env:Path = "$jdk\bin;" + $env:Path
    Write-Host "[*] 使用 JAVA_HOME = $jdk" -ForegroundColor Green
} else {
    Write-Host "[!] 未找到 JDK21（$jdk），将使用系统默认 Java，可能与 Neo4j 5.x 不兼容。" -ForegroundColor Yellow
}

# 3. 设置初始密码
Write-Host "[*] 设置初始密码为 '$initPwd' ..." -ForegroundColor Cyan
& "$NEO4J_HOME\bin\neo4j-admin.bat" dbms set-initial-password $initPwd 2>&1 | Write-Host

# 4. 启动控制台（前台运行；关闭窗口即停止）
Write-Host "[*] 启动 Neo4j（Ctrl+C 停止）。Browser: http://localhost:7474  Bolt: bolt://localhost:7687" -ForegroundColor Green
& "$NEO4J_HOME\bin\neo4j.bat" console
