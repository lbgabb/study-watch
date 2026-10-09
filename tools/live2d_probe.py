"""验证 pixi + pixi-live2d-display 能不能在无头浏览器里真的渲染这个模型。

上一版探测用的是手写 WebGL（想确认 Core 本身可用），已经证明：
  Cubism Core 5.1.0 加载成功、moc3 解析成功、269 个 drawable / 247 个参数。
这一版换成正路：pixi-live2d-display 负责渲染（那位大佬用的也是它），
目标是把模型真的画到 canvas 上，并读回像素确认不是空白。

用法：
    python tools/live2d_probe.py            # 手写 WebGL 版（Core 自检）
    python tools/live2d_probe.py --pixi     # pixi 版（真实渲染）
"""
import json
import shutil
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from cdp_check import CDP, launch   # noqa: E402

VENDOR = Path("E:/ds/_l2d_vendor")
MODEL = Path("E:/ds/_l2d_model")
PROBE_DIR = ROOT / "data" / "_l2d_probe"


def build_probe(pixi: bool) -> Path:
    shutil.rmtree(PROBE_DIR, ignore_errors=True)
    (PROBE_DIR / "vendor").mkdir(parents=True)
    (PROBE_DIR / "model").mkdir(parents=True)
    for n in ("live2dcubismcore.min.js", "pixi.min.js", "cubism4.min.js"):
        src = VENDOR / n
        if src.is_file():
            shutil.copy(src, PROBE_DIR / "vendor" / n)
    for f in MODEL.iterdir():
        if f.is_file():
            shutil.copy(f, PROBE_DIR / "model" / f.name)
    tex = MODEL / "c_0120.2048"
    if tex.is_dir():
        shutil.copytree(tex, PROBE_DIR / "model" / "c_0120.2048")

    if pixi:
        html = """<!doctype html><meta charset="utf-8">
<title>Live2D pixi probe</title>
<style>body{margin:0;background:#1b2430}canvas{display:block}</style>
<canvas id="stage" width="500" height="500"></canvas>
<script src="/vendor/live2dcubismcore.min.js"></script>
<script src="/vendor/pixi.min.js"></script>
<script src="/vendor/cubism4.min.js"></script>
<script>
window.RESULT = {stage: 'init'};
const set = o => Object.assign(window.RESULT, o);
window.addEventListener('error', e => set({error: String(e.message)}));

// 等 DOM 就绪：脚本在 body 末尾也会立刻执行，但 head 里执行时
// document.body 还是 null（踩过：appendChild 报 null）。
window.addEventListener('DOMContentLoaded', async () => {
  try {
    set({stage:'libs',
         hasCore: typeof Live2DCubismCore !== 'undefined',
         hasPIXI: typeof PIXI !== 'undefined',
         hasLLD: typeof PIXI !== 'undefined' && !!PIXI.live2d});
    if (typeof PIXI === 'undefined') { set({error:'PIXI 没加载'}); return; }
    if (!PIXI.live2d) { set({error:'pixi-live2d-display 没挂上 PIXI.live2d'}); return; }

    const view = document.getElementById('stage');
    const app = new PIXI.Application({view: view, width: 500, height: 500,
                                      backgroundAlpha: 0, antialias: true,
                                      autoStart: false, preserveDrawingBuffer: true});
    set({stage:'app-ready', rendererType: app.renderer.type,
         rendererName: app.renderer.name || ''});

    const model = await PIXI.live2d.Live2DModel.from('/model/c_0120.model3.json',
                                                     {autoInteract: false, autoUpdate: false});
    set({stage:'model-loaded',
         width: model.width, height: model.height,
         internalModel: !!model.internalModel,
         motionGroups: Object.keys((model.internalModel && model.internalModel.motionManager
                                    && model.internalModel.motionManager.definitions) || {})});
    app.stage.addChild(model);
    const sc = 460 / Math.max(model.width, model.height);
    model.scale.set(sc);
    model.anchor.set(0.5, 0.5);
    model.position.set(250, 250);

    model.update(1 / 60);
    app.renderer.render(app.stage);
    set({stage:'rendered'});

    const px = app.renderer.extract.pixels(app.stage);
    const d = px.pixels || px;
    let opaque = 0;
    for (let i = 3; i < d.length; i += 4) if (d[i] > 12) opaque++;
    set({opaquePixels: opaque, total: d.length / 4,
         opaqueRatio: +(opaque / (d.length / 4)).toFixed(4), done: true});
  } catch (e) {
    set({error: String((e && e.stack) || e)});
  }
});
</script>
"""
        (PROBE_DIR / "index.html").write_text(html, encoding="utf-8")
    else:
        html = (Path(__file__).parent / "_l2d_probe_webgl.html")
        if html.is_file():
            (PROBE_DIR / "index.html").write_text(html.read_text(encoding="utf-8"),
                                                  encoding="utf-8")
    return PROBE_DIR


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main() -> int:
    use_pixi = "--pixi" in sys.argv
    if not (VENDOR / "live2dcubismcore.min.js").is_file():
        print("  缺少 Cubism Core，先跑 tools/fetch_cubism_core.py")
        return 1
    if use_pixi and not (VENDOR / "cubism4.min.js").is_file():
        print("  缺少 cubism4.min.js / pixi.min.js")
        return 1

    d = build_probe(use_pixi)
    handler = partial(Quiet, directory=str(d))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"  临时服务：http://127.0.0.1:{port}/   （{'pixi' if use_pixi else '手写 WebGL'}）")

    proc, profile, ws = launch(f"http://127.0.0.1:{port}/")
    try:
        c = CDP(ws)
        c.call("Page.enable"); c.call("Runtime.enable")
        time.sleep(2)
        res = None
        for _ in range(60):
            res = c.eval_js("window.RESULT")
            if res and (res.get("done") or res.get("error")):
                break
            time.sleep(0.5)
        print()
        if not res:
            print("  没能读到页面结果")
            return 1
        for k, v in res.items():
            print(f"    {k}: {v}")
        # 顺手存一张截图，肉眼确认
        shot = ROOT / "data" / ("_l2d_pixi.png" if use_pixi else "_l2d_webgl.png")
        c.screenshot(shot)
        print(f"\n  截图：{shot}")
        ok = bool(res.get("done")) and res.get("opaquePixels", 0) > 5000
        print("  === 结论 ===")
        if res.get("error"):
            print(f"  X 失败：{res['error']}")
        elif ok:
            print(f"  OK 渲染成功，不透明像素 {res['opaquePixels']:,}"
                  f"（占比 {res.get('opaqueRatio', 0):.1%}）")
        else:
            print(f"  ? 流程走完但画面基本是空的（不透明像素 {res.get('opaquePixels')}）")
        return 0 if ok else 1
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        srv.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
