"""提醒：置顶小窗（tkinter）+ 系统提示音，失败时回退到系统通知。"""

from __future__ import annotations

import ctypes
import subprocess
import threading
import tkinter as tk
from typing import Any, Callable

user32 = ctypes.windll.user32


def _beep() -> None:
    def run():
        try:
            import winsound
            for _ in range(2):
                winsound.Beep(880, 180)
                winsound.Beep(660, 180)
        except Exception:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


def _toast(title: str, body: str) -> None:
    """回退方案：用 PowerShell 发 Windows 通知（不阻塞）。"""
    safe_title = title.replace("'", "''")
    safe_body = body.replace("'", "''").replace("\n", " ")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        f"$x=$t.GetElementsByTagName('text');$x.Item(0).AppendChild($t.CreateTextNode('{safe_title}')) > $null;"
        f"$x.Item(1).AppendChild($t.CreateTextNode('{safe_body}')) > $null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('学习监督').Show("
        "[Windows.UI.Notifications.ToastNotification]::new($t));"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


class ReminderWindow:
    """置顶提醒窗。非阻塞：由主循环周期性调用 pump()。"""

    def __init__(self, on_ack: Callable[[], None] | None = None,
                 on_mute: Callable[[int], None] | None = None,
                 auto_close_sec: int = 60,
                 mute_sec: int = 600):
        self.on_ack = on_ack
        self.on_mute = on_mute
        self.auto_close_sec = auto_close_sec
        self.mute_sec = mute_sec
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("学习监督")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.root.configure(bg="#1b2430")
        self._deadline = 0.0
        self._visible = False
        self._build()

    def _build(self) -> None:
        wrap = tk.Frame(self.root, bg="#1b2430", highlightthickness=1,
                        highlightbackground="#33465e")
        wrap.pack(fill="both", expand=True)

        head = tk.Frame(wrap, bg="#243447")
        head.pack(fill="x")
        self.title_lbl = tk.Label(head, text="别走神", bg="#243447", fg="#ffd166",
                                  font=("Microsoft YaHei UI", 12, "bold"), anchor="w", padx=12, pady=8)
        self.title_lbl.pack(side="left")

        self.body_lbl = tk.Label(wrap, text="", bg="#1b2430", fg="#e8eef6",
                                 font=("Microsoft YaHei UI", 10), justify="left",
                                 anchor="w", wraplength=440, padx=16, pady=10)
        self.body_lbl.pack(fill="both", expand=True)

        self.basis_lbl = tk.Label(wrap, text="", bg="#1b2430", fg="#8fa6bf",
                                  font=("Microsoft YaHei UI", 9), justify="left",
                                  anchor="w", wraplength=440, padx=16)
        self.basis_lbl.pack(fill="both", expand=True)

        bar = tk.Frame(wrap, bg="#1b2430")
        bar.pack(fill="x", pady=(8, 12), padx=16)
        self._button(bar, "知道了", self._ack, "#2f6f4f").pack(side="left")
        self._button(bar, f"安静 {self.mute_sec // 60} 分钟", self._mute,
                     "#3d4a5c").pack(side="left", padx=8)
        self._button(bar, "关闭", self.hide, "#3d4a5c").pack(side="right")

        for widget in (wrap, head, self.title_lbl, self.body_lbl, self.basis_lbl):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

    def _button(self, parent, text, cmd, color):
        b = tk.Label(parent, text=text, bg=color, fg="#ffffff", padx=12, pady=5,
                     font=("Microsoft YaHei UI", 9), cursor="hand2")
        b.bind("<Button-1>", lambda _e: cmd())
        return b

    def _start_drag(self, event) -> None:
        self._dx, self._dy = event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y()

    def _drag(self, event) -> None:
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")

    def _ack(self) -> None:
        self.hide()
        if self.on_ack:
            self.on_ack()

    def _mute(self) -> None:
        self.hide()
        if self.on_mute:
            self.on_mute(self.mute_sec)

    def show(self, verdict: dict[str, Any], goal: str = "") -> None:
        activity = verdict.get("activity") or "（模型没给出描述）"
        basis = verdict.get("basis") or ""
        cat = verdict.get("category") or "其他"

        self.title_lbl.config(text=f"别走神 · {cat}")
        self.body_lbl.config(text=f"检测到你正在：{activity}")
        self.basis_lbl.config(text=f"依据：{basis}" if basis else "")
        if goal:
            self.root.title(f"学习监督 · 目标：{goal}")

        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        sw = user32.GetSystemMetrics(0)
        x = max(20, sw - w - 40)
        self.root.geometry(f"+{x}+60")
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self._visible = True
        self._deadline = 0.0
        if self.auto_close_sec:
            import time
            self._deadline = time.time() + self.auto_close_sec

    def hide(self) -> None:
        self._visible = False
        self.root.withdraw()

    def pump(self) -> None:
        """在监控主循环里周期调用，用于处理按钮事件与自动关闭。"""
        try:
            self.root.update()
        except tk.TclError:
            return
        if self._visible and self._deadline:
            import time
            if time.time() > self._deadline:
                self.hide()

    def destroy(self) -> None:
        try:
            self.root.destroy()
        except tk.TclError:
            pass


class Notifier:
    """按配置选择提醒后端；后端不可用时自动回退。"""

    def __init__(self, cfg: dict[str, Any], on_mute: Callable[[int], None] | None = None):
        self.cfg = cfg
        self.backend = (cfg.get("reminder", {}).get("backend") or "auto").lower()
        self.window: ReminderWindow | None = None
        self._muted_until = 0.0
        if self.backend in ("auto", "tk", "window"):
            try:
                reminder = cfg.get("reminder", {})
                self.window = ReminderWindow(
                    on_mute=on_mute,
                    auto_close_sec=int(reminder.get("auto_close_sec", 60)),
                    mute_sec=max(60, int(reminder.get("mute_after_remind_sec", 600) or 600)),
                )
            except Exception as e:  # tkinter 不可用（如精简版 Python）
                print(f"[提醒] 置顶窗口不可用，改用系统通知：{e}")
                self.window = None
                self.backend = "toast"

    @property
    def muted(self) -> bool:
        import time
        return time.time() < self._muted_until

    def mute(self, seconds: int) -> None:
        import time
        self._muted_until = max(self._muted_until, time.time() + seconds)

    def notify(self, verdict: dict[str, Any], goal: str = "") -> None:
        reminder = self.cfg.get("reminder", {})
        if not reminder.get("enabled", True) or self.muted:
            return
        if reminder.get("sound", True):
            _beep()
        if self.window is not None:
            self.window.show(verdict, goal=goal)
        else:
            _toast("别走神 · " + str(verdict.get("category") or ""),
                   str(verdict.get("activity") or ""))
        mute_s = int(reminder.get("mute_after_remind_sec", 0) or 0)
        if mute_s:
            self.mute(mute_s)

    def pump(self) -> None:
        if self.window is not None:
            self.window.pump()

    def destroy(self) -> None:
        if self.window is not None:
            self.window.destroy()
