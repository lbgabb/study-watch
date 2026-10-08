"""图标生成：绘制各尺寸图标并写成多尺寸 .ico。

从 tests/make_icon.py 提上来的 —— 之前生成图标的逻辑住在 tests/ 目录里，
而 make_icon_bmp.py 又要反过来 import 它，属于依赖倒挂：
换机器只拷程序不拷测试时，图标就再也生成不出来了。

输出用 BMP/DIB 帧（兼容性最好，PNG 帧在部分 Shell 渲染路径上会显示成白纸）。
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 配色沿用提醒窗：深蓝底 + 琥珀色表盘 + 绿色对勾
BG = (27, 36, 48, 255)          # #1b2430
RING = (255, 209, 102, 255)     # #ffd166
CHECK = (76, 201, 122, 255)
HILITE = (51, 70, 94, 255)      # #33465e

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SS = 8                          # 超采样倍数


def rounded_bg(size: int) -> Image.Image:
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=BG, outline=HILITE,
                        width=max(1, int(s * 0.02)))
    return im


def draw_face(size: int) -> Image.Image:
    """表盘：12 个刻度点，4 个主刻度更长。"""
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = cy = s / 2
    ring_r = s * 0.335
    d.ellipse([cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
              outline=RING, width=max(1, int(s * 0.055)))
    for k in range(12):
        ang = math.radians(k * 30 - 90)
        major = k % 3 == 0
        r1 = ring_r - (s * 0.115 if major else s * 0.085)
        r2 = ring_r - s * 0.035
        w = max(1, int(s * (0.030 if major else 0.018)))
        d.line([cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                cx + r2 * math.cos(ang), cy + r2 * math.sin(ang)], fill=RING, width=w)
    return im


def draw_check(size: int) -> Image.Image:
    """对勾：整体收在表盘内侧，小尺寸也认得出。"""
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w = max(1, int(s * 0.11))
    d.line([(s * 0.335, s * 0.505), (s * 0.440, s * 0.610)], fill=CHECK, width=w, joint="curve")
    d.line([(s * 0.440, s * 0.610), (s * 0.630, s * 0.400)], fill=CHECK, width=w, joint="curve")
    for x, y in ((0.335, 0.505), (0.630, 0.400), (0.440, 0.610)):
        r = w / 2
        d.ellipse([s * x - r, s * y - r, s * x + r, s * y + r], fill=CHECK)
    return im


def build(size: int) -> Image.Image:
    """画一张指定尺寸的图标（RGBA）。"""
    im = rounded_bg(size)
    im.alpha_composite(draw_face(size))
    im.alpha_composite(draw_check(size))
    return im.resize((size, size), Image.LANCZOS)


def build_all(sizes: list[int] | None = None) -> dict[int, Image.Image]:
    return {s: build(s) for s in (sizes or SIZES)}


def bmp_frame(im: Image.Image) -> bytes:
    """把 RGBA 图编码成 ICO 里的 BMP 帧（BITMAPINFOHEADER + XOR 位图 + AND 掩码）。"""
    w, h = im.size
    px = im.load()

    xor = bytearray()                       # 自下而上、BGRA
    for y in range(h - 1, -1, -1):
        for x in range(w):
            r, g, b, a = px[x, y]
            xor += bytes((b, g, r, a))

    row_bytes = ((w + 31) // 32) * 4        # AND 掩码按 4 字节对齐
    and_mask = bytearray()
    for y in range(h - 1, -1, -1):
        bits = bytearray(row_bytes)
        for x in range(w):
            if px[x, y][3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        and_mask += bits

    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0,
                         len(xor) + len(and_mask), 0, 0, 0, 0)
    return header + bytes(xor) + bytes(and_mask)


def write_ico(images: dict[int, Image.Image], dest: Path) -> int:
    """写成多尺寸 .ico（BMP 帧）。返回文件字节数。"""
    frames = [(s, bmp_frame(images[s])) for s in sorted(images)]
    offset = 6 + 16 * len(frames)
    out = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    for size, data in frames:
        dim = 0 if size >= 256 else size      # 256 的宽高字段写 0
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for _, data in frames:
        out += data
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(bytes(out))
    return len(out)


def write_preview(images: dict[int, Image.Image], dest: Path) -> tuple[int, int]:
    """生成各尺寸并排的预览图，便于肉眼确认小尺寸可辨识度。"""
    sizes = sorted(images)
    pad, scale = 12, 3
    width = sum(s * scale + pad for s in sizes) + pad
    height = max(sizes) * scale + pad * 2 + 60
    canvas = Image.new("RGB", (width, height), (245, 246, 248))
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 14)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(canvas)

    x = pad
    for s in sizes:
        big = images[s].resize((s * scale, s * scale), Image.NEAREST)
        canvas.paste(big, (x, pad), big)
        d.text((x, pad + s * scale + 6), f"{s}px", fill=(60, 60, 60), font=font)
        x += s * scale + pad

    y = height - 46
    d.text((pad, y - 20), "实际大小：", fill=(60, 60, 60), font=font)
    x = pad + 80
    for s in (16, 24, 32, 48):
        if s in images:
            canvas.paste(images[s], (x, y - 6), images[s])
            x += s + 16

    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    return canvas.size


def main(argv: list[str] | None = None) -> int:
    """命令行入口：python -m lib.icon  [--assets 目录]"""
    import argparse

    from .config import ROOT

    ap = argparse.ArgumentParser(description="生成学习监督的图标")
    ap.add_argument("--assets", default=str(ROOT / "assets"), help="输出目录")
    args = ap.parse_args(argv)

    assets = Path(args.assets)
    images = build_all()
    ico = assets / "study-watch.ico"
    n = write_ico(images, ico)
    print(f"已写出 {ico}（{n} 字节，{len(images)} 帧，BMP/DIB）")
    size = write_preview(images, assets / "icon-preview.png")
    print(f"已写出 {assets / 'icon-preview.png'}（{size[0]}x{size[1]}）")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
