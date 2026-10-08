# 在桌面创建「学习监督」快捷方式（可重复运行，会覆盖旧的）
$ErrorActionPreference = 'Stop'
# 本脚本位于 tools\ 下，项目根目录是它的上一级
$here = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop '学习监督.lnk'
$icon = Join-Path $here 'assets\study-watch.ico'
$target = Join-Path $here 'study-watch.cmd'

if (-not (Test-Path $target)) { throw "找不到启动器：$target" }
if (-not (Test-Path $icon)) { throw "找不到图标：$icon（可运行 python -m lib.icon 重新生成）" }

$sh = New-Object -ComObject WScript.Shell
$sc = $sh.CreateShortcut($link)
$sc.TargetPath = $target
$sc.WorkingDirectory = $here
$sc.IconLocation = "$icon,0"
$sc.Description = '学习监督：每 3 分钟截屏判断你是否在学习，分心会弹窗提醒'
$sc.WindowStyle = 1
$sc.Save()

Start-Sleep -Milliseconds 300
if (Test-Path $link) {
    $v = $sh.CreateShortcut($link)
    Write-Host "已创建：$link"
    Write-Host "  目标      : $($v.TargetPath)"
    Write-Host "  起始位置  : $($v.WorkingDirectory)"
    Write-Host "  图标      : $($v.IconLocation)"
    Write-Host "  说明      : $($v.Description)"
} else {
    throw "快捷方式创建失败"
}
