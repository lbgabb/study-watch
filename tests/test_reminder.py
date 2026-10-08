"""测试提醒窗外观（不发 API 请求、不写日志）。

跑起来后 12 秒内会自动关闭窗口；也可以用 --keep 让它一直显示。
因为窗口测试完就退出，属于临时脚本，测完可删。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import load_config
from lib.notify import Notifier

FAKE = {
    "activity": "在浏览器里刷 B 站首页推荐视频，标题是《3 分钟看懂动量矩守恒》，页面有弹幕和点赞按钮",
    "category": "娱乐",
    "on_task": False,
    "confidence": 0.9,
    "basis": "屏幕上出现竖排推荐流：一屏一个视频 + 右侧弹幕列表 + 点赞/投币按钮，标题党式短标题",
}


def main() -> int:
    cfg = load_config()
    cfg["reminder"]["sound"] = True
    cfg["reminder"]["auto_close_sec"] = 12
    n = Notifier(cfg)
    if n.window is None:
        print("提醒窗不可用，回退到系统通知")
    n.notify(FAKE, goal=cfg["judge"]["goal"])
    if "--keep" in sys.argv:
        while True:
            n.pump()
            time.sleep(0.2)
    deadline = time.time() + 12
    while time.time() < deadline:
        n.pump()
        time.sleep(0.1)
    n.destroy()
    print("提醒窗测试结束")
    return 0


if __name__ == "__main__":
    sys.exit(main())
