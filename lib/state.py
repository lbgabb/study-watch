"""跨轮次/跨重启的小状态：上次判定时间、上次见到的前台应用、上次窗口句柄。

放在 data/state.json，而不是塞进日志行：
  - 截图策略需要"最后一次判定是什么时候、当时前台是谁"
  - 进程重启后仍要能续上，否则会立刻连打几次
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ROOT

EMPTY: dict[str, Any] = {
    "last_ok": None,        # 上次成功判定的时间（ISO）
    "last_app": None,       # 上次判定时的前台进程（归一化）
    "last_app_seen": None,  # 上次"见到"该应用并记录的时间（ISO）
    "last_hwnd": None,      # 上次前台窗口句柄
}


def state_path() -> Path:
    return ROOT / "data" / "state.json"


def load() -> dict[str, Any]:
    p = state_path()
    data = dict(EMPTY)
    if not p.exists():
        return data
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update({k: v for k, v in raw.items() if k in EMPTY})
    except (OSError, json.JSONDecodeError):
        pass
    return data


def save(state: dict[str, Any]) -> None:
    p = state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: state.get(k) for k in EMPTY}
        payload["updated"] = datetime.now().isoformat(timespec="seconds")
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)   # 原子替换，避免写一半被读到
    except OSError:
        pass


def record_capture(state: dict[str, Any], *, app: str, hwnd: int | None,
                   when: datetime | None = None) -> dict[str, Any]:
    """判定成功后调用：刷新所有时间戳。"""
    now = when or datetime.now()
    iso = now.isoformat(timespec="seconds")
    state["last_ok"] = iso
    state["last_app"] = app
    state["last_app_seen"] = iso
    state["last_hwnd"] = hwnd
    return state


def record_seen(state: dict[str, Any], *, app: str, hwnd: int | None,
                when: datetime | None = None) -> dict[str, Any]:
    """未判定（跳过/等待）时调用：只更新"见到该应用"的痕迹。

    注意不刷新 last_ok —— 否则等待逻辑永远等不到。
    """
    now = when or datetime.now()
    iso = now.isoformat(timespec="seconds")
    if app != (state.get("last_app") or ""):
        state["last_app"] = app
        state["last_app_seen"] = iso
    state["last_hwnd"] = hwnd
    return state
