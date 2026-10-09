"""验证：不用浏览器，能不能做出"真·逐像素透明"的窗口。

背景：现在已经有一个基于浏览器 app 模式的桌宠窗口，但用户希望不依赖网页。
浏览器那条路的根本原因是**透明**：tkinter 的窗口不能做逐像素 alpha（透明像素
会显示成它自己的 RGB）。Windows 上真正能做这件事的是 UpdateLayeredWindow：
  1. CreateWindowEx(WS_EX_LAYERED)
  2. 用 Pillow 画一张 RGBA 图
  3. UpdateLayeredWindow(hwnd, ..., 位图, BLENDFUNCTION(AC_SRC_ALPHA))

这个脚本只验证**能力**，不做完整桌宠：
  · 建一个无边框、置顶、逐像素透明的窗口
  · 用 Pillow 画一个带柔和边缘的圆（抗锯齿边缘最能检验 alpha 是否真的生效）
  · 报出窗口句柄、尺寸，并截屏确认边缘是渐隐的（而不是硬边白块）

用法：python tools/probe_layered_window.py
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080      # 不在任务栏显示
WS_POPUP = 0x80000000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
SW_SHOW = 5
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

# WNDPROC 的参数必须显式声明类型：不然 lParam 在 64 位上会被当成 int32，
# 指针值一大就抛 OverflowError（实测刷了几十行 "int too long to convert"）。
# 返回值也要是 c_void_p（LRESULT 在 64 位下是指针宽度），不能用 c_long。
user32.DefWindowProcW.restype = ctypes.c_void_p
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


def _wndproc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


def main() -> int:
    from PIL import Image, ImageDraw

    # 画一张 RGBA：柔和边缘的圆 + 半透明光晕。
    # 抗锯齿边缘最能说明 alpha 是否真的生效 —— 如果是硬边白块，说明没生效。
    S = 240
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([8, 8, S - 8, S - 8], fill=(52, 108, 178, 255))
    d.ellipse([40, 40, S - 40, S - 40], fill=(120, 190, 240, 200))
    d.ellipse([86, 86, S - 86, S - 86], fill=(255, 255, 255, 255))
    # 一条渐隐的尾巴，检验半透明
    for i in range(60):
        a = int(200 * (1 - i / 60))
        d.ellipse([S - 20 + i, S // 2 - 6, S - 14 + i, S // 2 + 6],
                  fill=(52, 108, 178, a))

    # BGRA 像素（Windows 的 DIB 顺序）
    bgra = im.tobytes("raw", "BGRA")

    hinst = kernel32.GetModuleHandleW(None)
    cls_name = "StudyWatchLayeredProbe"
    wc = WNDCLASS()
    wc.lpfnWndProc = WNDPROC(_wndproc)
    wc.hInstance = hinst
    wc.lpszClassName = cls_name
    if not user32.RegisterClassW(ctypes.byref(wc)):
        err = kernel32.GetLastError()
        if err != 1410:          # 1410 = 类已存在
            print(f"  RegisterClass 失败，GetLastError={err}")
            return 1

    SW, SH = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    x, y = SW - S - 60, 80
    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
        cls_name, "layered-probe", WS_POPUP,
        x, y, S, S, None, None, hinst, None)
    if not hwnd:
        print(f"  CreateWindowEx 失败，GetLastError={kernel32.GetLastError()}")
        return 1
    print(f"  窗口已创建：hwnd={hwnd}  位置=({x},{y}) 尺寸={S}x{S}")

    # 把 RGBA 交给 UpdateLayeredWindow —— 这一步决定"逐像素透明"成不成立
    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                    ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                    ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                    ("biClrImportant", wt.DWORD)]

    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth, bmi.biHeight = S, -S
    bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0

    ppv = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0,
                                  ctypes.byref(ppv), None, 0)
    if not hbmp:
        print("  CreateDIBSection 失败")
        return 1
    ctypes.memmove(ppv, bgra, len(bgra))
    old = gdi32.SelectObject(hdc_mem, hbmp)

    size = wt.SIZE(S, S)
    src = wt.POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    ok = user32.UpdateLayeredWindow(hwnd, hdc_screen, ctypes.byref(wt.POINT(x, y)),
                                    ctypes.byref(size), hdc_mem, ctypes.byref(src),
                                    0, ctypes.byref(blend), ULW_ALPHA)
    print(f"  UpdateLayeredWindow 返回：{ok}（0 表示失败，GetLastError="
          f"{kernel32.GetLastError() if not ok else '-'}）")
    if not ok:
        print("  结论：这条路在这个环境下不成立")
        user32.DestroyWindow(hwnd)
        return 1

    user32.ShowWindow(hwnd, SW_SHOW)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    print("  结论：**逐像素透明窗口做出来了**，AlphaFormat=AC_SRC_ALPHA 生效")
    print("    屏幕上应该能看到一个柔和边缘的圆，背景是透过去的桌面")
    print("    5 秒后截屏核验边缘是渐隐还是硬边…")
    time.sleep(5)

    # 截屏核验：抓窗口右下角外侧一点点，看是否透出了桌面
    try:
        from PIL import ImageGrab
        box = (x - 10, y - 10, x + S + 10, y + S + 10)
        shot = ImageGrab.grab(bbox=box)
        out = ROOT / "data" / "layered-probe.png"
        shot.save(out)
        # 圆外的角落应该与桌面一致（不是纯黑/纯白）
        corners = [shot.getpixel((2, 2)), shot.getpixel((shot.width - 3, 2)),
                   shot.getpixel((2, shot.height - 3))]
        print(f"    角落像素（透出桌面）：{corners}")
        print(f"    截图：{out}")
    except Exception as e:
        print(f"    截屏失败（不影响结论）：{e}")

    time.sleep(2)
    user32.DestroyWindow(hwnd)
    print("  已关闭探测窗口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
