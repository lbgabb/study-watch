"""截图策略自测：规则匹配、各动作语义、兜底闸门、跨重启续期。

全是纯函数测试，不截屏、不调用 API、不产生费用。
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import policy  # noqa: E402

NOW = datetime(2026, 10, 8, 12, 0, 0)
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


def ctx(process: str, title: str = "", hwnd: int = 1) -> dict:
    return {"process": process, "title": title, "hwnd": hwnd, "pid": 1}


def cfg_with(rules: list[dict], **cap) -> dict:
    base = {"enabled": True, "default_sec": None, "min_gap_sec": 20, "rules": rules}
    base.update(cap)
    return {"interval_sec": 120, "capture": base}


def decide(cfg, c, *, last_ok=None, last_app=None, last_seen=None):
    return policy.decide(cfg, c, now=NOW, last_ok=last_ok,
                         last_app_key=last_app, last_app_seen=last_seen)


def main() -> int:
    print("=== 归一化与匹配 ===")
    check("进程名归一化", policy.normalize("C:\\Program Files\\A\\WeChat.exe") == "wechat",
          policy.normalize("C:\\Program Files\\A\\WeChat.exe"))
    check("通配符匹配进程", policy.rule_matches({"process": ["*chrome*"]}, ctx("chrome.exe")))
    check("按标题匹配", policy.rule_matches({"title_contains": ["弹幕"]}, ctx("msedge.exe", "视频 弹幕")))
    check("不匹配时为假", not policy.rule_matches({"process": ["wechat"]}, ctx("msedge.exe")))
    check("空规则不命中", not policy.rule_matches({}, ctx("msedge.exe")))

    print()
    print("=== 书写顺序：第一条命中者生效 ===")
    rules = [
        {"name": "先命中", "process": ["msedge*"], "tick_sec": 60},
        {"name": "后命中", "process": ["*"], "tick_sec": 600},
    ]
    got = policy.find_rule(rules, ctx("msedge.exe"))
    check("取第一条命中", got and got.get("name") == "先命中", str(got and got.get("name")))

    print()
    print("=== action=skip：该应用不判定 ===")
    cfg = cfg_with([{"name": "游戏", "process": ["game*", "steam"], "action": "skip"}])
    d = decide(cfg, ctx("game.exe"))
    check("命中 skip 不截图", d["capture"] is False and d["reason"] == policy.REASON_SKIP, d["reason"])
    d = decide(cfg, ctx("msedge.exe"), last_ok=NOW - timedelta(seconds=999))
    check("未命中仍按全局查", d["capture"] is True, d["reason"])

    print()
    print("=== tick_sec：距上次判定满 N 秒才查 ===")
    cfg = cfg_with([{"name": "阅读", "process": ["sumatrapdf*"], "tick_sec": 300}])
    d = decide(cfg, ctx("SumatraPDF.exe"), last_ok=NOW - timedelta(seconds=100))
    check("未到 300 秒不查", d["capture"] is False, d["reason"])
    d = decide(cfg, ctx("SumatraPDF.exe"), last_ok=NOW - timedelta(seconds=301))
    check("超过 300 秒就查", d["capture"] is True and d["reason"] == policy.REASON_TICK, d["reason"])

    print()
    print("=== polling_sec：切换先查一次，之后按轮询 ===")
    cfg = cfg_with([{"name": "聊天", "process": ["wechat*", "qq*"], "polling_sec": 600}],
                   min_gap_sec=0)
    d = decide(cfg, ctx("WeChat.exe"), last_ok=NOW - timedelta(seconds=5),
               last_app="msedge", last_seen=NOW - timedelta(seconds=5))
    check("刚切到聊天软件仍会查一次", d["capture"] is True and d["reason"] == policy.REASON_NEW_APP,
          d["reason"])
    d = decide(cfg, ctx("WeChat.exe"), last_ok=NOW - timedelta(seconds=100),
               last_app="wechat", last_seen=NOW - timedelta(seconds=100))
    check("停留中未到 600 秒不查", d["capture"] is False, d["reason"])
    d = decide(cfg, ctx("WeChat.exe"), last_ok=NOW - timedelta(seconds=700),
               last_app="wechat", last_seen=NOW - timedelta(seconds=700))
    check("超过 600 秒再查", d["capture"] is True and d["reason"] == policy.REASON_POLL, d["reason"])

    print()
    print("=== switch_check：一切换到它就立刻查 ===")
    cfg = cfg_with([{"name": "短视频", "process": ["*douyin*", "msedge*"],
                     "title_contains": ["抖音"], "switch_check": True}], min_gap_sec=0)
    d = decide(cfg, ctx("msedge.exe", "抖音 - 浏览器"), last_ok=NOW - timedelta(seconds=3),
               last_app="wechat", last_seen=NOW - timedelta(seconds=3))
    check("切换即查", d["capture"] is True and d["reason"] == policy.REASON_SWITCH, d["reason"])
    d = decide(cfg, ctx("msedge.exe", "抖音 - 浏览器"), last_ok=NOW - timedelta(seconds=3),
               last_app="msedge", last_seen=NOW - timedelta(seconds=3))
    check("停在同应用不再触发切换查", d["capture"] is False, d["reason"])

    print()
    print("=== 兜底闸门 min_gap ===")
    # 注意：闸门是"最后一道"，只有在别的检查都放行时才会体现出来。
    # 所以这里故意用很短的 default_sec 让前面放行，再用大 min_gap 拦下。
    cfg = cfg_with([], min_gap_sec=45, default_sec=5)
    d = decide(cfg, ctx("msedge.exe"), last_ok=NOW - timedelta(seconds=10))
    check("间隔已到但距上次判定仅 10 秒 < 45 秒，闸门拦下",
          d["capture"] is False and d["reason"] == policy.REASON_MIN_GAP, d["reason"])
    d = decide(cfg, ctx("msedge.exe"), last_ok=NOW - timedelta(seconds=50))
    check("距上次判定 50 秒 > 45 秒，放行", d["capture"] is True, d["reason"])

    print()
    print("=== 闸门同样作用于应用规则 ===")
    cfg = cfg_with([{"name": "阅读", "process": ["sumatrapdf*"], "tick_sec": 300}],
                   min_gap_sec=600)
    d = decide(cfg, ctx("SumatraPDF.exe"), last_ok=NOW - timedelta(seconds=301))
    check("tick 到期但闸门拦下", d["capture"] is False and d["reason"] == policy.REASON_MIN_GAP,
          d["reason"])

    print()
    print("=== 全局间隔仍生效 ===")
    cfg = cfg_with([])
    d = decide(cfg, ctx("msedge.exe"), last_ok=NOW - timedelta(seconds=60))
    check("60 秒 < 全局 120 秒，不查", d["capture"] is False, d["reason"])
    d = decide(cfg, ctx("msedge.exe"), last_ok=NOW - timedelta(seconds=121))
    check("超过 120 秒，查", d["capture"] is True and d["reason"] == policy.REASON_DEFAULT, d["reason"])
    d = decide(cfg, ctx("msedge.exe"), last_ok=None)
    check("首次运行（无历史）就查", d["capture"] is True, d["reason"])

    print()
    print("=== 关闭策略时退回朴素行为 ===")
    cfg = cfg_with([{"process": ["*"], "action": "skip"}], enabled=False)
    d = decide(cfg, ctx("game.exe"))
    check("策略关闭时一律判定", d["capture"] is True, d["reason"])

    print()
    print("=== default_sec 覆盖全局间隔 ===")
    cfg = cfg_with([], default_sec=60)
    d = decide(cfg, ctx("msedge.exe"), last_ok=NOW - timedelta(seconds=70))
    check("按 default_sec=60 判定可查", d["capture"] is True, d["reason"])

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print()
    print(f"{passed}/{total} 项通过")
    if passed != total:
        for name, ok, detail in results:
            if not ok:
                print(f"  未通过：{name} {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
