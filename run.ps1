# 后台静默启动学习监督（隐藏窗口，适合脚本/计划任务调用）
# 桌面快捷方式用的是 study-watch.cmd（带查重与气泡提示），这个更"裸"一些。
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\run.ps1
#   powershell -ExecutionPolicy Bypass -File .\run.ps1 -Minutes 60 -Interval 180
param(
    [double]$Minutes = 0,
    [int]$Interval = 0,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
. (Join-Path $script:Root 'lib\common.ps1')

$python = Get-PythonPath
if (-not $python) { throw "未找到 Python，请安装 Python 3.10+ 或修改 lib\common.ps1 中的路径" }

$pyArgs = @("`"$(Join-Path $script:Root 'monitor.py')`"", "--background")
if ($Minutes -gt 0) { $pyArgs += "--minutes $Minutes" }
if ($Interval -gt 0) { $pyArgs += "--interval $Interval" }
if ($DryRun) { $pyArgs += "--dry-run" }

Write-Host "使用解释器：$python"
Write-Host "启动参数：$($pyArgs -join ' ')"
$p = Start-Process -FilePath $python -ArgumentList ($pyArgs -join ' ') -PassThru -WindowStyle Hidden
Write-Host "已在后台启动，PID = $($p.Id)"
Write-Host "日志：$(Join-Path $script:Root 'data\watch.log')"
Write-Host "日报：.\report.bat"
Write-Host "结束监督：.\stop.bat  或  Stop-Process -Id $($p.Id)"
