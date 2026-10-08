"""压力验证：反复读状态（模拟页面 5 秒轮询）不应产生任何副作用。

重点确认 /api/data 是纯只读的：
  - 不能启动/停掉进程
  - 不能改暂停/意图标记
  - 不能改 state.json

默认自己起一个临时服务（--port 0），这样不依赖"别的测试有没有把服务留在跑"。
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
from lib import proc  # noqa: E402

DATA = ROOT / "data"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def snapshot() -> dict:
    return {
        "monitors": proc.pids_matching("monitor.py"),
        "paused": (DATA / "paused").exists(),
        "intent": (DATA / "desired_running").exists(),
        "lock": (DATA / "start.lock").exists(),
        "state_mtime": (DATA / "state.json").stat().st_mtime if (DATA / "state.json").exists() else 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0,
                    help="要测的端口；默认 0 = 自己起临时服务")
    args = ap.parse_args()

    port = args.port or free_port()
    own = None
    if not args.port:
        print(f"启动临时仪表盘服务：127.0.0.1:{port}")
        own = subprocess.Popen(
            [sys.executable, str(ROOT / "lib" / "server.py"), "--port", str(port), "--no-open"],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
        )
        for _ in range(40):
            time.sleep(0.25)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/data", timeout=3).read()
                break
            except Exception:
                continue

    base = f"http://127.0.0.1:{port}"
    try:
        before = snapshot()
        print("压测前：", json.dumps(before, ensure_ascii=False))
        print("反复请求 /api/data 共 40 次（每 0.3 秒一次）…")

        states = []
        for _ in range(40):
            with urllib.request.urlopen(f"{base}/api/data", timeout=20) as r:
                states.append(json.loads(r.read())["state"])
            time.sleep(0.3)

        time.sleep(2)
        after = snapshot()
        print("压测后：", json.dumps(after, ensure_ascii=False))
        print(f"\n期间返回的 state：{sorted(set(states))}")

        ok = True
        if len(after["monitors"]) != len(before["monitors"]):
            print(f"✗ 监控进程数量变了：{before['monitors']} -> {after['monitors']}"
                  "（GET 状态不该启动/停掉进程）")
            ok = False
        else:
            print(f"✓ 监控进程数量不变：{after['monitors']}")
        for key in ("paused", "intent", "lock"):
            if after[key] != before[key]:
                print(f"✗ {key} 状态被改变了：{before[key]} -> {after[key]}")
                ok = False
            else:
                print(f"✓ {key} 未被改动（{after[key]}）")
        if after["state_mtime"] != before["state_mtime"]:
            print(f"⚠ state.json 被更新了（{before['state_mtime']} -> {after['state_mtime']}）"
                  "：如果这期间真有判定发生，属于正常")
        else:
            print("✓ state.json 未被写")
        return 0 if ok else 1
    finally:
        if own:
            own.terminate()
            try:
                own.wait(timeout=10)
            except subprocess.TimeoutExpired:
                own.kill()


if __name__ == "__main__":
    sys.exit(main())
