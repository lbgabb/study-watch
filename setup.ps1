# 学习监督 - 新机器一键部署
# 做四件事：找 Python -> 检查依赖 -> 检查 API key -> 生成图标与桌面快捷方式
# 用法：powershell -ExecutionPolicy Bypass -File .\setup.ps1
#      powershell -ExecutionPolicy Bypass -File .\setup.ps1 -NoShortcut
param([switch]$NoShortcut)

$ErrorActionPreference = 'Stop'
$script:Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ok = 0
$warn = 0
$fail = 0

function Say([string]$s) { Write-Host $s }
function Good([string]$s) { Write-Host "  [OK]   $s" -ForegroundColor Green; $script:ok++ }
function Warn([string]$s) { Write-Host "  [注意] $s" -ForegroundColor Yellow; $script:warn++ }
function Bad([string]$s)  { Write-Host "  [失败] $s" -ForegroundColor Red; $script:fail++ }

Say "=== 学习监督 · 环境检查与部署 ==="
Say "项目目录：$script:Root"
Say ""

# ---------- 1) Windows ----------
Say "[1/5] 系统"
if ($env:OS -eq 'Windows_NT') {
    Good "Windows（这个工具依赖 user32/gdi32 与 tkinter，只能在 Windows 上跑）"
} else {
    Bad "不是 Windows，无法运行"
    exit 1
}

# ---------- 2) Python ----------
Say ""
Say "[2/5] Python"
. (Join-Path $script:Root 'lib\common.ps1')
$python = Resolve-Python
if (-not $python) {
    Bad ("没有找到 Python。请先装 Python 3.10+（安装时勾选 Add to PATH），`n" +
         "         或者在项目目录下建一个 py-path.txt，第一行写解释器完整路径")
} else {
    $ver = & $python -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
    Good "找到 Python $ver ：$python"
    $major = [int](& $python -c "import sys; print(sys.version_info[0])")
    $minor = [int](& $python -c "import sys; print(sys.version_info[1])")
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Bad "版本太低（需要 3.10+，因为用到了 X | Y 类型标注语法）"
    }
}

if (-not $python) {
    Say ""
    Say "Python 是硬依赖，先装好再回来跑这个脚本。"
    exit 1
}

# ---------- 3) 依赖模块 ----------
Say ""
Say "[3/5] Python 依赖"
$script:missingRequired = @()
function Test-Module([string]$name, [string]$why, [switch]$Required) {
    # 关键：$ErrorActionPreference='Stop' 会把子进程的 stderr 当成终止错误，
    # 而"import 失败"正好会往 stderr 写 traceback —— 必须先临时放宽，
    # 否则缺依赖时脚本会直接崩掉（这恰恰是最常见的情况）。
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $null = & $python -c "import $name" 2>&1
        $code = $LASTEXITCODE
    } catch {
        $code = 1
    } finally {
        $ErrorActionPreference = $prev
    }

    if ($code -eq 0) { Good "$name（$why）" }
    elseif ($Required) {
        Bad "$name 缺失（$why）"
        $script:missingRequired += $name
    } else {
        Warn "$name 缺失（$why）—— 功能会降级"
    }
}
Test-Module "PIL" "截图与 JPEG 编码，必需" -Required
Test-Module "tkinter" "置顶提醒窗"
Test-Module "winsound" "提示音"

# 缺必需依赖时给出可直接照抄的安装命令，并尝试自动装
if ($script:missingRequired.Count -gt 0) {
    Say ""
    Say "  缺少必需的 Python 包，正在尝试自动安装…"
    $pkgs = @($script:missingRequired | ForEach-Object { if ($_ -eq 'PIL') { 'pillow' } else { $_ } })
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'

    function Try-PipInstall([string[]]$extra) {
        $base = @('-m', 'pip', 'install', '--disable-pip-version-check',
                  '--retries', '3', '--timeout', '60', '--quiet') + $extra + $pkgs
        $null = & $python @base 2>&1
        if ($LASTEXITCODE -ne 0) { return $false }
        $null = & $python -c "import PIL" 2>&1
        return ($LASTEXITCODE -eq 0)
    }

    try {
        $okNow = Try-PipInstall @()
        if (-not $okNow) {
            # 国内直连 PyPI 经常超时，换镜像再试
            Say "    默认源没成功（国内网络超时很常见），改用清华镜像重试…"
            $okNow = Try-PipInstall @('-i', 'https://pypi.tuna.tsinghua.edu.cn/simple')
        }
        if (-not $okNow) {
            $okNow = Try-PipInstall @('-i', 'https://mirrors.aliyun.com/pypi/simple/')
        }
    } catch {
        $okNow = $false
    } finally {
        $ErrorActionPreference = $prev
    }

    if ($okNow) {
        Good "已自动装好：$($pkgs -join ', ')"
    } else {
        Bad "自动安装没成功（多半是网络），请手动执行其中一行，然后重跑本脚本："
        Say ""
        Say "    `"$python`" -m pip install $($pkgs -join ' ')"
        Say "    `"$python`" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple $($pkgs -join ' ')"
        Say ""
        Say "  第二行走清华镜像，国内网络更稳。"
        Say "  若提示 pip 不存在，先执行：`"$python`" -m ensurepip --upgrade"
        Say ""
    }
}

# ---------- 4) API key ----------
Say ""
Say "[4/5] API key（用来调用视觉模型）"
$envKey = $env:DEEPSEEK_API_KEY
$credFile = Join-Path $env:USERPROFILE ".dsh\.credentials.yaml"
if ($envKey) {
    Good "环境变量 DEEPSEEK_API_KEY 已设置（长度 $($envKey.Length)）"
} elseif (Test-Path $credFile) {
    $hit = Select-String -Path $credFile -Pattern 'DEEPSEEK_API_KEY:\s*sk-' -ErrorAction SilentlyContinue
    if ($hit) { Good "从 $credFile 读到了 DEEPSEEK_API_KEY" }
    else { Warn "$credFile 里没有 DEEPSEEK_API_KEY" }
} else {
    Warn "没找到 key。两种配法："
    Say  "          1) 设环境变量：setx DEEPSEEK_API_KEY sk-xxxx"
    Say  "          2) 建 $credFile，内容：refs:`n               DEEPSEEK_API_KEY: sk-xxxx"
}

# ---------- 5) 图标与快捷方式 ----------
Say ""
Say "[5/5] 图标与桌面快捷方式"
$icon = Join-Path $script:Root 'assets\study-watch.ico'
if (-not (Test-Path $icon)) {
    Say "  图标不存在，正在生成…"
    & $python -m lib.icon --assets (Join-Path $script:Root 'assets')
    if (Test-Path $icon) { Good "已生成图标" } else { Warn "图标生成失败（不影响核心功能，只是快捷方式没图标）" }
} else {
    Good "图标已存在"
}

if ($NoShortcut) {
    Warn "按参数要求跳过了快捷方式"
} else {
    $mk = Join-Path $script:Root 'tools\make_shortcut.ps1'
    if (Test-Path $mk) {
        try {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $mk | Out-Null
            & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $script:Root 'tools\make_shortcut_dashboard.ps1') | Out-Null
            $desk = [Environment]::GetFolderPath('Desktop')
            if (Test-Path (Join-Path $desk '学习监督.lnk')) { Good "已创建桌面快捷方式「学习监督」" }
            else { Warn "快捷方式创建失败（可手动运行 tools\make_shortcut.ps1）" }
        } catch {
            Warn "创建快捷方式出错：$($_.Exception.Message)"
        }
    } else {
        # 精简分发包（不含 tools/）走这条：用内置逻辑建快捷方式
        try {
            $desk = [Environment]::GetFolderPath('Desktop')
            $sh = New-Object -ComObject WScript.Shell
            $pairs = @(
                @{ Name = '学习监督'; Target = 'study-watch.cmd';
                   Desc = '学习监督：每隔几分钟截屏判断你是否在学习，分心会弹窗提醒' },
                @{ Name = '学习监督 仪表盘'; Target = 'dashboard.bat';
                   Desc = '学习监督仪表盘：看今日时间轴、专注率、分心来源，并能启停监督' }
            )
            foreach ($p in $pairs) {
                $t = Join-Path $script:Root $p.Target
                if (-not (Test-Path $t)) { Warn "$($p.Target) 不存在，跳过快捷方式「$($p.Name)」"; continue }
                $lnk = Join-Path $desk ($p.Name + '.lnk')
                $sc = $sh.CreateShortcut($lnk)
                $sc.TargetPath = $t
                $sc.WorkingDirectory = $script:Root
                if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
                $sc.Description = $p.Desc
                $sc.Save()
                Good "已创建桌面快捷方式「$($p.Name)」"
            }
        } catch {
            Warn "创建快捷方式出错（可手动把 study-watch.cmd 发送到桌面）：$($_.Exception.Message)"
        }
    }
}

# ---------- 自检 ----------
Say ""
Say "=== 冒烟测试（不调用 API、不花钱）==="
Push-Location $script:Root
try {
    $out = & $python monitor.py --dry-run 2>&1 | Out-String
    if ($out -match 'dry_run') { Good "截图链路正常（$($out.Split("`n")[0].Trim())）" }
    else { Bad "截图链路异常：$($out.Trim().Substring(0, [Math]::Min(200, $out.Trim().Length)))" }
} finally { Pop-Location }

Say ""
Say "=== 结果：$ok 项正常 / $warn 项注意 / $fail 项失败 ==="
if ($fail -eq 0) {
    Say ""
    Say "可以用了："
    Say "  1) 双击桌面「学习监督」开始监督"
    Say "  2) 双击桌面「学习监督 仪表盘」看数据（默认 http://127.0.0.1:8770/）"
    Say "  3) 命令行体检：python monitor.py --status"
    Say "  4) 完整自测：.\selftest.bat"
} else {
    Say ""
    Say "先解决上面的失败项，再跑一次本脚本。" -ForegroundColor Red
}
exit $fail
