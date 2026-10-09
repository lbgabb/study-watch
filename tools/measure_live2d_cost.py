"""实测桌宠性能开销（对照组：启用 vs 停用）。

三个必须做对的地方，前面都踩过：

1. **只量我们的浏览器实例**。不能按进程名统计 msedge —— 这台机器上同时开着
   用户自己的 Edge，按名字量到的是用户的浏览行为。所以按唯一的
   --user-data-dir 定位进程树（tools/proc_tree_cpu.ps1）。
2. **必须让 WebGL 走真显卡**。cdp_check.launch() 里写死了 --disable-gpu，
   那样 WebGL 会退化成 CPU 软件渲染（SwiftShader），量出来的 CPU 高得离谱
   （实测 356% 单核），完全不反映用户实际体验。所以这里自己起浏览器，
   不加 --disable-gpu。
3. **对照组要真的停掉渲染**。把 PIXI 的 ticker 停掉再观察，差值才是净开销。

用法：
    python tools/measure_live2d_cost.py
"""
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

URL = "http://127.0.0.1:8770/"
OBSERVE_SEC = 15


def tree_cpu(profile_key: str) -> tuple[float, int, float]:
    """只量我们启动的那个实例（按 --user-data-dir 定位进程树）。"""
    script = Path(__file__).with_name("proc_tree_cpu.ps1")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-ProfileKey", profile_key],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=90, creationflags=0x08000000).stdout.strip()
        cpu_s, n, rss = out.split("|")
        return float(cpu_s), int(n), int(rss) / 1024 / 1024
    except Exception:
        return 0.0, 0, 0.0


def sample(label: str, profile_key: str, seconds: float) -> dict:
    c0, n, r0 = tree_cpu(profile_key)
    t0 = time.time()
    time.sleep(seconds)
    c1, _, r1 = tree_cpu(profile_key)
    dt = time.time() - t0
    return {"label": label, "sec": dt, "cpu_sec": max(0.0, c1 - c0),
            "cpu_pct": max(0.0, c1 - c0) / dt * 100.0, "procs": n,
            "rss_mb": (r0 + r1) / 2}


def main() -> int:
    try:
        urllib.request.urlopen(URL + "api/data", timeout=20).read()
    except Exception as e:
        print(f"  仪表盘没在跑（{e}）。先启动：python lib/server.py")
        return 1

    edge = find_edge()
    if not edge:
        print("  没找到 Edge")
        return 1
    port = free_port()
    profile = Path(tempfile.mkdtemp(prefix="cdp_perf_"))
    key = str(profile)
    # 关键：不加 --disable-gpu，让 WebGL 走真显卡
    proc = subprocess.Popen(
        [edge, "--headless=new", "--no-first-run", "--no-default-browser-check",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--window-size=1560,1100", URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        ws = None
        for _ in range(60):
            time.sleep(0.5)
            try:
                raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list",
                                             timeout=3).read()
                pages = [t for t in json.loads(raw)
                         if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                if pages:
                    ws = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
        if not ws:
            print("  连不上浏览器")
            return 1

        c = CDP(ws)
        c.call("Page.enable")
        c.call("Runtime.enable")
        time.sleep(9)                      # 等模型加载完

        info = c.eval_js("""(() => {
            const cv = document.getElementById('pet');
            const gl = cv && (cv.getContext('webgl2') || cv.getContext('webgl'));
            const dbg = gl && gl.getExtension('WEBGL_debug_renderer_info');
            const nav = performance.getEntriesByType('resource')
                .filter(e => /live2d|vendor/.test(e.name))
                .map(e => ({n: e.name.split('/').pop(),
                            kb: Math.round(e.transferSize/1024)}));
            const mem = performance.memory
                ? {heapMB: +(performance.memory.usedJSHeapSize/1048576).toFixed(1)} : null;
            return {
              tag: (document.getElementById('petTag')||{}).textContent,
              canvas: cv ? [cv.width, cv.height] : null,
              gpu: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
              nav, mem, totalKB: nav.reduce((a,b) => a + b.kb, 0),
            };
        })()""")

        print("  === 桌宠性能实测（WebGL 走真显卡）===")
        print(f"  桌宠状态：{info.get('tag')}｜画布 {info.get('canvas')}")
        print(f"  显卡：{info.get('gpu')}")
        print(f"  JS 堆：{info.get('mem')}")
        print(f"  首屏传输：{info.get('totalKB')} KB（含运行时；只下载一次，之后走缓存）")
        print()

        raf = c.eval_js("""new Promise(res => {
            const ts = []; let last = performance.now(), n = 0;
            function tick(t) {
                ts.push(t - last); last = t; n++;
                if (n < 120) requestAnimationFrame(tick);
                else { ts.sort((a,b)=>a-b);
                       res({median: +ts[Math.floor(n/2)].toFixed(2),
                            p95: +ts[Math.floor(n*0.95)].toFixed(2)}); }
            }
            requestAnimationFrame(tick);
        })""")
        print(f"  帧间隔：中位 {raf.get('median')} ms｜p95 {raf.get('p95')} ms"
              f"（60fps 预算 16.7ms）")
        print()
        print(f"  对照观察（各 {OBSERVE_SEC} 秒）…")

        on = sample("启用桌宠", key, OBSERVE_SEC)

        state = c.eval_js("""(() => {
            if (window.PIXI && PIXI.Ticker && PIXI.Ticker.shared) PIXI.Ticker.shared.stop();
            const cv = document.getElementById('pet');
            if (cv) cv.style.display = 'none';
            return 'rendering stopped';
        })()""")
        print(f"  已停用桌宠渲染：{state}")
        time.sleep(2)
        off = sample("停用桌宠", key, OBSERVE_SEC)

        print()
        print("  === 结果（只统计我们这个浏览器实例的进程树）===")
        for s in (on, off):
            print(f"  {s['label']}：CPU {s['cpu_sec']:6.2f} 秒 / {s['sec']:.0f} 秒"
                  f" = {s['cpu_pct']:5.1f}% 单核（多核合计）"
                  f"｜内存 {s['rss_mb']:6.0f} MB｜进程 {s['procs']} 个")
        d = on["cpu_pct"] - off["cpu_pct"]
        dm = on["rss_mb"] - off["rss_mb"]
        print()
        print(f"  桌宠净开销：CPU {d:+.1f} 个百分点｜内存 {dm:+.0f} MB")
        if off["cpu_pct"] > 1:
            print(f"               相对增幅 {d / off['cpu_pct'] * 100:+.0f}%")
        return 0
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
