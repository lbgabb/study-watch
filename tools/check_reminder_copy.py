"""检查提醒卡片文案的折行：不能出现"只有标点的一行"等排版毛病。

中文排版里句号/逗号/右括号不能落在行首（避头尾）。这个检查跑一遍
所有卡片的中英文文案，把不合理的折行打出来。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from make_reminder_cards import HERO_W, load_font, wrap   # noqa: E402
from lib.reminder_copy import CARDS                       # noqa: E402

NO_LINE_START = set("，。、；：？！）》」』】…—·,.;:?!)]}\"'")


def main() -> int:
    bad = 0
    checked = 0
    for key, info in sorted(CARDS.items()):
        for lang in ("zh", "en"):
            f = load_font(lang, "regular", 13)
            items = [("title", info[lang]["title"]), ("body", info[lang]["body"])]
            meta = (info.get("meta") or {}).get(lang, "")
            if meta:
                items.append(("meta", meta))
            for label, text in items:
                lines = wrap(text, f, HERO_W, lang)
                checked += 1
                for i, ln in enumerate(lines):
                    s = ln.strip()
                    if not s:
                        continue
                    if len(s) <= 1 and i > 0:
                        print(f"  X {key}.{lang}.{label} 第{i+1}行只有一个字符：{s!r}")
                        bad += 1
                    if i > 0 and s[0] in NO_LINE_START:
                        print(f"  X {key}.{lang}.{label} 第{i+1}行以标点开头：{ln!r}")
                        bad += 1
                    if f.getlength(ln) > HERO_W * 1.12:
                        print(f"  X {key}.{lang}.{label} 第{i+1}行明显超宽：{f.getlength(ln):.0f}px")
                        bad += 1

    print(f"  检查了 {checked} 段文案")
    print("  OK 折行正常" if not bad else f"  发现 {bad} 处问题")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
