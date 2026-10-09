"""验证独立桌宠窗口里"计划 + 提醒"两条链路是否真的生效。

背景：仪表盘里的桌宠有 tests/test_pet_integration.py 守着，但**独立窗口
（web/pet.js）当时只验证了"能加载、缩放对"**，没测事件与倒计时。
这个测试补上那块，否则可能出现"仪表盘里会变、独立窗口里不变"。

做法：起一个带调试端口的桌宠窗口，然后
  1. 开一个计划 -> 看气泡是否出现倒计时
  2. 写一条提醒事件 -> 看表情与台词是否跟着变
  3. 确认反应期内不被常规状态覆盖

用法：python tests/test_pet_window_integration.py
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
sys.path.insert(0, str(ROOT))
from cdp_check import CDP, find_edge, free_port   # noqa: E402
from lib import pet_event                          # noqa: E402

BASE = "http://127.0.0.1:8770"
PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [通过] {name}" + (f" -> {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  [失败] {name}" + (f" -> {detail}" if detail else ""))


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=90).read())


def get(path: str) -> dict:
    return json.loads(urllib.request.urlopen(BASE + path, timeout=30).read())


PROBE = """(() => ({
  say: (document.getElementById('say')||{}).textContent,
  title: (document.querySelector('#bar .title')||{}).textContent,
  exprNow: (typeof exprNow !== 'undefined') ? exprNow : 'undef',
  planActive: (typeof plan !== 'undefined' && plan) ? !!plan.active : null,
}))()"""


def main() -> int:
    print("=== 独立桌宠窗口：计划与提醒集成 ===")
    try:
        get("/api/pet")
    except Exception as e:
        print(f"  服务没在跑（{e}）；先启动 lib/server.py")
        return 1

    pet_event.clear()
    edge = find_edge()
    cdp_port = free_port()
    prof = Path(tempfile.mkdtemp(prefix="sw_petwin_"))
    p = subprocess.Popen(
        [edge, f"--app={BASE}/pet?style=solid", f"--remote-debugging-port={cdp_port}",
         f"--user-data-dir={prof}", "--no-first-run", "--no-default-browser-check",
         "--window-size=380,480"],
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
            print("  连不上桌宠窗口")
            return 1
        c = CDP(ws)
        c.call("Page.enable")
        c.call("Runtime.enable")
        time.sleep(9)

        st = c.eval_js(PROBE)
        check("窗口加载出了角色（气泡有内容）", bool(str(st.get("say") or "").strip()),
              st.get("say"))
        check("表情已应用", bool(st.get("exprNow")), str(st.get("exprNow")))

        # --- 1. 计划：开一个，看气泡里有没有倒计时 ---
        r = post("/api/plan", {"action": "start", "preset": "pomodoro",
                               "focus_min": 25, "break_min": 5,
                               "start_monitor": False})
        print(f"  计划：{r.get('message')}")
        # 独立窗口 4 秒轮询一次
        time.sleep(7)
        st2 = c.eval_js(PROBE)
        say2 = str(st2.get("say") or "")
        check("气泡里出现计划倒计时", "专注中" in say2 and ":" in say2, say2)
        check("气泡里带轮次", "轮" in say2, say2)

        # --- 2. 提醒事件：写一条，看表情与台词 ---
        seq0 = (get("/api/pet-window") or {}).get("ok") and \
               (get("/api/pet").get("event") or {}).get("seq") or 0
        pet_event.emit("reminder", "gaming",
                       activity="正在玩 Steam 游戏", basis="全屏游戏画面")
        time.sleep(7)
        st3 = c.eval_js(PROBE)
        say3 = str(st3.get("say") or "")
        check("气泡换成提醒内容", "Steam" in say3, say3)
        check("标题栏换成场景名（不是内部键）",
              "游戏" in str(st3.get("title") or ""), st3.get("title"))
        check("表情跟着换了", st3.get("exprNow") != st2.get("exprNow"),
              f"{st2.get('exprNow')} -> {st3.get('exprNow')}")

        # --- 3. 反应期内不被常规状态覆盖 ---
        time.sleep(5)
        st4 = c.eval_js(PROBE)
        check("反应期内台词没被覆盖回倒计时",
              "Steam" in str(st4.get("say") or ""), st4.get("say"))

        # --- 4. 计划控制条：桌宠这边能直接操作计划 ---
        # 下面是这次新加的能力（以前桌宠只能看不能动）。
        #
        # 不用 Page.reload 来"重置"状态：reload 之后 CDP 的旧执行上下文失效，
        # eval_js 会读到空值，看起来就像"按钮没渲染"——实测被这个骗过一次。
        # 改成轮询等待：等气泡从"刚发生的事"回到倒计时，控制条自然就更新了。
        btns = []
        for _ in range(20):                 # 最多等 60 秒（气泡停 30 秒）
            btns = c.eval_js("""Array.from(document.querySelectorAll('#planbar button'))
                                  .map(b => b.textContent)""") or []
            if any("结束计划" in b for b in btns):
                break
            time.sleep(3)
        check("运行中显示「提前休息」与「结束计划」",
              any("休息" in b for b in btns) and any("结束计划" in b for b in btns),
              str(btns))
        info = c.eval_js("(document.querySelector('#planbar .pinfo')||{}).textContent")
        check("控制条右侧显示计划倒计时",
              bool(info) and ":" in str(info), str(info))

        # 点「结束计划」，计划应当真的停掉
        c.eval_js("""(() => {
            const b = Array.from(document.querySelectorAll('#planbar button'))
                .find(x => x.textContent.includes('结束计划'));
            if (b) b.click();
        })()""")
        time.sleep(6)
        pd = get("/api/pet").get("plan") or {}
        check("点「结束计划」后计划真的停了", not pd.get("active"),
              f"active={pd.get('active')}")
        btns2 = c.eval_js("""Array.from(document.querySelectorAll('#planbar button'))
                               .map(b => b.textContent)""")
        check("停止后按钮变回「开始专注」",
              any("开始专注" in b for b in (btns2 or [])), str(btns2))

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
        try:
            post("/api/plan", {"action": "stop"})
            pet_event.clear()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
