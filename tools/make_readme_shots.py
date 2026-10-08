"""为 README 拍配图：番茄钟卡片 + 仪表盘全页。

做法是用 CDP 真的操作页面（起一个计划、把时间轴缩放到有内容的区间），
再截图。不手工修图，保证图里显示的都是真实界面。

用法：python tools/make_readme_shots.py
"""
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp_check import CDP, launch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
BASE = "http://127.0.0.1:8770"


def main() -> int:
    import json
    import urllib.request

    # 1) 起一个 25/5 的计划（经典预设，第 2 轮专注）——配图要体现"轮次"这件事
    req = urllib.request.Request(
        BASE + "/api/plan",
        data=json.dumps({"action": "start", "preset": "pomodoro", "focus_min": 25,
                         "break_min": 5, "long_every": 4, "long_break_min": 20,
                         "rounds": 4, "note": "线性代数 · 第三章习题"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    r = json.loads(urllib.request.urlopen(req, timeout=15).read())
    print(f"  计划已开始：{r.get('message')}")

    # 把它"推进"到第 2 轮：先跳到休息、再跳回专注。
    # 为了显示"已完成 1 轮专注"这种真实使用状态，先补一条真正完成的专注记录
    # （skip 出来的阶段 completed=False，不会被计入完成轮数，所以光靠 skip 会不自洽）
    import datetime as _dt
    st = json.loads(urllib.request.urlopen(BASE + "/api/data", timeout=15).read())["plan"]
    plan_file = ROOT / "data" / "plan.json"
    raw = json.loads(plan_file.read_text(encoding="utf-8"))
    now = _dt.datetime.now()
    raw["history"] = [{
        "phase": "focus", "round": 1,
        "started_at": (now - _dt.timedelta(minutes=31)).isoformat(timespec="seconds"),
        "ended_at": (now - _dt.timedelta(minutes=6)).isoformat(timespec="seconds"),
        "sec": 1500, "completed": True,
    }]
    plan_file.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    for _ in range(2):
        req2 = urllib.request.Request(
            BASE + "/api/plan", data=json.dumps({"action": "skip"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req2, timeout=15).read()
    st = json.loads(urllib.request.urlopen(BASE + "/api/data", timeout=15).read())["plan"]
    print(f"  已推进到：{st.get('phase_label')} 第 {st.get('round')} 轮"
          f"｜已完成 {st.get('done_focus_rounds')} 轮专注"
          f"（累计 {st.get('rounds_total_sec', 0) // 60} 分钟）")

    proc, profile, ws_url = launch(BASE)
    try:
        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        time.sleep(4)

        # 2) 把时间轴缩放到今天有数据的那一段（否则半屏是空的）
        span = cdp.eval_js("""(() => {
            const tag = document.getElementById('tlTag').textContent;
            const m = tag.match(/(\\d{2}:\\d{2})[–\\-](\\d{2}:\\d{2})/);
            if (!m) return null;
            const toMin = s => (+s.slice(0,2)) * 60 + (+s.slice(3));
            let a = toMin(m[1]), b = toMin(m[2]);
            if (b < a) b += 24 * 60;
            return b - a;
        })()""")
        print(f"  今日数据跨度：{span} 分钟")
        # 选一个恰好覆盖数据的预设，让时间轴铺满
        picked = None
        for label, mins in (("最近 1 小时", 60), ("最近 3 小时", 180),
                            ("最近 6 小时", 360), ("最近 12 小时", 720)):
            if span is not None and span <= mins:
                picked = label
                break
        if picked:
            cdp.eval_js(f"""(() => {{
                const b = Array.from(document.querySelectorAll('#tlPresets button'))
                    .find(x => x.textContent.indexOf({picked!r}) >= 0);
                if (b) b.click();
            }})()""")
            time.sleep(1)
            print(f"  时间轴已缩放到「{picked}」：{cdp.eval_js('document.getElementById(chr(116)+chr(108)+chr(84)+chr(97)+chr(103)).textContent') if False else cdp.eval_js('document.getElementById(\"tlTag\").textContent')}")

        # 3) 先把整页高度量出来，再按整页截图
        h = cdp.eval_js("document.body.scrollHeight")
        print(f"  页面高度：{h}px")

        # 番茄钟卡片单独一张（聚焦这个新功能）
        # 注意：clip 的坐标是"相对于页面"的 CSS 像素；先滚到顶，并让视口够高，
        # 否则截出来会带上无关区域、尺寸也会失控。
        cdp.eval_js("window.scrollTo(0, 0)")
        # 用窄视口拍卡片：1456px 宽时内容偏小，缩到 1040 让卡片占满画面，
        # 在 GitHub 上（渲染宽度有限）才看得清字
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": 1040, "height": 900, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1.2)
        rect = cdp.eval_js("""(() => {
            const el = document.getElementById('pomoCard');
            const r = el.getBoundingClientRect();
            const cs = getComputedStyle(el);
            const mt = parseFloat(cs.marginTop) || 0;
            const mb = parseFloat(cs.marginBottom) || 0;
            return {x: r.x + window.scrollX, y: r.y + window.scrollY - mt,
                    w: r.width, h: r.height + mt + mb};
        })()""")
        print(f"  卡片位置：x={rect['x']:.0f} y={rect['y']:.0f} "
              f"w={rect['w']:.0f} h={rect['h']:.0f}")
        shot_card = ASSETS / "pomodoro-card.png"
        data = cdp.call("Page.captureScreenshot",
                        {"format": "png",
                         "clip": {"x": max(0, rect["x"]), "y": max(0, rect["y"]),
                                  "width": rect["w"], "height": rect["h"],
                                  "scale": 1}})
        import base64
        shot_card.write_bytes(base64.b64decode(data["data"]))
        print(f"  已写出 {shot_card}（{shot_card.stat().st_size // 1024} KB）")

        # 再看整页
        h = cdp.eval_js("document.body.scrollHeight")
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": 1520, "height": min(int(h) + 40, 9000),
                  "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1.2)
        shot_full = ASSETS / "dashboard-preview.png"
        n = cdp.screenshot(shot_full)
        print(f"  已写出 {shot_full}（{n // 1024} KB，{h}px 高）")
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        # 结束用于拍照的计划
        req = urllib.request.Request(
            BASE + "/api/plan", data=json.dumps({"action": "stop"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=10).read()
        print("  拍照用计划已结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
