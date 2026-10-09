"""把插画 + 文案合成为提醒卡片（成品 PNG），供 tkinter 直接整张显示。

为什么要在 Pillow 里预合成，而不是用 tkinter 拼界面：
  tkinter 的 Label/PhotoImage 不支持 alpha 混合 —— 透明像素会显示成它自己的
  RGB 值（一般是白），不会露出父窗口的深色底。所以"深色圆角卡片 + 插画"
  必须在 Pillow 里合成好，再整张塞进窗口。

为什么不抠图：这批插画是完整构图（趴在桌上、端着茶、有气泡/方块等元素），
  强行去背会把构图一起毁掉（实测 sleepy 的桌子会变成"漂浮的桌子"）。
  所以保留整幅插画，只做圆角与尺寸规整。

文案与图片在哪：见 lib/reminder_copy.py（每张图对应一句吐槽）。

用法：
    python tools/make_reminder_cards.py            # 生成全部（中英双语）
    python tools/make_reminder_cards.py --lang zh  # 只生成中文
    python tools/make_reminder_cards.py --preview  # 额外拼一张总览图，方便一次看全
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.reminder_copy import CARDS, card_order          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "_reminder_src"
OUT = ROOT / "assets" / "reminder"
FONT_DIR = Path("C:/Windows/Fonts")

# 与 lib/notify.py 的窗口配色保持一致
BG = (27, 36, 48)            # #1b2430 卡片底
HEAD = (36, 52, 71)          # #243447
LINE = (51, 70, 94)          # #33465e 边框
INK = (232, 238, 246)        # #e8eef6 正文
DIM = (143, 166, 191)        # #8fa6bf 次要文字
AMBER = (255, 209, 102)      # #ffd166 标题
GREEN = (76, 201, 122)
PINK = (242, 130, 150)

CARD_W = 396
PAD = 16
HERO_W = CARD_W - PAD * 2
RADIUS = 14

FONTS = {
    "zh": {
        "regular": ["msyh.ttc", "msyh.ttf", "simhei.ttf"],
        "bold": ["msyhbd.ttc", "msyh.ttf", "simhei.ttf"],
    },
    "en": {
        "regular": ["segoeui.ttf"],
        "bold": ["seguisb.ttf", "segoeui.ttf"],
    },
}


def load_font(lang: str, weight: str, size: int) -> ImageFont.FreeTypeFont:
    for name in FONTS.get(lang, FONTS["zh"])[weight]:
        p = FONT_DIR / name
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def wrap(text: str, font: ImageFont.FreeTypeFont, max_w: int, lang: str) -> list[str]:
    """按像素宽度折行。中文逐字断，英文按单词断。

    中文要遵守"避头尾"：句号、逗号、右括号这类**不能出现在行首**，
    否则换行时会把一个标点单独挤到下一行（实测出现过一行只有「、」）。
    这里的规则是：如果下一个字符是句末标点，就连它一起放进来，
    哪怕略微超出宽度（中文排版本来也允许标点悬挂）。
    """
    lines: list[str] = []
    cur = ""
    if lang == "zh":
        # 不能出现在行首的字符
        NO_LINE_START = set("，。、；：？！）》」』】…—·,.;:?!)]}\"'")
        for ch in text:
            if ch == "\n":
                lines.append(cur); cur = ""
                continue
            if font.getlength(cur + ch) <= max_w:
                cur += ch
            elif cur and ch in NO_LINE_START:
                cur += ch                       # 标点跟着上一字走，不另起一行
            else:
                lines.append(cur); cur = ch
        if cur:
            lines.append(cur)
        return lines

    # 英文：优先在空格断，超长单词强制断
    for para in text.split("\n"):
        for word in para.split(" "):
            trial = (cur + " " + word).strip()
            if font.getlength(trial) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                while font.getlength(word) > max_w:
                    cut = len(word)
                    while cut > 1 and font.getlength(word[:cut]) > max_w:
                        cut -= 1
                    lines.append(word[:cut])
                    word = word[cut:]
                cur = word
        if cur:
            lines.append(cur); cur = ""
    return lines


def rounded(im: Image.Image, radius: int, *, top_only: bool = False) -> Image.Image:
    """给图片加圆角（带抗锯齿）。

    top_only=True 时只圆上面两个角——插画贴在卡片顶部，下方两角是直角，
    这样插画与卡片边缘严丝合缝，不会在圆角处露出插画自己的浅色底。
    """
    im = im.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    d = ImageDraw.Draw(mask)
    if top_only:
        # 先画一个只有上方圆角的形状：整体圆角矩形向下延伸，再裁掉多余部分
        d.rounded_rectangle([0, 0, im.width - 1, im.height - 1 + radius],
                            radius=radius, fill=255)
    else:
        d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=255)
    out = im.copy()
    out.putalpha(mask)
    return out


def build_card(key: str, lang: str, reason: str = "", *,
               out_dir: Path | None = None, name: str = "") -> Path | None:
    """合成一张提醒卡片。

    reason：本次判定的依据（"屏幕上看到什么所以这么说"）。画进卡片里，
    这样窗口只剩"卡片 + 按钮"，视觉上是一整块；同时也让吐槽有据可依，
    不至于变成随口指责。为空时不留这块。
    out_dir/name：允许调用方指定输出位置（运行时按需生成时用缓存目录）。
    """
    info = CARDS.get(key)
    if not info:
        print(f"  跳过（没有文案）：{key}")
        return None
    src = SRC / info["file"]
    if not src.is_file():
        print(f"  跳过（找不到素材）：{info['file']}")
        return None

    copy = info[lang]
    title = copy["title"]
    body = copy["body"]
    tone = copy.get("tone", "warn")

    # ---- 主图：整幅保留，等比缩放到卡片内宽 ----
    art = Image.open(src).convert("RGB")
    ratio = HERO_W / art.width
    # 顶部要多留 PAD 那么高：插画要从卡片最上沿（含边框内侧）开始贴，
    # 否则 y=1..PAD 那一段会露出卡片底色，卡片上沿出现一条横向细缝。
    hero_h = max(1, round(art.height * ratio))
    art = art.resize((HERO_W, hero_h + PAD), Image.LANCZOS)
    hero_h = art.height - PAD
    art = rounded(art, RADIUS + 4, top_only=True)

    # ---- 文字排版（先算高度，再决定卡片总高）----
    f_title = load_font(lang, "bold", 17 if lang == "zh" else 16)
    f_body = load_font(lang, "regular", 13)
    f_meta = load_font(lang, "regular", 11)

    body_lines = wrap(body, f_body, HERO_W, lang)
    meta = info.get("meta", {}).get(lang, "")
    meta_lines = wrap(meta, f_meta, HERO_W, lang) if meta else []
    reason_lines = wrap(reason, f_meta, HERO_W, lang) if reason else []

    y = PAD + hero_h + 14
    title_h = 24
    line_h = 21
    body_h = line_h * len(body_lines)
    tail_h = 0
    if meta_lines:
        tail_h += 6 + 16 * len(meta_lines)
    if reason_lines:
        tail_h += 10 + 16 * len(reason_lines)
    footer = 16

    card_h = y + title_h + 6 + body_h + tail_h + footer
    card = Image.new("RGB", (CARD_W, card_h), BG)
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([0, 0, CARD_W - 1, card_h - 1], radius=RADIUS + 4,
                        fill=BG, outline=LINE, width=1)
    card.paste(art, (PAD, 1), art)

    accent = {"warn": AMBER, "good": GREEN, "praise": GREEN, "rest": GREEN}.get(tone, AMBER)
    d.text((PAD, y), title, font=f_title, fill=accent)
    y += title_h + 6
    for ln in body_lines:
        d.text((PAD, y), ln, font=f_body, fill=INK)
        y += line_h
    if meta_lines:
        y += 6
        for ln in meta_lines:
            d.text((PAD, y), ln, font=f_meta, fill=DIM)
            y += 16
    if reason_lines:
        y += 10
        # 依据前画一条细分割线，和正文区分开
        d.line([(PAD, y - 5), (CARD_W - PAD, y - 5)], fill=LINE, width=1)
        for i, ln in enumerate(reason_lines):
            prefix = "依据：" if (i == 0 and lang == "zh") else ("Why: " if i == 0 else "")
            d.text((PAD, y), prefix + ln, font=f_meta, fill=DIM)
            y += 16

    target_dir = out_dir if out_dir is not None else OUT
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if lang == "zh" else ".en"
    out = target_dir / (name or f"card-{key}{suffix}.png")
    card.save(out, "PNG", optimize=True)
    return out


def face_crop(im: Image.Image, size: int = 200) -> Image.Image:
    """从插画里裁一个方形头像（仪表盘用）。

    取偏上的部分：角色是 Q 版，头在上半身，脸大约在高度 15%~55% 之间。
    不抠图 —— 仪表盘卡片本身就是浅色，插画的白底直接放在上面不会突兀。
    """
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = max(0, int(h * 0.06))
    if top + side > h:
        top = max(0, h - side)
    im = im.crop((left, top, left + side, top + side))
    return im.resize((size, size), Image.LANCZOS)


def build_faces() -> list[Path]:
    """为每张卡片的角色生成方形头像，供仪表盘复用同一批素材。"""
    out_dir = OUT / "face"
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for key in card_order():
        info = CARDS.get(key)
        if not info:
            continue
        src = SRC / info["file"]
        if not src.is_file():
            continue
        with Image.open(src) as im:
            face = face_crop(im.convert("RGB"))
        p = out_dir / f"{key}.png"
        face.save(p, "PNG", optimize=True)
        made.append(p)
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["zh", "en", "both"], default="both")
    ap.add_argument("--preview", action="store_true", help="额外拼一张总览图")
    ap.add_argument("--faces", action="store_true", help="只生成仪表盘用的方形头像")
    args = ap.parse_args()

    if args.faces:
        made = build_faces()
        print(f"=== 方形头像（{len(made)} 张）===")
        for p in made:
            im = Image.open(p)
            print(f"  {p.name:<16} {im.width}x{im.height}  {p.stat().st_size // 1024} KB")
        return 0

    langs = ["zh", "en"] if args.lang == "both" else [args.lang]
    made: list[tuple[str, str, Path]] = []
    for lang in langs:
        print(f"=== {lang} ===")
        for key in card_order():
            p = build_card(key, lang)
            if p:
                im = Image.open(p)
                made.append((key, lang, p))
                print(f"  {p.name:<28} {im.width}x{im.height}  {p.stat().st_size // 1024} KB")

    if args.preview and made:
        cols = 3
        rows = (len(made) + cols - 1) // cols
        heights = [Image.open(p).height for _, _, p in made]
        cell_w = CARD_W + 24
        cell_h = max(heights) + 24
        sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (14, 20, 28))
        for i, (_, _, p) in enumerate(made):
            im = Image.open(p)
            sheet.paste(im, (24 + (i % cols) * cell_w, 24 + (i // cols) * cell_h))
        preview = ROOT / "assets" / "reminder-cards-preview.png"
        sheet.save(preview)
        print(f"\n  总览图：{preview.name}（{sheet.width}x{sheet.height}）")

    print(f"\n共生成 {len(made)} 张")
    return 0


if __name__ == "__main__":
    sys.exit(main())
