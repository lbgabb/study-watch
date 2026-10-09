"""构建期工具：把 Live2D 模型渲染成带 alpha 的帧序列（供 Python 桌宠播放）。

为什么要预渲染：
  运行时要"不依赖浏览器"，而 Live2D 必须有 Cubism 运行时（WebGL）。
  Python 侧没有可用绑定，所以把"渲染"这一步挪到构建期：
  用无头浏览器把固定几段动画烘成 RGBA 帧，运行时只用 Pillow 播放。

这个脚本先只做一件事：**量清楚资产体积**。渲染一段 idle 循环，逐帧导出，
报出每帧大小与总量 —— 体积决定了这个方案可不可行，不能靠猜。

用法：
    python tools/build_pet_frames.py                 # 量 idle 循环（默认 60 帧）
    python tools/build_pet_frames.py --frames 80 --fps 20
    python tools/build_pet_frames.py --size 380x480
"""
import argparse
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
from cdp_check import CDP, find_edge, free_port   # noqa: E402

OUT = ROOT / "assets" / "petframes"

# 在页面里把模型准备好，并暴露一个"渲染第 n 帧并返回 PNG base64"的函数。
# 逐帧用固定时间步长推进，保证循环可重复（不依赖真实时钟）。
PAGE = """<!doctype html><meta charset="utf-8">
<title>frame baker</title>
<style>html,body{margin:0;background:transparent;overflow:hidden}
canvas{display:block}</style>
<canvas id="c"></canvas>
<script src="/vendor/live2dcubismcore.min.js"></script>
<script src="/vendor/pixi.min.js"></script>
<script src="/vendor/cubism4.min.js"></script>
<script>
window.BAKE = {ready:false, error:null, frames:0, w:0, h:0};
(async () => {
  try {
    const W = __W__, H = __H__;
    const cv = document.getElementById('c');
    cv.width = W; cv.height = H;
    const app = new PIXI.Application({view: cv, width: W, height: H,
      backgroundAlpha: true, antialias: true, autoStart: false,
      preserveDrawingBuffer: true, resolution: 1});
    const model = await PIXI.live2d.Live2DModel.from('__MODEL__',
                                                     {autoInteract:false, autoUpdate:false});
    app.stage.addChild(model);
    model.anchor.set(0.5, 0.5);
    // 和运行时一致：按未缩放占用反推缩放
    model.scale.set(1); model.position.set(0, 0);
    let b = model.getBounds();
    const sc = Math.min(W / b.width, H / b.height) * 0.98;
    model.scale.set(sc);
    model.position.set(W / 2, H / 2);

    const mm = model.internalModel.motionManager;
    // 播 idle：让动作把参数推起来，之后按固定步长逐帧推进
    try { model.motion('idle'); } catch (e) {}
    BAKE.w = W; BAKE.h = H;

    // 预热若干帧，跳过动作淡入的不自然段
    for (let i = 0; i < 40; i++) { model.update(1/30); }
    let t = 0;
    BAKE.step = function (dt) {
      t += dt;
      model.update(dt);
      app.renderer.render(app.stage);
      return app.renderer.extract.base64(app.stage);
    };
    BAKE.ready = true;
  } catch (e) {
    BAKE.error = String((e && e.stack) || e);
  }
})();
</script>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--size", default="380x480")
    ap.add_argument("--out", default="")
    ap.add_argument("--keep", action="store_true", help="保留渲染出的帧文件")
    args = ap.parse_args()

    try:
        w, h = (int(v) for v in args.size.lower().split("x"))
    except ValueError:
        print("  --size 形如 380x480")
        return 1

    if not (ROOT / "assets" / "live2d" / "c_0120.model3.json").is_file():
        print("  缺少模型，先跑 tools/build_live2d_model.py")
        return 1

    edge = find_edge()
    if not edge:
        print("  没找到 Edge")
        return 1

    # 起一个临时站点：模型 + 运行时 + 这个烧帧页面
    site = Path(tempfile.mkdtemp(prefix="sw_bake_"))
    (site / "vendor").mkdir(parents=True)
    (site / "model").mkdir(parents=True)
    for n in ("live2dcubismcore.min.js", "pixi.min.js", "cubism4.min.js"):
        shutil.copy(ROOT / "assets" / "vendor" / n, site / "vendor" / n)
    shutil.copytree(ROOT / "assets" / "live2d", site / "model", dirs_exist_ok=True)
    (site / "index.html").write_text(
        PAGE.replace("__W__", str(w)).replace("__H__", str(h))
            .replace("__MODEL__", "/model/c_0120.model3.json"), encoding="utf-8")

    srv = None
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(site)))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    cdp_port = free_port()
    prof = Path(tempfile.mkdtemp(prefix="sw_bakeprof_"))
    p = subprocess.Popen(
        [edge, "--headless=new", "--no-first-run", "--no-default-browser-check",
         f"--remote-debugging-port={cdp_port}", f"--user-data-dir={prof}",
         f"--window-size={w},{h}", f"http://127.0.0.1:{port}/index.html"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws = None
        for _ in range(60):
            time.sleep(0.5)
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{cdp_port}/json/list", timeout=3).read()
                pages = [t for t in json.loads(raw)
                         if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    ws = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
        if not ws:
            print("  连不上渲染页")
            return 1
        c = CDP(ws)
        c.call("Page.enable")
        c.call("Runtime.enable")
        for _ in range(40):
            time.sleep(0.5)
            st = c.eval_js("window.BAKE")
            if st and (st.get("ready") or st.get("error")):
                break
        st = c.eval_js("window.BAKE") or {}
        if st.get("error"):
            print(f"  页面报错：{st['error']}")
            return 1
        if not st.get("ready"):
            print("  模型没准备好")
            return 1
        print(f"  渲染准备就绪：{st.get('w')}x{st.get('h')}")

        dt = 1.0 / args.fps
        frames = []
        t0 = time.time()
        for i in range(args.frames):
            data = c.eval_js(f"BAKE.step({dt})")
            if not data:
                print(f"  第 {i} 帧没拿到数据")
                break
            if "," in data:
                data = data.split(",", 1)[1]
            frames.append(base64.b64decode(data))
        dt_all = time.time() - t0
        print(f"  渲染 {len(frames)} 帧用了 {dt_all:.1f} 秒"
              f"（{len(frames) / max(dt_all, 0.01):.1f} 帧/秒）")

        if args.keep and frames:
            OUT.mkdir(parents=True, exist_ok=True)
            for i, b in enumerate(frames):
                (OUT / f"frame_{i:03d}.png").write_bytes(b)

        total = sum(len(b) for b in frames)
        if not frames:
            print("  没有渲染出帧")
            return 1
        print()
        print(f"  === 资产体积（{args.size}，{len(frames)} 帧）===")
        print(f"    PNG 单帧平均 {total / len(frames) / 1024:.1f} KB"
              f"｜最小 {min(len(b) for b in frames) / 1024:.1f} KB"
              f"｜最大 {max(len(b) for b in frames) / 1024:.1f} KB")
        print(f"    这一段的 PNG 总量：{total / 1024 / 1024:.2f} MB"
              f"（{len(frames)} 帧 ≈ {len(frames) / args.fps:.1f} 秒循环）")
        # 同一批帧用 WebP 有损再压一次，看看能省多少
        try:
            import io
            from PIL import Image
            wsum = 0
            for i, b in enumerate(frames[:20]):
                im = Image.open(io.BytesIO(b)).convert("RGBA")
                buf = io.BytesIO()
                im.save(buf, "WEBP", quality=82, method=4)
                wsum += buf.tell()
            avg = wsum / max(1, len(frames[:20]))
            print(f"    WebP(q82) 单帧平均 {avg / 1024:.1f} KB"
                  f" -> 整段约 {avg * len(frames) / 1024 / 1024:.2f} MB"
                  f"（抽 20 帧估算）")
        except Exception as e:
            print(f"    WebP 估算失败：{e}")
        return 0
    finally:
        p.terminate()
        try:
            p.wait(timeout=8)
        except Exception:
            p.kill()
        shutil.rmtree(prof, ignore_errors=True)
        shutil.rmtree(site, ignore_errors=True)
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
