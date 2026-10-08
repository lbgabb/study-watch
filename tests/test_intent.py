"""验证"停止之后不会被状态刷新拉起来"（意图标记的正确性）。

这是我自己引入过的真 bug：页面每 5 秒刷新 /api/data，如果状态路径也做自愈，
用户点「停止」后监控会在几秒内被重新拉起，等于停不掉。

用例：
  1. 没有意图标记时启动服务 -> 不应该自动起监控
  2. 点「开始监督」-> 起来，且意图标记被写下
  3. 杀掉监控进程 + 反复调用 /api/data（模拟页面刷新）-> 监控必须保持停止
  4. 点「继续监督」-> 意图恢复，监控被拉起
  5. 点「停止监督」-> 意图清除；再刷 10 次 /api/data -> 仍然停止
"""
import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402

INTENT = ROOT / "data" / "desired_running"
PAUSE = ROOT / "data" / "paused"
results: list[tuple[str, bool, str]] = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(path: str, method: str = "GET", base: str = "", timeout: int = 60) -> dict:
    req = urllib.request.Request(base + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def state(base: str) -> dict:
    d = call("/api/data", base=base)
    return {"state": d["state"], "pids": d["pids"]}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


def kill_monitor() -> int:
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
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    port = args.port or free_port()
    base = f"http://127.0.0.1:{port}"

    # 归零：清掉标记与进程
    for f in (INTENT, PAUSE):
        f.unlink(missing_ok=True)
    kill_monitor()

    print(f"启动临时服务：{base}")
    own = subprocess.Popen(
        [sys.executable, str(ROOT / "lib" / "server.py"), "--port", str(port), "--no-open"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=0x08000000,
    )
    try:
        for _ in range(40):
            time.sleep(0.25)
            try:
                call("/api/data", base=base, timeout=3)
                break
            except Exception:
                continue

        # 1) 没有意图标记 -> 服务启动不应自动起监控
        time.sleep(2)
        s = state(base)
        check("无意图标记时，服务启动不会自动起监控",
              s["state"] == "stopped" and not s["pids"], f"state={s['state']} pids={s['pids']}")

        # 2) 点开始 -> 起来 + 写下意图
        r = call("/api/start", "POST", base=base)
        time.sleep(3)
        s = state(base)
        check("点「开始监督」后运行中", s["state"] == "running" and s["pids"],
              f"{r.get('message')}｜pids={s['pids']}")
        check("意图标记已写下（表示用户要它跑）", INTENT.exists())

        # 3) 停止 -> 意图清除；然后疯狂刷新状态，监控不能自己回来
        r = call("/api/stop", "POST", base=base)
        time.sleep(3)
        check("点「停止监督」后停止", state(base)["state"] == "stopped", r.get("message", ""))
        check("意图标记已清除", not INTENT.exists())
        for _ in range(10):
            call("/api/data", base=base, timeout=10)
            time.sleep(0.4)
        s = state(base)
        check("刷新 10 次状态后仍然是停止（不会被自愈拉起来）",
              s["state"] == "stopped" and not s["pids"], f"state={s['state']} pids={s['pids']}")

        # 4) 杀掉监控后，反复刷新也不该自愈（因为意图是"停"）
        call("/api/start", "POST", base=base)
        time.sleep(3)
        killed = kill_monitor()
        time.sleep(2)
        for _ in range(8):
            call("/api/data", base=base, timeout=10)
            time.sleep(0.4)
        s = state(base)
        check(f"杀掉监控({killed}个)后刷新，不会被自动拉起（界面如实显示未运行）",
              s["state"] == "stopped" and not s["pids"], f"state={s['state']} pids={s['pids']}")

        # 5) 但用户主动点「继续监督」应该能恢复
        r = call("/api/resume", "POST", base=base)
        time.sleep(3)
        s = state(base)
        check("用户主动点「继续监督」能重新拉起",
              s["state"] == "running" and s["pids"], f"{r.get('message')}｜pids={s['pids']}")

        # 6) 并发点「开始监督」只能起一个（曾经在这里起出过两个进程）
        call("/api/stop", "POST", base=base)
        time.sleep(3)
        import threading

        results_par: list[str] = []

        def hit():
            try:
                results_par.append(call("/api/start", "POST", base=base).get("message", ""))
            except Exception as e:
                results_par.append(f"ERR {e}")

        threads = [threading.Thread(target=hit) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        time.sleep(4)
        s = state(base)
        check("并发点 4 次「开始监督」只起 1 个监控进程",
              s["state"] == "running" and len(s["pids"]) == 1,
              f"pids={s['pids']}｜返回：{results_par}")
        print(f"     并发返回：{results_par}")

        call("/api/stop", "POST", base=base)
        time.sleep(2)
    finally:
        own.terminate()
        try:
            own.wait(timeout=10)
        except subprocess.TimeoutExpired:
            own.kill()
        for f in (INTENT, PAUSE):
            f.unlink(missing_ok=True)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
