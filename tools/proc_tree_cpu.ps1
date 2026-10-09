# 量一个浏览器实例（及其子进程）的累计 CPU 时间与工作集。
#
# 为什么不按进程名量：这台机器上同时开着用户自己的 Edge（几十个 msedge 进程），
# 按名字统计会把用户的浏览行为算进来，量出来的是"用户在干什么"，不是桌宠开销。
# 所以按**唯一的 --user-data-dir** 定位：无头实例用的是临时 profile 目录，
# 这个字符串就是它的指纹。找到根进程后再递归收子进程。
#
# 输出：<累计CPU秒>|<进程数>|<工作集字节>
param([Parameter(Mandatory=$true)][string]$ProfileKey)

$all = Get-CimInstance Win32_Process
$root = $all | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($ProfileKey) }
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
