"""记录存储：按天写 JSONL，便于审计与统计。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import data_dir


def log_path(cfg: dict[str, Any], day: date | None = None) -> Path:
    day = day or date.today()
    d = data_dir(cfg) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{day:%Y-%m-%d}.jsonl"


def append(cfg: dict[str, Any], record: dict[str, Any]) -> None:
    record.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    with log_path(cfg).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_raw(cfg: dict[str, Any], verdict: dict[str, Any]) -> str:
    """保存模型原始回复，便于排查误判。"""
    if not cfg.get("privacy", {}).get("save_api_raw", True):
        return ""
    d = data_dir(cfg) / "raw"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    p.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(p)


def load_day(cfg: dict[str, Any], day: date | None = None) -> list[dict[str, Any]]:
    p = log_path(cfg, day)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_range(cfg: dict[str, Any], days: int = 7) -> list[tuple[date, list[dict]]]:
    today = date.today()
    out = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        recs = load_day(cfg, d)
        if recs:
            out.append((d, recs))
    return out


def list_days(cfg: dict[str, Any]) -> list[date]:
    d = data_dir(cfg) / "logs"
    if not d.exists():
        return []
    days = []
    for f in d.glob("*.jsonl"):
        try:
            days.append(datetime.strptime(f.stem, "%Y-%m-%d").date())
        except ValueError:
            continue
    return sorted(days)
