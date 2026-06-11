# 以管理员身份运行：启用 WSL2 所需的 Windows 组件并记录日志
$log = "$env:TEMP\enable_wsl2_log.txt"
"==== $(Get-Date) 开始 ====" | Out-File $log -Encoding utf8

try {
    "--- 当前功能状态 ---" | Out-File $log -Append -Encoding utf8
    dism /online /get-featureinfo /featurename:VirtualMachinePlatform 2>&1 |
        Select-String "State|状态" | Out-File $log -Append -Encoding utf8

    "--- 启用 VirtualMachinePlatform ---" | Out-File $log -Append -Encoding utf8
    dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart 2>&1 |
        Out-File $log -Append -Encoding utf8

    "--- 启用 Microsoft-Windows-Subsystem-Linux ---" | Out-File $log -Append -Encoding utf8
    dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart 2>&1 |
        Out-File $log -Append -Encoding utf8

    "--- 设置 hypervisorlaunchtype = Auto ---" | Out-File $log -Append -Encoding utf8
    bcdedit /set hypervisorlaunchtype auto 2>&1 | Out-File $log -Append -Encoding utf8

    "==== 完成，请重启电脑 ====" | Out-File $log -Append -Encoding utf8
} catch {
    "出错: $_" | Out-File $log -Append -Encoding utf8
}
