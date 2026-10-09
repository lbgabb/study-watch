"""独立桌宠窗口：用浏览器 app 模式做一个无边框、置顶、可拖动的小窗口。

为什么走浏览器而不是 tkinter：
  桌宠要渲染 Live2D，而 Live2D 需要 WebGL —— tkinter 没有。
  浏览器 app 模式（--app=URL）给出一个无标题栏的窗口，正好当容器，
  而且它已经在跑（不用额外装运行时）。

透明窗口的现状（实测记录，别再重复试）：
  · 页面背景可以做成透明的（getComputedStyle 里是 rgba(0,0,0,0)）✓
  · 但窗口本身在 Windows 上仍被合成成不透明（--app +
    --default-background-color=00000000 也不行，实测四角是不透明的白）✗
  · 备选方案是 Windows 颜色键透明（SetLayeredWindowAttributes 的
    LWA_COLORKEY）：把某个纯色设为全透明。能做出"抠掉背景"的效果，
    但抗锯齿边缘会留下同色的硬边 —— 所以做成可选项，默认关闭。

用法：
    python lib/pet_window.py              # 独立桌宠窗口（自带一个轻量页面）
    python lib/pet_window.py --close      # 关掉
    python lib/pet_window.py --status
"""
from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.config import load_config          # noqa: E402

user32 = ctypes.windll.user32
PIDFILE = ROOT / "data" / "pet_window.json"


# ---------------------------------------------------------------- 进程管理
def _alive(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{'1'}} else {{'0'}}"],
            capture_output=True, text=True, timeout=20,
            creationflags=0x08000000).stdout.strip()
        return out == "1"
    except Exception:
        return False


def _load() -> dict:
    if not PIDFILE.is_file():
        return {}
    try:
        return json.loads(PIDFILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def running_pids() -> list[int]:
    d = _load()
    pids = [int(p) for p in (d.get("pids") or []) if str(p).isdigit()]
    return [p for p in pids if _alive(p)]


def stop() -> int:
    pids = running_pids()
    for p in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"],
                           capture_output=True, timeout=20,
                           creationflags=0x08000000)
        except Exception:
            pass
    PIDFILE.unlink(missing_ok=True)
    print(f"  已关闭桌宠窗口（{len(pids)} 个进程）" if pids else "  桌宠窗口本来就没在跑")
    return 0


def show_status() -> int:
    pids = running_pids()
    if pids:
        print(f"  桌宠窗口：运行中（PID {', '.join(map(str, pids))}）")
    else:
        print("  桌宠窗口：未运行")
    return 0


# ---------------------------------------------------------------- 启动窗口
def _pet_page_url(port: int, style: str) -> str:
    return f"http://127.0.0.1:{port}/pet?style={style}"


def _edge_exe() -> str | None:
    from tools.cdp_check import find_edge
    return find_edge()


def _find_window(title_sub: str) -> int:
    """按标题找窗口句柄。app 模式的窗口标题就是页面 title。"""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if title_sub in buf.value:
                found.append(int(hwnd))
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0


def _make_layered(hwnd: int, colorkey: str) -> bool:
    """Windows 颜色键透明：把 colorkey 这个颜色整片挖掉。

    代价：抗锯齿边缘会留下同色的硬边，所以只作为可选项。
    """
    try:
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        LWA_COLORKEY = 0x00000001
        cur = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur | WS_EX_LAYERED)
        # 颜色键是 COLORREF（0x00BBGGRR），不是 RGB
        s = colorkey.lstrip("#")
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        ref = (b << 16) | (g << 8) | r
        ok = user32.SetLayeredWindowAttributes(hwnd, ref, 0, LWA_COLORKEY)
        # 置顶 + 无边框（app 模式本来就没标题栏）
        HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE = -1, 0x0002, 0x0001
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE)
        return bool(ok)
    except Exception:
        return False


def _system_dpi_scale() -> float:
    """系统 DPI 缩放（150% -> 1.5）。

    为什么需要：Chromium 的 --window-size 收的是**物理像素**，而用户填的
    是"看起来多大"。不做换算的话，200% 缩放屏上 300x380 会变成一个
    150x190 的小窗（实测踩过）。
    """
    try:
        # GetDpiForSystem 是 Win10 1607+ 的 API
        dpi = user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    try:
        hdc = user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)   # LOGPIXELSX
        user32.ReleaseDC(0, hdc)
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def start(*, port: int = 0, style: str = "", colorkey: str = "",
          width: int = 300, height: int = 380, x: int = 0, y: int = 0) -> int:
    if running_pids():
        print("  桌宠窗口已经在跑（要先关掉再开：--close）")
        return 1
    edge = _edge_exe()
    if not edge:
        print("  没找到 Edge，无法启动桌宠窗口")
        return 1

    cfg = load_config().get("pet") or {}
    style = style or ("colorkey" if cfg.get("transparent") else "solid")
    colorkey = colorkey or str(cfg.get("colorkey") or "#010203")
    width = int(cfg.get("window_width") or width)
    height = int(cfg.get("window_height") or height)

    # 服务可能已经从别的端口起来了（比如仪表盘占了 8770）。
    # 必须先问清实际端口，否则桌宠页面会指向一个没人监听的端口 ——
    # 实测踩过两次：一次窗口起来了但页面一直加载失败（指到 8771），
    # 一次 ensure_service 在 8771 起了个重复服务。
    # 顺序：显式指定的端口 -> 默认端口 -> 依次往后找第一个活着的。
    from lib.server import DEFAULT_PORT, ensure_service, service_alive
    candidates: list[int] = []
    if port:
        candidates.append(port)
    candidates += [DEFAULT_PORT, 8771, 8772, 8773]
    actual = next((p for p in candidates if service_alive(p)), 0)
    if not actual:
        ensure_service(port or DEFAULT_PORT)
        time.sleep(1.2)
        actual = next((p for p in candidates if service_alive(p)), 0)
    if not actual:
        print("  仪表盘服务没起来，桌宠窗口没有数据可显示")
        return 1

    scale = _system_dpi_scale()
    px_w = max(120, round(width * scale))
    px_h = max(120, round(height * scale))

    prof = ROOT / "data" / "pet-window-profile"
    prof.mkdir(parents=True, exist_ok=True)
    flags = ["--app=" + _pet_page_url(actual, style),
             f"--window-size={px_w},{px_h}",
             "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={prof}",
             "--disable-features=Translate,msEdgeSplitScreen"]
    if x or y:
        flags.append(f"--window-position={round(x * scale)},{round(y * scale)}")
    p = subprocess.Popen([edge, *flags],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=0x00000008 | 0x08000000)  # DETACHED | NO_WINDOW

    hwnd = 0
    for _ in range(40):
        time.sleep(0.5)
        hwnd = _find_window("学习监督 桌宠")
        if hwnd:
            break

    # --window-size 在这个环境下不可靠（实测要 320x400，页面视口却只有 215x332，
    # 像是被 DPI 又缩了一次）。所以窗口起来后用 Win32 直接定成精确尺寸，
    # 页面那边用 ResizeObserver 跟随，不依赖启动参数。
    if hwnd:
        HWND_TOPMOST = -1
        SWP_SHOWWINDOW = 0x0040
        user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x or 0), int(y or 0),
                            px_w, px_h, SWP_SHOWWINDOW)
        time.sleep(0.4)

    layered = False
    if hwnd and style == "colorkey":
        layered = _make_layered(hwnd, colorkey)

    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(json.dumps({
        "pids": [p.pid], "hwnd": hwnd, "style": style,
        "colorkey": colorkey if layered else "",
        "port": actual, "size": [width, height], "dpi_scale": scale,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  桌宠窗口已启动：PID {p.pid}｜窗口句柄 {hwnd or '未找到'}")
    print(f"    服务端口：{actual}（页面 {_pet_page_url(actual, style)}）")
    print(f"    样式：{'颜色键透明' if layered else '不透明背景'}"
          f"{'（' + colorkey + '）' if layered else ''}")
    print(f"    逻辑尺寸：{width}x{height}｜实际像素：{px_w}x{px_h}"
          f"（系统缩放 {scale:.2f}x）")
    if style == "colorkey" and not layered:
        print("    注意：颜色键透明没设置成功，窗口会是不透明的")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="独立桌宠窗口")
    ap.add_argument("--close", action="store_true", help="关闭桌宠窗口")
    ap.add_argument("--status", action="store_true", help="查看是否在跑")
    ap.add_argument("--port", type=int, default=8771, help="仪表盘服务端口")
    ap.add_argument("--style", choices=["solid", "colorkey"], default="",
                    help="solid=不透明背景（稳）；colorkey=颜色键透明（边缘会有硬边）")
    ap.add_argument("--colorkey", default="", help="颜色键，形如 #010203")
    ap.add_argument("--width", type=int, default=300)
    ap.add_argument("--height", type=int, default=380)
    ap.add_argument("--x", type=int, default=0)
    ap.add_argument("--y", type=int, default=0)
    args = ap.parse_args()
    if args.close:
        return stop()
    if args.status:
        return show_status()
    return start(port=args.port, style=args.style, colorkey=args.colorkey,
                 width=args.width, height=args.height, x=args.x, y=args.y)


if __name__ == "__main__":
    sys.exit(main())
