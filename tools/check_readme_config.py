"""交叉核验：README 里写的配置键，是否与 lib/config.py 的默认值真的对得上。

写文档最容易出的错是"照着记忆写"，结果键名或默认值与代码不符。
这个检查把 README 配置示例里的键抽出来，逐个与 config.py 的 DEFAULTS 比对。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.config import DEFAULTS       # noqa: E402


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


defaults = flatten(DEFAULTS)
print(f"  config.py 里共 {len(defaults)} 个叶子配置键")
print()

# README 里有好几个 jsonc 例子（截图策略、完整配置…）。要挑**完整配置**那个，
# 判据是"含有 interval_sec 或 capture 顶层键"——踩过一次：只取第一个块，
# 结果拿到的是截图策略示例，把 capture 规则里的字段全报成"可疑"。
def config_block(text: str) -> str:
    for b in re.findall(r"```jsonc\n(.*?)\n```", text, re.S):
        if re.search(r'"(interval_sec|capture|api)"\s*:', b) and len(b) > 600:
            return b
    return ""


def strip_comments(text: str) -> str:
    """去掉 jsonc 注释。

    **不要用 `//[^\\n]*`** —— 它会把 URL 里的 `//` 也当注释，
    `"https://api.deepseek.com"` 会被截成 `"https:`，于是报出假的解析失败。
    只把行首或空白之后的 `//` 当注释。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//(?!/)[^\n]*", r"\1", text)


leaf_names = {d.split(".")[-1] for d in defaults}
top_names = set(DEFAULTS.keys())


def leaf_keys(d, pre=""):
    """只取叶子键（与 flatten(DEFAULTS) 的口径一致）。

    第一版把父级段名也算进去了，于是报出"多 7 个键"的假差异 ——
    两边口径必须一致，否则数字对不上却又不是真问题。
    """
    out = set()
    for k, v in d.items():
        key = pre + k
        if isinstance(v, dict):
            out |= leaf_keys(v, key + ".")
        else:
            out.add(key)
    return out


bad = 0

for name in ("README.zh-CN.md", "README.md"):
    t = (ROOT / name).read_text(encoding="utf-8")
    body = config_block(t)
    if not body:
        print(f"  {name}: 找不到完整的配置示例")
        bad += 1
        continue
    try:
        parsed = json.loads(strip_comments(body))
    except Exception as e:
        print(f"  {name}: 配置示例不是合法 JSON（去注释后）-> {e}")
        bad += 1
        continue
    a, b = leaf_keys(parsed), set(defaults)
    print(f"  {name}: 合法 JSON｜{len(a)} 个键与 config.py "
          + ("完全一致 OK" if a == b else f"不一致！多 {sorted(a - b)} 少 {sorted(b - a)}"))
    if a != b:
        bad += 1

print()
print("  结论：全部对上" if bad == 0 else f"  有 {bad} 处需要人工确认")
