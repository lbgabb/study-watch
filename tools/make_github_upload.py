"""生成"可直接拖到 GitHub 网页上传"的文件夹。

为什么不用 zip：GitHub 网页版上传是把你拖进去的**文件夹内容当作仓库根**，
所以需要一份摊平的目录（顶层就是 monitor.py / lib / web ...），
而不是 zip 里那种多套一层 `study-watch/` 的结构。

另外顺手生成 .gitattributes 处理换行符，避免以后在 Linux/Mac 上 clone 时
脚本被改成 LF 而出现奇怪问题。
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_ZIP_CONTENT = ROOT          # 直接从工作区取文件，保证是最新的
DEST = Path(r"E:\ds\github-upload")

EXCLUDE_DIRS = {"data", "__pycache__", ".git", ".venv", "venv", ".idea", ".vscode"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".tmp", ".bak", ".testbak", ".log", ".pid"}
INCLUDE_DIRS = ["lib", "web", "assets", "tests", "tools"]
INCLUDE_ROOT = [
    ".gitignore", "LICENSE", "README.md", "requirements.txt", "config.json",
    "monitor.py", "setup.ps1", "selftest.ps1", "selftest.bat",
    "study-watch.cmd", "dashboard.bat", "dashboard.ps1", "launch.ps1",
    "start.ps1", "start.bat", "start-25min.bat",
    "report.bat", "stop.bat", "stop-watch.ps1", "run.ps1",
]

GITATTRIBUTES = """# 脚本必须保持 CRLF：Windows 的 .cmd/.bat 与 PowerShell 脚本都按本地换行解读，
# 在 Linux/Mac 上被改成 LF 后，回车符丢失会导致批处理行为异常。
*.cmd  text eol=crlf
*.bat  text eol=crlf
*.ps1  text eol=crlf

# 文本文件正常按 LF 存储即可
*.py   text
*.js   text
*.html text
*.json text
*.md   text

# 二进制资源不做换行转换
*.ico  binary
*.png  binary
"""


def main() -> int:
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    copied = 0
    for d in INCLUDE_DIRS:
        src = SRC_ZIP_CONTENT / d
        if not src.is_dir():
            continue
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(src)
            if any(part in EXCLUDE_DIRS for part in rel.parts):
                continue
            if p.suffix.lower() in EXCLUDE_SUFFIX:
                continue
            if p.name.startswith("_") and p.suffix.lower() == ".png":
                continue
            target = DEST / d / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            copied += 1

    for name in INCLUDE_ROOT:
        src = SRC_ZIP_CONTENT / name
        if src.is_file():
            shutil.copy2(src, DEST / name)
            copied += 1

    (DEST / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")
    copied += 1

    # 逐项列出，方便人工核对
    print(f"已生成：{DEST}")
    print(f"  共 {copied} 个文件")
    print()
    print("顶层内容（拖进 GitHub 时这些就是仓库根）：")
    for p in sorted(DEST.iterdir()):
        kind = "目录" if p.is_dir() else "文件"
        if p.is_dir():
            n = len(list(p.rglob("*")))
            print(f"  [{kind}] {p.name}/  （{n} 项）")
        else:
            print(f"  [{kind}] {p.name}")
    print()
    print("确认没有 data/ 与凭据：")
    print(f"  data/ 存在？ {(DEST / 'data').exists()}")
    print(f"  secrets.json 存在？ {any(DEST.rglob('secrets.json'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
