"""把监控进程发生的"值得让桌宠演一下"的事写成一个事件文件，供仪表盘读取。

为什么需要这个中转：
  提醒由**监控进程**（Python，独立后台进程）产生，
  桌宠在**浏览器**里（仪表盘页面）。
  两边没有长连接，所以用一个很小的 JSON 文件当信箱：
  监控进程写，仪板盘每 5 秒轮询时把它读走。

为什么不用 WebSocket / SSE：
  这个项目的服务端是纯标准库 ThreadingHTTPServer，加长连接要处理重连、
  心跳、多标签页广播；而事件本身就是"几秒内看到就行"的东西，
  5 秒轮询完全够用。少一个会坏的部件。

防重复播放：带一个自增序号 seq，浏览器记住"上次播到几号"，
  只有 seq 变大才播，刷新页面也不会把旧提醒重演一遍。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import ROOT

EVENT_PATH = ROOT / "data" / "pet_event.json"

# 保留最近这么多条，避免文件无限增长
KEEP = 20


def _read_raw() -> dict[str, Any]:
    if not EVENT_PATH.is_file():
        return {"seq": 0, "events": []}
    try:
        d = json.loads(EVENT_PATH.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return {"seq": 0, "events": []}
        d.setdefault("seq", 0)
        d.setdefault("events", [])
        return d
    except (OSError, json.JSONDecodeError):
        return {"seq": 0, "events": []}


def emit(kind: str, card: str, *, activity: str = "", basis: str = "",
         extra: dict | None = None) -> None:
    """追加一条事件。

    kind   分心 / 阶段切换 / 计划完成 之类的类型，前端按它决定动画
    card   用哪张提醒卡片（也就是用哪个表情），与 lib/reminder_copy 的键一致
    """
    try:
        d = _read_raw()
        seq = int(d.get("seq") or 0) + 1
        ev = {
            "seq": seq,
            "ts": time.time(),
            "time": time.strftime("%H:%M:%S"),
            "kind": kind,
            "card": card,
            "activity": activity[:200],
            "basis": basis[:300],
        }
        if extra:
            ev.update(extra)
        events = list(d.get("events") or [])
        events.append(ev)
        EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EVENT_PATH.write_text(
            json.dumps({"seq": seq, "events": events[-KEEP:]}, ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        # 桌宠事件是锦上添花，写失败绝不能影响监督本身
        pass


def latest() -> dict[str, Any]:
    """给仪表盘读：最新一条事件 + 总序号。"""
    d = _read_raw()
    events = d.get("events") or []
    return {"seq": int(d.get("seq") or 0),
            "latest": events[-1] if events else None,
            "recent": events[-5:]}


def clear() -> None:
    try:
        EVENT_PATH.unlink(missing_ok=True)
    except OSError:
        pass
