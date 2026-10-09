# 独立桌宠窗口的入口。双击 pet.bat 或直接跑这个脚本。
#
# 为什么是"独立窗口"而不是仪表盘里的一个卡片：
#   仪表盘要主动打开、还占满屏幕；桌宠的价值在于**一直陪着**。
#   这个窗口无边框、置顶、可拖动，关掉它不影响监督与统计。
param(
    [switch]$Close,
    [switch]$Status,
    [ValidateSet('solid', 'colorkey')][string]$Style = '',
    [int]$Width = 0,
    [int]$Height = 0,
    [int]$X = -1,
    [int]$Y = -1
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
. (Join-Path $root 'lib\common.ps1')
$py = Resolve-Python
if (-not $py) { Show-Msg '找不到 Python，请先运行 setup.ps1'; exit 1 }

$args = @((Join-Path $root 'lib\pet_window.py'))
if ($Close) { $args += '--close' }
elseif ($Status) { $args += '--status' }
else {
    if ($Style) { $args += @('--style', $Style) }
    if ($Width -gt 0) { $args += @('--width', $Width) }
    if ($Height -gt 0) { $args += @('--height', $Height) }
    if ($X -ge 0) { $args += @('--x', $X) }
    if ($Y -ge 0) { $args += @('--y', $Y) }
}

& $py @args
exit $LASTEXITCODE
