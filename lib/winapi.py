"""Windows 侧信息采集：前台窗口 / 进程、空闲时间、控制台可见性。

零第三方依赖，全部走 ctypes。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as w
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def foreground_window() -> dict:
    """返回当前前台窗口的 hwnd / 标题 / 进程名 / exe 路径。"""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {"hwnd": 0, "title": "", "process": "", "exe": "", "pid": 0}

    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)

    pid = w.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    exe = ""
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            pbuf = ctypes.create_unicode_buffer(1024)
            size = w.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, pbuf, ctypes.byref(size)):
                exe = pbuf.value
        finally:
            kernel32.CloseHandle(handle)

    return {
        "hwnd": int(hwnd),
        "title": buf.value,
        "process": Path(exe).name if exe else "",
        "exe": exe,
        "pid": int(pid.value),
    }


def idle_seconds() -> float:
    """距上次键鼠输入的秒数（休眠/锁屏时会很大）。"""
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    tick = kernel32.GetTickCount()
    # dwTime 是 32 位毫秒计数，会回绕，用掩码做差
    return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0


def virtual_screen() -> tuple[int, int, int, int]:
    """整个虚拟桌面（含多显示器）的 left, top, width, height。"""
    gsm = user32.GetSystemMetrics
    return gsm(76), gsm(77), gsm(78), gsm(79)  # XVIRTUALSCREEN..CYVIRTUALSCREEN


def own_pid() -> int:
    return int(kernel32.GetCurrentProcessId())


def is_session_locked() -> bool:
    """锁屏检测：能打开输入桌面说明是解锁状态。"""
    try:
        h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_READOBJECTS
        if h:
            user32.CloseDesktop(h)
            return False
        return True
    except Exception:
        return False


def hide_console() -> None:
    hwnd = kernel32.GetConsoleWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 0)  # SW_HIDE


def set_dpi_aware() -> None:
    """让截图坐标与物理像素一致（避免 125%/150% 缩放下截图模糊或被裁剪）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
