"""跨进程启动互斥验证：两个独立进程同时启动监控，只能起一个。

之前的教训：锁在单进程内有效（4 个并发请求只起 1 个），但
"服务自愈"和"命令行脚本启动"是两个独立进程，必须靠文件锁跨进程串行化。
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402
from lib import proc  # noqa: E402

PY = sys.executable
(ROOT / "data").mkdir(parents=True, exist_ok=True)   # 全新 checkout 时 data/ 还不存在
LOCK = ROOT / "data" / "start.lock"

WORKER = r'''
import sys, time
sys.path.insert(0, r"{root}")
from lib.server import _ensure_monitor_alive, running_monitors
t0 = time.time()
started, msg = _ensure_monitor_alive()
print(f"{{'STARTED' if started else 'SKIPPED'}} {{msg}} pids={{running_monitors(force=True)}} 用时{{time.time()-t0:.1f}}s")
'''


def kill_monitors() -> int:
    pids = proc.pids_matching("monitor.py")
    for p in pids:
        subprocess.run(["taskkill", "/PID", str(p), "/F"],
                       capture_output=True, creationflags=0x08000000)
    return len(pids)


def main() -> int:
    print("先清干净…")
    n = kill_monitors()
    LOCK.unlink(missing_ok=True)
    (ROOT / "data" / "paused").unlink(missing_ok=True)
    time.sleep(2)
    print(f"  清掉 {n} 个监控进程，锁定文件已清")

    script = ROOT / "data" / "_race_worker.py"
    script.write_text(WORKER.format(root=str(ROOT)), encoding="utf-8")

    print("\n同时启动 3 个独立进程，各调一次 _ensure_monitor_alive()…")
    procs = [
        subprocess.Popen([PY, str(script)], cwd=str(ROOT),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="replace", creationflags=0x08000000)
        for _ in range(3)
    ]
    for i, p in enumerate(procs, 1):
        out, _ = p.communicate(timeout=90)
        print(f"  进程{i}: {out.strip()}")

    time.sleep(3)
    pids = proc.pids_matching("monitor.py")
    print(f"\n最终监控进程：{pids}")
    ok = len(pids) == 1
    print("  [%s] 跨进程并发只起了一个监控进程" % ("通过" if ok else "失败"))

    # 收尾
    kill_monitors()
    script.unlink(missing_ok=True)
    LOCK.unlink(missing_ok=True)
    time.sleep(1)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
