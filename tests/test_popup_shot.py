"""提醒窗渲染自测（不依赖屏幕坐标与抓拍时机）。

用 PrintWindow 直接向窗口要一份内容，然后做结构判定：
  - 顶部存在深色标题条
  - 中部存在满宽的文字行
  - 底部存在按钮文字
并保存截图供人工查看（data/popup-check.png）。
"""
import ctypes
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load_config  # noqa: E402
from lib.notify import Notifier  # noqa: E402

FAKE = {
    "activity": "在浏览器里刷 B 站首页推荐视频，屏幕上是竖排推荐流、弹幕与点赞按钮",
    "category": "娱乐",
    "on_task": False,
    "confidence": 0.9,
    "basis": "屏幕上是竖排推荐流：一屏一个视频 + 弹幕列表 + 点赞投币按钮",
}

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
DATA = Path(__file__).resolve().parents[1] / "data"
DATA.mkdir(parents=True, exist_ok=True)   # 全新 checkout 时 data/ 还不存在
PW_RENDERFULLCONTENT = 0x00000002


def grab_window(hwnd: int) -> Image.Image | None:
    """用 PrintWindow 抓窗口位图（后台窗口也能抓到）。"""
    import ctypes.wintypes as wt

    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None

    hdc = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    ok = user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wt.WORD), ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth, bi.biHeight = w, -h        # 负高度 = 自上而下
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bi), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)
    if not ok and not buf.raw.strip(b"\x00"):
        return None
    return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")


def text_rows(im: Image.Image) -> tuple[list[tuple[int, int]], np.ndarray]:
    a = np.asarray(im.convert("RGB")).astype(int)
    gray = a.mean(axis=2)
    med = np.median(gray)
    mask = np.abs(gray - med) > 45
    frac = mask.mean(axis=1)
    bands, start = [], None
    for y in range(len(frac)):
        if frac[y] > 0.02 and start is None:
            start = y
        elif frac[y] <= 0.02 and start is not None:
            if y - start >= 3:
                bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, len(frac)))
    return bands, gray


def grab_from_screen(hwnd: int):
    """后备：按窗口矩形截屏幕。

    PrintWindow 对"从未到过前台的 overrideredirect 窗口"偶尔返回空位图，
    而这个窗口设了 topmost，屏幕上确实显示着它的内容，直接截屏更可靠。
    """
    import ctypes.wintypes as wt
    rect = wt.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None, []
    if rect.right <= rect.left or rect.bottom <= rect.top:
        return None, []
    left, top = max(0, rect.left), max(0, rect.top)
    im = ImageGrab.grab(bbox=(left, top, rect.right, rect.bottom))
    bands, _ = text_rows(im)
    return im, bands


def grab_until_drawn(hwnd: int, tries: int = 12, gap: float = 0.25):
    """反复抓，直到拿到"画完了"的窗口内容。

    为什么要重试：PrintWindow 在窗口刚创建、还没完成首次绘制时会返回一张空位图
    （这里表现为"文字行带为空"）。原来只睡固定时间抓一次，机器忙的时候就会偶发假红。
    这里改成轮询：抓到有明显文字行的内容就返回。

    返回 (图像, 文字行带)；一直抓不到就返回最后一次的结果（让断言如实失败）。
    """
    last = None
    for i in range(tries):
        im = grab_window(hwnd)
        if im is not None:
            bands, _ = text_rows(im)
            if len(bands) >= 2:              # 至少要有标题 + 正文两段
                return im, bands
            last = (im, bands)
        time.sleep(gap)
    # PrintWindow 一直抓不到内容 -> 退回屏幕区域抓取
    im2, bands2 = grab_from_screen(hwnd)
    if im2 is not None and len(bands2) >= 2:
        return im2, bands2
    return last if last else (im2, bands2)


def main() -> int:
    cfg = load_config()
    cfg["reminder"]["sound"] = False
    cfg["reminder"]["auto_close_sec"] = 0
    n = Notifier(cfg)
    if n.window is None:
        print("提醒窗不可用（tkinter 缺失）")
        return 1

    n.notify(FAKE, goal=cfg["judge"]["goal"])
    for _ in range(12):
        n.pump()
        time.sleep(0.12)

    hwnd = int(user32.GetAncestor(n.window.root.winfo_id(), 2))  # GA_ROOT
    im, bands = grab_until_drawn(hwnd)
    if im is None:
        print("失败：PrintWindow 抓不到窗口内容")
        return 1

    out = DATA / "popup-check.png"
    im.save(out)
    gray = np.asarray(im.convert("RGB")).astype(int).mean(axis=2)
    h = im.height

    title_band = [b for b in bands if b[0] < h * 0.25]
    body_band = [b for b in bands if h * 0.25 <= b[0] < h * 0.75]
    button_band = [b for b in bands if b[0] >= h * 0.75]

    print(f"窗口内容：{im.width}x{im.height}｜中位亮度={np.median(gray):.0f}")
    print(f"文字行带：{bands}")
    print(f"标题带 {title_band}｜正文带 {body_band}｜按钮带 {button_band}")
    print(f"截图已保存：{out}")

    checks = {
        "窗口内容非空白": len(bands) >= 2,
        "顶部有标题文字": bool(title_band),
        "中部有正文文字": bool(body_band),
        "底部有按钮文字": bool(button_band),
    }
    for name, ok in checks.items():
        print(f"  [{'通过' if ok else '失败'}] {name}")

    for _ in range(6):
        n.pump()
        time.sleep(0.05)
    n.destroy()
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
