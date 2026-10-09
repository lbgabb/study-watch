# 量一个浏览器实例（及其子进程）的累计 CPU 时间与工作集。
#
# 为什么不按进程名量：这台机器上同时开着用户自己的 Edge（几十个 msedge 进程），
# 按名字统计会把用户的浏览行为算进来，量出来的是"用户在干什么"，不是桌宠开销。
# 所以按**唯一的 --user-data-dir** 定位：无头实例用的是临时 profile 目录，
# 这个字符串就是它的指纹。找到根进程后再递归收子进程。
#
# 输出：<累计CPU秒>|<进程数>|<工作集字节>
#
# 指纹从**文件**读，不用命令行参数 —— 这里踩过一个非常隐蔽的坑：
# 从 Python 的 subprocess 调这个脚本时，"-ProfileKey <值>" 传进来是**空的**
# （直接手敲 powershell -File 则正常）。而 `$_.CommandLine.Contains("")`
# 对任何进程都返回 True，于是把整台机器 228 个进程全算进去，量出来的
# CPU/内存完全是 QQ/微信/浏览器自己的开销。文件传参实测可靠。
param([string]$KeyFile = "")

if ([string]::IsNullOrWhiteSpace($KeyFile) -or -not (Test-Path $KeyFile)) {
    Write-Output "ERR|no-key-file|0"
    exit 1
}
$ProfileKey = (Get-Content $KeyFile -Raw).Trim()

# 这里踩过一次很隐蔽的坑：参数没传进来时 $ProfileKey 是空串，
# 而 `$_.CommandLine.Contains("")` **对任何字符串都返回 True**，
# 于是把整台机器的进程（含用户自己的浏览器、QQ、微信）全算进来，
# 量出来的 CPU/内存完全是别的软件的开销。所以这里直接报错退出，
# 宁可量不出来，也不能给一个看着合理的错数字。

$all = Get-CimInstance Win32_Process
# 排除：本脚本自己、任何 powershell/pwsh/conhost，以及不是浏览器的进程。
#
# 这里踩过一个很坑的 bug：测量工具本身就是"用 powershell 调这个脚本"，
# 而**上一次测量留下的孤儿 powershell** 命令行里同样带着指纹字符串，
# 会被当成目标进程。实测传一个完全假的指纹也能匹配到 4 个进程、
# 0.7 秒 CPU、330 MB 内存 —— 全是测量工具自己的开销。
$root = $all | Where-Object {
    $_.ProcessId -ne $PID -and
    $_.Name -notlike 'powershell*' -and
    $_.Name -notlike 'pwsh*' -and
    $_.Name -notlike 'conhost*' -and
    $_.CommandLine -and $_.CommandLine.Contains($ProfileKey)
}
if (-not $root) { Write-Output "0|0|0"; exit 0 }

$ids = @($root | Select-Object -ExpandProperty ProcessId)
# 递归收子进程（渲染进程、GPU 进程、utility 进程都是子进程）
for ($i = 0; $i -lt 8; $i++) {
    $kids = $all | Where-Object { $ids -contains $_.ParentProcessId -and $ids -notcontains $_.ProcessId }
    if (-not $kids) { break }
    $ids += @($kids | Select-Object -ExpandProperty ProcessId)
}

$ps = Get-Process -Id $ids -ErrorAction SilentlyContinue
if (-not $ps) { Write-Output "0|0|0"; exit 0 }

$cpu = ($ps | ForEach-Object { $_.TotalProcessorTime.TotalSeconds } | Measure-Object -Sum).Sum
$ws  = ($ps | ForEach-Object { $_.WorkingSet64 } | Measure-Object -Sum).Sum
Write-Output ("{0}|{1}|{2}" -f $cpu, @($ps).Count, $ws)
