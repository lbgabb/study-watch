# 学习监督 - 共用函数（被 start.ps1 / dashboard.ps1 / selftest.ps1 等 dot-source 调用）
# 注意：本文件必须保存为 UTF-8 with BOM，否则 PowerShell 5.1 会把中文按 GBK 解码。

function Resolve-Python {
    <#
    找 Python 解释器。顺序：
      1. 项目根目录下的 py-path.txt（第一行写解释器完整路径）
         —— 给自己用的本地配置，已列入 .gitignore，不会进仓库
      2. 常见安装位置：扫 LOCALAPPDATA / Program Files 下的 Python3x 目录
         **优先挑已经装了 Pillow 的那个**，其次取版本号最高的。
         一台机器上装了两个 Python 时，没依赖的那个跑不起来，所以要挑能用的。
      3. PATH 里的 python
    #>
    function Test-HasPillow([string]$exe) {
        if (-not $exe) { return $false }
        try {
            & $exe -c "import PIL" 2>$null | Out-Null
            return ($LASTEXITCODE -eq 0)
        } catch {
            return $false
        }
    }

    function Select-BestPython($list) {
        $cands = @($list | Where-Object { $_ } | Select-Object -Unique)
        if (-not $cands) { return $null }
        $withPil = @($cands | Where-Object { Test-HasPillow $_ })
        $pool = if ($withPil.Count -gt 0) { $withPil } else { $cands }
        # 路径名里带版本号（Python312 / Python311），降序取第一个即最高版本
        return ($pool | Sort-Object -Descending | Select-Object -First 1)
    }

    # 1) 本地固定路径：显式指定就用它，不再挑
    if ($script:Root) {
        $cfg = Join-Path $script:Root 'py-path.txt'
        if (Test-Path $cfg) {
            $first = Get-Content -LiteralPath $cfg -TotalCount 1 -ErrorAction SilentlyContinue
            if ($first) {
                $p = $first.Trim().Trim('"')
                if ($p -and (Test-Path $p)) { return $p }
                Write-Host "提示：py-path.txt 里的路径不存在（$p），改为自动查找。" -ForegroundColor Yellow
            }
        }
    }

    # 2) 扫常见安装位置
    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        'C:\'
    ) | Where-Object { $_ -and (Test-Path $_) }

    $found = @()
    foreach ($r in $roots) {
        $found += @(Get-ChildItem -Path $r -Filter 'Python3*' -Directory -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName 'python.exe' } |
            Where-Object { Test-Path $_ })
    }
    $best = Select-BestPython $found
    if ($best) { return $best }

    # 3) PATH
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    return $null
}

# 保留旧名字，避免已有脚本报错
function Get-PythonPath { return Resolve-Python }

function Test-PidAlive([int]$ProcessId) {
    if ($ProcessId -le 0) { return $false }
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        return -not $p.HasExited
    } catch {
        return $false
    }
}

function Get-RunningWatch {
    # 只认真正活着、且命令行里带 monitor.py 的进程（避免把已退出的进程当成"在监督"）
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*monitor.py*' -and (Test-PidAlive $_.ProcessId) }
}

function Show-Msg([string]$text, [string]$title, [int]$seconds = 8) {
    try {
        $w = New-Object -ComObject WScript.Shell
        $w.Popup($text, $seconds, $title, 64) | Out-Null   # 64 = 信息图标
    } catch {
        Write-Host $text
    }
}

function Get-IntervalSec {
    $cfg = Get-Content -LiteralPath (Join-Path $script:Root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    return [int]$cfg.interval_sec
}
