# 一键把服务与监督都拉起来（供命令行/排障使用）
# 用法：powershell -ExecutionPolicy Bypass -File .\tools\ensure_running.ps1
#       powershell -ExecutionPolicy Bypass -File .\tools\ensure_running.ps1 -NoStart
param([switch]$NoStart)

$ErrorActionPreference = 'Stop'
$script:Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
. (Join-Path $script:Root 'lib\common.ps1')

$python = Get-PythonPath
if (-not $python) { Write-Host "未找到 Python" -ForegroundColor Red; exit 2 }

function Test-Port([int]$p) {
    try { return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction Stop) }
    catch { return $false }
}

$port = 8770
if (-not (Test-Port $port)) {
    Write-Host "启动仪表盘服务…" -ForegroundColor Cyan
    Start-Process -FilePath $python `
        -ArgumentList "`"$script:Root\lib\server.py`" --no-open --port $port" `
        -WorkingDirectory $script:Root -WindowStyle Minimized
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 250
        if (Test-Port $port) { break }
    }
}
if (Test-Port $port) { Write-Host "  服务在线：http://127.0.0.1:$port/" -ForegroundColor Green }
else { Write-Host "  服务启动失败" -ForegroundColor Red; exit 1 }

if (-not $NoStart) {
    $mon = Get-RunningWatch
    if ($mon) {
        Write-Host ("  监督已在运行：PID " + (($mon | ForEach-Object { $_.ProcessId }) -join ', ')) -ForegroundColor Green
    } else {
        Write-Host "  启动监督…" -ForegroundColor Cyan
        $body = '{}'
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/start" -Method Post -TimeoutSec 60
            Write-Host ("  " + $r.message) -ForegroundColor Green
        } catch {
            Write-Host ("  启动失败：" + $_.Exception.Message) -ForegroundColor Red
        }
    }
}

Start-Sleep -Seconds 2
try {
    $d = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/data" -TimeoutSec 15
    Write-Host ("`n当前状态：state={0}｜PID {1}｜今日 {2} 次判定｜专注率 {3}%" -f `
        $d.state, ($d.pids -join ','), $d.today.checks, [math]::Round($d.today.on_task_rate * 100))
} catch {
    Write-Host "读状态失败：$($_.Exception.Message)" -ForegroundColor Yellow
}
