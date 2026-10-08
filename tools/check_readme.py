"""检查两个 README 的 Markdown 语法是否自洽（不依赖渲染器）。

重点：**加粗** 允许跨行，所以逐行数 `**` 的奇偶没有意义；
要在整个文档层面（去掉代码块与行内代码后）检查总数是否为偶数。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")


def strip_code(text: str) -> str:
    return INLINE_CODE.sub("", FENCE.sub("", text))


def check(name: str) -> bool:
    p = ROOT / name
    if not p.is_file():
        print(f"  {name}: 不存在")
        return False
    raw = p.read_text(encoding="utf-8")
    body = strip_code(raw)
    ok = True

    n_bold = body.count("**")
    if n_bold % 2:
        ok = False
        print(f"  {name}: ** 共 {n_bold} 个 —— 不成对！定位第一处：")
        acc = 0
        for i, l in enumerate(body.splitlines(), 1):
            acc += l.count("**")
            if acc % 2:
                print(f"    第 {i} 行：{l.strip()[:78]}")
                break
    else:
        print(f"  {name}: ** 共 {n_bold} 个，成对 OK")

    # 表格：每个表格的列数应一致（| 分隔写错会露出来）
    ragged = []
    block = []
    for i, l in enumerate(raw.splitlines(), 1):
        if l.lstrip().startswith("|"):
            block.append((i, l.count("|")))
        else:
            if len(block) > 2:
                counts = {c for _, c in block[1:]}   # 跳过分隔行
                if len(counts) > 1:
                    ragged.append((block[0][0], sorted(counts)))
            block = []
    if ragged:
        ok = False
        for line_no, counts in ragged:
            print(f"  {name}: 第 {line_no} 行起的表格列数不一致：{counts}")
    else:
        print(f"  {name}: 表格列数一致 OK")

    # 代码块围栏成对
    fences = raw.count("```")
    if fences % 2:
        ok = False
        print(f"  {name}: ``` 围栏 {fences} 个 —— 未闭合！")
    else:
        print(f"  {name}: 代码块围栏 {fences // 2} 对，闭合 OK")

    # 内部锚点链接是否都有对应标题
    heads = set()
    heading_texts = []
    for l in raw.splitlines():
        if l.startswith("#"):
            t = l.lstrip("#").strip()
            heading_texts.append(t)
            anchor = re.sub(r"[^\w\u4e00-\u9fff\s-]", "", t).strip().lower()
            anchor = re.sub(r"\s+", "-", anchor)
            heads.add(anchor)
    bad_links = []
    for m in re.finditer(r"\]\(#([^)]+)\)", raw):
        if m.group(1) not in heads:
            bad_links.append(m.group(1))
    if bad_links:
        ok = False
        print(f"  {name}: 有 {len(bad_links)} 个锚点链接找不到标题：{bad_links[:5]}")
        print("       注意：标题里的 / 会先被去掉再转连字符——"
              "「A / B」的锚点是 a-b 而不是 a--b。"
              "最稳的做法是标题里别放 /。")
    else:
        print(f"  {name}: 锚点链接都能对上 OK")

    # 标题里带 / 本身就是锚点歧义源，单独提醒
    risky = [t for t in heading_texts if "/" in t]
    if risky:
        print(f"  {name}: 有 {len(risky)} 个标题含 /，锚点容易写错：")
        for t in risky:
            print(f"       {t}")
    return ok


def main() -> int:
    print("=== README 语法自检 ===")
    results = [check(n) for n in ("README.md", "README.zh-CN.md")]
    print()
    print("全部通过" if all(results) else "有问题，见上面")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
