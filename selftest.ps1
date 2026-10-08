# 一键跑全部自测，并汇总结果
$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
. (Join-Path $script:Root 'lib\common.ps1')

if (-not (Test-Path (Join-Path $script:Root 'tests'))) {
    Write-Host "这个分发包里没有 tests\ 目录（精简版），自测脚本不适用。" -ForegroundColor Yellow
    Write-Host "想验证运行是否正常，请用这两条："
    Write-Host "  python monitor.py --status      体检：进程/服务/配置"
    Write-Host "  python monitor.py --dry-run     截图链路（不调用 API、不花钱）"
    exit 0
}

$python = Get-PythonPath
if (-not $python) { Write-Host "未找到 Python。" -ForegroundColor Red; exit 2 }

$steps = @(
    @{ Name = 'JSON 解析健壮性（畸形输出修补）'; Script = 'tests\test_json_repair.py' },
    @{ Name = '服务商兼容性（降级链与报错提示）';  Script = 'tests\test_provider_compat.py' },
    @{ Name = '截图策略（按前台应用分配截图）';   Script = 'tests\test_policy.py' },
    @{ Name = '日报聚合与时长折算';             Script = 'tests\test_report.py' },
    @{ Name = '提醒窗渲染（PrintWindow 结构判定）'; Script = 'tests\test_popup_shot.py' },
    @{ Name = '仪表盘 API 与启停控制';          Script = 'tests\test_server.py' },
    @{ Name = '设置读写（校验/白名单/还原）';    Script = 'tests\test_config_api.py' },
    @{ Name = '控制面板流程（开/暂停/恢复/停）'; Script = 'tests\control_flow.py' },
    @{ Name = '服务韧性（监控被杀后自动拉起）';  Script = 'tests\test_recovery.py --port 0' },
    @{ Name = '用户意图（停止后不被刷新拉起）';  Script = 'tests\test_intent.py --port 0' },
    @{ Name = '状态接口只读性（轮询无副作用）';  Script = 'tests\test_readonly_status.py --port 0' },
    @{ Name = '跨进程启动互斥（只起一个监控）';  Script = 'tests\test_cross_process_lock.py' },
    @{ Name = '截图与前台窗口采集（不调用 API）'; Script = 'monitor.py --dry-run' }
)

$results = @()
$i = 0
foreach ($step in $steps) {
    $i++
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $i, $steps.Count, $step.Name) -ForegroundColor Cyan
    Write-Host ("-" * 60) -ForegroundColor DarkGray

    $parts = $step.Script.Split(' ')
    $exe = $parts[0]
    $exeArgs = @()
    if ($parts.Count -gt 1) { $exeArgs = $parts[1..($parts.Count - 1)] }

    & $python (Join-Path $script:Root $exe) @exeArgs
    $code = $LASTEXITCODE
    $results += [pscustomobject]@{ Name = $step.Name; Code = $code }
}

Write-Host ""
Write-Host ("=" * 60) -ForegroundColor DarkGray
Write-Host "自测汇总" -ForegroundColor Cyan
$failed = 0
foreach ($r in $results) {
    if ($r.Code -eq 0) {
        Write-Host ("  [通过] {0}" -f $r.Name) -ForegroundColor Green
    } else {
        Write-Host ("  [失败] {0}（退出码 {1}）" -f $r.Name, $r.Code) -ForegroundColor Red
        $failed++
    }
}
Write-Host ""
if ($failed -eq 0) {
    Write-Host "全部通过。提醒窗外观已保存在 data\popup-check.png" -ForegroundColor Green
} else {
    Write-Host "$failed 项失败，请看上面的输出。" -ForegroundColor Red
}
exit $failed
