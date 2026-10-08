# 修复并刷新两个桌面快捷方式的图标。
# 处理两件事：
#   1) 重建快捷方式，确保 IconLocation 指向存在的 .ico（绝对路径）
#   2) 清掉 Windows 图标缓存并让 explorer 重画（图标改过但桌面还显示旧图标时必做）
$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$desktop = [Environment]::GetFolderPath('Desktop')
$icon = Join-Path $here 'assets\study-watch.ico'

if (-not (Test-Path $icon)) { throw "找不到图标文件：$icon" }

Write-Host "图标文件：$icon" -ForegroundColor Cyan
Write-Host ("  大小 {0} 字节，修改时间 {1}" -f (Get-Item $icon).Length, (Get-Item $icon).LastWriteTime)

# ---- 1) 重建快捷方式 ----
$sh = New-Object -ComObject WScript.Shell
$defs = @(
    @{ Name = '学习监督';        Target = 'study-watch.cmd'; Desc = '学习监督：每 3 分钟截屏判断你是否在学习，分心会弹窗提醒' },
    @{ Name = '学习监督 仪表盘'; Target = 'dashboard.bat';   Desc = '学习监督仪表盘：看今日时间轴、专注率、分心来源，并能启停监督' }
)

foreach ($d in $defs) {
    $target = Join-Path $here $d.Target
    if (-not (Test-Path $target)) { throw "找不到启动器：$target" }
    $link = Join-Path $desktop ($d.Name + '.lnk')
    $sc = $sh.CreateShortcut($link)
    $sc.TargetPath = $target
    $sc.WorkingDirectory = $here
    $sc.IconLocation = "$icon,0"
    $sc.Description = $d.Desc
    $sc.WindowStyle = 1
    $sc.Save()
    Write-Host "已重建：$link" -ForegroundColor Green
}

# ---- 2) 刷新图标缓存 ----
Write-Host ""
Write-Host "正在清理 Windows 图标缓存（会短暂重启资源管理器）…" -ForegroundColor Cyan

$explorer = Get-Process explorer -ErrorAction SilentlyContinue
if ($explorer) {
    Stop-Process -Id $explorer.Id -Force
    Start-Sleep -Seconds 2
    Write-Host "  已停止 explorer，等待它自动重启…"
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
        if (Get-Process explorer -ErrorAction SilentlyContinue) { break }
    }
    if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) {
        Start-Process explorer.exe
        Start-Sleep -Seconds 2
        Write-Host "  explorer 未自动重启，已手动拉起"
    } else {
        Write-Host "  explorer 已重启"
    }
}

# 删除图标缓存数据库（explorer 停止时才能删干净）
$cacheDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer'
$removed = 0
if (Test-Path $cacheDir) {
    Get-ChildItem $cacheDir -Filter 'iconcache*.db' -Force -ErrorAction SilentlyContinue | ForEach-Object {
        try { Remove-Item $_.FullName -Force -ErrorAction Stop; $removed++ }
        catch { Write-Host ("  跳过（占用中）：{0}" -f $_.Name) -ForegroundColor DarkYellow }
    }
}
Write-Host ("  已删除 {0} 个 iconcache 数据库文件" -f $removed)

# 让 Shell 重新广播图标变更
try { & ie4uinit.exe -show } catch { }
try { & ie4uinit.exe -ClearIconCache } catch { }
Write-Host "  已触发图标缓存重建"

# ---- 3) 结果确认 ----
Write-Host ""
Write-Host "结果：" -ForegroundColor Cyan
foreach ($d in $defs) {
    $link = Join-Path $desktop ($d.Name + '.lnk')
    $v = $sh.CreateShortcut($link)
    $iconOk = Test-Path ($v.IconLocation -replace ',\d+$', '')
    Write-Host ("  {0}.lnk" -f $d.Name)
    Write-Host ("    目标 {0}" -f $v.TargetPath)
    Write-Host ("    图标 {0}  文件存在={1}" -f $v.IconLocation, $iconOk)
}
Write-Host ""
Write-Host "如果桌面上的图标还是旧的：在桌面按 F5 刷新一次；若仍不对，注销后重新登录必定生效。" -ForegroundColor Yellow
