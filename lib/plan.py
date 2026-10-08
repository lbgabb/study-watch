"""番茄钟 / 专注计划：把"专注块 + 休息"的节奏真正跑起来。

与"只监督 N 分钟"的区别：这里有阶段状态机（专注→短休→…→长休）、
跨重启续上、并且**把休息时间的判定与专注时间分开统计**——
否则你老老实实休息反而会把专注率拉低，那就本末倒置了。

关于"科学规律"的一点说明（写在文档里，也写在这里免得以后有人当成随便编的数字）：

  · 25/5（Pomodoro 经典）：Francesco Cirillo 在 1980 年代末的实践总结，
    **不是实验结论**。它的价值主要在于把"开始"这个动作变得足够小。
  · 90/20（超日节律）：Kleitman 的 BRAC（基础休息-活动周期）认为清醒时也存在
    约 90 分钟的警觉度波动。观察性研究支持这个量级，但个体差异很大。
  · 52/17：DeskTime 2014 年对自家用户的一次**观察性统计**（效率最高的一组的
    平均工作/休息时长），不是对照实验，也会受"自愿上报"的偏差影响。

共同结论比具体数字更可靠：**连续专注有上限，休息要真的离开任务；
把时长固定下来能减少每次"要不要休息"的决策消耗。** 所以三种都给了预设，
挑一个能坚持的比挑一个"最科学"的更重要。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, date
from pathlib import Path
from typing import Any

from .config import ROOT

PLAN_PATH = ROOT / "data" / "plan.json"

# 预设：名字 -> (专注分钟, 短休分钟, 每几轮一次长休, 长休分钟)
PRESETS: dict[str, dict[str, Any]] = {
    "pomodoro": {
        "label": "25 / 5（番茄钟经典）",
        "focus_min": 25, "break_min": 5, "long_every": 4, "long_break_min": 20,
        "basis": "Cirillo 的实践总结：把任务切到足以立刻开始的大小；每 4 轮一次长休",
    },
    "ultradian": {
        "label": "90 / 20（超日节律）",
        "focus_min": 90, "break_min": 20, "long_every": 0, "long_break_min": 0,
        "basis": "Kleitman 的 BRAC：清醒时警觉度约 90 分钟一个周期。适合深度任务，但别硬扛",
    },
    "desktime": {
        "label": "52 / 17（DeskTime 统计）",
        "focus_min": 52, "break_min": 17, "long_every": 0, "long_break_min": 0,
        "basis": "DeskTime 2014 年对用户数据的观察性统计（效率最高一组的平均节奏）",
    },
    "sprint": {
        "label": "15 / 3（低启动成本）",
        "focus_min": 15, "break_min": 3, "long_every": 6, "long_break_min": 15,
        "basis": "状态差、任务难启动时的短冲刺。先做 15 分钟，往往就顺势做下去了",
    },
    "custom": {
        "label": "自定义",
        "focus_min": 25, "break_min": 5, "long_every": 4, "long_break_min": 20,
        "basis": "自己填的节奏",
    },
}

PHASE_FOCUS = "focus"
PHASE_BREAK = "break"
PHASE_LONG_BREAK = "long_break"

PHASE_LABEL = {
    PHASE_FOCUS: "专注",
    PHASE_BREAK: "短休息",
    PHASE_LONG_BREAK: "长休息",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Plan:
    """一个正在跑（或刚跑完）的专注计划。"""
    preset: str = "pomodoro"
    phase: str = PHASE_FOCUS
    round: int = 1                     # 当前是第几轮专注（从 1 开始）
    target_rounds: int = 0             # 计划做几轮；0 = 不限，直到手动停
    focus_min: int = 25
    break_min: int = 5
    long_every: int = 4
    long_break_min: int = 20
    remind_on_break: bool = False      # 休息时是否还提醒分心
    strict_break: bool = False         # 休息时是否把判定计入统计
    started_at: float = 0.0            # 整个计划开始时间（epoch 秒）
    phase_started_at: float = 0.0      # 当前阶段开始时间
    finished: bool = False
    stop_reason: str = ""
    note: str = ""                     # 用户给这次计划标的主题
    history: list[dict] = field(default_factory=list)   # 每阶段完成时记一条

    # ---------------------------------------------------------------- 派生值
    @property
    def phase_sec(self) -> int:
        if self.phase == PHASE_FOCUS:
            return self.focus_min * 60
        if self.phase == PHASE_LONG_BREAK:
            return self.long_break_min * 60
        return self.break_min * 60

    @property
    def phase_ends_at(self) -> float:
        return self.phase_started_at + self.phase_sec

    def remaining_sec(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        return max(0, int(round(self.phase_ends_at - now)))

    @property
    def is_break(self) -> bool:
        return self.phase in (PHASE_BREAK, PHASE_LONG_BREAK)

    def phase_label(self) -> str:
        return PHASE_LABEL.get(self.phase, self.phase)

    def done_focus_rounds(self) -> int:
        return sum(1 for h in self.history if h.get("phase") == PHASE_FOCUS
                   and h.get("completed"))

    def next_phase(self) -> tuple[str, int]:
        """返回 (下一个阶段, 下一个轮次)。

        规则：专注结束 -> 到点就是休息；每 long_every 轮专注后换成一次长休。
        """
        if self.phase == PHASE_FOCUS:
            need_long = (self.long_every > 0 and self.round % self.long_every == 0
                         and self.long_break_min > 0)
            return (PHASE_LONG_BREAK if need_long else PHASE_BREAK), self.round
        # 休息结束 -> 回到专注，轮次 +1
        return PHASE_FOCUS, self.round + 1


def load() -> Plan | None:
    if not PLAN_PATH.is_file():
        return None
    try:
        raw = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        known = {f for f in Plan.__dataclass_fields__}
        return Plan(**{k: v for k, v in raw.items() if k in known})
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def save(plan: Plan | None) -> None:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    if plan is None:
        try:
            PLAN_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        return
    tmp = PLAN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(plan), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(PLAN_PATH)


def start(preset: str = "pomodoro", *, target_rounds: int = 0,
          focus_min: int | None = None, break_min: int | None = None,
          long_every: int | None = None, long_break_min: int | None = None,
          note: str = "", remind_on_break: bool = False,
          strict_break: bool = False) -> Plan:
    """开始一个计划（会覆盖正在跑的那个）。"""
    base = dict(PRESETS.get(preset) or PRESETS["pomodoro"])
    plan = Plan(
        preset=preset if preset in PRESETS else "custom",
        phase=PHASE_FOCUS, round=1, target_rounds=max(0, int(target_rounds or 0)),
        focus_min=int(focus_min or base["focus_min"]),
        break_min=int(break_min or base["break_min"]),
        long_every=int(long_every if long_every is not None else base["long_every"]),
        long_break_min=int(long_break_min if long_break_min is not None
                           else base["long_break_min"]),
        remind_on_break=bool(remind_on_break),
        strict_break=bool(strict_break),
        started_at=time.time(), phase_started_at=time.time(),
        note=(note or "").strip(),
    )
    save(plan)
    return plan


def advance(plan: Plan, *, now: float | None = None, completed: bool = True) -> Plan:
    """把计划推进到下一阶段。返回更新后的 plan（可能已 finished）。"""
    now = now if now is not None else time.time()
    finished_phase = plan.phase
    plan.history.append({
        "phase": finished_phase,
        "round": plan.round,
        "started_at": datetime.fromtimestamp(plan.phase_started_at).isoformat(timespec="seconds"),
        "ended_at": datetime.fromtimestamp(now).isoformat(timespec="seconds"),
        "sec": max(0, int(now - plan.phase_started_at)),
        "completed": bool(completed),
    })

    # 专注阶段正常结束 -> 累计一个完成的专注轮
    if finished_phase == PHASE_FOCUS and completed:
        if plan.target_rounds and plan.round >= plan.target_rounds:
            plan.finished = True
            plan.stop_reason = "已完成计划的全部轮次"
            save(plan)
            return plan

    nxt, nxt_round = plan.next_phase()
    plan.phase = nxt
    plan.round = nxt_round
    plan.phase_started_at = now
    save(plan)
    return plan


def stop(plan: Plan | None, reason: str = "手动停止") -> Plan | None:
    if plan is None:
        return None
    plan.finished = True
    plan.stop_reason = reason
    save(plan)
    return plan


def clear() -> None:
    save(None)


# ---------------------------------------------------------------- 与监督循环对接
def phase_for(plan: Plan | None, now: float | None = None) -> tuple[str, dict]:
    """给当前这一轮判定用的上下文。

    返回 (phase, extra)，extra 会并进判定记录，便于事后按阶段统计。
    没有计划时返回 ("", {})，此时行为与不用番茄钟完全一致。
    """
    if plan is None or plan.finished:
        return "", {}
    return plan.phase, {
        "plan_preset": plan.preset,
        "plan_round": plan.round,
        "plan_phase": plan.phase,
    }


def describe(plan: Plan | None, now: float | None = None) -> dict:
    """给仪表盘用的完整状态。前端自己算倒计时，所以这里给的是绝对时间戳。"""
    if plan is None:
        return {"active": False}
    now = now if now is not None else time.time()
    remain = plan.remaining_sec(now)
    return {
        "active": not plan.finished,
        "finished": plan.finished,
        "stop_reason": plan.stop_reason,
        "preset": plan.preset,
        "preset_label": (PRESETS.get(plan.preset) or {}).get("label", plan.preset),
        "phase": plan.phase,
        "phase_label": plan.phase_label(),
        "is_break": plan.is_break,
        "round": plan.round,
        "target_rounds": plan.target_rounds,
        "phase_sec": plan.phase_sec,
        "phase_ends_at": plan.phase_ends_at,
        "remaining_sec": remain,
        "started_at": plan.started_at,
        "note": plan.note,
        "remind_on_break": plan.remind_on_break,
        "strict_break": plan.strict_break,
        "focus_min": plan.focus_min,
        "break_min": plan.break_min,
        "long_every": plan.long_every,
        "long_break_min": plan.long_break_min,
        "done_focus_rounds": plan.done_focus_rounds(),
        "rounds_total_sec": sum(h.get("sec", 0) for h in plan.history
                                if h.get("phase") == PHASE_FOCUS),
        "history": plan.history[-40:],
        "basis": (PRESETS.get(plan.preset) or {}).get("basis", ""),
    }


def presets_for_ui() -> list[dict]:
    out = []
    for key, p in PRESETS.items():
        out.append({
            "key": key, "label": p["label"], "focus_min": p["focus_min"],
            "break_min": p["break_min"], "long_every": p["long_every"],
            "long_break_min": p["long_break_min"], "basis": p["basis"],
        })
    return out
