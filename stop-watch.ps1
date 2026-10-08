# 结束学习监督
# 按"命令行里含 monitor.py"识别进程，不依赖解释器装在哪儿 —— 换台机器也能停掉。
$ErrorActionPreference = 'Stop'
$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
. (Join-Path $script:Root 'lib\common.ps1')

$python = Get-PythonPath
if ($python) {
    & $python (Join-Path $script:Root 'monitor.py') --stop
    exit $LASTEXITCODE
}

# 没找到 Python 时的退路：按命令行匹配，直接结束
Write-Host "未找到 Python，改用进程匹配方式结束。" -ForegroundColor Yellow
$targets = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*monitor.py*' -and $_.ProcessId -ne $PID }
if (-not $targets) {
    Write-Host "没有正在运行的学习监督进程。"
    exit 0
}
foreach ($t in $targets) {
    Write-Host "结束 PID $($t.ProcessId)"
    Stop-Process -Id $t.ProcessId -Force -ErrorAction SilentlyContinue
}
Write-Host "已结束。日报可用：.\report.bat"
