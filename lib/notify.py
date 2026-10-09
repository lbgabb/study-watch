"""提醒：置顶小窗（tkinter）+ 系统提示音，失败时回退到系统通知。"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from .config import ROOT, load_config
from .reminder_copy import CARDS, pick_card, text_for

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


CARD_DIR = ROOT / "assets" / "reminder"


def card_path(card_key: str, reason: str = "") -> Path | None:
    """取提醒卡片素材。

    卡片由 tools/make_reminder_cards.py 预合成。有两种来源：
      1. 装了带依据的版本（card-<key>-r.png）—— 首次遇到某条依据时现场生成，
         这样"屏幕上看到什么"也能画进卡片，窗口里就只剩卡片 + 按钮；
      2. 通用版本（card-<key>.png）—— 仓库自带的兜底。
    都找不到就返回 None，调用方退回纯文字提醒。
    """
    if reason:
        cached = _reason_card(card_key, reason)
        if cached is not None:
            return cached
    for suffix in ("", ".en"):
        p = CARD_DIR / f"card-{card_key}{suffix}.png"
        if p.is_file():
            return p
    p = CARD_DIR / "card-general.png"
    return p if p.is_file() else None


# 带依据的卡片运行时生成，按内容缓存，避免同一句话重复渲染
_REASON_CACHE: dict[str, Path] = {}


def _reason_card(card_key: str, reason: str) -> Path | None:
    """现场合成"含依据"的卡片（失败不影响提醒，返回 None 即可）。"""
    import hashlib
    key = hashlib.sha1(f"{card_key}|{reason}".encode("utf-8")).hexdigest()[:12]
    cache_dir = ROOT / "data" / "reminder-cache"
    out = cache_dir / f"{card_key}-{key}.png"
    if out.is_file():
        return out
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from make_reminder_cards import build_card        # 延迟导入，避免启动开销
        import shutil
        cache_dir.mkdir(parents=True, exist_ok=True)
        # 生成到 assets 再由调用方读？不——直接让生成器写到缓存目录
        made = build_card(card_key, _ui_lang(), reason=reason, out_dir=cache_dir,
                          name=f"{card_key}-{key}.png")
        if made and made.is_file():
            _REASON_CACHE[key] = made
            return made
    except Exception:
        return None
    return None


def _ui_lang() -> str:
    """界面语言：配置里写明了就用它，否则看系统默认代码页。"""
    try:
        cfg_lang = (load_config().get("reminder") or {}).get("lang")
        if cfg_lang in ("zh", "en"):
            return cfg_lang
    except Exception:
        pass
    try:
        import locale
        code = (locale.getdefaultlocale()[0] or "").lower()
        return "zh" if code.startswith("zh") else "en"
    except Exception:
        return "zh"


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
        """搭好窗口骨架。

        布局顺序（从上到下）：
            卡片插画（有素材时） → 标题栏 → 判断依据 → 按钮行

        卡片是首次提醒时才载入的，如果那时才 pack()，tkinter 会把它排在最后
        （pack 按调用顺序排列），视觉上就变成"按钮在卡片上面"。所以这里
        先在顶部占一个占位 Frame，并记住它，之后把卡片塞进占位里 ——
        位置固定，不会再受创建时机影响。
        """
        wrap = tk.Frame(self.root, bg="#1b2430", highlightthickness=1,
                        highlightbackground="#33465e")
        wrap.pack(fill="both", expand=True)
        self._wrap = wrap

        # 顶部占位：卡片将来塞进这里，保证它永远在最上面
        self.art_slot = tk.Frame(wrap, bg="#141c26")
        self.art_lbl: tk.Label | None = None

        head = tk.Frame(wrap, bg="#243447")
        head.pack(fill="x")
        self._head = head
        self.title_lbl = tk.Label(head, text="别走神", bg="#243447", fg="#ffd166",
                                  font=("Microsoft YaHei UI", 12, "bold"), anchor="w", padx=12, pady=8)
        self.title_lbl.pack(side="left")

        self.body_lbl = tk.Label(wrap, text="", bg="#1b2430", fg="#e8eef6",
                                 font=("Microsoft YaHei UI", 10), justify="left",
                                 anchor="w", wraplength=396, padx=16, pady=10)
        self.body_lbl.pack(fill="both", expand=True)

        self.basis_lbl = tk.Label(wrap, text="", bg="#1b2430", fg="#8fa6bf",
                                  font=("Microsoft YaHei UI", 9), justify="left",
                                  anchor="w", wraplength=396, padx=16, pady=6)
        self.basis_lbl.pack(fill="x")

        bar = tk.Frame(wrap, bg="#1b2430")
        bar.pack(fill="x", pady=(6, 12), padx=16)
        self._bar = bar
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

    def _show_card(self, card_key: str, reason: str = "") -> str:
        """显示卡片。返回 "reason"（依据已画进卡片）/ "plain"（通用卡片）/ ""（无卡片）。"""
        """显示预合成的提醒卡片（插画 + 文案已由 Pillow 画进同一张图）。

        为什么整张显示而不是用 tkinter 拼：
          tkinter 的 Label 不支持 alpha 混合，透明区域会露出它自己的 RGB（白），
          没法把"透明圆角插画"叠在深色卡片上。所以合成在 Pillow 里做完。
        透明 PNG 在 Label 上仍会显示成白/黑块，所以这里用 flattened 的 RGB 卡片。
        """
        path = card_path(card_key, reason)
        if path is None:
            return ""
        try:
            from PIL import Image, ImageTk
            im = Image.open(path).convert("RGB")
        except Exception:
            return False

        self._art_cache = getattr(self, "_art_cache", {})
        photo = self._art_cache.get(card_key)
        if photo is None:
            try:
                photo = ImageTk.PhotoImage(im)
            except Exception:
                return False
            self._art_cache[card_key] = photo
        self._art = photo                      # 防止被 GC 回收

        # 卡片塞进 _build() 里预留的顶部占位，保证它在最上面。
        # 关键：占位要在 head **之前** pack —— 用 before= 指定顺序，
        # 否则首次显示时才 pack 的部件会排到最后（按钮下面）。
        if getattr(self, "art_lbl", None) is None:
            self.art_slot.pack(side="top", fill="x", before=self._head)
            self.art_lbl = tk.Label(self.art_slot, borderwidth=0, bg="#141c26")
            self.art_lbl.pack(side="top", fill="x")
        self.art_lbl.config(image=photo)
        # 依据是否已经画进卡片：看这张图是不是运行时合成的缓存版本。
        # 不能用内存缓存判断 —— 命中磁盘缓存时不会写内存，会误判成通用卡片。
        cache_dir = ROOT / "data" / "reminder-cache"
        try:
            is_reason = path.parent == cache_dir
        except Exception:
            is_reason = False
        return "reason" if is_reason else "plain"

    def show(self, verdict: dict[str, Any], goal: str = "", *,
             card_key: str = "", event: str = "", returning: bool = False) -> None:
        activity = verdict.get("activity") or "（模型没给出描述）"
        basis = verdict.get("basis") or ""
        cat = verdict.get("category") or "其他"

        # 先决定用哪张卡片。给了 card_key 就用它；
        # 否则按类别 / 事件 / 是不是刚回到正轨自动挑。
        key = card_key or pick_card(
            cat, returning=returning, event=event,
            process=verdict.get("process") or "", title=verdict.get("title") or "",
        )
        shown = self._show_card(key, basis)

        if shown:
            # 卡片上已经画了标题与文案，不再重复显示"别走神 · 类别"那一行
            self._head.pack_forget()
            self.body_lbl.pack_forget()
            self.root.title(f"学习监督 · {text_for(key)['title']}")
            # 依据已经画进卡片时就不再单独显示一行，否则会重复两遍
            if shown == "reason":
                self.basis_lbl.pack_forget()
            elif not self.basis_lbl.winfo_manager():
                self.basis_lbl.pack(fill="x")
        else:
            # 没有卡片素材就退回纯文字版，功能不受影响
            if not self._head.winfo_manager():
                self._head.pack(fill="x", before=self.basis_lbl)
            if not self.body_lbl.winfo_manager():
                self.body_lbl.pack(fill="both", expand=True, before=self.basis_lbl)
            if not self.basis_lbl.winfo_manager():
                self.basis_lbl.pack(fill="x")
            self.title_lbl.config(text=f"别走神 · {cat}")
            self.body_lbl.config(text=f"检测到你正在：{activity}")
            self.root.title("学习监督")

        # 判断依据始终要有出处：卡片上写的是吐槽，依据写的是"我凭什么这么说"。
        # 少了它，这工具就变成了随口指责。依据已画进卡片时就不重复了。
        self.basis_lbl.config(text=(f"依据：{basis}" if basis else f"检测到：{activity}"))

        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        h = self.root.winfo_reqheight()
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        x = max(20, sw - w - 40)
        y = max(20, min(60, sh - h - 60))
        self.root.geometry(f"+{x}+{y}")
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

    def notify(self, verdict: dict[str, Any], goal: str = "", *,
               card_key: str = "", event: str = "", returning: bool = False) -> None:
        reminder = self.cfg.get("reminder", {})
        if not reminder.get("enabled", True) or self.muted:
            return
        if reminder.get("sound", True):
            _beep()
        if self.window is not None:
            self.window.show(verdict, goal=goal, card_key=card_key,
                             event=event, returning=returning)
        else:
            key = card_key or pick_card(str(verdict.get("category") or ""),
                                        returning=returning, event=event)
            _toast("学习监督 · " + text_for(key)["title"],
                   str(verdict.get("activity") or ""))
        # 只对"分心"类提醒做静音；正反馈（回来啦/该休息/完成）不该被静音吞掉，
        # 否则用户永远看不到鼓励
        if not card_key or (CARDS.get(card_key, {}).get("tone") == "warn"):
            mute_s = int(reminder.get("mute_after_remind_sec", 0) or 0)
            if mute_s:
                self.mute(mute_s)

    def pump(self) -> None:
        if self.window is not None:
            self.window.pump()

    def destroy(self) -> None:
        if self.window is not None:
            self.window.destroy()
