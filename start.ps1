# 学习监督 - 控制台模式
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\start.ps1                持续监督（Ctrl+C 结束）
#   powershell -ExecutionPolicy Bypass -File .\start.ps1 --minutes 25   番茄钟 25 分钟
#   powershell -ExecutionPolicy Bypass -File .\start.ps1 --report       今日日报
# 说明：参数原样透传给 monitor.py，所以用 --minutes / --report 这种 Python 侧写法。
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Extra)

$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
. (Join-Path $script:Root 'lib\common.ps1')

$python = Get-PythonPath
if (-not $python) {
    Write-Host "未找到 Python。请安装 Python 3.10+，或修改 lib\common.ps1 里的候选路径。" -ForegroundColor Red
    exit 2
}

$pyArgs = @((Join-Path $script:Root 'monitor.py'))
if ($Extra) { $pyArgs += $Extra }

Write-Host "学习监督（Ctrl+C 结束并打印本次小结）" -ForegroundColor Cyan
Write-Host "解释器：$python"
Write-Host ""
& $python @pyArgs
