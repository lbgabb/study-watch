"""端到端验证截图策略：真跑一轮监督，看策略决定是否写进日志并省钱。

用临时配置把间隔压到很短，跑 80 秒；同时脚本内会临时切到"记事本"触发一次窗口切换。
会调用真实 API（约 3~5 次判定，<$0.005）。
"""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402

PY = sys.executable
TMPCFG = ROOT / "data" / "_policy_e2e.json"


def main() -> int:
    # 临时配置：写终端/编辑器规则，并让"记事本"命中 tick 规则
    cfg = {
        "interval_sec": 12,
        "idle_skip_sec": 600,
        "capture": {
            "enabled": True,
            "min_gap_sec": 3,
            "rules": [
                {"name": "记事本：每 25 秒看一次", "process": ["notepad*"], "tick_sec": 25},
                {"name": "计算器：不判定", "process": ["calc*", "calculator*"], "action": "skip"},
            ],
        },
        "reminder": {"enabled": False},
        "privacy": {"save_shots": False, "save_api_raw": False},
    }
    TMPCFG.parent.mkdir(parents=True, exist_ok=True)
    TMPCFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"临时配置：{TMPCFG}")

    log_before = _log_size()
    proc = subprocess.Popen(
        [PY, str(ROOT / "monitor.py"), "--config", str(TMPCFG), "--minutes", "1.4",
         "--interval", "12"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=0x08000000,
    )

    # 中途开一个记事本，制造一次窗口切换（顺便让 tick 规则生效）
    time.sleep(18)
    print("打开记事本，制造窗口切换…")
    np_proc = subprocess.Popen(["notepad.exe"])
    time.sleep(3)
    # 把记事本切到前台
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.FindWindowW("Notepad", None)
        if hwnd:
            u.SetForegroundWindow(hwnd)
            print("记事本已切到前台")
    except Exception as e:
        print("切换失败：", e)

    time.sleep(45)
    try:
        np_proc.terminate()
    except Exception:
        pass

    out, _ = proc.communicate(timeout=120)
    print()
    print("=== 监督输出（末尾）===")
    for line in (out or "").splitlines()[-22:]:
        print("  " + line)

    print()
    print("=== 本次新增的日志记录里的策略信息 ===")
    recs = _new_records(log_before)
    for r in recs:
        print(f"  {r.get('ts','')[11:]} status={r.get('status'):<12} "
              f"process={r.get('process','')!r:<22} "
              f"policy={r.get('policy_reason','-')!r} rule={r.get('policy_rule')!r}")

    TMPCFG.unlink(missing_ok=True)
    return 0


def _log_path() -> Path:
    d = ROOT / "data" / "logs"
    return sorted(d.glob("*.jsonl"))[-1]


def _log_size() -> int:
    p = _log_path()
    return p.stat().st_size if p.exists() else 0


def _new_records(before: int) -> list[dict]:
    p = _log_path()
    if not p.exists():
        return []
    raw = p.read_bytes()[before:]
    out = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


if __name__ == "__main__":
    sys.exit(main())
