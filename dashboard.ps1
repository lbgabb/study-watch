# 学习监督 - 打开可视化仪表盘（本地网页界面）
# 已在运行就直接开浏览器复用，不会起第二个服务。
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\dashboard.ps1
#   powershell -ExecutionPolicy Bypass -File .\dashboard.ps1 -Port 8800 -NoOpen
param(
    [int]$Port = 8770,
    [switch]$NoOpen
)

$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
. (Join-Path $script:Root 'lib\common.ps1')

function Test-PortListening([int]$p) {
    try {
        return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop)
    } catch {
        return $false
    }
}

$url = "http://127.0.0.1:$Port/"

# 1) 端口已经有人在听：说明服务在跑，直接开页面（避免起第二个服务抢端口）
if (Test-PortListening $Port) {
    Write-Host "仪表盘服务已在运行（$url），直接打开页面。" -ForegroundColor Green
    $mon = Get-RunningWatch
    if ($mon) {
        Write-Host ("监督进程：" + (($mon | ForEach-Object { $_.ProcessId }) -join ', '))
    } else {
        Write-Host "注意：当前没有监督进程在跑，可以在页面上点「开始监督」。" -ForegroundColor Yellow
    }
    if (-not $NoOpen) {
        try { Start-Process $url; Write-Host "已在浏览器打开：$url" -ForegroundColor Green }
        catch { Write-Host "请手动在浏览器打开：$url" -ForegroundColor Yellow }
    }
    exit 0
}

# 2) 没在跑：启动服务
$python = Get-PythonPath
if (-not $python) {
    Write-Host "未找到 Python。请安装 Python 3.10+，或修改 lib\common.ps1 里的候选路径。" -ForegroundColor Red
    exit 2
}

$pyArgs = @((Join-Path $script:Root 'lib\server.py'), '--port', $Port)
if ($NoOpen) { $pyArgs += '--no-open' }

Write-Host "正在启动学习监督仪表盘…" -ForegroundColor Cyan
Write-Host "（这个窗口就是仪表盘服务；关掉它网页就断了，但监督进程不受影响）"
Write-Host ""
& $python @pyArgs
