"""配置加载：config.json + 环境变量覆盖。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent   # lib/
ROOT = PROJECT_DIR.parent                       # 项目根目录
CONFIG_PATH = ROOT / "config.json"              # 配置在根目录，不在 lib/ 下

DEFAULTS: dict[str, Any] = {
    "interval_sec": 120,
    "min_gap_sec": 30,
    "max_width": 1600,
    "jpeg_quality": 85,
    "detail": "low",
    "idle_skip_sec": 300,
    # 按前台应用分配截图：命中规则的应用可以少查、跳过或切换即查
    "capture": {
        "enabled": True,
        "default_sec": None,      # None 表示用 interval_sec
        "min_gap_sec": 20,        # 两次判定之间至少间隔这么久（防止重启后连打）
        "rules": [],
    },
    # 番茄钟 / 专注计划：记住用户上次选的节奏与自定义数值，
    # 省得每次打开都要重填一遍
    "plan": {
        "preset": "pomodoro",     # 上次用的预设；自定义时也会记成 custom
        "focus_min": 25,
        "break_min": 5,
        "long_every": 4,
        "long_break_min": 20,
        "rounds": 0,              # 0 = 不限轮数
        "remind_on_break": False,
        "strict_break": False,
        "start_monitor": True,    # 点「开始专注」时是否连带启动监督
    },
    "api": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
        "credentials_file": "~/.dsh/.credentials.yaml",
        "temperature": 0,
        "max_tokens": 900,
        "timeout_sec": 90,
    },
    "judge": {
        "goal": "学习（课程、教材、网课、题库、编程、外语、写作业与笔记）",
        "strictness": "normal",
        "extra_rules": [],
        "alias_rules": [],
    },
    "reminder": {
        "enabled": True,
        "backend": "auto",
        "sound": True,
        "mute_after_remind_sec": 300,
        "off_task_streak_required": 1,
        "auto_close_sec": 60,
    },
    "privacy": {
        "save_shots": False,
        "save_api_raw": True,
        "shots_dir": "data/shots",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULTS)
    cfg_path = path or CONFIG_PATH
    if cfg_path.exists():
        try:
            user = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg = _deep_merge(cfg, user)
        except json.JSONDecodeError as e:
            raise SystemExit(f"{cfg_path.name} 解析失败：{e}")

    env = os.environ
    if env.get("STUDY_WATCH_MODEL"):
        cfg["api"]["model"] = env["STUDY_WATCH_MODEL"]
    if env.get("STUDY_WATCH_BASE_URL"):
        cfg["api"]["base_url"] = env["STUDY_WATCH_BASE_URL"]
    if env.get("STUDY_WATCH_INTERVAL"):
        try:
            cfg["interval_sec"] = max(10, int(env["STUDY_WATCH_INTERVAL"]))
        except ValueError:
            pass
    return cfg


def data_dir(cfg: dict[str, Any]) -> Path:
    d = ROOT / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d
