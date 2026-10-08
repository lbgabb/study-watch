"""番茄钟与监控进程的联动实测：阶段到点后，监控自己推进并写日志。

这是闭环里最容易出错的一环：计划是"文件里的状态"，而推进它的是监控循环。
如果监控不检查或检查时机不对，番茄钟就只是个摆设。

做法：起一个 1 分钟一轮的短计划，跑一个后台监控，等它跨过阶段边界，
再读日志确认它真的播报了阶段切换。
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import plan as P              # noqa: E402
from lib.config import ROOT           # noqa: E402

LOG = ROOT / "data" / "watch.log"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


def call(body: dict) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:8770/api/plan",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def kill_monitors() -> int:
    from lib import proc
    pids = proc.pids_matching("monitor.py")
    for p in pids:
        subprocess.run(["taskkill", "/PID", str(p), "/F"],
                       capture_output=True, creationflags=0x08000000)
    return len(pids)


def tail_since(mark: int) -> str:
    if not LOG.is_file():
        return ""
    data = LOG.read_bytes()
    return data[mark:].decode("utf-8", errors="replace")


def main() -> int:
    print("=== 准备：停掉现有监控，起一个 1 分钟一轮的计划 ===")
    n = kill_monitors()
    print(f"  停掉 {n} 个监控进程")
    time.sleep(1)

    # 通过界面用的同一个接口开始计划（也顺带验证了接口）
    r = call({"action": "start", "preset": "custom", "focus_min": 1, "break_min": 1,
              "rounds": 2, "note": "联动测试", "long_every": 0})
    check("计划已开始", r.get("ok") is True, r.get("message", ""))
    check("预设被识别为自定义、时长 1 分钟",
          r["plan"]["focus_min"] == 1 and r["plan"]["phase"] == "focus",
          f"{r['plan']['focus_min']}分 {r['plan']['phase']}")

    mark = LOG.stat().st_size if LOG.is_file() else 0

    print()
    print("=== 起后台监控，让它跨过阶段边界（约 70 秒）===")
    py = sys.executable
    mon = subprocess.Popen(
        [py, str(ROOT / "monitor.py"), "--background"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=0x08000000)
    print(f"  监控 PID {mon.pid}")

    try:
        # 先确认它起来了
        time.sleep(6)
        from lib import proc
        alive = mon.pid in proc.pids_matching("monitor.py")
        check("监控进程在运行", alive, f"PID {mon.pid}")

        # 等阶段切换（1 分钟专注 + 缓冲）
        deadline = time.time() + 100
        phase_now = None
        while time.time() < deadline:
            time.sleep(4)
            p = P.load()
            if p and p.phase != "focus":
                phase_now = p
                break

        check("监控把计划推进到了休息阶段（没等我们手动操作）",
              phase_now is not None and phase_now.phase == "break",
              f"{phase_now.phase if phase_now else '仍是 focus'} 轮{phase_now.round if phase_now else '?'}")

        log_text = tail_since(mark)
        check("日志里播报了阶段切换", "短休息" in log_text or "进入" in log_text,
              next((l for l in log_text.splitlines() if "休息" in l), "")[:90])
        check("日志里播报了计划内容（轮次/剩余时间）",
              "专注计划" in log_text,
              next((l for l in log_text.splitlines() if "专注计划" in l), "")[:90])
        check("日志里带上了主题", "联动测试" in log_text, "主题：联动测试")

        # 休息期间的判定应被标记为不计入统计
        print()
        print("=== 休息时段的记录应带 exclude_from_stats ===")
        from lib import store
        from lib.config import load_config
        from datetime import date
        recs = store.load_day(load_config(), date.today())
        break_recs = [x for x in recs if x.get("plan_phase") in ("break", "long_break")]
        if break_recs:
            check("休息时段已有判定记录", True, f"{len(break_recs)} 条")
            check("这些记录被标记为不计入统计",
                  all(x.get("exclude_from_stats") for x in break_recs),
                  str([x.get("exclude_from_stats") for x in break_recs]))
            check("记录里带上了计划信息（便于事后按阶段分析）",
                  all(x.get("plan_round") and x.get("plan_preset") for x in break_recs),
                  json.dumps({k: break_recs[-1].get(k)
                              for k in ("plan_preset", "plan_round", "plan_phase")},
                             ensure_ascii=False))
        else:
            print("  （这段时间没产生判定记录，跳过——可能被截图策略跳过了）")

        # 到点后阶段还会继续推进
        print()
        print("=== 再等一会儿：休息结束应回到第 2 轮专注 ===")
        deadline = time.time() + 110
        back = None
        while time.time() < deadline:
            time.sleep(4)
            p = P.load()
            if p and p.phase == "focus" and p.round >= 2:
                back = p
                break
        check("休息结束后回到下一轮专注", back is not None,
              f"轮{back.round}" if back else "仍未回到专注")
    finally:
        print()
        print("=== 收尾 ===")
        try:
            mon.terminate()
            mon.wait(timeout=10)
        except Exception:
            mon.kill()
        call({"action": "clear"})
        print("  已停止测试监控并清除计划")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    for name, ok, detail in results:
        if not ok:
            print(f"  失败：{name} {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
