"""验证桌宠的三条集成路径：计划倒计时、提醒事件、开关。

为什么必须用真实浏览器测：
  桌宠是 Pixi + WebGL 渲染的，DOM 里只有一个 canvas，看不出对错。
  之前两个 bug 都是"DOM 看着正常但实际没生效"：
    · petSetExpr 表情没变时提前 return，把标签与台词更新一起跳过了
    · petReact 之后常规流程又跑一遍，把反应覆盖回默认值
  这类问题只有真的读回界面状态才会暴露。

用法：
    python tests/test_pet_integration.py
"""
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
from cdp_check import CDP, launch          # noqa: E402
from lib import pet_event                  # noqa: E402

URL = "http://127.0.0.1:8770/"
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
    req = urllib.request.Request(URL.rstrip("/") + path,
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=90).read())


def get(path: str) -> dict:
    return json.loads(urllib.request.urlopen(URL.rstrip("/") + path, timeout=30).read())


PROBE = """(() => ({
  tag: (document.getElementById('petTag')||{}).textContent,
  say: (document.getElementById('petSay')||{}).textContent,
  cardShown: (document.getElementById('petCard')||{}).style.display !== 'none',
  maxFPS: (window.PIXI && PIXI.Ticker.shared) ? PIXI.Ticker.shared.maxFPS : null,
  hasModel: (typeof petModel !== 'undefined') && !!petModel,
  failed: (typeof petFailed !== 'undefined') ? petFailed : null,
}))()"""


def main() -> int:
    print("=== 桌宠集成测试 ===")
    try:
        get("/api/data")
    except Exception as e:
        print(f"  仪表盘没在跑（{e}）")
        return 1

    # 起一个计划，倒计时那条路径才有东西可测
    pet_event.clear()
    r = post("/api/plan", {"action": "start", "preset": "pomodoro",
                           "focus_min": 25, "break_min": 5, "start_monitor": False})
    print(f"  计划：{r.get('message')}")

    proc, profile, ws = launch(URL)
    try:
        c = CDP(ws)
        c.call("Page.enable")
        c.call("Runtime.enable")
        time.sleep(10)

        st = c.eval_js(PROBE)
        check("桌宠卡片显示出来", bool(st.get("cardShown")))
        check("模型加载成功", bool(st.get("hasModel")),
              f"failed={st.get('failed')}")
        check("帧率上限已设到 ticker", st.get("maxFPS") == 20,
              f"maxFPS={st.get('maxFPS')}")
        # 集成点 1：专注计划倒计时出现在桌宠气泡里
        say = str(st.get("say") or "")
        check("气泡里显示专注计划倒计时",
              "专注中" in say and ":" in say, say)
        check("气泡里带轮次", "轮" in say, say)

        # 集成点 2：监控进程写提醒事件 -> 桌宠换表情 + 说话
        seq0 = (get("/api/data").get("pet") or {}).get("seq") or 0
        pet_event.emit("reminder", "gaming",
                       activity="正在玩 Steam 游戏", basis="全屏游戏画面")
        # 仪表盘 5 秒轮询一次，留足余量
        time.sleep(9)
        st2 = c.eval_js(PROBE)
        check("事件被桌宠接收（序号前进）",
              ((get("/api/data").get("pet") or {}).get("seq") or 0) > seq0)
        check("气泡换成提醒内容",
              "Steam" in str(st2.get("say") or ""), st2.get("say"))
        check("标签换成场景名（不是内部键）",
              str(st2.get("tag") or "").startswith("游戏"), st2.get("tag"))

        # 反应期内不被常规状态覆盖 —— 这是踩过的坑，专门守一条。
        # 注意窗口要落在提醒停留时间（30 秒）之内：等太久气泡本来就会
        # 过期并切回倒计时，那不是 bug 而是设计。
        time.sleep(5)
        st3 = c.eval_js(PROBE)
        check("反应期内台词没被覆盖回默认值",
              "Steam" in str(st3.get("say") or ""), st3.get("say"))

        # 集成点 3：开关关掉后不再渲染
        post("/api/config", {"edits": {"pet.enabled": False}})
        proc2, profile2, ws2 = launch(URL)
        try:
            c2 = CDP(ws2)
            c2.call("Page.enable")
            c2.call("Runtime.enable")
            time.sleep(8)
            st4 = c2.eval_js(PROBE)
            check("关掉桌宠后卡片收起", not st4.get("cardShown"))
            check("关掉桌宠后不加载模型", not st4.get("hasModel"))
        finally:
            try:
                proc2.terminate(); proc2.wait(timeout=10)
            except Exception:
                proc2.kill()
            shutil.rmtree(profile2, ignore_errors=True)
        post("/api/config", {"edits": {"pet.enabled": True}})

        print()
        print(f"  {PASS} 通过 / {FAIL} 失败")
        return 0 if FAIL == 0 else 1
    finally:
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
        try:
            post("/api/plan", {"action": "stop"})
            pet_event.clear()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
