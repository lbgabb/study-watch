"""日报渲染自测：造一天假数据（含分心与错误），检查日报与 Markdown 导出。

只读真实日志之外的部分，写入 data/logs/_selftest-*.jsonl（不污染当日真实记录）。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import report, store
from lib.config import load_config


def main() -> int:
    cfg = load_config()
    today = date.today()
    recs = []
    base_minutes = 0
    samples = [
        (True, "学习", "msedge.exe", "在 B 站看理论力学期末复习课，画面是转动惯量课件"),
        (True, "学习", "msedge.exe", "在 B 站看理论力学期末复习课，画面是例题讲解"),
        (False, "娱乐", "msedge.exe", "在刷 B 站首页推荐短视频，竖屏一屏一个视频"),
        (False, "娱乐", "msedge.exe", "还在刷推荐流短视频，屏幕下方有弹幕"),
        (True, "学习", "WINWORD.EXE", "在 Word 里整理理论力学笔记"),
        (True, "学习", "python.exe", "在 VS Code 里写作业代码并运行测试"),
        (True, "学习", "msedge.exe", "在看教材 PDF，页面是动量矩定理章节"),
    ]

    class FakeDT:
        pass

    from datetime import datetime, timedelta as td
    start = datetime.combine(today, datetime.min.time()).replace(hour=19)
    for i, (on_task, cat, proc, act) in enumerate(samples):
        ts = start + td(minutes=2 * i)
        recs.append({
            "ts": ts.isoformat(timespec="seconds"),
            "status": "ok", "title": f"{proc} 窗口", "process": proc,
            "category": cat, "on_task": on_task, "confidence": 0.85,
            "activity": act, "basis": "屏幕截图显示：" + act,
            "interval_sec": 120, "tokens_in": 660, "tokens_out": 480,
            "cost_usd": 0.00077, "latency_ms": 3100, "reminded": not on_task,
        })
    recs.append({"ts": (start + td(minutes=15)).isoformat(timespec="seconds"),
                 "status": "idle_skip", "idle_sec": 420.0})
    recs.append({"ts": (start + td(minutes=16)).isoformat(timespec="seconds"),
                 "status": "error", "error": "HTTP 429: rate limited"})

    out = report.render_day(recs, today)
    print(out)
    print()

    agg = report.aggregate(recs)
    assert agg["checks"] == len(samples), agg["checks"]
    assert agg["errors"] == 1
    assert agg["skipped"] == 1
    assert agg["off_task_sec"] > 0 and agg["on_task_sec"] > 0
    assert 0 < agg["on_task_rate"] < 1
    assert "娱乐" in agg["cat_sec"] and "学习" in agg["cat_sec"]

    # 分心时长应约等于 2 次分心 × 2 分钟间隔
    off_min = agg["off_task_sec"] / 60
    assert 3.5 <= off_min <= 4.5, off_min

    md = report.render_markdown(recs, today) if hasattr(report, "render_markdown") else None
    print("[自测通过] 聚合数值符合预期：",
          f"在状态 {report.fmt_dur(agg['on_task_sec'])}｜分心 {report.fmt_dur(agg['off_task_sec'])}"
          f"｜专注率 {agg['on_task_rate']*100:.0f}%｜成本 ${agg['cost_usd']:.4f}")
    if md:
        print(md[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
