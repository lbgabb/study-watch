# 在桌面创建「学习监督 仪表盘」快捷方式（可重复运行）
$ErrorActionPreference = 'Stop'
# 本脚本位于 tools\ 下，项目根目录是它的上一级
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$desktop = [Environment]::GetFolderPath('Desktop')
$icon = Join-Path $here 'assets\study-watch.ico'
$target = Join-Path $here 'dashboard.bat'

if (-not (Test-Path $target)) { throw "找不到启动器：$target" }
if (-not (Test-Path $icon)) { throw "找不到图标：$icon（可运行 python -m lib.icon 重新生成）" }

$sh = New-Object -ComObject WScript.Shell
$link = Join-Path $desktop '学习监督 仪表盘.lnk'
$sc = $sh.CreateShortcut($link)
$sc.TargetPath = $target
$sc.WorkingDirectory = $here
$sc.IconLocation = "$icon,0"
$sc.Description = '学习监督仪表盘：看今日时间轴、专注率、分心来源，并能启停监督'
$sc.WindowStyle = 1
$sc.Save()

Start-Sleep -Milliseconds 300
if (Test-Path $link) {
    $v = $sh.CreateShortcut($link)
    Write-Host "已创建：$link"
    Write-Host "  目标     : $($v.TargetPath)"
    Write-Host "  起始位置 : $($v.WorkingDirectory)"
    Write-Host "  图标     : $($v.IconLocation)"
} else {
    throw "快捷方式创建失败"
}
