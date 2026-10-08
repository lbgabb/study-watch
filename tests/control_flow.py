"""控制面板流程自测：开始 → 暂停 → 恢复 → 停止，以及边界情况。

行为约定（v2）：
  - 监控没在跑时点「暂停 / 恢复」不再报错，而是先把监控拉起来再执行
    （用户视角：点了就该有用，而不是让他先去看为什么没在跑）
  - 已经在跑时重复点「开始监督」不重复启动

默认自己起一个临时服务来测（--port 0），不依赖你正在跑的仪表盘。
"""
import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402

PAUSE = ROOT / "data" / "paused"
results: list[tuple[str, bool, str]] = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(path: str, method: str = "GET", timeout: int = 240, base: str = "") -> dict:
    req = urllib.request.Request(base + path, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def state(base: str) -> dict:
    d = call("/api/data", base=base)
    return {"state": d["state"], "pids": d["pids"], "paused": d["paused"]}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


def step(base: str, name: str, expect: str, action: str | None = None,
         wait: float = 2.0, timeout: float = 15.0) -> bool:
    """执行动作后等待状态变成期望值。

    为什么是"等待"而不是"睡固定时间后读一次"：机器忙的时候（同时跑着仪表盘、
    Edge、多个 python）状态转换会慢半拍，读一次就断言会偶发假红。
    这里改成轮询到超时为止——真出问题时仍然会失败，只是不再因为慢而误报。
    """
    msg = ""
    if action:
        msg = call(action, "POST", base=base).get("message", "")

    deadline = time.time() + timeout
    if wait:
        time.sleep(min(wait, timeout))
    s = state(base)
    while s["state"] != expect and time.time() < deadline:
        time.sleep(0.4)
        s = state(base)

    ok = s["state"] == expect
    check(name, ok, f"state={s['state']}（期望 {expect}） paused={s['paused']} "
                    f"pids={s['pids']}" + (f"｜{msg}" if msg else ""))
    if PAUSE.exists() != s["paused"]:
        check("暂停标记文件与实际状态一致", False,
              f"文件存在={PAUSE.exists()} 状态={s['paused']}")
        return False
    return ok


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
                call("/api/data", timeout=3, base=f"http://127.0.0.1:{port}")
                break
            except Exception:
                continue

    base = f"http://127.0.0.1:{port}"
    print(f"目标服务：{base}")
    try:
        call("/api/stop", "POST", base=base)      # 先归零
        time.sleep(2)

        step(base, "初始应为停止", "stopped", wait=0)
        step(base, "点「开始监督」", "running", "/api/start", wait=3)
        step(base, "点「暂停判定」", "paused", "/api/pause", wait=2)
        step(base, "点「继续监督」", "running", "/api/resume", wait=2)
        step(base, "重复点「开始」应被拦住", "running", "/api/start", wait=2)
        step(base, "点「停止监督」", "stopped", "/api/stop", wait=3)

        # 边界：监控没在跑时点暂停/恢复会自动拉起（而不是报错）
        r = call("/api/pause", "POST", base=base)
        time.sleep(3)
        s = state(base)
        check("没在跑时点「暂停」会自动拉起并暂停",
              s["state"] == "paused" and len(s["pids"]) >= 1,
              f"{r.get('message')}｜state={s['state']} pids={s['pids']}")

        r = call("/api/resume", "POST", base=base)
        time.sleep(2)
        s = state(base)
        check("点「继续监督」恢复正常", s["state"] == "running",
              f"{r.get('message')}｜state={s['state']}")

        # 未知接口
        try:
            call("/api/nope", "POST", base=base)
            check("未知接口返回 404", False, "竟然成功了")
        except urllib.error.HTTPError as e:
            check("未知接口返回 404", e.code == 404, f"HTTP {e.code}")

        call("/api/stop", "POST", base=base)
        time.sleep(2)
    finally:
        if own:
            own.terminate()
            try:
                own.wait(timeout=10)
            except subprocess.TimeoutExpired:
                own.kill()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
