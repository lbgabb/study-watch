# 番茄钟（专注计划）命令行入口
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\pomodoro.ps1                     # 25/5 经典，不限轮数
#   powershell -ExecutionPolicy Bypass -File .\pomodoro.ps1 -Preset ultradian   # 90/20
#   powershell -ExecutionPolicy Bypass -File .\pomodoro.ps1 -Rounds 4 -Note "高数第三章"
#   powershell -ExecutionPolicy Bypass -File .\pomodoro.ps1 -Focus 50 -Break 10 # 自定义
#   powershell -ExecutionPolicy Bypass -File .\pomodoro.ps1 -Status
#   powershell -ExecutionPolicy Bypass -File .\pomodoro.ps1 -Stop
#
# 实现说明：请求体写成临时 JSON 文件交给 Python 读，而不是当命令行参数传 ——
# PowerShell 把字符串传给外部程序时会把引号吃掉，JSON 必坏（这个坑踩过）。
param(
    [ValidateSet('pomodoro', 'ultradian', 'desktime', 'sprint', 'custom')]
    [string]$Preset = 'pomodoro',
    [int]$Rounds = 0,
    [string]$Note = '',
    [int]$Focus = 0,
    [int]$Break = 0,
    [int]$LongEvery = 0,
    [int]$LongBreak = 0,
    [switch]$Status,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
. (Join-Path $script:Root 'lib\common.ps1')

$python = Resolve-Python
if (-not $python) { Write-Host "未找到 Python。" -ForegroundColor Red; exit 2 }

$body = @{ action = 'start'; preset = $Preset; rounds = $Rounds; note = $Note }
if ($Focus -gt 0) { $body.preset = 'custom'; $body.focus_min = $Focus }
if ($Break -gt 0) { $body.break_min = $Break }
if ($LongEvery -gt 0) { $body.long_every = $LongEvery }
if ($LongBreak -gt 0) { $body.long_break_min = $LongBreak }
if ($Status) { $body = @{ action = 'status' } }
if ($Stop) { $body = @{ action = 'stop' } }

$tag = [guid]::NewGuid().ToString('N').Substring(0, 8)
$reqFile = Join-Path $env:TEMP "sw_plan_req_$tag.json"
$pyFile = Join-Path $env:TEMP "sw_plan_$tag.py"
Set-Content -LiteralPath $reqFile -Value ($body | ConvertTo-Json -Compress) -Encoding UTF8

$script = @'
import json, sys, urllib.request, urllib.error

with open(sys.argv[1], encoding="utf-8-sig") as f:
    body = json.load(f)

url = "http://127.0.0.1:8770/api/plan"
try:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    r = json.loads(urllib.request.urlopen(req, timeout=15).read())
except urllib.error.URLError:
    print("仪表盘服务没在运行。先双击桌面「学习监督 仪表盘」，或运行 tools/ensure_running.ps1")
    sys.exit(1)

if r.get("message"):
    print(r["message"])

p = r.get("plan") or {}
if p.get("active"):
    m, s = divmod(max(0, int(p.get("remaining_sec") or 0)), 60)
    print(f"  当前：{p.get('phase_label')} 第 {p.get('round')} 轮｜剩余 {m:02d}:{s:02d}")
    line = f"  节奏：{p.get('focus_min')} 分专注 / {p.get('break_min')} 分休息"
    if p.get("long_every"):
        line += f"｜每 {p.get('long_every')} 轮长休 {p.get('long_break_min')} 分钟"
    print(line)
    if p.get("note"):
        print(f"  主题：{p.get('note')}")
    print("  倒计时和轮次进度在仪表盘上（每秒刷新）")
elif p.get("finished"):
    print(f"  上次：{p.get('preset_label')}｜完成 {p.get('done_focus_rounds')} 轮专注")

sys.exit(0 if r.get("ok") else 1)
'@
Set-Content -LiteralPath $pyFile -Value $script -Encoding UTF8

try {
    & $python $pyFile $reqFile
    exit $LASTEXITCODE
} finally {
    Remove-Item -LiteralPath $pyFile, $reqFile -Force -ErrorAction SilentlyContinue
}
