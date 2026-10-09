"""学习监督的本地仪表盘：纯标准库 HTTP 服务。

访问 http://127.0.0.1:<port> 就能看到时间轴、类别占比、近 7 天与分心来源，
还能直接开始/停止监督、立刻判一次、导出日报。

不依赖任何第三方包，也不改变 monitor.py 的行为；这个进程只是"读日志 + 遥控"。
"""

from __future__ import annotations

import ctypes
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # 允许 python lib/server.py 直接运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "lib"

from .config import ROOT, load_config  # noqa: E402
from .config import CONFIG_PATH  # noqa: E402
from . import proc, report, store, vision  # noqa: E402
from . import plan  # noqa: E402
from .avatars import with_avatars  # noqa: E402
from . import pet_event  # noqa: E402
from .reminder_copy import pick_card  # noqa: E402

# 允许通过 /avatars/<key>.png 取到的头像（白名单，不做路径拼接）
AVATAR_KEYS = {"general", "shortvideo", "gaming", "social",
               "sleepy", "thumbsup", "relax", "celebrate"}

WEB_DIR = ROOT / "web"
DEFAULT_PORT = 8770
JSONL_KEEP = 200          # 前端"最近判定"展示条数
TIMELINE_KEEP = 400       # 时间轴最多画的段数


# ---------------------------------------------------------------- 进程状态
_RUNNING_CACHE: dict[str, Any] = {"at": 0.0, "pids": []}
_RUNNING_TTL = 2.0   # 秒：进程检测很快（纯 ctypes，约 10ms），但仍缓存一下削峰


def running_monitors(force: bool = False) -> list[int]:
    """找出正在跑 monitor.py 的进程（带短缓存）。

    主路径是纯 ctypes 读 PEB 拿命令行（lib/proc.py，约 10ms，不起子进程）；
    拿不到再退回 PowerShell/CIM，最后退回 data/monitor.pid。
    换机器时哪怕没有 PowerShell 也能正常工作。
    """
    import time as _time

    now = _time.time()
    if not force and now - _RUNNING_CACHE["at"] < _RUNNING_TTL:
        return list(_RUNNING_CACHE["pids"])

    pids = proc.pids_matching("monitor.py")

    if not pids:
        # 兜底 1：有些环境读不了其它进程的 PEB（权限/沙箱），退回 PowerShell
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" "
            "| Where-Object { $_.CommandLine -like '*monitor.py*' } "
            "| Select-Object -ExpandProperty ProcessId"
        )
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=20, creationflags=0x08000000,
            ).stdout or ""
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass

    if not pids:
        # 兜底 2：监控进程自己写的 pid 文件
        pidfile = ROOT / "data" / "monitor.pid"
        try:
            rec = json.loads(pidfile.read_text(encoding="utf-8"))
            pid = int(rec.get("pid", 0))
            if pid and _pid_alive(pid):
                pids = [pid]
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    # 双保险：结果里可能有刚退出、或命令行恰好含 monitor.py 的进程
    pids = [p for p in sorted(set(pids)) if _pid_alive(p)]
    _RUNNING_CACHE["at"] = now
    _RUNNING_CACHE["pids"] = pids
    return pids


def _pid_alive(pid: int) -> bool:
    k32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return code.value == 259  # STILL_ACTIVE
        return False
    finally:
        k32.CloseHandle(h)


# ---------------------------------------------------------------- 数据装配
def _records_on(day: date) -> list[dict]:
    return [r for r in store.load_day(load_config(), day) if r.get("status") == "ok"]


def _with_slots(recs: list[dict]) -> list[dict]:
    """给每条记录补上"持续了多少秒"（用与下一条的间隔，封顶 15 分钟）。"""
    out = []
    for i, r in enumerate(recs):
        sec = float(r.get("interval_sec") or 120)
        if i + 1 < len(recs):
            try:
                a = datetime.fromisoformat(r["ts"])
                b = datetime.fromisoformat(recs[i + 1]["ts"])
                gap = (b - a).total_seconds()
                if 0 < gap < 15 * 60:
                    sec = gap
            except (KeyError, ValueError):
                pass
        item = dict(r)
        item["sec"] = round(sec, 1)
        out.append(item)
    return out


def _proc_off(recs: list[dict]) -> list[dict]:
    agg: dict[str, float] = {}
    for r in recs:
        if r.get("on_task"):
            continue
        name = str(r.get("process") or "(未知)")
        agg[name] = agg.get(name, 0.0) + float(r.get("sec") or 0)
    return [{"name": k, "sec": round(v, 1)} for k, v in sorted(agg.items(), key=lambda kv: -kv[1])[:8]]


def _find_key(cfg: dict) -> tuple[bool, str]:
    try:
        vision.resolve_api_key(cfg)
        return True, ""
    except RuntimeError as e:
        return False, str(e)


def _pause_file() -> Path:
    return ROOT / "data" / "paused"


def _intent_file() -> Path:
    """用户意图标记：存在表示"用户希望它在监督"。

    为什么要它：如果无条件自愈，用户点了「停止」之后，页面每 5 秒的状态刷新
    又会把监控拉起来——停止就永远停不掉。所以只在意图为"要跑"时才自愈。
    """
    return ROOT / "data" / "desired_running"


def set_intent(on: bool) -> None:
    p = _intent_file()
    try:
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
        elif p.exists():
            p.unlink()
    except OSError:
        pass


def get_intent() -> bool:
    return _intent_file().exists()


def is_paused() -> bool:
    return _pause_file().exists()


def set_paused(on: bool) -> bool:
    p = _pause_file()
    try:
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
        elif p.exists():
            p.unlink()
        return True
    except OSError:
        return False


def _start_lock() -> Path:
    return ROOT / "data" / "start.lock"


class _StartLock:
    """跨进程互斥：防止"用户点开始"和"自动自愈"同时启动出两个监控进程。

    之前真出现过：两个请求都看到"没在跑"，各起一个，于是有两份监督在跑，
    重复判定、重复扣费、提醒也会弹两次。
    """

    def __enter__(self) -> bool:
        p = _start_lock()
        p.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(50):                      # 最多等 5 秒
            try:
                fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {datetime.now().isoformat(timespec='seconds')}".encode())
                os.close(fd)
                self.acquired = True
                return True
            except FileExistsError:
                # 拿锁的进程可能已经死了（上次异常退出），超时就清掉重试
                try:
                    if time.time() - p.stat().st_mtime > 30:
                        p.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(0.1)
        self.acquired = False
        return False

    def __exit__(self, *exc) -> None:
        if getattr(self, "acquired", False):
            try:
                _start_lock().unlink(missing_ok=True)
            except OSError:
                pass


def _ensure_monitor_alive() -> tuple[bool, str]:
    """在"用户希望它在跑"的前提下，确保监控进程真的在跑（带互斥）。

    只用于用户主动点按钮的路径（开始/暂停/继续），以及服务启动时的一次性恢复。
    状态刷新（/api/data）绝不调用它，否则「停止」会被刷新逻辑反复撤销。
    """
    if running_monitors(force=True):
        return False, ""
    with _StartLock():
        # 拿到锁后再确认一次：可能刚才另一个请求已经起好了
        if running_monitors(force=True):
            return False, ""
        set_paused(False)
        set_intent(True)
        pid = _spawn_background()
        time.sleep(0.6)                          # 给它一点时间出现在进程表里
        running_monitors(force=True)
        return True, f"已开始监督（PID {pid}）"


def _avatar_for(rec: dict, prev: dict | None = None) -> str:
    """给一条判定记录算"该显示哪个角色头像"。

    复用提醒卡片的选择逻辑（lib.reminder_copy.pick_card），仪表盘和提醒窗
    因此是同一套素材、同一套判断，不会出现"弹窗说是游戏、列表说是娱乐"。

    规则：
      · 休息时段 -> relax（该休息了）
      · 分心     -> 按类别/进程选（游戏、短视频、社交、发呆…）
      · 在状态   -> **刚从不专注切回来**才给 thumbsup（回来啦）；
                    一直专注时用中性头像，否则满屏竖拇指，看着像刷屏
    """
    if rec.get("plan_phase") in ("break", "long_break"):
        return "relax"
    if not rec.get("on_task"):
        return pick_card(
            str(rec.get("category") or ""),
            process=str(rec.get("process") or ""),
            title=str(rec.get("title") or ""),
        )
    return "thumbsup" if (prev is not None and not prev.get("on_task")) else "general"


def _query_day(path: str) -> date | None:
    """从 /api/data?day=YYYY-MM-DD 里取日期；没有或格式不对就返回 None（=今天）。"""
    if "?" not in path:
        return None
    qs = path.split("?", 1)[1]
    for pair in qs.split("&"):
        if pair.startswith("day="):
            raw = pair[4:].strip()
            try:
                return date.fromisoformat(raw)
            except ValueError:
                return None
    return None


def _int_or_none(v: Any) -> int | None:
    """把表单里可能是字符串/空值的数字转成 int；空值返回 None（= 用预设默认）。"""
    if v is None or v == "":
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _plan_action(action: str, body: dict) -> dict:
    """专注计划（番茄钟）的开始 / 结束 / 跳过 / 清除。

    数值来源优先级：本次请求里传的 > config.json 的 plan 段（用户上次调好的）> 预设默认。
    这样"自定义一次，以后就按你的来"，不用每次重填。
    """
    if action == "start":
        saved = load_config().get("plan") or {}
        preset = str(body.get("preset") or saved.get("preset") or "pomodoro")

        def pick(key: str, fallback: Any) -> Any:
            """请求里有就用请求的；否则用保存的；否则用兜底。"""
            v = _int_or_none(body.get(key))
            if v is not None:
                return v
            v = _int_or_none(saved.get(key))
            return v if v is not None else fallback

        base = plan.PRESETS.get(preset) or plan.PRESETS["pomodoro"]
        rounds = _int_or_none(body.get("rounds"))
        if rounds is None:
            rounds = int(saved.get("rounds") or 0)

        p = plan.start(
            preset,
            target_rounds=rounds,
            focus_min=pick("focus_min", base["focus_min"]),
            break_min=pick("break_min", base["break_min"]),
            long_every=(0 if body.get("long_every") == 0 else
                        pick("long_every", base["long_every"])),
            long_break_min=(0 if body.get("long_break_min") == 0 else
                            pick("long_break_min", base["long_break_min"])),
            note=str(body.get("note") or "").strip()[:80],
            remind_on_break=bool(body.get("remind_on_break", saved.get("remind_on_break"))),
            strict_break=bool(body.get("strict_break", saved.get("strict_break"))),
        )
        msg = f"已开始：{p.phase_label()} {p.phase_sec // 60} 分钟"
        if p.target_rounds:
            msg += f"｜计划 {p.target_rounds} 轮"

        # 联动启动监督。默认开（界面上的复选框默认勾选），传 False 可只当计时器用。
        # 注意：这是用户点「开始专注」触发的，属于明确意图，所以会写 intent。
        mon = None
        if body.get("start_monitor", True):
            try:
                mon = ensure_monitor()
                msg += "｜" + mon["message"]
            except Exception as e:
                mon = {"started": False, "error": str(e)}
                msg += "｜监督没能自动启动（计划照常计时）"

        return {"ok": True, "plan": plan.describe(p), "message": msg, "monitor": mon}

    if action == "status":
        p = plan.load()
        if p is None:
            return {"ok": True, "plan": {"active": False}, "message": "当前没有专注计划"}
        return {"ok": True, "plan": plan.describe(p), "message": "当前计划"}

    if action == "stop":
        p = plan.load()
        if p is None:
            return {"ok": True, "plan": {"active": False}, "message": "当前没有进行中的计划"}
        plan.stop(p, "手动结束")
        return {"ok": True, "plan": plan.describe(p),
                "message": f"已结束（完成 {p.done_focus_rounds()} 轮专注）"}

    if action == "clear":
        plan.clear()
        return {"ok": True, "plan": {"active": False}, "message": "已清除计划记录"}

    if action == "skip":
        p = plan.load()
        if p is None or p.finished:
            return {"ok": False, "message": "当前没有进行中的计划"}
        p = plan.advance(p, completed=False)
        if p.finished:
            return {"ok": True, "plan": plan.describe(p), "message": "计划已结束"}
        return {"ok": True, "plan": plan.describe(p),
                "message": f"已跳到{plan.PHASE_LABEL.get(p.phase, p.phase)}"
                           f"（{p.phase_sec // 60} 分钟）"}

    return {"ok": False, "message": f"未知操作：{action}"}


def build_data(day: date | None = None) -> dict[str, Any]:
    """组装仪表盘数据。

    day 指定"看哪一天"（默认今天）。概览卡、时间轴、分心明细、类别占比都属于这一天；
    近 7 天与进程状态始终按当前情况给，不受影响。
    """
    cfg = load_config()
    today = date.today()
    view_day = day or today
    all_recs = _records_on(view_day)
    slotted = _with_slots(all_recs)
    # 传 slotted 而不是 all_recs：aggregate 要复用记录上的 sec，
    # 否则它会自己在"排除休息后的子集"里重算间隔，口径与时间轴不一致
    agg = report.aggregate(slotted)

    # 时间轴：按间隔折算后连续排布。头像要按"前一条是什么"来算
    # （判断是否刚从不专注切回专注），所以整体过一次 with_avatars。
    timeline = with_avatars(
        [{"ts": r["ts"], "sec": r["sec"], "on_task": bool(r.get("on_task")),
          # 休息时段单独标出来：它的判定不计入统计（aggregate 会排除），
          # 所以时间轴必须用不同样式画。否则休息会被当作"在状态"着色，
          # 时间轴总时长也就和概览卡的"在状态+分心"对不上
          # （实测差过 594s，正好是一条 long_break）。
          "is_break": bool(r.get("exclude_from_stats")
                           or r.get("plan_phase") in ("break", "long_break")),
          "category": r.get("category") or "其他", "activity": r.get("activity") or "",
          "basis": r.get("basis") or "", "process": r.get("process") or "",
          "plan_phase": r.get("plan_phase") or "",
          "title": r.get("title") or ""}
         for r in slotted[-TIMELINE_KEEP:]],
        _avatar_for,
    )

    days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        recs = _records_on(d)
        a = report.aggregate(_with_slots(recs))
        days.append({
            "date": d.isoformat(), "checks": a["checks"],
            "on_task_sec": a["on_task_sec"], "off_task_sec": a["off_task_sec"],
            "on_task_rate": a["on_task_rate"], "cost_usd": a["cost_usd"],
        })

    # 有记录的日子列表（供日切换器用），从近 7 天的范围内再往外多找一些
    available = []
    try:
        for d in store.list_days(cfg):
            available.append(d.isoformat())
    except Exception:
        available = [x["date"] for x in days if x["checks"]]
    if view_day.isoformat() not in available:
        available.append(view_day.isoformat())
    available = sorted(set(available), reverse=True)[:60]

    key_ok, hint = _find_key(cfg)
    pids = running_monitors()
    paused = is_paused()
    last = None
    if slotted:
        r = slotted[-1]
        prev_rec = slotted[-2] if len(slotted) > 1 else None
        last = {
            "ts": r["ts"], "activity": r.get("activity"), "basis": r.get("basis"),
            "category": r.get("category"), "on_task": bool(r.get("on_task")),
            "process": r.get("process"), "confidence": r.get("confidence", 0),
            "cost_usd": r.get("cost_usd", 0),
            "avatar": _avatar_for(r, prev_rec),
        }

    return {
        "running": bool(pids),
        "paused": paused,
        "state": ("paused" if paused and pids else "running" if pids else "stopped"),
        "pids": pids,
        "interval_sec": cfg["interval_sec"],
        "model": cfg["api"]["model"],
        "save_shots": bool(cfg["privacy"].get("save_shots")),
        "key_ok": key_ok,
        "key_hint": hint,
        "today": {
            "checks": agg["checks"], "errors": agg["errors"], "skipped": agg["skipped"],
            "span_sec": agg["span_sec"], "on_task_sec": agg["on_task_sec"],
            "off_task_sec": agg["off_task_sec"], "on_task_rate": agg["on_task_rate"],
            "cost_usd": agg["cost_usd"], "tokens_in": agg["tokens_in"],
            "tokens_out": agg["tokens_out"], "avg_latency_ms": agg["avg_latency_ms"],
            "cat_sec": [{"cat": k, "sec": v} for k, v in agg["cat_sec"].items()],
            "proc_off": _proc_off(slotted),
            "off_events": with_avatars(agg["off_events"][-20:], _avatar_for),
            "timeline": timeline,
            "recent": with_avatars(slotted[-JSONL_KEEP:], _avatar_for),
            "last": last,
        },
        "days": days,
        "view_day": view_day.isoformat(),
        "is_today": view_day == today,
        "available_days": available,
        "plan": plan.describe(plan.load()),
        "plan_presets": plan.presets_for_ui(),
        # 桌宠要播的事件（监控进程写，仪表盘轮询时读走）。见 lib/pet_event.py
        "pet": pet_event.latest(),
    }


# ---------------------------------------------------------------- 控制动作
def _python_exe() -> str:
    return sys.executable


def _monitor_cmd(*args: str) -> list[str]:
    return [_python_exe(), str(ROOT / "monitor.py"), *args]


def _spawn_background() -> int:
    """后台静默启动 monitor.py，返回 pid。"""
    flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    p = subprocess.Popen(
        _monitor_cmd("--background"),
        cwd=str(ROOT), creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return p.pid


def _monitor_pids() -> list[int]:
    """当前在跑的监控进程（不含自己）。"""
    try:
        out = subprocess.run(
            _monitor_cmd("--status", "--pids-only"), cwd=str(ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, creationflags=0x08000000,
        ).stdout or ""
    except Exception:
        return []
    return [int(l.strip()) for l in out.splitlines() if l.strip().isdigit()]


def ensure_monitor() -> dict[str, Any]:
    """确保监督在跑：没跑就起来，已经在跑就不重复起。

    为什么需要这个：界面上的「开始专注」原本只开计时器，用户还得再点一次
    「开始监督」——两个动作，而且忘了点第二次的话，这一整轮 90 分钟不会有
    任何判定记录，等于白计时（没统计）。做成联动后又必须防重复启动，
    否则会起出两个监控：重复截图、重复扣费、提醒弹两次。
    """
    before = _monitor_pids()
    if before:
        return {"started": False, "already": True, "pids": before,
                "message": "监督已经在跑"}
    set_intent(True)                     # 记住"用户要它在跑"，进程意外退出后能自愈
    pid = _spawn_background()
    return {"started": True, "already": False, "pids": [pid],
            "message": "已同时启动监督"}


def _run_once() -> dict[str, Any]:
    """跑一次 --once，解析出 JSON 结果（这条路径不产生后台进程）。"""
    proc = subprocess.run(
        _monitor_cmd("--once"), cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
        creationflags=0x08000000,
    )
    text = proc.stdout or ""
    start = text.find("{")
    if start < 0:
        return {"ok": False, "message": "没有拿到判定结果", "raw": text[-400:]}
    try:
        data = json.loads(text[start:])
    except json.JSONDecodeError:
        return {"ok": False, "message": "判定结果解析失败", "raw": text[-400:]}
    if data.get("status") != "ok":
        return {"ok": False, "message": data.get("error") or f"状态：{data.get('status')}",
                "activity": data.get("activity")}
    return {
        "ok": True, "message": ("在状态" if data.get("on_task") else "分心")
                                + " · " + str(data.get("category") or ""),
        "activity": data.get("activity"),
    }


def _render_markdown() -> dict[str, Any]:
    cfg = load_config()
    p = report.export_markdown(cfg, date.today())
    return {"ok": True, "message": f"已导出：{p}"}


# ---------------------------------------------------------------- 配置读写（控制面板用）
# 哪些项改了要重启监控才生效 —— 这些值在监控进程里是"一轮内固定"的
RESTART_KEYS = {
    "api.base_url": "接口地址", "api.model": "模型", "api.api_key_env": "key 环境变量名",
    "api.credentials_file": "凭据文件路径", "api.timeout_sec": "超时",
    "max_width": "截图宽度", "privacy.save_shots": "截图落盘", "privacy.shots_dir": "截图目录",
}
# 哪些项下一轮就会生效
HOT_KEYS = {
    "interval_sec": "判定间隔", "idle_skip_sec": "空闲跳过阈值", "jpeg_quality": "JPEG 质量",
    "detail": "图片精度", "capture.enabled": "截图策略开关", "capture.min_gap_sec": "兜底间隔",
    "capture.default_sec": "全局间隔覆盖", "judge.goal": "学习目标", "judge.strictness": "严格程度",
    "judge.extra_rules": "额外规则", "judge.alias_rules": "归类约定",
    "reminder.enabled": "提醒开关", "reminder.sound": "提示音",
    "reminder.mute_after_remind_sec": "提醒后安静时长",
    "reminder.off_task_streak_required": "连续几次才提醒", "reminder.auto_close_sec": "提醒窗自动关闭",
    "privacy.save_api_raw": "保存模型原始回复",
    "plan.preset": "番茄钟预设", "plan.focus_min": "专注时长", "plan.break_min": "休息时长",
    "plan.long_every": "长休间隔", "plan.long_break_min": "长休时长",
    "plan.rounds": "计划轮数", "plan.remind_on_break": "休息时是否提醒",
    "plan.strict_break": "休息是否计入统计",
    "plan.start_monitor": "开始专注时是否连带启动监督",
    "pet.enabled": "启用 Live2D 桌宠", "pet.max_fps": "桌宠帧率上限",
    "pet.show_plan": "桌宠显示专注计划", "pet.speak": "桌宠说出提醒内容",
    "pet.pause_when_hidden": "切到后台时暂停桌宠",
}

# 允许通过面板修改的字段（白名单，避免误写坏配置）
EDITABLE: dict[str, type] = {
    "interval_sec": int, "idle_skip_sec": float, "jpeg_quality": int, "detail": str,
    "max_width": int,
    "capture.enabled": bool, "capture.min_gap_sec": float, "capture.default_sec": (int, type(None)),
    "judge.goal": str, "judge.strictness": str,
    "judge.extra_rules": list, "judge.alias_rules": list,
    "reminder.enabled": bool, "reminder.sound": bool,
    "reminder.mute_after_remind_sec": int, "reminder.off_task_streak_required": int,
    "reminder.auto_close_sec": int,
    "privacy.save_shots": bool, "privacy.save_api_raw": bool, "privacy.shots_dir": str,
    "api.base_url": str, "api.model": str, "api.api_key_env": str,
    "api.credentials_file": str, "api.timeout_sec": int,
    "api.temperature": float, "api.max_tokens": int,
    # 番茄钟的默认节奏（用户自定义的数值靠这些项持久化）
    "plan.preset": str, "plan.focus_min": int, "plan.break_min": int,
    "plan.long_every": int, "plan.long_break_min": int, "plan.rounds": int,
    "plan.remind_on_break": bool, "plan.strict_break": bool,
    "plan.start_monitor": bool,
    "pet.enabled": bool, "pet.max_fps": int, "pet.show_plan": bool,
    "pet.speak": bool, "pet.pause_when_hidden": bool,
}

VALID_DETAIL = ("low", "high", "auto")
VALID_STRICTNESS = ("loose", "normal", "strict")


def _dig(d: dict, path: str) -> Any:
    cur: Any = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _poke(d: dict, path: str, value: Any) -> None:
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def _validate_edit(path: str, value: Any) -> tuple[bool, Any, str]:
    """返回 (是否接受, 规范化后的值, 拒绝原因)。"""
    expect = EDITABLE.get(path)
    if expect is None:
        return False, None, "不允许修改这项"
    if value is None:
        if path in ("capture.default_sec",):
            return True, None, ""
        return False, None, "不能为空"
    # bool 要放在 int 前面判断（Python 里 True 也是 int）
    if expect is bool:
        if not isinstance(value, bool):
            return False, None, "需要 true/false"
        return True, value, ""
    if expect is int:
        if isinstance(value, bool) or not isinstance(value, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                return False, None, "需要整数"
        return True, value, ""
    if expect is float:
        try:
            return True, float(value), ""
        except (TypeError, ValueError):
            return False, None, "需要数字"
    if expect is list:
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            return True, [x.strip() for x in value if x.strip()], ""
        return False, None, "需要字符串数组"
    if expect is str:
        s = str(value).strip()
        if path == "api.base_url":
            if not (s.startswith("http://") or s.startswith("https://")):
                return False, None, "要写成 http(s):// 开头"
            s = s.rstrip("/")
        if path == "detail" and s not in VALID_DETAIL:
            return False, None, f"只能是 {'/'.join(VALID_DETAIL)}"
        if path == "judge.strictness" and s not in VALID_STRICTNESS:
            return False, None, f"只能是 {'/'.join(VALID_STRICTNESS)}"
        if not s and path not in ("judge.goal",):
            return False, None, "不能为空"
        return True, s, ""
    return False, None, "类型不支持"


def read_config_for_ui() -> dict[str, Any]:
    cfg = load_config()
    return {
        "values": {
            "interval_sec": cfg["interval_sec"],
            "idle_skip_sec": cfg["idle_skip_sec"],
            "jpeg_quality": cfg["jpeg_quality"],
            "detail": cfg["detail"],
            "max_width": cfg["max_width"],
            "capture.enabled": (cfg.get("capture") or {}).get("enabled", True),
            "capture.min_gap_sec": (cfg.get("capture") or {}).get("min_gap_sec", 20),
            "capture.default_sec": (cfg.get("capture") or {}).get("default_sec"),
            "judge.goal": cfg["judge"].get("goal", ""),
            "judge.strictness": cfg["judge"].get("strictness", "normal"),
            "judge.extra_rules": cfg["judge"].get("extra_rules") or [],
            "judge.alias_rules": cfg["judge"].get("alias_rules") or [],
            "reminder.enabled": cfg["reminder"].get("enabled", True),
            "reminder.sound": cfg["reminder"].get("sound", True),
            "reminder.mute_after_remind_sec": cfg["reminder"].get("mute_after_remind_sec", 300),
            "reminder.off_task_streak_required": cfg["reminder"].get("off_task_streak_required", 1),
            "reminder.auto_close_sec": cfg["reminder"].get("auto_close_sec", 60),
            "privacy.save_shots": cfg["privacy"].get("save_shots", False),
            "privacy.save_api_raw": cfg["privacy"].get("save_api_raw", True),
            "privacy.shots_dir": cfg["privacy"].get("shots_dir", "data/shots"),
            "api.base_url": cfg["api"].get("base_url", ""),
            "api.model": cfg["api"].get("model", ""),
            "api.api_key_env": cfg["api"].get("api_key_env", "DEEPSEEK_API_KEY"),
            "api.credentials_file": cfg["api"].get("credentials_file", ""),
            "api.timeout_sec": cfg["api"].get("timeout_sec", 90),
            "api.temperature": cfg["api"].get("temperature", 0),
            "api.max_tokens": cfg["api"].get("max_tokens", 900),
            # 番茄钟：用户上次的选择（自定义数值也在这里，重启后不丢）
            "plan.preset": (cfg.get("plan") or {}).get("preset", "pomodoro"),
            "plan.focus_min": (cfg.get("plan") or {}).get("focus_min", 25),
            "plan.break_min": (cfg.get("plan") or {}).get("break_min", 5),
            "plan.long_every": (cfg.get("plan") or {}).get("long_every", 4),
            "plan.long_break_min": (cfg.get("plan") or {}).get("long_break_min", 20),
            "plan.rounds": (cfg.get("plan") or {}).get("rounds", 0),
            "plan.remind_on_break": (cfg.get("plan") or {}).get("remind_on_break", False),
            "plan.strict_break": (cfg.get("plan") or {}).get("strict_break", False),
    "plan.start_monitor": (cfg.get("plan") or {}).get("start_monitor", True),
    "pet.enabled": (cfg.get("pet") or {}).get("enabled", True),
    "pet.max_fps": (cfg.get("pet") or {}).get("max_fps", 20),
    "pet.show_plan": (cfg.get("pet") or {}).get("show_plan", True),
    "pet.speak": (cfg.get("pet") or {}).get("speak", True),
    "pet.pause_when_hidden": (cfg.get("pet") or {}).get("pause_when_hidden", True),
        },
        "key": vision.key_status(cfg),
        "config_path": str(CONFIG_PATH),
        "restart_keys": RESTART_KEYS,
        "hot_keys": HOT_KEYS,
        "rules_count": len((cfg.get("capture") or {}).get("rules") or []),
    }


def apply_config_edits(edits: dict[str, Any], api_key: str | None = None) -> dict[str, Any]:
    """校验并写入 config.json（可选同时保存 key 到 data/secrets.json）。"""
    if not isinstance(edits, dict):
        return {"ok": False, "message": "请求格式不对"}

    current = load_config()
    accepted: dict[str, Any] = {}
    rejected: list[str] = []

    for path, value in edits.items():
        ok, norm, why = _validate_edit(path, value)
        if ok:
            _poke(current, path, norm)
            accepted[path] = norm
        else:
            rejected.append(f"{path}：{why}")

    if rejected and not accepted:
        return {"ok": False, "message": "没有可保存的改动 —— " + "；".join(rejected)}
    if rejected:
        return {"ok": False, "message": "部分项不合法，已全部取消保存 —— " + "；".join(rejected)}

    # 写入时保留规则等未在面板暴露的内容（load_config 已经合并了默认值，直接整体写回）
    payload = {k: v for k, v in current.items() if not k.startswith("_")}
    try:
        tmp = CONFIG_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
    except OSError as e:
        return {"ok": False, "message": f"写配置文件失败：{e}"}

    key_saved = False
    if api_key is not None and str(api_key).strip():
        env_name = current["api"].get("api_key_env") or "DEEPSEEK_API_KEY"
        secrets = vision.read_local_secrets()
        secrets[env_name] = str(api_key).strip()
        vision.write_local_secrets(secrets)
        key_saved = True

    to_restart = [RESTART_KEYS[p] for p in accepted if p in RESTART_KEYS]
    hot = [HOT_KEYS[p] for p in accepted if p in HOT_KEYS]

    msg = f"已保存 {len(accepted)} 项"
    if key_saved:
        msg += "（含新的 API key）"
    if to_restart:
        msg += f"；其中「{'、'.join(to_restart)}」需重启监督才生效"
    elif hot:
        msg += f"；下一轮判定起生效（{'、'.join(hot)}）"

    return {"ok": True, "message": msg, "saved": list(accepted.keys()),
            "need_restart": to_restart, "hot": hot, "key_saved": key_saved}


def test_api_config(edits: dict[str, Any] | None = None, api_key: str | None = None) -> dict[str, Any]:
    """用"当前配置 + 面板里刚填的值"测一次，不落盘。"""
    cfg = load_config()
    if isinstance(edits, dict):
        for path, value in edits.items():
            ok, norm, _ = _validate_edit(path, value)
            if ok:
                _poke(cfg, path, norm)
    try:
        r = vision.check_api(cfg, key_override=api_key)
    except Exception as e:
        return {"ok": False, "message": str(e)}
    return {
        "ok": True,
        "message": (f"连通正常（{r['latency_ms']} ms，tokens {r['tokens_in']}/{r['tokens_out']}）"
                    + ("" if r["json_ok"] else "，但模型没按 JSON 回复，建议换个模型")),
        "seen": (r["parsed"].get("seen") or r["parsed"].get("activity") or "") if r["json_ok"] else "",
        "json_ok": r["json_ok"],
        "model": r["model"],
        "base_url": r["base_url"],
    }


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "StudyWatch/1.0"
    protocol_version = "HTTP/1.1"

    # ---- 输出助手
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj: Any, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _file(self, path: Path, ctype: str) -> None:
        if not path.is_file():
            self._json({"ok": False, "message": f"缺少文件 {path.name}"}, 404)
            return
        self._send(200, path.read_bytes(), ctype)

    # ---- 路由
    def do_GET(self) -> None:
        route = self.path.split("?")[0]
        if route in ("/", "/index.html"):
            self._file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        elif route == "/app.js":
            self._file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
        elif route == "/pet.js":
            self._file(WEB_DIR / "pet.js", "application/javascript; charset=utf-8")
        elif route == "/pet":
            # 独立桌宠窗口用的页面（无顶栏、只有角色与气泡）。
            # 与仪表盘共用同一个服务，所以用户只开桌宠也能用。
            self._file(WEB_DIR / "pet.html", "text/html; charset=utf-8")
        elif route == "/api/pet":
            # 桌宠专用的轻量接口：只给窗口需要的东西，
            # 不拉整天的时间轴与图表数据（那个接口是给仪表盘用的）。
            try:
                cfg = load_config()
                pet_cfg = cfg.get("pet") or {}
                day = _records_on(date.today())
                slotted = _with_slots(day)
                last = None
                off_streak = 0
                if slotted:
                    r = slotted[-1]
                    prev_rec = slotted[-2] if len(slotted) > 1 else None
                    last = {"ts": r["ts"], "on_task": bool(r.get("on_task")),
                            "activity": r.get("activity") or "",
                            "category": r.get("category") or "",
                            "confidence": r.get("confidence"),
                            "avatar": _avatar_for(r, prev_rec)}
                    # 末尾连续分心了几次。桌宠用它决定要不要"哭"。
                    # 在服务端算而不是让前端数：前端只拿到一条 last，
                    # 要数就得把当天所有记录都传过去 —— 而这是个刻意做轻的接口。
                    for rec in reversed(slotted):
                        if rec.get("on_task"):
                            break
                        off_streak += 1
                # 深夜：23 点到次日 5 点，且此刻不在状态。
                # 只在"该睡却在跑神"时提示，正常熬夜学习不打扰。
                hour = datetime.now().hour
                self._json({
                    "pet.enabled": pet_cfg.get("enabled", True),
                    "pet.max_fps": pet_cfg.get("max_fps", 20),
                    "pet.show_plan": pet_cfg.get("show_plan", True),
                    "pet.speak": pet_cfg.get("speak", True),
                    "pet.pause_when_hidden": pet_cfg.get("pause_when_hidden", True),
                    "plan": plan.describe(plan.load()),
                    "last": last,
                    "off_streak": off_streak,
                    "night": hour >= 23 or hour < 5,
                    "event": pet_event.latest().get("latest"),
                })
            except Exception as e:
                self._json({"error": str(e)})
        elif route == "/favicon.ico":
            icon = ROOT / "assets" / "study-watch.ico"
            self._file(icon, "image/x-icon") if icon.is_file() else self._send(204, b"", "image/x-icon")
        elif route == "/api/pet-window":
            # 独立桌宠窗口是否在跑（POST 那个分支负责开关）
            try:
                from lib import pet_window as pw
                pids = pw.running_pids()
                self._json({"ok": True, "running": bool(pids), "pids": pids})
            except Exception as e:
                self._json({"ok": False, "running": False, "message": str(e)})
        elif route.startswith("/live2d/") or route.startswith("/vendor/"):
            # Live2D 模型与运行时。只允许白名单扩展名，且路径里不许出现 ..
            rel = route.lstrip("/")
            if ".." in rel or rel.startswith("/"):
                self._send(403, b"bad path", "text/plain; charset=utf-8")
            elif Path(rel).suffix.lower() not in (".json", ".png", ".js", ".moc3"):
                self._send(403, b"bad type", "text/plain; charset=utf-8")
            else:
                f = ROOT / "assets" / rel
                if f.is_file():
                    ct = {".json": "application/json; charset=utf-8",
                          ".png": "image/png",
                          ".js": "application/javascript; charset=utf-8",
                          ".moc3": "application/octet-stream"}[f.suffix.lower()]
                    self._file(f, ct)
                else:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
        elif route.startswith("/avatars/"):
            # 角色头像（assets/reminder/face/<key>.png）。白名单文件名，
            # 不做路径拼接，避免 ../ 之类的问题。
            name = route[len("/avatars/"):]
            key = name[:-4] if name.endswith(".png") else name
            if key in AVATAR_KEYS:
                f = ROOT / "assets" / "reminder" / "face" / f"{key}.png"
                if f.is_file():
                    self._file(f, "image/png")
                else:
                    self._send(404, b"no avatar", "text/plain; charset=utf-8")
            else:
                self._send(404, b"unknown avatar", "text/plain; charset=utf-8")
        elif route == "/api/data":
            try:
                self._json(build_data(_query_day(self.path)))
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        elif route == "/api/config":
            try:
                self._json(read_config_for_ui())
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        route = self.path.split("?")[0]
        try:
            if route == "/api/start":
                set_intent(True)           # 记住"用户要它在跑"
                if running_monitors(force=True) and not is_paused():
                    self._json({"ok": True, "message": "已经在监督中了，没有重复启动"})
                    return
                # 走带互斥的统一入口，避免并发请求各起一个
                started, msg = _ensure_monitor_alive()
                if started:
                    self._json({"ok": True, "message": msg})
                elif is_paused():
                    set_paused(False)
                    self._json({"ok": True, "message": "已在运行，已从暂停恢复"})
                else:
                    self._json({"ok": True, "message": "已经在监督中了，没有重复启动"})
            elif route == "/api/pause":
                started, msg = _ensure_monitor_alive()
                ok = set_paused(True)
                if started:
                    self._json({"ok": True, "message": f"{msg}，并已暂停"})
                else:
                    self._json({"ok": ok, "message": "已暂停判定（进程待命，恢复即继续）" if ok
                                else "暂停标记写入失败"})
            elif route == "/api/resume":
                started, msg = _ensure_monitor_alive()
                ok = set_paused(False)
                if started:
                    self._json({"ok": True, "message": f"{msg}，正在判定"})
                else:
                    self._json({"ok": ok, "message": "已恢复判定" if ok else "清除暂停标记失败"})
            elif route == "/api/stop":
                set_paused(False)
                set_intent(False)          # 记住"用户不要它跑了"，状态刷新不会把它拉回来
                pids = running_monitors(force=True)
                if not pids:
                    self._json({"ok": True, "message": "当前没有在监督"})
                    return
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except OSError:
                        try:
                            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                           capture_output=True, creationflags=0x08000000)
                        except Exception:
                            pass
                running_monitors(force=True)
                self._json({"ok": True, "message": f"已停止 {len(pids)} 个监督进程"})
            elif route == "/api/once":
                self._json(_run_once())
            elif route == "/api/export":
                self._json(_render_markdown())
            elif route == "/api/config":
                body = self._read_json_body()
                if body is None:
                    self._json({"ok": False, "message": "请求体不是合法 JSON"}, 400)
                    return
                self._json(apply_config_edits(body.get("edits") or {}, body.get("api_key")))
            elif route == "/api/check-api":
                body = self._read_json_body() or {}
                self._json(test_api_config(body.get("edits"), body.get("api_key")))
            elif route == "/api/plan":
                body = self._read_json_body() or {}
                self._json(_plan_action(str(body.get("action") or "start"), body))
            elif route == "/api/pet-window":
                # 独立桌宠窗口的开关。窗口是**另一个进程**，所以这里只负责
                # 起/停它并回报状态；关掉窗口不影响监督与统计。
                body = self._read_json_body() or {}
                action = str(body.get("action") or "status")
                from lib import pet_window as pw
                if action == "open":
                    flags = 0x00000008 | 0x08000000
                    subprocess.Popen(
                        [sys.executable, str(ROOT / "lib" / "pet_window.py")],
                        cwd=str(ROOT), creationflags=flags,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, close_fds=True)
                    time.sleep(1.2)
                    pids = pw.running_pids()
                    self._json({"ok": True, "running": bool(pids), "pids": pids,
                                "message": "桌宠窗口正在打开" if pids else "正在启动，几秒后出现"})
                elif action == "close":
                    pw.stop()
                    self._json({"ok": True, "running": False, "pids": [],
                                "message": "桌宠窗口已关闭"})
                else:
                    pids = pw.running_pids()
                    self._json({"ok": True, "running": bool(pids), "pids": pids})
            else:
                self._json({"ok": False, "message": "未知接口"}, 404)
        except Exception as e:
            self._json({"ok": False, "message": f"{type(e).__name__}: {e}"}, 500)

    def _read_json_body(self) -> dict | None:
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n <= 0:
                return {}
            raw = self.rfile.read(n)
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("STUDY_WATCH_WEB_VERBOSE"):
            sys.stderr.write("[web] " + (fmt % args) + "\n")


def _pick_port(preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"端口 {preferred}~{preferred + 19} 都被占用了")


def service_alive(port: int = DEFAULT_PORT, timeout: float = 3.0) -> bool:
    """探测仪表盘服务是否已经在跑。"""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/data",
                               timeout=timeout).read(64)
        return True
    except Exception:
        return False


def ensure_service(port: int = DEFAULT_PORT, *, wait_sec: float = 12.0) -> int:
    """服务没在跑就起一个（脱离当前进程）。返回实际端口。

    为什么桌宠需要它：桌宠窗口是个浏览器页面，得有个服务给它提供模型与
    状态数据。用户可能只开了桌宠、没开仪表盘，所以这里要能把服务拉起来。
    """
    if service_alive(port):
        return port
    flags = 0x00000008 | 0x08000000        # DETACHED_PROCESS | CREATE_NO_WINDOW
    subprocess.Popen(
        [sys.executable, str(ROOT / "lib" / "server.py"),
         "--no-open", "--port", str(port)],
        cwd=str(ROOT), creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        close_fds=True)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if service_alive(port):
            return port
        time.sleep(0.4)
    return port


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="学习监督仪表盘（本地网页界面）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)

    port = _pick_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True

    print(f"学习监督仪表盘已启动：{url}")
    print("（Ctrl+C 结束；这个进程只负责显示与遥控，关掉它不影响正在进行的监督）")

    # 一次性自愈：如果上次关服务时用户是"要监督"的状态，把监控进程接回来。
    # 注意只在启动时做一次 —— 状态刷新路径绝不自动启动，否则「停止」会被反复撤销。
    if get_intent():
        started, msg = _ensure_monitor_alive()
        print(("  已恢复上次的监督状态：" + msg) if started else "  监督进程仍在运行")
    else:
        print("  当前没有监督进程（用户上次是停止状态）；可在页面上点「开始监督」")

    if not args.no_open:
        threading.Thread(target=lambda: (webbrowser.open(url)), daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出仪表盘")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
