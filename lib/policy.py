"""截图策略：结合前台应用决定这一轮要不要截图、要不要调用模型。

设计原则：
  - 这是"省钱 + 提准"的过滤器，不改变判定本身的质量
  - decide() 是纯函数，只依赖传入的时间戳，方便单测
  - 任何规则都不匹配时，退回全局 interval_sec 的行为
  - 状态只存在日志里（上次判定时间、上次见到某应用的时间），重启后不丢

规则语义（都按书写顺序，第一条命中者生效）：
  action=skip         该应用不做判定（游戏、全屏视频、私密应用）
  tick_sec=N          距上次判定满 N 秒才查（适合滚动阅读：PDF、IDE、网页）
  polling_sec=N       切到该应用先查一次，之后每 N 秒查一次
                      （适合长时间停在一个窗口的：聊天、视频播放）
  switch_check=true   窗口一切换到该应用就立刻查一次（不等间隔）
"""

from __future__ import annotations

import fnmatch
from datetime import datetime
from typing import Any

REASON_DEFAULT = "全局间隔到期"
REASON_TICK = "应用计时到期"
REASON_POLL = "应用轮询到期"
REASON_SWITCH = "窗口切换"
REASON_NEW_APP = "切换到新应用"
REASON_MIN_GAP = "距上次判定过近"
REASON_WAIT = "未到下次判定时间"
REASON_SKIP = "该应用不判定"


def normalize(name: str) -> str:
    """进程名/标题归一化：去路径、去 .exe、转小写。"""
    s = (name or "").strip().strip('"')
    if "\\" in s or "/" in s:
        s = s.replace("/", "\\").rsplit("\\", 1)[-1]
    if s.lower().endswith(".exe"):
        s = s[:-4]
    return s.lower()


def _match_any(patterns: list[str], value: str) -> bool:
    v = normalize(value)
    if not v:
        return False
    for p in patterns or []:
        pat = normalize(p)
        if pat and fnmatch.fnmatch(v, pat):
            return True
    return False


def _patterns(rule: dict, key: str) -> list[str]:
    out = list(rule.get(key) or [])
    contains = rule.get(f"{key}_contains")
    if contains:
        if isinstance(contains, str):
            contains = [contains]
        out += [f"*{c}*" for c in contains]
    return out


def rule_matches(rule: dict, ctx: dict) -> bool:
    """进程 或 窗口标题 命中即算命中；两者都没配则不命中。"""
    procs = _patterns(rule, "process")
    titles = _patterns(rule, "title")
    if not procs and not titles:
        return False
    if procs and _match_any(procs, ctx.get("process", "")):
        return True
    if titles and _match_any(titles, ctx.get("title", "")):
        return True
    return False


def find_rule(rules: list[dict], ctx: dict) -> dict | None:
    for rule in rules or []:
        if rule_matches(rule, ctx):
            return rule
    return None


def rule_label(rule: dict | None) -> str | None:
    if not rule:
        return None
    if rule.get("name"):
        return str(rule["name"])
    for key in ("process", "title"):
        vals = rule.get(key)
        if vals:
            return str(vals[0])
    return None


def parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def decide(
    cfg: dict[str, Any],
    ctx: dict,
    *,
    now: datetime,
    last_ok: datetime | None,
    last_app_key: str | None,
    last_app_seen: datetime | None,
) -> dict[str, Any]:
    """决定这一轮是否截图判定。

    返回 {"capture": bool, "reason": str, "rule": str|None, "app": str}
      app 是本次归一化后的前台标识（进程名），调用方应把它与现在的时间写进日志，
      作为下一次的 last_app_key / last_app_seen。
    """
    app = normalize(ctx.get("process", "")) or "(未知)"
    cap = cfg.get("capture") or {}

    if not cap.get("enabled", True):
        return {"capture": True, "reason": "策略已关闭", "rule": None, "app": app}

    rule = find_rule(cap.get("rules") or [], ctx)
    label = rule_label(rule)
    min_gap = float(cap.get("min_gap_sec") or 0)
    is_new_app = app != (last_app_key or "")

    def gate(reason: str) -> dict[str, Any]:
        """兜底闸门：距上次判定太近就不查，避免重启后连打。"""
        if last_ok and min_gap > 0 and (now - last_ok).total_seconds() < min_gap:
            return {"capture": False, "reason": REASON_MIN_GAP, "rule": label, "app": app}
        return {"capture": True, "reason": reason, "rule": label, "app": app}

    # 1) 该应用不判定
    if rule and str(rule.get("action", "check")).lower() == "skip":
        return {"capture": False, "reason": REASON_SKIP, "rule": label, "app": app}

    # 2) 应用专属节奏
    if rule:
        switch_check = bool(rule.get("switch_check"))
        if switch_check and is_new_app:
            return gate(REASON_SWITCH)

        tick = rule.get("tick_sec")
        poll = rule.get("polling_sec")
        if tick is not None:
            if not last_ok or (now - last_ok).total_seconds() >= float(tick):
                return gate(REASON_TICK)
            return {"capture": False, "reason": REASON_WAIT, "rule": label, "app": app}
        if poll is not None:
            # 刚切过来：先查一次摸清状态；否则按"距上次见到该应用"计时
            if is_new_app:
                return gate(REASON_NEW_APP)
            if last_app_seen and (now - last_app_seen).total_seconds() < float(poll):
                return {"capture": False, "reason": REASON_WAIT, "rule": label, "app": app}
            return gate(REASON_POLL)

    # 3) 全局间隔
    interval = float(cap.get("default_sec") or cfg.get("interval_sec") or 120)
    if last_ok and (now - last_ok).total_seconds() < interval:
        return {"capture": False, "reason": REASON_WAIT, "rule": label, "app": app}
    return gate(REASON_DEFAULT)
