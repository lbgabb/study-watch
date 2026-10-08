"""生成一份"看起来像真的"的演示数据，用于截图与文档。

为什么需要它：README 里的界面截图如果直接截真实数据，会把聊天记录、
浏览内容、工作轨迹一起公开出去。演示数据能保证图好看、内容可信，
同时**零隐私**。

数据是确定性生成的（固定种子），所以每次跑出来的图都一样，方便对比。

用法：python tools/make_demo_data.py            # 生成 3 天
      python tools/make_demo_data.py --days 7
      python tools/make_demo_data.py --clean    # 删掉演示数据
"""
import argparse
import json
import random
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import ROOT  # noqa: E402

LOGS = ROOT / "data" / "logs"
RAW = ROOT / "data" / "raw"
MARK = "demo"          # 演示记录的标记，便于一键清理

# 一条"学习日"的剧本：(开始时间, 持续分钟, 在状态?, 类别, 在做什么, 依据, 程序)
SCRIPT = [
    ("09:05", 42, True, "学习", "在 B 站观看《理论力学》期末复习课，画面正在推导动量守恒",
     "播放区是课程讲义，第 7 讲「动量守恒与碰撞」，右侧目录列到「刚体动力学」", "msedge.exe"),
    ("09:47", 18, True, "学习", "在 OneNote 里整理力学笔记，手写公式与例题步骤",
     "窗口标题「理论力学笔记 - OneNote」，正文可见动量定理与题号 3-12", "onenote.exe"),
    ("10:05", 26, False, "娱乐", "在 B 站首页刷推荐视频，一屏一个短视频并开着弹幕",
     "页面为推荐流形态，有弹幕与点赞投币；标题为娱乐类综艺剪辑", "msedge.exe"),
    ("10:31", 55, True, "学习", "在 VS Code 里写 Python 作业，正在调试报错",
     "编辑器中是 homework/kinematics.py，终端显示 AssertionError 与堆栈", "code.exe"),
    ("11:26", 12, False, "社交", "在微信里回复同学消息，聊周末安排",
     "前台为微信聊天窗口，左侧会话列表与右侧对话内容均为日常聊天", "wechat.exe"),
    ("11:38", 48, True, "学习", "在做线性代数习题，屏幕上是行列式计算的题目与草稿",
     "PDF 阅读器显示习题册第 42 页，旁边白板窗口有手写计算过程", "sumatrapdf.exe"),
    ("14:02", 35, True, "学习", "在 Anki 里背英语单词，卡片正在翻面显示例句",
     "卡片界面显示单词与例句，底部有 Again / Good 按钮与剩余数量", "anki.exe"),
    ("14:37", 40, True, "工作", "在写实验报告，Word 里正在排版公式与图表",
     "文档标题「大学物理实验报告 - 单摆测重力加速度」，含表格与坐标图", "winword.exe"),
    ("15:17", 22, False, "游戏", "打开了游戏启动器，正在等更新",
     "前台为游戏平台客户端，显示「正在下载更新 42%」，无学习相关内容", "steam.exe"),
    ("15:39", 50, True, "学习", "在 Coursera 上看机器学习课程，正在讲梯度下降",
     "视频页面标题为 Gradient Descent Intuition，字幕为英文字幕", "msedge.exe"),
    ("16:29", 15, True, "学习", "在题库网站做练习题，连续答对三题",
     "页面为在线题库，显示「第 12 / 20 题」与答题反馈", "msedge.exe"),
    ("16:44", 30, False, "娱乐", "在看动漫，画面为动画场景",
     "播放器为视频网站，内容为动画剧集，无课程或教材要素", "msedge.exe"),
    ("17:14", 45, True, "学习", "在复习化学笔记，屏幕上是反应方程式的整理",
     "笔记软件中列出化学方程式与配平过程，标题「无机化学 第三章」", "onenote.exe"),
    ("19:30", 38, True, "学习", "在写代码作业，实现二叉树遍历并跑通了测试",
     "编辑器中是 bst.py，终端显示 6 passed，右侧为测试用例列表", "code.exe"),
    ("20:08", 20, False, "购物", "在电商网站比价，浏览商品详情页",
     "页面为购物网站商品列表与详情，含价格与「加入购物车」按钮", "msedge.exe"),
    ("20:28", 52, True, "学习", "在听网课并同步做笔记，双屏一边视频一边记录",
     "左侧为课程视频，右侧为笔记窗口，内容对应本节课的公式推导", "msedge.exe"),
    ("21:20", 25, True, "学习", "在整理错题本，把今天的错题抄进表格",
     "表格文件标题「错题整理」，逐行记录题目来源与错因", "excel.exe"),
]

CAT_COST = {"学习": 0.0007, "工作": 0.0008, "娱乐": 0.0008,
            "社交": 0.0008, "游戏": 0.0009, "购物": 0.0009}

# 同一场景会连着产生好几条判定（每 3 分钟一条）。如果每条文案都一样，
# 截图里的分心列表会像复制粘贴，很假。给每条加一个随进度变化的细节。
PROGRESS_HINT = ["进行中", "还在继续", "持续中", "仍未切换", "保持在同一页面"]


def _variant(text: str, basis: str, k: int, n: int) -> tuple[str, str]:
    """给同一场景内的第 k 条（共 n 条）加一点变化。"""
    if n <= 1 or k == 0:
        return text, basis
    tag = PROGRESS_HINT[min(k - 1, len(PROGRESS_HINT) - 1)]
    return f"{text}（{tag}）", f"{basis}；与上一次判定画面一致"


def records_for(day: date, rng: random.Random) -> list[dict]:
    """把剧本摊成一条条判定记录（间隔约 3 分钟，与默认配置一致）。"""
    out: list[dict] = []
    for i, (hhmm, mins, on_task, cat, activity, basis, proc) in enumerate(SCRIPT):
        h, m = (int(x) for x in hhmm.split(":"))
        start = datetime.combine(day, dtime(h, m))
        n = max(1, int(mins / 3))               # 每 3 分钟一条
        for k in range(n):
            ts = start + timedelta(minutes=3 * k)
            if ts.date() != day:
                break
            # 末尾那条留一点"还没结束"的感觉：时长稍短
            sec = 180 if k < n - 1 else max(60, (mins % 3) * 60 or 150)
            act, bas = _variant(activity, basis, k, n)
            out.append({
                "status": "ok",
                "ts": ts.isoformat(timespec="seconds"),
                "sec": sec,
                "interval_sec": 180,
                "on_task": on_task,
                "category": cat,
                "activity": act,
                "basis": bas,
                "confidence": round(rng.uniform(0.78, 0.93), 2),
                "process": proc,
                "title": "",
                "tokens_in": rng.randint(430, 690),
                "tokens_out": rng.randint(280, 520),
                "cost_usd": CAT_COST.get(cat, 0.0008) + rng.uniform(-0.0002, 0.0003),
                "latency_ms": rng.randint(1900, 4200),
                "model": "deepseek-flash",
                "demo": True,
                "policy_reason": "全局间隔到期" if i else "首次判定",
            })
    return out


def pomodoro_demo(plan_rounds: int = 4) -> None:
    """顺手写一份"正在专注中"的计划，方便拍番茄钟的图。"""
    plan_path = ROOT / "data" / "plan.json"
    now = datetime.now()
    started = now - timedelta(minutes=7, seconds=22)      # 假装已经专注了 7 分多
    data = {
        "preset": "pomodoro", "phase": "focus", "round": 2, "target_rounds": plan_rounds,
        "focus_min": 25, "break_min": 5, "long_every": 4, "long_break_min": 20,
        "remind_on_break": False, "strict_break": False,
        "started_at": (now - timedelta(minutes=39)).timestamp(),
        "phase_started_at": started.timestamp(),
        "finished": False, "stop_reason": "", "note": "线性代数 · 第三章习题",
        "history": [
            {"phase": "focus", "round": 1,
             "started_at": (now - timedelta(minutes=72)).isoformat(timespec="seconds"),
             "ended_at": (now - timedelta(minutes=47)).isoformat(timespec="seconds"),
             "sec": 1500, "completed": True},
            {"phase": "break", "round": 1,
             "started_at": (now - timedelta(minutes=47)).isoformat(timespec="seconds"),
             "ended_at": (now - timedelta(minutes=42)).isoformat(timespec="seconds"),
             "sec": 300, "completed": True},
            {"phase": "focus", "round": 2,
             "started_at": (now - timedelta(minutes=42)).isoformat(timespec="seconds"),
             "ended_at": (now - timedelta(minutes=39)).isoformat(timespec="seconds"),
             "sec": 180, "completed": False},
        ],
    }
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  已写演示计划：专注第 2 轮（剩约 {25 - 7} 分钟）")


def clean() -> None:
    n = 0
    for p in sorted(LOGS.glob("*.jsonl")):
        keep = [l for l in p.read_text(encoding="utf-8").splitlines()
                if l.strip() and not _is_demo(l)]
        removed = 0
        lines = p.read_text(encoding="utf-8").splitlines()
        removed = len([l for l in lines if l.strip() and _is_demo(l)])
        if removed:
            n += removed
            if keep:
                p.write_text("\n".join(keep) + "\n", encoding="utf-8")
            else:
                p.unlink()
                print(f"  删除 {p.name}（整份都是演示数据）")
    for p in sorted(RAW.glob("*.json")):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("demo"):
                p.unlink()
                n += 1
        except (OSError, json.JSONDecodeError):
            pass
    plan = ROOT / "data" / "plan.json"
    if plan.is_file():
        plan.unlink()
    print(f"  已清理 {n} 条演示记录 + 演示计划")


def _is_demo(line: str) -> bool:
    try:
        return bool(json.loads(line).get("demo"))
    except json.JSONDecodeError:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--clean", action="store_true", help="删掉演示数据")
    ap.add_argument("--keep-real", action="store_true",
                    help="保留已有的真实记录（默认也会保留，只是提醒你别发截图）")
    ap.add_argument("--plan", action="store_true", help="同时写一份演示用的进行中计划")
    args = ap.parse_args()

    if args.clean:
        clean()
        return 0

    LOGS.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261009)          # 固定种子：每次生成一样的数据
    total = 0
    today = date.today()
    for i in range(args.days - 1, -1, -1):
        day = today - timedelta(days=i)
        recs = records_for(day, rng)
        path = LOGS / f"{day.isoformat()}.jsonl"
        existing = []
        if path.is_file():
            existing = [l for l in path.read_text(encoding="utf-8").splitlines()
                        if l.strip() and not _is_demo(l)]
        lines = existing + [json.dumps(r, ensure_ascii=False) for r in recs]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        total += len(recs)
        a = sum(1 for r in recs if r["on_task"])
        print(f"  {day}  写入 {len(recs):>3} 条（在状态 {a} 条，"
              f"{sum(r['sec'] for r in recs if r['on_task']) / 3600:.1f} 小时）")

    if args.plan:
        pomodoro_demo()

    print()
    print(f"共写入 {total} 条演示记录（标记 demo:true）")
    print("提醒：这些数据用来截图。截完图建议跑 --clean 清掉，")
    print("      否则仪表盘上的数字会混着演示数据，看着不像你自己的。")
    if not args.keep_real:
        print("      （真实记录没被动过，仍在同一批文件里）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
