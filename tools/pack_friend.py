"""打包"给朋友试试"的分发包：只带运行必需的东西。

与 tools/pack_source.py 的区别：
  - pack_source.py   → 发 GitHub 的**源码包**：含 tests/ 与全部 tools/
  - pack_friend.py   → 发给朋友的**运行包**：不带 tests/，只留两个最实用的排障脚本

两类包都会做密钥扫描，且都不包含 data/。
"""
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
OUT_DIR = ROOT.parent

# 运行必需（整个目录打包）
INCLUDE_DIRS = ["lib", "web", "assets"]

# 运行必需的根目录文件
INCLUDE_ROOT_FILES = [
    "monitor.py", "config.json", "requirements.txt", "LICENSE",
    "setup.ps1", "study-watch.cmd", "dashboard.bat", "dashboard.ps1",
    "launch.ps1", "start.ps1", "start.bat", "start-25min.bat",
    "report.bat", "stop.bat", "stop-watch.ps1",
]

# 只带这两个排障脚本：出现问题朋友自己能看懂，其余工具对使用者没意义
INCLUDE_TOOLS = ["status.py", "list_procs.py"]

# 分发包额外附带的说明文件
EXTRA_FILES = {"使用说明-先看这个.md": "FRIEND_README.md"}

EXCLUDE_SUFFIX = {".pyc", ".pyo", ".tmp", ".bak", ".testbak", ".log", ".pid"}
SECRET_PAT = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")


def collect() -> list[Path]:
    out: list[Path] = []
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT)
            if any(part in {"__pycache__", ".git"} for part in rel.parts):
                continue
            if p.suffix.lower() in EXCLUDE_SUFFIX:
                continue
            out.append(rel)

    for name in INCLUDE_ROOT_FILES:
        p = ROOT / name
        if p.is_file():
            out.append(Path(name))

    for name in INCLUDE_TOOLS:
        p = ROOT / "tools" / name
        if p.is_file():
            out.append(Path("tools") / name)

    return out


def scan(paths: list[Path]) -> list[str]:
    bad = []
    for rel in paths:
        p = ROOT / rel
        if p.suffix.lower() not in {".py", ".ps1", ".bat", ".cmd", ".js", ".html",
                                    ".json", ".md", ".txt"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in SECRET_PAT.finditer(line):
                s = m.group(0)
                if "xxxx" in s.lower() or "your" in line.lower():
                    continue
                bad.append(f"{rel}:{i}  {s[:20]}…")
    return bad


def main() -> int:
    files = collect()
    extra_src = ROOT / "FRIEND_README.md"
    if not extra_src.is_file():
        print(f"✗ 缺少 {extra_src.name}（分发包的使用说明）")
        return 1

    bad = scan(files)
    if bad:
        print("✗ 发现疑似密钥，已中止：")
        for b in bad:
            print("   " + b)
        return 1

    stamp = datetime.now().strftime("%Y%m%d")
    zip_path = OUT_DIR / f"学习监督-给朋友试用-{stamp}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            z.write(ROOT / rel, Path("学习监督") / rel)
        z.write(extra_src, Path("学习监督") / "使用说明-先看这个.md")

    size = zip_path.stat().st_size
    print(f"已打包：{zip_path}")
    print(f"  文件数 {len(files) + 1}｜压缩后 {size / 1024:.0f} KB")
    print(f"  密钥扫描：通过")
    print()
    print("包内清单：")
    for rel in files:
        print(f"  {rel}")
    print("  使用说明-先看这个.md  （由 FRIEND_README.md 生成）")
    print()
    print("刻意未包含：tests/（自测）、大部分 tools/、data/（日志与凭据）、__pycache__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
