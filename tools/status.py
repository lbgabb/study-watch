"""查看学习监督当前状态：进程、最近判定、今日汇总。

用法：python tools/status.py
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import report, store  # noqa: E402
from lib.config import ROOT, load_config  # noqa: E402

(ROOT / "data").mkdir(parents=True, exist_ok=True)   # 全新 checkout 时 data/ 还不存在

PS = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe' OR Name = 'pythonw.exe'\" "
    "| Where-Object { $_.CommandLine -like '*monitor.py*' } "
    "| ForEach-Object { $_.ProcessId }"
)


def monitors() -> list[int]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", PS],
                         capture_output=True, text=True, encoding="utf-8",
                         creationflags=0x08000000).stdout
    return sorted(int(x) for x in out.split() if x.strip().isdigit())


def main() -> int:
    cfg = load_config()
    pids = monitors()
    print(f"监督进程：{'运行中 PID ' + ', '.join(map(str, pids)) if pids else '未运行'}")
    print(f"判定间隔：{cfg['interval_sec']} 秒｜模型：{cfg['api']['model']}")

    pidfile = ROOT / "data" / "monitor.pid"
    if pidfile.exists():
        try:
            rec = json.loads(pidfile.read_text(encoding="utf-8"))
            pid = int(rec.get("pid", 0))
            alive = pid in pids
            print(f"pid 文件：PID {pid}，启动于 {rec.get('started')}"
                  + ("（已退出，是残留文件，可删）" if not alive else ""))
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    recs = store.load_day(cfg, date.today())
    print(f"\n今日记录：{len(recs)} 条")
    if recs:
        print(report.render_day(recs, date.today()))
    else:
        print("（今天还没有判定记录）")

    log = ROOT / "data" / "watch.log"
    if log.exists():
        print("\n运行日志最后 5 行：")
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
