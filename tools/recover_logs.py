"""从 data/raw/ 的模型原始回复重建每日判定日志（data/logs/*.jsonl）。

用途：如果日志被误删，raw 目录里每条判定的完整结果还在，可以据此恢复。

能恢复的字段：activity / category / on_task / confidence / basis /
             latency_ms / tokens_in / tokens_out / cost_usd / model
需要推算的字段：
  · ts   —— 从文件名里的时间戳得到（YYYYMMDD-HHMMSS-micro）
  · sec —— 按与下一条判定的间隔推算（最后一条用默认 interval）

恢复不出来的：policy_reason（哪条截图规则放行/跳过）这类只在日志里写的字段。
恢复出的记录会带 recovered:true 标记，便于和你后面的新记录区分。

用法：
    python tools/recover_logs.py                  # 先看会恢复什么（不写盘）
    python tools/recover_logs.py --apply          # 真的写入
    python tools/recover_logs.py --apply --only 2026-10-08
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
LOGS = ROOT / "data" / "logs"
DEFAULT_SEC = 180


def parse_name(p: Path) -> datetime | None:
    """20261009-143056-414050.json -> datetime"""
    stem = p.stem                      # 20261009-143056-414050
    parts = stem.split("-")
    if len(parts) != 3:
        return None
    try:
        return datetime.strptime(parts[0] + parts[1], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def collect() -> dict[str, list[dict]]:
    """按日期归集恢复出的记录。"""
    by_day: dict[str, list[tuple[datetime, dict]]] = {}
    for p in sorted(RAW.glob("*.json")):
        ts = parse_name(p)
        if ts is None:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("demo"):
            continue
        rec = {
            "status": "ok",
            "ts": ts.isoformat(timespec="seconds"),
            "on_task": bool(data.get("on_task")),
            "category": data.get("category") or "其他",
            "activity": data.get("activity") or "",
            "basis": data.get("basis") or "",
            "confidence": data.get("confidence"),
            "latency_ms": data.get("latency_ms"),
            "tokens_in": data.get("tokens_in"),
            "tokens_out": data.get("tokens_out"),
            "cost_usd": data.get("cost_usd"),
            "model": data.get("model") or "",
            "recovered": True,
            "recovered_from": p.name,
        }
        # 进程/标题在 raw 里没有，留空；sec 稍后按间隔补
        by_day.setdefault(ts.date().isoformat(), []).append((ts, rec))

    out: dict[str, list[dict]] = {}
    for day, items in by_day.items():
        items.sort(key=lambda x: x[0])
        recs = []
        for i, (ts, rec) in enumerate(items):
            if i + 1 < len(items):
                gap = (items[i + 1][0] - ts).total_seconds()
                rec["sec"] = int(gap) if 0 < gap < 3600 else DEFAULT_SEC
            else:
                rec["sec"] = DEFAULT_SEC
            rec["interval_sec"] = DEFAULT_SEC
            recs.append(rec)
        out[day] = recs
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的写入（默认只预览）")
    ap.add_argument("--only", help="只处理某一天：2026-10-08")
    args = ap.parse_args()

    if not RAW.is_dir():
        print(f"  找不到 {RAW}")
        return 1

    days = collect()
    if args.only:
        days = {k: v for k, v in days.items() if k == args.only}
    if not days:
        print("  没有可恢复的记录")
        return 1

    total = 0
    for day in sorted(days):
        recs = days[day]
        on = sum(1 for r in recs if r["on_task"])
        cost = sum(float(r.get("cost_usd") or 0) for r in recs)
        total += len(recs)
        print(f"  {day}  可恢复 {len(recs):>3} 条（在状态 {on} 条，"
              f"约 {sum(r['sec'] for r in recs) / 3600:.1f} 小时，花费 ${cost:.4f}）")
        print(f"            首条 {recs[0]['ts'][11:16]}｜末条 {recs[-1]['ts'][11:16]}")

        if not args.apply:
            continue
        LOGS.mkdir(parents=True, exist_ok=True)
        path = LOGS / f"{day}.jsonl"
        existing = []
        if path.is_file():
            existing = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        lines = existing + [json.dumps(r, ensure_ascii=False) for r in recs]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"            -> 已写入 {path.name}（原有 {len(existing)} 条 + 恢复 {len(recs)} 条）")

    print()
    if args.apply:
        print(f"  共恢复 {total} 条，写入 data/logs/")
        print("  提示：恢复的记录带 recovered:true，且没有 policy_reason 字段。")
    else:
        print(f"  预览：共 {total} 条。加 --apply 才会写入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
