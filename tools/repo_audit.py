"""发布前审计：扫描某个目录里将要公开的文件，找密钥与个人路径。

用法：
    python tools/repo_audit.py                 # 默认扫项目根目录
    python tools/repo_audit.py <某个目录>       # 例如准备上传 GitHub 的文件夹

检查三类问题：
  1. 真实密钥（sk- 开头的长串、key=、JWT）
  2. 硬编码的个人路径（C:\\Users\\某人、本机的固定盘符）
  3. 不该进仓库的东西（data/、secrets.json、日志、__pycache__）

退出码非 0 表示发现问题，可直接用在发布脚本里做闸门。
"""
import argparse
import re
import sys
from pathlib import Path

TEXT_EXT = {".py", ".ps1", ".bat", ".cmd", ".js", ".html", ".css", ".json",
            ".md", ".txt", ".yml", ".yaml", ".toml", ".cfg", ".ini",
            ".gitignore", ".gitattributes"}

SECRET_PATTERNS = [
    (r"sk-[A-Za-z0-9_\-]{16,}", "疑似 API key（sk- 开头长串）"),
    (r"(?i)(api[_-]?key|apikey|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{16,}['\"]",
     "疑似硬编码凭据"),
    (r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "疑似 JWT"),
]
PERSONAL_PATTERNS = [
    (r"[A-Za-z]:\\Users\\[A-Za-z0-9._\-]+", "硬编码的用户目录"),
    (r"dsh-runtimes", "指向作者本机 DSH 运行时的路径"),
]
# 这些名字出现在待发布目录里就直接报警
FORBIDDEN_NAMES = {"secrets.json", "monitor.pid", "paused", "desired_running",
                   "start.lock", "state.json", "watch.log"}
FORBIDDEN_DIRS = {"data", "__pycache__", ".venv", "venv", "node_modules"}

# 本来就只存在于本机、且已被 .gitignore 排除的文件：
# 它们含本机路径是正常的，不该报"个人路径泄漏"
LOCAL_ONLY_FILES = {"py-path.txt"}

# 这个工具自身的源码里必然出现要匹配的模式，跳过自己
SELF_NAME = "repo_audit.py"


def is_gitignored(root: Path, rel: Path) -> bool:
    """粗略判断是否被 .gitignore 排除（只处理最常见的顶层条目）。"""
    gi = root / ".gitignore"
    if not gi.is_file():
        return False
    try:
        lines = gi.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False
    parts = rel.parts
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        entry = line.rstrip("/").lstrip("/")
        if not entry or any(ch in entry for ch in "*?["):
            continue
        if entry in parts:
            return True
    return False


def looks_like_placeholder(line: str, hit: str) -> bool:
    low = (line + hit).lower()
    return any(k in low for k in ("xxxx", "your_", "your-", "placeholder", "example",
                                  "fake", "not-real", "<你的"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=None, help="要审计的目录（默认项目根）")
    ap.add_argument("--verbose", action="store_true", help="列出被忽略的本机文件")
    args = ap.parse_args()

    root = Path(args.path).resolve() if args.path else Path(__file__).resolve().parents[1]
    if not root.is_dir():
        print(f"不是目录：{root}")
        return 2

    print("=" * 72)
    print(f"发布前审计：{root}")
    print("=" * 72)

    secrets: list[str] = []
    personal: list[str] = []
    forbidden: list[str] = []
    skipped_local: list[str] = []
    n_files = 0
    bad_dirs: set[str] = set()

    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        # data/ 这类目录只报一次，不逐个文件刷屏
        hit_dir = next((d for d in FORBIDDEN_DIRS if d in rel.parts), None)
        if hit_dir:
            bad_dirs.add(hit_dir)
            continue

        if p.name in LOCAL_ONLY_FILES:
            skipped_local.append(str(rel))
            continue

        if not p.is_file():
            continue
        n_files += 1
        if p.name == SELF_NAME:
            continue
        if p.name in FORBIDDEN_NAMES:
            if is_gitignored(root, rel):
                skipped_local.append(str(rel))
                continue
            forbidden.append(f"{rel}（运行数据/凭据，且未被 .gitignore 排除）")
        if p.suffix.lower() not in TEXT_EXT and p.name not in {".gitignore", ".gitattributes"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat, why in SECRET_PATTERNS:
                for m in re.finditer(pat, line):
                    if looks_like_placeholder(line, m.group(0)):
                        continue
                    secrets.append(f"{rel}:{i}  {why}  -> {m.group(0)[:24]}…")
            for pat, why in PERSONAL_PATTERNS:
                for m in re.finditer(pat, line):
                    personal.append(f"{rel}:{i}  {why}  -> {m.group(0)[:60]}")

    print(f"\n[1] 扫描了 {n_files} 个文件")
    if skipped_local:
        print(f"    跳过 {len(skipped_local)} 个本机专用文件（已在 .gitignore 里，不会上传）")
        if args.verbose:
            for s in skipped_local:
                print(f"      {s}")

    print(f"\n[2] 密钥/凭据：{len(secrets)} 处")
    for s in secrets:
        print("    " + s)

    print(f"\n[3] 个人路径：{len(personal)} 处")
    for s in personal[:15]:
        print("    " + s)
    if len(personal) > 15:
        print(f"    …另有 {len(personal) - 15} 处")
    if personal:
        print("    提示：$env:USERPROFILE 这类环境变量写法不算问题；写死用户名才需要处理。")

    print(f"\n[4] 不该发布的内容：{len(forbidden) + len(bad_dirs)} 处")
    for d in sorted(bad_dirs):
        print(f"    {d}/（整个目录都应排除）")
    for s in forbidden[:15]:
        print("    " + s)
    if len(forbidden) > 15:
        print(f"    …另有 {len(forbidden) - 15} 处")
    print("    说明：只按\"是否会进仓库\"判断 —— 有 .gitignore 覆盖的会被跳过。")

    fatal = bool(secrets) or bool(forbidden)
    print("\n[5] 结论")
    if fatal:
        print("    ✗ 有必须先处理的问题（密钥或不该发布的内容）")
    elif personal:
        print("    ⚠ 没有密钥，但有个人路径 —— 请人工确认是否可接受")
    else:
        print("    ✓ 干净：没有密钥、没有个人路径、没有会误发布的运行数据")
    return 1 if fatal else 0


if __name__ == "__main__":
    sys.exit(main())
