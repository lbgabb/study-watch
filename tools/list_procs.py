"""列出所有监控进程及其启动时间与完整命令行，用于排查重复进程。"""
import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PS = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" "
    "| Where-Object { $_.CommandLine -like '*monitor.py*' -or $_.CommandLine -like '*server.py*' } "
    "| Select-Object ProcessId, CreationDate, CommandLine | ConvertTo-Json -Compress"
)


def main() -> int:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", PS],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", creationflags=0x08000000).stdout.strip()
    if not out:
        print("没有任何 monitor/server 进程")
        return 0
    data = out if out.startswith("[") else f"[{out}]"
    import json
    items = json.loads(data)
    print(f"共 {len(items)} 个相关进程：")
    monitors, servers = [], []
    for it in items:
        pid = it["ProcessId"]
        cmd = it.get("CommandLine", "")
        created = it.get("CreationDate", "")
        kind = "监控" if "monitor.py" in cmd else "服务"
        (monitors if kind == "监控" else servers).append(pid)
        print(f"  [{kind}] PID {pid:<7} 启动 {created}")
        print(f"         {cmd[:150]}")
    print()
    print(f"监控进程 {len(monitors)} 个：{monitors}")
    print(f"服务进程 {len(servers)} 个：{servers}")
    if len(monitors) > 1:
        print("\n⚠ 有重复监控进程（会重复判定、重复扣费、提醒弹两次）")
        print("  排查方向：是不是有旧进程在被清理前留下了？看上面的启动时间。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
