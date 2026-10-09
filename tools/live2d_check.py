"""验证入库后的模型能被加载，并且动作组与表情都注册成功。

跟 live2d_probe.py 的区别：那个是验证"能不能渲染"（用手工解包的临时目录），
这个是验证**仓库里整理好的模型**是否完整可用——包括我们自己生成的
model3.json 里那些动作组与表情，以及表情切换是否真的改变了画面。

用法：
    python tools/live2d_check.py
"""
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

VENDOR = ROOT / "assets" / "vendor"
MODEL = ROOT / "assets" / "live2d"
PAGE = ROOT / "web" / "pet.html"

PAGE_HTML = """<!doctype html><meta charset="utf-8">
<title>live2d check</title>
<style>html,body{margin:0;background:#1b2430;height:100%}
#stage{display:block;width:420px;height:420px}</style>
<canvas id="stage" width="420" height="420"></canvas>
<script src="/vendor/live2dcubismcore.min.js"></script>
<script src="/vendor/pixi.min.js"></script>
<script src="/vendor/cubism4.min.js"></script>
<script>
window.RESULT = {stage:'init'};
const set = o => Object.assign(window.RESULT, o);
window.addEventListener('error', e => set({error:String(e.message)}));

window.addEventListener('DOMContentLoaded', async () => {
  try {
    set({libs: {core: typeof Live2DCubismCore !== 'undefined',
                pixi: typeof PIXI !== 'undefined',
                lld: typeof PIXI !== 'undefined' && !!PIXI.live2d}});
    const app = new PIXI.Application({view: document.getElementById('stage'),
      width: 420, height: 420, backgroundAlpha: 0, antialias: true,
      autoStart: false, preserveDrawingBuffer: true});
    const model = await PIXI.live2d.Live2DModel.from('/model/c_0120.model3.json',
                                                     {autoInteract:false, autoUpdate:false});
    app.stage.addChild(model);
    const sc = 400 / Math.max(model.width, model.height);
    model.scale.set(sc); model.anchor.set(0.5, 0.5); model.position.set(210, 210);

    const mm = model.internalModel.motionManager;
    const defs = (mm && mm.definitions) || {};
    const em = model.internalModel.motionManager.expressionManager;
    const exprs = (em && em.definitions) || [];
    set({motionGroups: Object.keys(defs),
         expressionCount: exprs.length,
         expressionNames: exprs.map(d => d.Name).slice(0, 20)});

    const shots = {};
    const grab = () => {
      model.update(1/60);
      app.renderer.render(app.stage);
      const px = app.renderer.extract.pixels(app.stage);
      const d = px.pixels || px;
      let op = 0, sum = 0;
      for (let i = 0; i < d.length; i += 4) {
        if (d[i+3] > 12) { op++; sum += d[i] + d[i+1] + d[i+2]; }
      }
      return {opaque: op, meanColor: op ? Math.round(sum / (op*3)) : 0};
    };
    set({noExpression: grab()});

    // 逐个切表情，比较画面是否真的变了
    const diffs = {};
    for (const d of exprs) {
      try {
        await em.setExpression(d.Name);
        diffs[d.Name] = grab();
      } catch (e) { diffs[d.Name] = {error: String(e.message)}; }
    }
    set({expressionShots: diffs});

    // 播一个动作，确认动作组可用。
    // 注意：model.motion() 返回的是内部 motion 对象（序列化成 {}），
    // 不是布尔值 —— 所以这里判断的是"有没有抛错"，不是返回值真假。
    try {
      model.motion('idle');
      model.motion('selfie');
      set({motionPlay: {ok: true, note: 'idle 与 selfie 都没有抛错'}});
    } catch (e) { set({motionPlay: {ok: false, error: String(e.message)}}); }
    set({done: true});
  } catch (e) { set({error: String((e && e.stack) || e)}); }
});
</script>
"""


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def main() -> int:
    if not (VENDOR / "live2dcubismcore.min.js").is_file():
        print("  缺少 assets/vendor 下的运行时，先跑 tools/fetch_cubism_core.py")
        return 1
    if not (MODEL / "c_0120.model3.json").is_file():
        print("  缺少 assets/live2d 模型，先跑 tools/build_live2d_model.py")
        return 1

    # 用临时站点把仓库目录拼起来（vendor + live2d + 页面）
    site = ROOT / "data" / "_l2d_site"
    shutil.rmtree(site, ignore_errors=True)
    (site / "vendor").mkdir(parents=True)
    (site / "model").mkdir(parents=True)
    for n in ("live2dcubismcore.min.js", "pixi.min.js", "cubism4.min.js"):
        if (VENDOR / n).is_file():
            shutil.copy(VENDOR / n, site / "vendor" / n)
    shutil.copytree(MODEL, site / "model", dirs_exist_ok=True)
    (site / "index.html").write_text(PAGE_HTML, encoding="utf-8")

    handler = partial(Quiet, directory=str(site))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    print(f"  临时站点：http://127.0.0.1:{port}/")

    proc, profile, ws = launch(f"http://127.0.0.1:{port}/")
    failed = 0
    try:
        c = CDP(ws)
        c.call("Page.enable"); c.call("Runtime.enable")
        time.sleep(2)
        res = None
        for _ in range(80):
            res = c.eval_js("window.RESULT")
            if res and (res.get("done") or res.get("error")):
                break
            time.sleep(0.5)
        print()
        if not res:
            print("  读不到页面结果")
            return 1
        libs = res.get("libs") or {}
        print(f"  运行时：core={libs.get('core')} pixi={libs.get('pixi')} lld={libs.get('lld')}")
        if res.get("error"):
            print(f"  X 失败：{res['error']}")
            return 1
        groups = res.get("motionGroups") or []
        print(f"  动作组 {len(groups)} 个：{groups}")
        print(f"  表情 {res.get('expressionCount')} 个：{res.get('expressionNames')}")
        base = res.get("noExpression") or {}
        print(f"  无表情时：不透明 {base.get('opaque'):,}｜均色 {base.get('meanColor')}")
        shots = res.get("expressionShots") or {}
        changed = 0
        for name, v in shots.items():
            if v.get("error"):
                print(f"    X {name}: {v['error']}")
                failed += 1
                continue
            diff = abs((v.get("opaque") or 0) - (base.get("opaque") or 0)) > 50
            if diff:
                changed += 1
        print(f"  切换表情后画面发生变化的：{changed}/{len(shots)}")
        mp = res.get("motionPlay") or {}
        print(f"  动作播放：{mp}")
        print()
        checks = {
            "运行时齐全": bool(libs.get("core") and libs.get("pixi") and libs.get("lld")),
            "动作组已注册": len(groups) >= 6,
            "表情已注册": int(res.get("expressionCount") or 0) >= 10,
            "模型真的画出来了": int(base.get("opaque") or 0) > 5000,
            "表情切换有效果": changed >= max(3, len(shots) // 3),
            "动作能播（不抛错）": bool(mp.get("ok")),
        }
        for k, v in checks.items():
            print(f"  [{'通过' if v else '失败'}] {k}")
        return 0 if all(checks.values()) else 1
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
