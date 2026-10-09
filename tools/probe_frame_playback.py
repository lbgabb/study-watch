"""验证方案 A 的最后一环：Pillow 能不能在 20fps 下实时"合成 + 推帧"。

方案 A 的链路：
    WebP 帧（带 alpha） --Pillow 解码--> RGBA --UpdateLayeredWindow--> 屏幕
这条链路如果每帧超过 50ms 就撑不住 20fps，必须提前知道。

测量项：
  1. 单帧解码 + 缩放（若需要）+ 转 BGRA 的耗时
  2. UpdateLayeredWindow 的耗时
  3. 连续 60 帧的实际帧间隔（含 sleep 到目标帧率）

用法：python tools/probe_frame_playback.py

决策记录：见 docs/pet-render-choice.md。这里验证的是「预渲染帧」方案的
播放性能；当时评估后没采用 —— 桌宠最终用浏览器窗口。
"""

import ctypes
import ctypes.wintypes as wt
import io
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WS_EX_LAYERED, WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x00080000, 0x00000008, 0x00000080
WS_POPUP, ULW_ALPHA, SW_SHOW = 0x80000000, 0x00000002, 5
HWND_TOPMOST = -1
SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = 0x0002, 0x0001, 0x0010
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.restype = ctypes.c_void_p
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD),
                ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


def _wndproc(h, m, w, l):
    return user32.DefWindowProcW(h, m, w, l)


def main() -> int:
    frames_dir = ROOT / "assets" / "petframes"
    srcs = sorted(frames_dir.glob("frame_*.png"))
    if not srcs:
        print("  没有帧可测，先跑：python tools/build_pet_frames.py --frames 24 --keep")
        return 1
    from PIL import Image

    # 转成 WebP 序列（模拟真实资产）
    webps: list[bytes] = []
    for p in srcs:
        im = Image.open(p).convert("RGBA")
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=82, method=4)
        webps.append(buf.getvalue())
    W, H = Image.open(srcs[0]).size
    print(f"  素材：{len(webps)} 帧 WebP｜{W}x{H}"
          f"｜平均 {sum(len(b) for b in webps) / len(webps) / 1024:.1f} KB")

    # --- 1. 解码 + 转 BGRA 的耗时 ---
    dec = []
    for b in webps:
        t0 = time.perf_counter()
        im = Image.open(io.BytesIO(b)).convert("RGBA")
        bgra = im.tobytes("raw", "BGRA")
        dec.append((time.perf_counter() - t0) * 1000)
    print(f"  解码+转BGRA：中位 {statistics.median(dec):.2f} ms"
          f"｜最大 {max(dec):.2f} ms")

    # --- 2. 建窗口并测 UpdateLayeredWindow ---
    hinst = kernel32.GetModuleHandleW(None)
    cls = "StudyWatchFrameProbe"
    wc = WNDCLASS()
    wc.lpfnWndProc = WNDPROC(_wndproc)
    wc.hInstance = hinst
    wc.lpszClassName = cls
    if not user32.RegisterClassW(ctypes.byref(wc)) and kernel32.GetLastError() != 1410:
        print("  RegisterClass 失败")
        return 1
    SW = user32.GetSystemMetrics(0)
    x, y = SW - W - 60, 80
    hwnd = user32.CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW, cls, "frame-probe",
        WS_POPUP, x, y, W, H, None, None, hinst, None)
    if not hwnd:
        print("  CreateWindowEx 失败")
        return 1

    hdc_screen = user32.GetDC(None)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    bmi = BMIH()
    bmi.biSize = ctypes.sizeof(BMIH)
    bmi.biWidth, bmi.biHeight = W, -H
    bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
    ppv = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0,
                                  ctypes.byref(ppv), None, 0)
    gdi32.SelectObject(hdc_mem, hbmp)
    size = wt.SIZE(W, H)
    pt_src = wt.POINT(0, 0)
    pt_dst = wt.POINT(x, y)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

    def blit(bgra: bytes) -> float:
        t0 = time.perf_counter()
        ctypes.memmove(ppv, bgra, len(bgra))
        user32.UpdateLayeredWindow(hwnd, hdc_screen, ctypes.byref(pt_dst),
                                   ctypes.byref(size), hdc_mem,
                                   ctypes.byref(pt_src), 0,
                                   ctypes.byref(blend), ULW_ALPHA)
        return (time.perf_counter() - t0) * 1000

    user32.ShowWindow(hwnd, SW_SHOW)
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    blits = []
    for b in webps[:10]:
        im = Image.open(io.BytesIO(b)).convert("RGBA")
        blits.append(blit(im.tobytes("raw", "BGRA")))
    print(f"  UpdateLayeredWindow：中位 {statistics.median(blits):.2f} ms"
          f"｜最大 {max(blits):.2f} ms")

    # --- 3. 连续播放，量实际帧间隔 ---
    target_fps = 20
    budget = 1000.0 / target_fps
    print(f"  连续播放 {len(webps)} 帧，目标 {target_fps} fps（预算 {budget:.1f} ms/帧）…")
    # 先全部解码好放内存（真实实现也会预解码）
    prepared = [Image.open(io.BytesIO(b)).convert("RGBA").tobytes("raw", "BGRA")
                for b in webps]
    gaps = []
    t_start = time.perf_counter()
    n_loops = 3
    for _ in range(n_loops):
        for buf in prepared:
            t_frame = time.perf_counter()
            blit(buf)
            spent = (time.perf_counter() - t_frame) * 1000
            gaps.append(spent)
            rest = (budget - spent) / 1000.0
            if rest > 0:
                time.sleep(rest)
    total = time.perf_counter() - t_start
    real_fps = len(gaps) / total
    print(f"  单帧耗时（缓冲已就绪）：中位 {statistics.median(gaps):.2f} ms"
          f"｜p95 {sorted(gaps)[int(len(gaps) * 0.95)]:.2f} ms"
          f"｜最大 {max(gaps):.2f} ms")
    print(f"  实测帧率：{real_fps:.1f} fps")
    cpu_ok = statistics.median(gaps) < budget * 0.5
    print(f"  [{'通过' if cpu_ok else '失败'}] 单帧耗时低于预算的一半"
          f"（有余量跑更高帧率或更复杂的合成）")

    time.sleep(1)
    user32.DestroyWindow(hwnd)
    return 0 if cpu_ok else 1


if __name__ == "__main__":
    sys.exit(main())
