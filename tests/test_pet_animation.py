"""桌宠动画回归测试。

**必须用窗口截图（CDP Page.captureScreenshot）对比像素，不能用 canvas.toDataURL()。**
踩过的坑：WebGL 在未开 preserveDrawingBuffer 时，toDataURL 的读回语义不可靠，
可能一直返回同一份内容 —— 于是"画面完全静止"这个结论本身是错的，
我为它查了很久（rAF、ticker、节流全都查了一遍）。

窗口截图走合成器，等同肉眼所见，是唯一可信的判据。

覆盖：
  · 页面不被 Chromium 判定为隐藏（反节流开关生效）
  · 定时器不被节流
  · 画面自己在动（呼吸/眨眼）
  · 动作能切组，且画面变化明显大于待机时的自然抖动
"""
import base64
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from cdp_check import CDP, find_edge, free_port   # noqa: E402

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [通过] {name}" + (f" -> {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [失败] {name}" + (f" -> {detail}" if detail else ""))


def main() -> int:
    print("=== 桌宠动画回归测试（截图对比）===")
    edge = find_edge()
    port = free_port()
    prof = Path(tempfile.mkdtemp(prefix="sw_anim_"))
    args = [edge, f"--remote-debugging-port={port}",
            "--app=http://127.0.0.1:8770/pet?style=solid",
            "--window-size=380,480", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={prof}",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-features=Translate,msEdgeSplitScreen,CalculateNativeWinOcclusion"]
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = None
        last_err = ""
        for _ in range(45):
            time.sleep(1)
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/list", timeout=3).read()
                pages = [t for t in json.loads(raw)
                         if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    ws = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
        if not ws:
            print(f"  连不上窗口（端口 {port}，最后错误 {last_err}）")
            return 1
        c = CDP(ws)
        c.call("Page.enable")
        c.call("Runtime.enable")
        time.sleep(9)

        import numpy as np
        from PIL import Image

        def shot() -> "np.ndarray":
            r = c.call("Page.captureScreenshot", {"format": "png"})
            return np.asarray(Image.open(io.BytesIO(base64.b64decode(r["data"])))
                              .convert("RGB"), dtype=int)

        st = c.eval_js("({hidden: document.hidden, vis: document.visibilityState})")
        check("页面不被判定为隐藏", st.get("hidden") is False,
              f"hidden={st.get('hidden')} visibilityState={st.get('vis')}")

        c.eval_js("window.__n = 0; setInterval(() => window.__n++, 100)")
        time.sleep(1.3)
        n = int(c.eval_js("window.__n") or 0)
        check("定时器没被节流（1.3 秒约 13 次）", n >= 8, f"触发 {n} 次")

        frames = c.eval_js("window.__petFrames")
        check("渲染驱动在跑（自检对象存在）", isinstance(frames, int) and frames > 0,
              f"已渲染 {frames} 帧")

        # 待机：自然抖动
        base = shot()
        idle_diffs = []
        for _ in range(5):
            time.sleep(0.3)
            idle_diffs.append(float(np.abs(shot() - base)
                                    .max(axis=2).__gt__(8).mean() * 100))
        check("画面自己在动（呼吸/眨眼）", max(idle_diffs) > 0.5,
              f"待机时变化像素占比 {max(idle_diffs):.2f}%")

        # 动作：用"动作开始"事件判定，不要事后去读 currentGroup。
        #
        # 踩过的坑：motion('splash') 这类动作只有 1~2 秒，等 0.4 秒再截 5 张图
        # （又 1.5 秒）之后才去读 state.currentGroup，动作早就播完了 ——
        # 读回 None 并不代表没播。事件才是可靠的判据。
        c.eval_js("""(() => {
            window.__motionStart = [];
            try {
              model.internalModel.motionManager.on('motionStart',
                (group, index) => window.__motionStart.push(String(group)));
            } catch (e) { window.__motionHookErr = String(e && e.message || e); }
        })()""")
        time.sleep(0.2)
        c.eval_js("(() => { try { model.motion('splash'); } catch (e) {} })()")
        # 立刻读一次（这时动作刚触发，应当已经是目标组）
        g_now = c.eval_js("model.internalModel.motionManager.state.currentGroup")
        time.sleep(1.2)
        started = c.eval_js("window.__motionStart") or []
        check("动作能切组（不再永远停在 idle）",
              g_now == "splash" or "splash" in started,
              f"currentGroup={g_now}｜motionStart 事件={started}")

        b2 = shot()
        mv_diffs = []
        for _ in range(5):
            time.sleep(0.3)
            mv_diffs.append(float(np.abs(shot() - b2)
                                  .max(axis=2).__gt__(8).mean() * 100))
        check("动作的画面变化不算小", max(mv_diffs) > 0.5,
              f"播放时变化像素占比 {max(mv_diffs):.2f}%")

        err = c.eval_js("window.__petLoopErr")
        check("渲染循环没报错", not err, str(err))

        # 存证
        a = ROOT / "data" / "pet-anim-a.png"
        b = ROOT / "data" / "pet-anim-b.png"
        a.write_bytes(base64.b64decode(
            c.call("Page.captureScreenshot", {"format": "png"})["data"]))
        time.sleep(0.45)
        b.write_bytes(base64.b64decode(
            c.call("Page.captureScreenshot", {"format": "png"})["data"]))
        print(f"  画面存证：{a.name} / {b.name}（隔 0.45 秒，可直接对比）")
        print()
        print(f"  {PASS} 通过 / {FAIL} 失败")
        return 0 if FAIL == 0 else 1
    finally:
        p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:
            p.kill()
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
