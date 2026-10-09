"""体检独立桌宠窗口：页面是否正常、模型是否渲染、缩放到不到位。

**不要用 PrintWindow 抓这个窗口**：Chromium 的 WebGL 内容不在 PrintWindow
的绘制路径里，抓到的是空白或别的窗口（实测为此浪费了好几轮，把好窗口
误判成坏的）。正确做法是走 CDP 的 Page.captureScreenshot —— 它走合成器，
能看到 WebGL 画布。

用法：
    python tools/check_pet_window.py             # 体检正在跑的窗口（自己起临时实例）
    python tools/check_pet_window.py --shot      # 顺便存一张截图
"""
import base64
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
sys.path.insert(0, str(ROOT))
from cdp_check import CDP, find_edge, free_port   # noqa: E402

URL = "http://127.0.0.1:8770/pet?style=solid"


def main() -> int:
    edge = find_edge()
    if not edge:
        print("  没找到 Edge")
        return 1
    port = free_port()
    prof = Path(tempfile.mkdtemp(prefix="sw_petchk_"))
    p = subprocess.Popen(
        [edge, f"--app={URL}", f"--remote-debugging-port={port}",
         f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
         "--window-size=380,480"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    failed = 0
    try:
        ws = None
        for _ in range(40):
            time.sleep(0.5)
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/list", timeout=3).read()
                pages = [t for t in json.loads(raw)
                         if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    ws = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
        if not ws:
            print("  连不上桌宠页面")
            return 1
        c = CDP(ws)
        c.call("Page.enable")
        c.call("Runtime.enable")
        time.sleep(9)

        st = c.eval_js("""(() => {
            const cv = document.getElementById('pet');
            const r = cv ? cv.getBoundingClientRect() : null;
            return {
              url: location.href,
              title: document.title,
              pixi: typeof PIXI !== 'undefined' && !!PIXI.live2d,
              hasCanvas: !!cv,
              canvasBox: r ? [Math.round(r.width), Math.round(r.height)] : null,
              fit: window.__petFit || null,
              say: (document.getElementById('say')||{}).textContent,
              barButtons: document.querySelectorAll('#bar .btn').length,
              dpr: window.devicePixelRatio || 1,
            };
        })()""")
        print(f"  页面：{st.get('title')!r}｜{st.get('url')}")
        fit = st.get("fit") or {}
        print(f"  画布：{st.get('canvasBox')}（dpr {st.get('dpr')}）"
              f"｜renderer {fit.get('rw')}x{fit.get('rh')}")
        print(f"  模型：{fit.get('modelWH')}｜未缩放时占 {fit.get('bounds')}"
              f"｜scale {fit.get('sc')}")
        print(f"  气泡：{st.get('say')!r}｜顶栏按钮 {st.get('barButtons')} 个")

        # 关键判定：scale 必须明显小于 1（4068 单位的模型要缩到几百像素）。
        # 若接近 1，说明缩算错，角色会大到只剩一块皮肤。
        sc = float(fit.get("sc") or 0)
        checks = {
            "页面加载了 Live2D 运行时": bool(st.get("pixi")),
            "画布存在且有尺寸": bool(st.get("hasCanvas")) and
                                all(v and v > 40 for v in (st.get("canvasBox") or [0, 0])),
            "缩放算对了（明显小于 1）": 0 < sc < 0.5,
            "顶栏三个按钮都在": int(st.get("barButtons") or 0) == 3,
            "气泡有内容": bool(str(st.get("say") or "").strip()),
        }
        for k, v in checks.items():
            print(f"  [{'通过' if v else '失败'}] {k}")
            if not v:
                failed += 1

        if "--shot" in sys.argv:
            c.eval_js("document.body.style.background='#1b2430'")
            time.sleep(0.6)
            shot = c.call("Page.captureScreenshot", {"format": "png"})
            out = ROOT / "data" / "pet-window-check.png"
            out.write_bytes(base64.b64decode(shot["data"]))
            print(f"  截图：{out}")
        return 0 if failed == 0 else 1
    finally:
        p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:
            p.kill()
        shutil.rmtree(prof, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
