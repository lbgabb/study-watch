"""服务韧性自测：监控进程被杀掉之后，控制面板能否自动把它拉回来。

场景（真实发生过）：
  1. 仪表盘服务还在，但监控进程已经退出（被任务管理器杀了 / 开机后没启动）
  2. 用户点「暂停」或「继续监督」——旧版本会报"无法暂停"，什么都做不了
  3. 期望：把这些操作变成"先拉起监控，再执行操作"

用法：
  python tests/test_recovery.py                # 测正在运行的仪表盘（默认 8770）
  python tests/test_recovery.py --port 51234   # 测指定端口
  python tests/test_recovery.py --port 0       # 自己起一个临时服务再测（不依赖现有服务）
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402

PAUSE = ROOT / "data" / "paused"
results: list[tuple[str, bool, str]] = []


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(path: str, method: str = "GET", timeout: int = 120, base: str = "") -> dict:
    req = urllib.request.Request(base + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def state(base: str) -> dict:
    d = call("/api/data", base=base)
    return {"state": d["state"], "pids": d["pids"]}


def wait_state(base: str, expect: str, timeout: float = 15.0) -> dict:
    """轮询直到状态变成期望值（机器忙时状态转换会慢半拍，读一次就断言会假红）。"""
    deadline = time.time() + timeout
    s = state(base)
    while s["state"] != expect and time.time() < deadline:
        time.sleep(0.4)
        s = state(base)
    return s


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


def kill_monitor() -> int:
    """杀掉监控进程（保留服务），返回杀掉的数量。"""
    ps = ("Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" "
          "| Where-Object { $_.CommandLine -like '*monitor.py*' } "
          "| Select-Object -ExpandProperty ProcessId")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, encoding="utf-8",
                         creationflags=0x08000000).stdout
    pids = [int(x) for x in out.split() if x.strip().isdigit()]
    for p in pids:
        subprocess.run(["taskkill", "/PID", str(p), "/F"],
                       capture_output=True, creationflags=0x08000000)
    return len(pids)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8770,
                    help="要测的端口；传 0 表示自己起一个临时服务再测")
    args = ap.parse_args()

    own_server: subprocess.Popen | None = None
    port = args.port
    if port == 0:
        port = free_port()
        print(f"启动临时仪表盘服务：127.0.0.1:{port}")
        own_server = subprocess.Popen(
            [sys.executable, str(ROOT / "lib" / "server.py"), "--port", str(port), "--no-open"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        for _ in range(40):
            time.sleep(0.25)
            try:
                call("/api/data", timeout=3, base=f"http://127.0.0.1:{port}")
                break
            except Exception:
                continue

    base = f"http://127.0.0.1:{port}"
    print(f"目标服务：{base}")
    try:
        call("/api/data", timeout=10, base=base)
    except Exception as e:
        print(f"  服务未运行，先启动它再跑本测试：{e}")
        if own_server:
            own_server.terminate()
        return 2

    try:
        # 0) 归零：停止一切
        call("/api/stop", "POST", base=base)
        check("初始为停止状态",
              wait_state(base, "stopped", timeout=10)["state"] == "stopped",
              str(state(base)))

        # 1) 服务在跑但监控没起 -> 点「暂停」应自动拉起并暂停
        r = call("/api/pause", "POST", base=base)
        s = wait_state(base, "paused")
        check("监控未运行时点「暂停」会先拉起再暂停",
              s["state"] == "paused" and len(s["pids"]) >= 1,
              f"{r.get('message')}｜state={s['state']} pids={s['pids']}")
        check("暂停标记文件已写入", PAUSE.exists())

        # 2) 杀掉监控进程，模拟"任务管理器强杀"
        killed = kill_monitor()
        s = wait_state(base, "stopped")
        check(f"强杀 {killed} 个监控进程后，界面如实显示未运行",
              s["state"] == "stopped" and not s["pids"], f"state={s['state']} pids={s['pids']}")

        # 3) 这个状态下点「继续监督」也应自动拉起
        r = call("/api/resume", "POST", base=base)
        s = wait_state(base, "running")
        check("监控已死时点「继续监督」会重新拉起",
              s["state"] == "running" and len(s["pids"]) >= 1,
              f"{r.get('message')}｜state={s['state']} pids={s['pids']}")
        check("拉起后暂停标记已清除", not PAUSE.exists())

        # 4) 正常运行时的暂停/恢复仍要工作
        r = call("/api/pause", "POST", base=base)
        check("正常暂停", wait_state(base, "paused")["state"] == "paused", r.get("message", ""))
        r = call("/api/resume", "POST", base=base)
        check("正常恢复", wait_state(base, "running")["state"] == "running", r.get("message", ""))

        # 5) 收尾
        r = call("/api/stop", "POST", base=base)
        check("停止后干净退出", wait_state(base, "stopped")["state"] == "stopped", r.get("message", ""))
    finally:
        if own_server:
            own_server.terminate()
            try:
                own_server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                own_server.kill()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
