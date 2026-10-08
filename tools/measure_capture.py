"""实测截屏开销：尺寸、编码耗时、JPEG 体积、base64 体积。

只做截图与编码，不调用任何 API、不落盘、不产生费用。
"""
import base64
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import ImageGrab

from lib import vision, winapi
from lib.config import load_config


def main() -> int:
    cfg = load_config()
    winapi.set_dpi_aware()

    print("=== 屏幕与参数 ===")
    left, top, w, h = winapi.virtual_screen()
    print(f"虚拟桌面 bbox = ({left},{top}) 尺寸 {w}x{h}")
    print(f"主屏 = {winapi.user32.GetSystemMetrics(0)}x{winapi.user32.GetSystemMetrics(1)}")
    print(f"配置：max_width={cfg['max_width']}  jpeg_quality={cfg['jpeg_quality']}  "
          f"detail={cfg['detail']}  interval={cfg['interval_sec']}s  idle_skip={cfg['idle_skip_sec']}s")

    print()
    print("=== 连续 5 次截屏 + 编码 ===")
    print(f"{'次数':>4} {'抓屏ms':>8} {'缩放ms':>8} {'编码ms':>8} {'原始尺寸':>12} {'发送尺寸':>12} "
          f"{'JPEG KB':>9} {'base64 KB':>10}")
    stats = []
    for i in range(1, 6):
        t0 = time.perf_counter()
        left, top, w, h = winapi.virtual_screen()
        im = ImageGrab.grab(bbox=(left, top, left + w, top + h)) if w > 0 else ImageGrab.grab()
        t1 = time.perf_counter()
        raw = im.size
        if im.width > cfg["max_width"]:
            nh = max(1, round(im.height * cfg["max_width"] / im.width))
            im = im.resize((cfg["max_width"], nh), 1)
        t2 = time.perf_counter()
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=cfg["jpeg_quality"], optimize=True)
        data = buf.getvalue()
        t3 = time.perf_counter()
        b64 = base64.b64encode(data)
        stats.append((t1 - t0, t2 - t1, t3 - t2, len(data)))
        print(f"{i:>4} {(t1-t0)*1000:>8.1f} {(t2-t1)*1000:>8.1f} {(t3-t2)*1000:>8.1f} "
              f"{str(raw):>12} {str(im.size):>12} {len(data)/1024:>9.1f} {len(b64)/1024:>10.1f}")

    grab = sum(s[0] for s in stats) / len(stats) * 1000
    scale = sum(s[1] for s in stats) / len(stats) * 1000
    enc = sum(s[2] for s in stats) / len(stats) * 1000
    size_kb = sum(s[3] for s in stats) / len(stats) / 1024
    print()
    print(f"平均：抓屏 {grab:.0f} ms + 缩放 {scale:.0f} ms + 编码 {enc:.0f} ms = "
          f"{grab + scale + enc:.0f} ms｜JPEG 平均 {size_kb:.0f} KB")

    print()
    print("=== 空闲判定与锁屏判定 ===")
    print(f"当前空闲秒数：{winapi.idle_seconds():.1f}（超过 {cfg['idle_skip_sec']} 秒即跳过本次判定）")
    print(f"是否锁屏：{winapi.is_session_locked()}")

    print()
    print("=== 是否落盘 ===")
    print(f"save_shots = {cfg['privacy'].get('save_shots')} -> "
          + ("会写入 data/shots" if cfg["privacy"].get("save_shots") else "只在内存里，不写磁盘"))

    # 用一次真实路径跑一遍（不调用 API）
    print()
    print("=== 走一遍 vision.capture()（真实调用路径）===")
    t0 = time.perf_counter()
    shot = vision.capture(cfg, save_dir=None)
    dt = (time.perf_counter() - t0) * 1000
    print(f"耗时 {dt:.0f} ms｜原始 {shot['raw_size']} -> 发送 {shot['sent_size']}｜"
          f"JPEG {shot['bytes']/1024:.0f} KB｜base64 长度 {len(shot['b64'])}｜落盘路径={shot['shot_path'] or '（无）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
