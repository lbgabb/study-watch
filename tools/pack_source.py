"""打包发布源码：只收集"会进仓库"的文件，生成 zip 供人工检查。

刻意排除：
  - data/          日志、判定记录、模型原始回复、截图、状态、以及面板里填的 key
  - __pycache__    编译缓存
  - 临时产物       *.tmp / *.bak / *_*.png（排查截图）
打包后会逐项打印清单，并再跑一次密钥扫描。
"""
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
OUT_DIR = ROOT.parent

EXCLUDE_DIRS = {"data", "__pycache__", ".git", ".idea", ".vscode", "venv", ".venv"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".tmp", ".bak", ".testbak", ".log", ".pid"}

SECRET_PAT = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")


def collect() -> list[Path]:
    out = []
    for p in sorted(ROOT.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in EXCLUDE_SUFFIX:
            continue
        if p.name.startswith("_") and p.suffix.lower() == ".png":
            continue
        if p.name.endswith(".json.testbak"):
            continue
        if p == SELF:
            continue
        out.append(rel)
    return out


def scan(paths: list[Path]) -> list[str]:
    """对将打包的文本文件再扫一遍密钥。"""
    bad = []
    for rel in paths:
        p = ROOT / rel
        if p.suffix.lower() not in {".py", ".ps1", ".bat", ".cmd", ".js", ".html",
                                    ".json", ".md", ".txt", ".yml", ".yaml", ".toml"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in SECRET_PAT.finditer(line):
                s = m.group(0)
                # 文档里的占位符不算
                if "xxxx" in s.lower() or s.endswith("xxxx") or "your" in line.lower():
                    continue
                bad.append(f"{rel}:{i}  {s[:20]}…")
    return bad


def main() -> int:
    files = collect()
    stamp = datetime.now().strftime("%Y%m%d")
    zip_path = OUT_DIR / f"study-watch-src-{stamp}.zip"

    bad = scan(files)
    if bad:
        print("✗ 发现疑似密钥，已中止打包：")
        for b in bad:
            print("   " + b)
        return 1

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(ROOT / rel, Path("study-watch") / rel)

    size = zip_path.stat().st_size
    print(f"已打包：{zip_path}")
    print(f"  文件数 {len(files)}｜压缩后 {size / 1024:.0f} KB")
    print(f"  密钥扫描：通过（{len(files)} 个文件无命中）")
    print()
    print("包含的文件：")
    for rel in files:
        print(f"  {rel}")
    print()
    print("已排除：data/（日志与凭据）、__pycache__、*.tmp/*.bak、排查用截图")
    return 0


if __name__ == "__main__":
    sys.exit(main())
