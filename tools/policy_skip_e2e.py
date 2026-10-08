"""专门验证策略的"不判定"分支：让前台窗口命中 skip / 长 tick 规则，确认真的不截图、不调用 API。

用临时配置，跑两段短监督，检查：
  1) 命中 skip 时，日志里没有 ok 记录、且总结里有"按应用策略省下 N 次判定"
  2) 命中 tick_sec=300 时，前台一直停在该应用上不会重复判定
"""
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402

PY = sys.executable
CFG = ROOT / "data" / "_policy_skip_e2e.json"
user32 = ctypes.windll.user32


def run_case(name: str, rules: list[dict], seconds: float, focus: str) -> tuple[str, list[dict]]:
    """起一段监督，同时把指定窗口切到前台。返回 (控制台输出, 新增记录)。"""
    cfg = {
        "interval_sec": 10,
        "idle_skip_sec": 600,
        "capture": {"enabled": True, "min_gap_sec": 2, "rules": rules},
        "reminder": {"enabled": False},
        "privacy": {"save_shots": False, "save_api_raw": False},
    }
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    before = _size()
    print(f"\n=== {name} ===")
    print(f"规则：{json.dumps(rules, ensure_ascii=False)}")

    proc = subprocess.Popen(
        [PY, str(ROOT / "monitor.py"), "--config", str(CFG),
         "--minutes", str(seconds / 60), "--interval", "10"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=0x08000000,
    )

    # 把目标窗口切到前台并保持
    deadline = time.time() + seconds
    hwnd = 0
    for _ in range(20):
        hwnd = user32.FindWindowW(focus, None) if focus else 0
        if hwnd:
            break
        time.sleep(0.3)
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        print(f"已把 {focus} 切到前台")

    # 期间不断把它拉回前台，避免被别的窗口抢走
    while time.time() < deadline:
        if hwnd:
            user32.SetForegroundWindow(hwnd)
        time.sleep(1.0)

    out, _ = proc.communicate(timeout=120)
    recs = _new(before)
    print(f"新增判定记录 {len(recs)} 条：")
    for r in recs:
        print(f"  {r.get('ts','')[11:]} {r.get('status')} {r.get('process')!r} "
              f"policy={r.get('policy_reason','-')!r}")
    for line in (out or "").splitlines():
        if "本次监督结束" in line or "策略" in line and "省下" not in line and "恢复判定" in line:
            print("  >> " + line.strip())
        elif "本次监督结束" in line:
            print("  >> " + line.strip())
    return out or "", recs


def _log_path() -> Path:
    return sorted((ROOT / "data" / "logs").glob("*.jsonl"))[-1]


def _size() -> int:
    p = _log_path()
    return p.stat().st_size if p.exists() else 0


def _new(before: int) -> list[dict]:
    raw = _log_path().read_bytes()[before:]
    out = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def main() -> int:
    results = []

    # 用例 1：记事本命中 skip -> 不该有任何判定
    out1, recs1 = run_case(
        "用例 1：记事本命中 action=skip",
        [{"name": "记事本不判定", "process": ["notepad*"], "action": "skip"}],
        seconds=40, focus="Notepad",
    )
    ok1 = len(recs1) == 0 and "省下" in out1
    skipped1 = [l for l in out1.splitlines() if "本轮不截图" in l]
    print(f"  [{'通过' if ok1 else '失败'}] 命中 skip 时没有产生任何判定记录")
    if skipped1:
        print(f"  >> 日志里的提示：{skipped1[0].strip()}")
    results.append(ok1)

    # 用例 2：记事本命中 tick_sec=300 -> 40 秒内最多 1 次判定
    out2, recs2 = run_case(
        "用例 2：记事本命中 tick_sec=300",
        [{"name": "记事本每 5 分钟", "process": ["notepad*"], "tick_sec": 300}],
        seconds=40, focus="Notepad",
    )
    ok2 = len(recs2) <= 1
    print(f"  [{'通过' if ok2 else '失败'}] 40 秒内判定次数 {len(recs2)} <= 1")
    results.append(ok2)

    CFG.unlink(missing_ok=True)
    passed = sum(1 for r in results if r)
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
