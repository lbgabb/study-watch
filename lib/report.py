"""统计报表：把 JSONL 记录聚合成学习时长、分心次数与来源。"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from . import store

FOCUS_CATEGORIES = {"学习", "工作"}
# 两次判定之间最多按这么长时间计入时长（防止长时间挂机被算成学习）
MAX_SLOT_SEC = 15 * 60


def _dt(rec: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(rec["ts"])
    except (KeyError, ValueError):
        return None


def _load_sec(rec: dict) -> float:
    try:
        return max(0.0, float(rec.get("load_sec") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def aggregate(records: list[dict]) -> dict[str, Any]:
    """把一天的记录按下一次判定的间隔折算成时长。

    番茄钟休息时段的记录（exclude_from_stats）单独归到 break_sec，不计入
    专注率与类别占比——否则老老实实休息反而把数据拉低，那就本末倒置了。
    """
    all_ok = [r for r in records if r.get("status") == "ok"]
    err = [r for r in records if r.get("status") == "error"]
    skipped = [r for r in records if str(r.get("status", "")).startswith(("idle", "own", "locked"))]
    break_sec = sum(float(r.get("sec") or 0) for r in all_ok if r.get("exclude_from_stats"))
    ok = [r for r in all_ok if not r.get("exclude_from_stats")]

    cat_sec: dict[str, float] = {}
    proc_sec: dict[str, float] = {}
    off_task_sec = 0.0
    on_task_sec = 0.0
    focus_sec = 0.0
    off_events: list[dict] = []
    cost = 0.0
    tokens_in = tokens_out = 0
    latencies: list[int] = []

    for i, r in enumerate(ok):
        ts = _dt(r)
        if ts is None:
            continue
        load = _load_sec(r) or float(r.get("interval_sec") or 120)
        if i + 1 < len(ok):
            nxt = _dt(ok[i + 1])
            if nxt:
                gap = (nxt - ts).total_seconds()
                if 0 < gap < MAX_SLOT_SEC:
                    load = gap
        load = min(load, MAX_SLOT_SEC)

        cat = str(r.get("category") or "其他")
        cat_sec[cat] = cat_sec.get(cat, 0.0) + load
        proc = str(r.get("process") or "(未知)")
        proc_sec[proc] = proc_sec.get(proc, 0.0) + load

        if r.get("on_task"):
            on_task_sec += load
            if cat in FOCUS_CATEGORIES:
                focus_sec += load
        else:
            off_task_sec += load
            off_events.append(r)

        cost += float(r.get("cost_usd") or 0.0)
        tokens_in += int(r.get("tokens_in") or 0)
        tokens_out += int(r.get("tokens_out") or 0)
        if r.get("latency_ms"):
            latencies.append(int(r["latency_ms"]))

    span = 0.0
    times = [t for t in (_dt(r) for r in ok) if t]
    if len(times) > 1:
        span = (times[-1] - times[0]).total_seconds()

    return {
        "checks": len(ok),
        "errors": len(err),
        "skipped": len(skipped),
        "break_sec": break_sec,
        "break_checks": len(all_ok) - len(ok),
        "span_sec": span,
        "on_task_sec": on_task_sec,
        "off_task_sec": off_task_sec,
        "focus_sec": focus_sec,
        "on_task_rate": (on_task_sec / (on_task_sec + off_task_sec)) if (on_task_sec + off_task_sec) else 0.0,
        "cat_sec": dict(sorted(cat_sec.items(), key=lambda kv: -kv[1])),
        "proc_sec": dict(sorted(proc_sec.items(), key=lambda kv: -kv[1])),
        "off_events": off_events,
        "cost_usd": cost,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "avg_latency_ms": int(sum(latencies) / len(latencies)) if latencies else 0,
    }


def fmt_dur(sec: float) -> str:
    sec = int(sec)
    h, m = divmod(sec // 60, 60)
    if h:
        return f"{h}小时{m:02d}分"
    if m:
        return f"{m}分{sec % 60}秒"
    return f"{sec}秒"


def render_day(records: list[dict], day: date | None = None, top: int = 8) -> str:
    day = day or date.today()
    agg = aggregate(records)
    lines: list[str] = []
    lines.append(f"=== 学习监督日报 {day:%Y-%m-%d} ===")
    if not agg["checks"]:
        lines.append("（这一天没有任何判定记录）")
        return "\n".join(lines)

    lines.append(
        f"判定次数 {agg['checks']} 次（错误 {agg['errors']}｜跳过 {agg['skipped']}）"
        f"，覆盖 {fmt_dur(agg['span_sec'])}"
    )
    lines.append(
        f"在状态 {fmt_dur(agg['on_task_sec'])}｜分心 {fmt_dur(agg['off_task_sec'])}"
        f"｜专注率 {agg['on_task_rate'] * 100:.0f}%"
    )
    lines.append("")
    lines.append("- 各类别时长 -")
    for cat, sec in agg["cat_sec"].items():
        lines.append(f"  {cat:<4} {fmt_dur(sec):>10}  {'#' * max(1, round(sec / 60))}")
    lines.append("")
    lines.append(f"- 分心来源 Top{top} -")
    for proc, sec in list(agg["proc_sec"].items())[:top]:
        lines.append(f"  {proc:<24} {fmt_dur(sec):>10}")
    lines.append("")
    if agg["off_events"]:
        lines.append(f"- 分心记录（最近 10 条 / 共 {len(agg['off_events'])} 条）-")
        for r in agg["off_events"][-10:]:
            lines.append(f"  {r.get('ts','')[11:19]}  [{r.get('category')}] {r.get('activity','')[:60]}")
        lines.append("")
    if agg["cost_usd"]:
        lines.append(
            f"- 成本：${agg['cost_usd']:.4f}｜tokens in {agg['tokens_in']} / out {agg['tokens_out']}"
            f"｜平均延迟 {agg['avg_latency_ms']} ms"
        )
    return "\n".join(lines)


def render_range(cfg: dict[str, Any], days: int = 7) -> str:
    data = store.load_range(cfg, days)
    if not data:
        return "没有历史记录。"
    lines = [f"=== 最近 {days} 天汇总 ===", ""]
    lines.append(f"{'日期':<12}{'判定':>5}{'在状态':>10}{'分心':>10}{'专注率':>8}")
    total_focus = total_off = 0.0
    for d, recs in data:
        agg = aggregate(recs)
        total_focus += agg["on_task_sec"]
        total_off += agg["off_task_sec"]
        lines.append(
            f"{d:%Y-%m-%d}  {agg['checks']:>5}{fmt_dur(agg['on_task_sec']):>10}"
            f"{fmt_dur(agg['off_task_sec']):>10}{agg['on_task_rate'] * 100:>7.0f}%"
        )
    overall = (total_focus / (total_focus + total_off) * 100) if (total_focus + total_off) else 0
    lines.append("")
    lines.append(f"合计：在状态 {fmt_dur(total_focus)}｜分心 {fmt_dur(total_off)}｜专注率 {overall:.0f}%")
    return "\n".join(lines)


def export_markdown(cfg: dict[str, Any], day: date | None = None) -> Path:
    day = day or date.today()
    recs = store.load_day(cfg, day)
    agg = aggregate(recs)
    out_dir = Path(store.data_dir(cfg)) / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{day:%Y-%m-%d}.md"

    md = [f"# 学习监督日报 {day:%Y-%m-%d}", ""]
    md.append(f"- 判定次数：{agg['checks']}")
    md.append(f"- 在状态：{fmt_dur(agg['on_task_sec'])}")
    md.append(f"- 分心：{fmt_dur(agg['off_task_sec'])}")
    md.append(f"- 专注率：{agg['on_task_rate'] * 100:.0f}%")
    md.append("")
    md.append("| 类别 | 时长 |")
    md.append("| --- | --- |")
    for cat, sec in agg["cat_sec"].items():
        md.append(f"| {cat} | {fmt_dur(sec)} |")
    md.append("")
    md.append("| 程序 | 时长 |")
    md.append("| --- | --- |")
    for proc, sec in agg["proc_sec"].items():
        md.append(f"| {proc} | {fmt_dur(sec)} |")
    if agg["off_events"]:
        md.append("")
        md.append("## 分心记录")
        md.append("")
        md.append("| 时间 | 类别 | 在做什么 | 依据 |")
        md.append("| --- | --- | --- | --- |")
        for r in agg["off_events"]:
            md.append(
                f"| {str(r.get('ts',''))[11:19]} | {r.get('category','')} "
                f"| {str(r.get('activity','')).replace('|', '/')} "
                f"| {str(r.get('basis',''))[:80].replace('|', '/')} |"
            )
    p.write_text("\n".join(md), encoding="utf-8-sig")  # 带 BOM，Windows 记事本/Excel 打开不乱码
    return p
