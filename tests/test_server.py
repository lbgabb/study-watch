"""仪表盘自测：起一个独立服务实例，验证 API、数据一致性与启停控制。

会真实启停一次监督进程（用 --minutes 20 自动收尾），但不调用视觉 API，不产生费用。
"""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402

PY = sys.executable
SERVER = ROOT / "lib" / "server.py"
MONITOR = ROOT / "monitor.py"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(port: int, path: str, method: str = "GET", timeout: int = 120):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        body = r.read()
        if "json" in ctype:
            return r.status, json.loads(body)
        return r.status, body


def main() -> int:
    port = free_port()
    print(f"启动测试用仪表盘实例：127.0.0.1:{port}")
    srv = subprocess.Popen(
        [PY, str(SERVER), "--port", str(port), "--no-open"],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=0x08000000,
    )
    monitor_started = False
    try:
        # 等服务起来
        up = False
        for _ in range(40):
            try:
                get(port, "/api/data", timeout=5)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        check("服务能启动并响应 /api/data", up)
        if not up:
            return 1

        # 静态资源
        s, html = get(port, "/")
        check("GET / 返回 HTML", s == 200 and b"<!DOCTYPE html>" in html, f"{len(html)} 字节")
        check("页面引用了 app.js", b"/app.js" in html)
        s, js = get(port, "/app.js")
        check("GET /app.js 返回脚本", s == 200 and b"renderTimeline" in js, f"{len(js)} 字节")
        s, icon = get(port, "/favicon.ico")
        check("GET /favicon.ico 返回图标", s == 200 and len(icon) > 1000, f"{len(icon)} 字节")

        # 数据一致性
        s, d = get(port, "/api/data")
        ok_shape = all(k in d for k in ("running", "pids", "today", "days", "interval_sec", "key_ok"))
        check("数据字段齐全", ok_shape)
        check("近 7 天恰好 7 项", len(d.get("days", [])) == 7, str(len(d.get("days", []))))
        check("检测到 API key", bool(d.get("key_ok")))

        t = d["today"]
        cat_sum = sum(c["sec"] for c in t["cat_sec"])
        total = t["on_task_sec"] + t["off_task_sec"]
        check("类别时长合计 ≈ 在状态+分心",
              abs(cat_sum - total) < max(5.0, total * 0.02),
              f"类别 {cat_sum:.0f}s vs 合计 {total:.0f}s")
        tl_sum = sum(i["sec"] for i in t["timeline"])
        check("时间轴段长合计 ≈ 在状态+分心",
              abs(tl_sum - total) < max(5.0, total * 0.02),
              f"时间轴 {tl_sum:.0f}s vs 合计 {total:.0f}s")
        if t["timeline"]:
            secs = [i["sec"] for i in t["timeline"]]
            check("每段时长都在合理区间", all(0 < s2 <= 900 for s2 in secs),
                  f"最小 {min(secs):.0f}s 最大 {max(secs):.0f}s")
        check("时间轴按时间升序", all(t["timeline"][i]["ts"] <= t["timeline"][i + 1]["ts"]
                                     for i in range(len(t["timeline"]) - 1)))

        # 控制：启动
        s, r = get(port, "/api/start", "POST")
        check("POST /api/start 成功", r.get("ok") is True, r.get("message", ""))
        monitor_started = True
        time.sleep(2)
        s, d2 = get(port, "/api/data")
        check("启动后状态显示运行中", bool(d2["running"]) and len(d2["pids"]) >= 1,
              f"pids={d2['pids']}")

        # 控制：重复启动
        s, r = get(port, "/api/start", "POST")
        check("重复启动被拦住", r.get("ok") is True and "已经" in str(r.get("message", "")),
              r.get("message", ""))

        # 控制：导出
        s, r = get(port, "/api/export", "POST")
        check("POST /api/export 成功", r.get("ok") is True, r.get("message", ""))

        # 控制：停止
        s, r = get(port, "/api/stop", "POST")
        check("POST /api/stop 成功", r.get("ok") is True, r.get("message", ""))
        time.sleep(2)
        s, d3 = get(port, "/api/data")
        check("停止后状态显示未运行", not d3["running"], f"pids={d3['pids']}")
        monitor_started = bool(d3["running"])

        # 未知接口
        try:
            get(port, "/api/nope", "POST")
            check("未知接口返回 404", False, "竟然成功了")
        except urllib.error.HTTPError as e:
            check("未知接口返回 404", e.code == 404, f"HTTP {e.code}")

    finally:
        # 收尾：停监控 + 停服务
        try:
            if monitor_started:
                get(port, "/api/stop", "POST", timeout=30)
        except Exception:
            pass
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()

    failed = [n for n, ok, _ in results if not ok]
    print()
    print(f"{len(results) - len(failed)} 通过 / {len(failed)} 失败")
    if failed:
        for n in failed:
            print("  未通过：" + n)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
