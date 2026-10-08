"""统一脚本编码，避免中文被系统 ANSI 代码页（GBK）解码成乱码。

结论（实测）：
- .ps1  **必须** UTF-8 with BOM：PowerShell 5.1 靠 BOM 才能认出 UTF-8，
        否则中文注释会被按 GBK 拆字节，连引号配对都被破坏、直接语法报错。
- .cmd/.bat **必须不要** BOM：cmd.exe 在解析 chcp 之前就按 ANSI 读文件，
        行首的 BOM 字节会让第一行 "@echo off" 失效（乱码被当命令执行）。
        所以批处理里不宜放中文，UI 文案交给 PowerShell。

用法：
    python tools/fix_script_encoding.py           # 修正
    python tools/fix_script_encoding.py --check   # 只检查，有问题就返回非 0

--check 用在自测里：这个坑踩过两次（都是用脚本改文件时把 BOM 写掉了），
所以让流水线自己报错，而不是靠人记得跑一次修正。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    ps1, bat = [], []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix not in {".ps1", ".cmd", ".bat"}:
            continue
        raw = p.read_bytes()
        has_bom = raw.startswith(BOM)
        try:
            text = raw[3:].decode("utf-8") if has_bom else raw.decode("utf-8")
        except UnicodeDecodeError:
            print(f"[警告] {p.relative_to(ROOT)} 不是 UTF-8，跳过（请手动检查）")
            continue

        if suffix == ".ps1":
            if not has_bom:
                if check_only:
                    ps1.append(p.relative_to(ROOT))
                else:
                    p.write_bytes(BOM + text.encode("utf-8"))
                    ps1.append(p.relative_to(ROOT))
        else:
            if has_bom:
                if check_only:
                    bat.append(p.relative_to(ROOT))
                else:
                    p.write_bytes(text.encode("utf-8"))
                    bat.append(p.relative_to(ROOT))

    if check_only:
        bad = 0
        for r in ps1:
            print(f"  [失败] {r} 缺少 BOM —— PowerShell 5.1 会把中文按 GBK 解码而报错")
            bad += 1
        for r in bat:
            print(f"  [失败] {r} 有多余 BOM —— cmd.exe 会让首行 @echo off 失效")
            bad += 1
        if not bad:
            print("  [通过] 所有 .ps1 都带 BOM，所有 .cmd/.bat 都没有 BOM")
            return 0
        print(f"\n  {bad} 个文件编码不对，跑一次 python tools/fix_script_encoding.py 修正")
        return 1

    for r in ps1:
        print(f"[.ps1 加 BOM ] {r}")
    for r in bat:
        print(f"[.bat 去 BOM ] {r}")
    if not ps1 and not bat:
        print("所有脚本编码都已正确，无需改动")
    else:
        print(f"\n修正 {len(ps1) + len(bat)} 个文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())

