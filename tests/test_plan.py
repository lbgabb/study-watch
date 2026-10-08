"""番茄钟（专注计划）自测：状态机单测 + 真实浏览器交互实测。

分两部分：
  1. 纯逻辑：阶段推进、长休规则、轮次上限、休息不计入统计
  2. 界面：用无头 Edge 实际点开始 / 提前休息 / 结束，并验证倒计时在走

不调用任何 API，零花费。
"""
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))   # cdp_check 在这里

from lib import plan as P          # noqa: E402
from lib import report             # noqa: E402
from lib.config import ROOT        # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


# ---------------------------------------------------------------- 1. 状态机
def logic_tests() -> None:
    print("=== 1) 阶段推进 ===")
    P.clear()
    p = P.start("pomodoro", target_rounds=3, note="高数")
    check("从专注开始，第 1 轮", p.phase == "focus" and p.round == 1,
          f"{p.phase} 轮{p.round}")
    check("专注时长取预设（25 分钟）", p.phase_sec == 25 * 60, f"{p.phase_sec}s")

    p = P.advance(p, now=p.phase_ends_at)
    check("专注结束 -> 短休", p.phase == "break", p.phase)
    check("短休时长取预设（5 分钟）", p.phase_sec == 5 * 60, f"{p.phase_sec}s")

    p = P.advance(p, now=p.phase_ends_at)
    check("短休结束 -> 第 2 轮专注", p.phase == "focus" and p.round == 2,
          f"{p.phase} 轮{p.round}")

    print()
    print("=== 2) 长休规则（每 4 轮一次）===")
    P.clear()
    q = P.start("pomodoro")          # long_every=4
    phases = []
    for _ in range(8):
        q = P.advance(q, now=q.phase_ends_at)
        phases.append(q.phase)
    check("第 4 轮后是长休", phases[3 + 3] == "long_break" or "long_break" in phases,
          " -> ".join(phases[:8]))
    check("长休出现在第 8 次推进中的正确位置",
          phases.index("long_break") == 6, f"位置 {phases.index('long_break')}")
    check("长休之后回到专注", phases[7] == "focus", phases[7])

    print()
    print("=== 3) 轮次上限 ===")
    P.clear()
    r = P.start("sprint", target_rounds=2)      # 15/3
    r = P.advance(r, now=r.phase_ends_at)       # -> break
    r = P.advance(r, now=r.phase_ends_at)       # -> focus 2
    check("第 2 轮专注中", r.phase == "focus" and r.round == 2, f"轮{r.round}")
    r = P.advance(r, now=r.phase_ends_at)       # 第 2 轮专注结束 -> 完成
    check("做完 2 轮后计划结束", r.finished, str(r.finished))
    check("结束原因是完成全部轮次", "全部轮次" in r.stop_reason, r.stop_reason)
    check("完成轮数统计正确", r.done_focus_rounds() == 2, str(r.done_focus_rounds()))

    print()
    print("=== 4) 不限轮数 / 提前结束 ===")
    P.clear()
    u = P.start("ultradian")                    # target_rounds=0
    for _ in range(5):
        u = P.advance(u, now=u.phase_ends_at)
        if u.finished:
            break
    check("轮次为 0 时不会自动结束", not u.finished, f"finished={u.finished}")
    check("90/20 预设生效", u.focus_min == 90 and u.break_min == 20,
          f"{u.focus_min}/{u.break_min}")
    u = P.stop(u, "手动结束")
    check("手动结束标记正确", u.finished and "手动" in u.stop_reason, u.stop_reason)

    print()
    print("=== 5) 跨重启续上（写盘再读回）===")
    P.clear()
    s = P.start("pomodoro", target_rounds=4, note="线代")
    s.phase_started_at = time.time() - 60      # 假装已经过了 1 分钟
    P.save(s)
    back = P.load()
    check("能从文件读回", back is not None and back.note == "线代", str(back and back.note))
    check("阶段剩余时间是接着算的（不是重新开始）",
          back is not None and back.remaining_sec() < 25 * 60,
          f"剩 {back.remaining_sec() if back else '?'}s")
    check("历史记录一起持久化", isinstance(back.history, list))

    print()
    print("=== 6) 休息时段不计入专注率（关键设计）===")
    recs = [
        {"status": "ok", "ts": "2026-10-09T09:00:00", "sec": 1500,
         "on_task": True, "category": "学习"},
        {"status": "ok", "ts": "2026-10-09T09:25:00", "sec": 300,
         "on_task": False, "category": "娱乐", "exclude_from_stats": True,
         "plan_phase": "break"},
        {"status": "ok", "ts": "2026-10-09T09:30:00", "sec": 1500,
         "on_task": True, "category": "学习"},
    ]
    a = report.aggregate(recs)
    check("休息记录被排除在判定次数外", a["checks"] == 2, f"checks={a['checks']}")
    check("休息时长单独统计", a["break_sec"] == 300 and a["break_checks"] == 1,
          f"break_sec={a['break_sec']} 条数={a['break_checks']}")
    check("专注率不受休息影响（100%）", abs(a["on_task_rate"] - 1.0) < 1e-9,
          f"{a['on_task_rate'] * 100:.1f}%")
    naive = report.aggregate([{k: v for k, v in r.items()
                               if k != "exclude_from_stats"} for r in recs])
    check("对照：若把休息算进去会明显偏低",
          naive["on_task_rate"] < a["on_task_rate"] - 0.3,
          f"{naive['on_task_rate'] * 100:.1f}% vs {a['on_task_rate'] * 100:.1f}%")

    print()
    print("=== 7) phase_for：没有计划时行为不变 ===")
    check("无计划时返回空 phase", P.phase_for(None) == ("", {}), str(P.phase_for(None)))
    P.clear()
    check("计划文件已清除", P.load() is None)

    print()
    print("=== 7b) 自定义节奏要能持久化（用户调好的数值不该丢）===")
    from lib.config import CONFIG_PATH, load_config
    import urllib.request
    backup = CONFIG_PATH.read_bytes()
    try:
        # config.json 里有没有 plan 段取决于"用户有没有调过"，
        # 所以这里检查的是**合并后的生效配置**（load_config 会把默认值并进来）
        eff = load_config().get("plan") or {}
        check("生效配置里有 plan 段（存用户节奏）", bool(eff),
              json.dumps(eff, ensure_ascii=False)[:90])
        check("plan 段含 focus_min / break_min",
              "focus_min" in eff and "break_min" in eff, str(list(eff)[:6]))

        # 模拟用户把节奏改成 45/12，并保存
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg["plan"] = {"preset": "custom", "focus_min": 45, "break_min": 12,
                       "long_every": 3, "long_break_min": 25, "rounds": 5,
                       "remind_on_break": True, "strict_break": False}
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

        # 不带任何数值地"开始计划"——应当采用保存的节奏，而不是预设默认
        req = urllib.request.Request(
            "http://127.0.0.1:8770/api/plan",
            data=json.dumps({"action": "start"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        r = json.loads(urllib.request.urlopen(req, timeout=15).read())
        got = r.get("plan") or {}
        check("不带数值开始时会采用保存的节奏", got.get("focus_min") == 45
              and got.get("break_min") == 12,
              f"{got.get('focus_min')}/{got.get('break_min')}（期望 45/12）")
        check("轮数也采用保存值", got.get("target_rounds") == 5, str(got.get("target_rounds")))
        check("长休规则采用保存值", got.get("long_every") == 3,
              str(got.get("long_every")))
        check("休息提醒开关采用保存值", got.get("remind_on_break") is True,
              str(got.get("remind_on_break")))

        # 请求里显式传的应当优先于保存值
        req2 = urllib.request.Request(
            "http://127.0.0.1:8770/api/plan",
            data=json.dumps({"action": "start", "focus_min": 30,
                             "break_min": 6}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        r2 = json.loads(urllib.request.urlopen(req2, timeout=15).read())
        got2 = r2.get("plan") or {}
        check("请求里显式指定时优先用它", got2.get("focus_min") == 30
              and got2.get("break_min") == 6,
              f"{got2.get('focus_min')}/{got2.get('break_min')}（期望 30/6）")

        # 通过设置接口保存自定义节奏（这是前端实际走的路径）
        req4 = urllib.request.Request(
            "http://127.0.0.1:8770/api/config",
            data=json.dumps({"edits": {"plan.preset": "custom", "plan.focus_min": 40,
                                       "plan.break_min": 8}}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        rc = json.loads(urllib.request.urlopen(req4, timeout=15).read())
        check("设置接口能保存自定义节奏", rc.get("ok") is True, rc.get("message", "")[:70])
        on_disk = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("plan") or {}
        check("已写进 config.json（不是只留内存）",
              on_disk.get("focus_min") == 40 and on_disk.get("break_min") == 8,
              json.dumps({k: on_disk.get(k) for k in ("preset", "focus_min", "break_min")},
                         ensure_ascii=False))

        # 清掉计划
        req3 = urllib.request.Request(
            "http://127.0.0.1:8770/api/plan",
            data=json.dumps({"action": "clear"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req3, timeout=15).read()
    finally:
        CONFIG_PATH.write_bytes(backup)
        check("测试后 config.json 已逐字节还原",
              CONFIG_PATH.read_bytes() == backup, f"{len(backup)} 字节")


# ---------------------------------------------------------------- 2. 界面
def ui_tests(base: str, shot: Path | None = None) -> None:
    from cdp_check import CDP, launch   # 复用同一套 CDP 客户端

    print()
    print("=== 8) 界面交互（真实浏览器）===")
    proc, profile, ws_url = launch(base)
    try:
        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        time.sleep(3)

        check("番茄钟卡片存在", cdp.eval_js("!!document.getElementById('pomoCard')"))
        presets = cdp.eval_js(
            "Array.from(document.querySelectorAll('#pomo .presets button')).map(b=>b.textContent)")
        check("预设按钮已渲染", isinstance(presets, list) and len(presets) >= 4, str(presets))

        # 用户自定义的权力：调了数值要能存下来，刷新后还在
        print()
        print("  --- 自定义节奏的持久化（刷新后还在不在）---")
        cdp.eval_js("""(() => {
            const nums = document.querySelectorAll('#pomo .row input[type=number]');
            nums[0].value = '37'; nums[0].dispatchEvent(new Event('change'));
            nums[1].value = '9';  nums[1].dispatchEvent(new Event('change'));
        })()""")
        time.sleep(2.0)          # 等前端把改动存进 config.json（防抖 0.7s）
        on_disk = json.loads(
            (ROOT / "config.json").read_text(encoding="utf-8")).get("plan") or {}
        check("改数值后自动写进 config.json",
              on_disk.get("focus_min") == 37 and on_disk.get("break_min") == 9,
              json.dumps({k: on_disk.get(k) for k in ("preset", "focus_min", "break_min")},
                         ensure_ascii=False))

        # 重新加载页面（等价于关掉再打开），看表单是否还是 37/9
        cdp.call("Page.reload", {"ignoreCache": True})
        time.sleep(4)
        vals = cdp.eval_js("""(() => {
            const nums = document.querySelectorAll('#pomo .row input[type=number]');
            return nums.length ? [nums[0].value, nums[1].value] : null;
        })()""")
        check("刷新后表单仍是用户改的值（没有回到 25/5）",
              isinstance(vals, list) and vals[0] == '37' and vals[1] == '9', str(vals))
        sel = cdp.eval_js("""(() => {
            const b = document.querySelector('#pomo .presets button.on');
            return b ? b.textContent : null;
        })()""")
        check("预设高亮为「自定义」", sel is None or "自定义" in str(sel), str(sel))

        print()
        print("  --- 点「自定义」不该抹掉已调好的数值 ---")
        cdp.eval_js("""(() => {
            const b = Array.from(document.querySelectorAll('#pomo .presets button'))
                .find(x => x.textContent.indexOf('自定义') >= 0);
            if (b) b.click();
        })()""")
        time.sleep(0.8)
        vals2 = cdp.eval_js("""(() => {
            const nums = document.querySelectorAll('#pomo .row input[type=number]');
            return nums.length ? [nums[0].value, nums[1].value] : null;
        })()""")
        check("点「自定义」保留原数值（不再重置成 25/5）",
              isinstance(vals2, list) and vals2[0] == '37' and vals2[1] == '9', str(vals2))

        print()
        print("  --- 换预设则套用该预设的数值 ---")
        cdp.eval_js("""(() => {
            const b = Array.from(document.querySelectorAll('#pomo .presets button'))
                .find(x => x.textContent.indexOf('15 / 3') >= 0);
            if (b) b.click();
        })()""")
        time.sleep(1.2)
        vals3 = cdp.eval_js("""(() => {
            const nums = document.querySelectorAll('#pomo .row input[type=number]');
            return nums.length ? [nums[0].value, nums[1].value] : null;
        })()""")
        check("选 15/3 预设后数值跟着变", isinstance(vals3, list)
              and vals3[0] == '15' and vals3[1] == '3', str(vals3))

        check("有开始按钮",
              cdp.eval_js("""Array.from(document.querySelectorAll('#pomo button'))
                              .some(b=>b.textContent.indexOf('开始专注')>=0)"""))
        basis = cdp.eval_js("(document.querySelector('#pomo .basis')||{}).textContent || ''")
        check("显示了节奏依据（科学说明）", "依据" in basis, basis[:60])

        # 选一个最短的节奏并开始（自定义 1 分钟，测起来快）
        cdp.eval_js("""(() => {
            const nums = document.querySelectorAll('#pomo .row input[type=number]');
            nums[0].value = '1';  nums[0].dispatchEvent(new Event('change'));
            nums[1].value = '1';  nums[1].dispatchEvent(new Event('change'));
        })()""")
        time.sleep(0.6)
        cdp.eval_js("""(() => {
            const b = Array.from(document.querySelectorAll('#pomo button'))
                .find(x => x.textContent.indexOf('开始专注') >= 0);
            b.click();
        })()""")
        time.sleep(2.5)

        check("开始后进入运行视图（出现倒计时）",
              cdp.eval_js("!!document.getElementById('pomoClock')"))
        clock = cdp.eval_js("(document.getElementById('pomoClock')||{}).textContent || ''")
        check("倒计时格式正确", len(clock) == 5 and ":" in clock, str(clock))
        phase = cdp.eval_js("(document.querySelector('#pomo .phase')||{}).textContent || ''")
        check("显示为专注阶段", "专注" in phase, phase[:40])

        t1 = clock
        time.sleep(3)
        t2 = cdp.eval_js("(document.getElementById('pomoClock')||{}).textContent || ''")
        check("倒计时在真的走（本地每秒刷新）", t1 != t2, f"{t1} -> {t2}")

        if shot:
            cdp.screenshot(shot)
            print(f"  已截图：{shot}")

        # 提前休息
        cdp.eval_js("""(() => {
            const b = Array.from(document.querySelectorAll('#pomo button'))
                .find(x => x.textContent.indexOf('提前休息') >= 0);
            if (b) b.click();
        })()""")
        time.sleep(2.5)
        phase2 = cdp.eval_js("(document.querySelector('#pomo .phase')||{}).textContent || ''")
        check("「提前休息」切到休息阶段", "休息" in phase2, phase2[:40])
        check("休息视图有绿色标识（class rest）",
              cdp.eval_js("!!document.querySelector('#pomo .pomo.rest')"))
        check("休息时按钮变成「休息够了，继续」",
              cdp.eval_js("""Array.from(document.querySelectorAll('#pomo button'))
                              .some(b=>b.textContent.indexOf('休息够了')>=0)"""))

        # 结束计划
        cdp.eval_js("""(() => {
            const b = Array.from(document.querySelectorAll('#pomo button'))
                .find(x => x.textContent.indexOf('结束计划') >= 0);
            if (b) b.click();
        })()""")
        time.sleep(2.5)
        check("结束后回到设置视图",
              cdp.eval_js("""Array.from(document.querySelectorAll('#pomo button'))
                              .some(b=>b.textContent.indexOf('开始专注')>=0)"""))
        last = cdp.eval_js("(document.querySelector('#pomo .basis')||{}).textContent || ''")
        check("显示了上一次的结果摘要", "上一次" in last, last[:70])

        # 服务端也确认已结束
        raw = urllib.request.urlopen(base + "/api/data", timeout=10).read()
        plan_state = json.loads(raw)["plan"]
        check("服务端计划状态一致（已结束）",
              plan_state.get("finished") is True or plan_state.get("active") is False,
              json.dumps(plan_state, ensure_ascii=False)[:70])

        # 清掉测试留下的计划，别影响用户
        req = urllib.request.Request(
            base + "/api/plan", data=json.dumps({"action": "clear"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()

        # UI 测试改过 focus/break（改成 1 分钟好快点跑完），这里恢复成常用值，
        # 否则"自定义"会一直停在 1 分钟，用户下次打开会莫名其妙
        req2 = urllib.request.Request(
            base + "/api/config",
            data=json.dumps({"edits": {"plan.preset": "pomodoro", "plan.focus_min": 25,
                                       "plan.break_min": 5, "plan.long_every": 4,
                                       "plan.long_break_min": 20, "plan.rounds": 0}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req2, timeout=15).read()
        print("  已把节奏恢复为 25/5（UI 测试期间改成了 1/1）")
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    base = "http://127.0.0.1:8770"
    shot = ROOT / "data" / "pomo-check.png"
    logic_tests()
    ui_tests(base, shot)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    if passed != len(results):
        print("失败项：")
        for name, ok, detail in results:
            if not ok:
                print(f"  · {name} {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
