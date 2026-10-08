# 学习监督启动器：已在运行则提示，否则静默后台启动
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Show-Msg([string]$text, [string]$title) {
    try {
        $w = New-Object -ComObject WScript.Shell
        $w.Popup($text, 8, $title, 64) | Out-Null   # 64 = 信息图标，8 秒自动关闭
    } catch {
        Write-Host $text
    }
}

# 找 Python：优先 py-path.txt，其次扫常见安装位置，最后 PATH
$script:Root = $here
. (Join-Path $here 'lib\common.ps1')
$python = Resolve-Python
if (-not $python) {
    Show-Msg ("没有找到 Python。`n`n请先安装 Python 3.10+（安装时勾选 Add Python to PATH），`n" +
              "或者在项目目录下建一个 py-path.txt，第一行写解释器的完整路径。") "学习监督 - 启动失败"
    exit 1
}

# 是否已在运行（匹配命令行里带 monitor.py 的 python 进程）
$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*monitor.py*' }
if ($running) {
    $ids = ($running | ForEach-Object { $_.ProcessId }) -join ', '
    Show-Msg "学习监督已经在运行了（PID $ids），不重复启动。`n`n要停止：双击 stop.bat`n看日报：双击 report.bat" "学习监督"
    exit 0
}

$args = "`"$here\monitor.py`" --background"
Start-Process -FilePath $python -ArgumentList $args -WindowStyle Hidden | Out-Null
Start-Sleep -Milliseconds 2500

$now = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*monitor.py*' }
if ($now) {
    $cfg = Get-Content -LiteralPath "$here\config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $ruleCount = @($cfg.capture.rules).Count
    Show-Msg ("已开始监督：每 $($cfg.interval_sec) 秒判定一次，按应用分配截图的规则 $ruleCount 条已生效。`n`n" +
              "分心时会弹提醒窗。`n" +
              "看数据：双击桌面「学习监督 仪表盘」`n" +
              "停止监督：双击 stop.bat`n" +
              "文字日报：双击 report.bat") "学习监督 - 运行中"
} else {
    Show-Msg "启动失败。`n请在命令行手动运行查看报错：`n`n  python monitor.py --once" "学习监督 - 启动失败"
    exit 2
}
