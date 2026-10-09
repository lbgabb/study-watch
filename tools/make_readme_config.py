"""用 lib/config.py 的真实默认值**生成** README 里的配置示例。

为什么不再手写：手写这个 jsonc 块我已经改坏三次（漏逗号、多逗号、缩进错位）。
按代码生成就同时解决两件事：语法一定正确、内容和 DEFAULTS 一定同步。

注释（每个字段一句说明）单独维护在下表里；代码里没注释的字段就不写注释。
生成后用"去注释再严格解析"验证，并且与 DEFAULTS 的键集比对。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lib.config import DEFAULTS       # noqa: E402

FENCE = "`" * 3

# 字段说明（中英各一份）。键是点分路径；不在表里的字段不加注释。
ZH = {
    "interval_sec": "判定间隔（秒）",
    "idle_skip_sec": "超过这么久没键鼠输入就跳过",
    "max_width": "截图缩放宽度，越小越省",
    "detail": '图片精度：low 更省，high 能看清小字',
    "capture": '见上文「截图策略」',
    "plan": "番茄钟默认值；在仪表盘里调过就记在这里",
    "plan.preset": "上次用的节奏",
    "plan.rounds": "0 = 不限轮数",
    "plan.remind_on_break": "休息时是否也提醒分心（默认关）",
    "plan.strict_break": "休息是否计入统计（默认关）",
    "plan.start_monitor": "点「开始专注」时是否连带启动监督",
    "pet": "Live2D 桌宠（住在仪表盘 / 独立窗口里）",
    "pet.enabled": "关掉后刷新页面即不再加载 3.9MB 模型与渲染库",
    "pet.max_fps": "帧率上限；呼吸眨眼在 20fps 下看不出差别",
    "pet.show_plan": "气泡里是否显示专注计划倒计时",
    "pet.speak": "是否把提醒内容说进气泡",
    "pet.pause_when_hidden": "标签页不可见时停掉渲染",
    "api": "走标准 OpenAI 兼容协议，任何支持图片输入的模型都行",
    "api.api_key_env": "去这个环境变量里找 key",
    "api.credentials_file": "没有环境变量时，从这个 yaml 里读",
    "judge": "判定标准",
    "judge.strictness": "loose 宽松 / normal / strict 严格",
    "judge.extra_rules": "额外规则，例如「看论文算学习」",
    "judge.alias_rules": "归类约定，例如把某程序固定算作学习",
    "reminder": "提醒方式",
    "reminder.mute_after_remind_sec": "提醒一次后安静多久",
    "reminder.off_task_streak_required": "改成 2 就是「连续 2 次分心才提醒」",
    "reminder.auto_close_sec": "提醒窗自动关闭（0 = 不自动关）",
    "privacy": "隐私开关",
    "privacy.save_shots": "true 会把截图存到 data/shots",
    "privacy.save_api_raw": "存模型原始回复，方便排查误判",
}

EN = {
    "interval_sec": "seconds between checks",
    "idle_skip_sec": "skip if there has been no input for this long",
    "max_width": "screenshot scale width; smaller is cheaper",
    "detail": "image detail: low is cheaper, high can read small text",
    "capture": 'see "Capture policy" above',
    "plan": "pomodoro defaults; remembered from the dashboard",
    "plan.preset": "last rhythm used",
    "plan.rounds": "0 = unlimited rounds",
    "plan.remind_on_break": "also remind during breaks (off by default)",
    "plan.strict_break": "count break time in stats (off by default)",
    "plan.start_monitor": 'also start monitoring when you press "start focus"',
    "pet": "the Live2D pet (lives in the dashboard / standalone window)",
    "pet.enabled": "off + refresh means the 3.9MB model and renderer are never loaded",
    "pet.max_fps": "frame cap; breathing and blinking look identical at 20fps",
    "pet.show_plan": "show the focus-plan countdown in the speech bubble",
    "pet.speak": "let her say the reminder in the bubble",
    "pet.pause_when_hidden": "stop rendering while the tab is not visible",
    "api": "standard OpenAI-compatible protocol; any vision-capable model works",
    "api.api_key_env": "environment variable to read the key from",
    "api.credentials_file": "fallback yaml when the env var is missing",
    "judge": "judging criteria",
    "judge.strictness": "loose / normal / strict",
    "judge.extra_rules": 'extra rules, e.g. "reading papers counts as studying"',
    "judge.alias_rules": "category aliases, e.g. pin an app to studying",
    "reminder": "how you get reminded",
    "reminder.mute_after_remind_sec": "quiet period after one reminder",
    "reminder.off_task_streak_required": 'set to 2 to require two consecutive misses',
    "reminder.auto_close_sec": "auto-close the popup (0 = never)",
    "privacy": "privacy switches",
    "privacy.save_shots": "true writes screenshots to data/shots",
    "privacy.save_api_raw": "keep raw model replies, useful for diagnosing misjudgements",
}

# 这些字段的值是"示例"，不适合原样搬（作者的凭据路径等）
OVERRIDE = {"api.credentials_file": "~/.study-watch/credentials.yaml"}


def dump(node, notes, path="", indent=1):
    """把 dict 渲染成带注释的 jsonc。缩进 2 空格一层。"""
    pad = "  " * indent
    lines = []
    items = list(node.items())
    for idx, (k, v) in enumerate(items):
        key = f"{path}{k}"
        last = idx == len(items) - 1
        comma = "" if last else ","
        note = notes.get(key)
        tail = f"  // {note}" if note else ""
        if isinstance(v, dict):
            lines.append(f'{pad}"{k}": {{{tail}')
            lines.extend(dump(v, notes, key + ".", indent + 1))
            lines.append(f"{pad}}}{comma}")
        else:
            val = OVERRIDE.get(key, v)
            lines.append(f"{pad}{json.dumps(k, ensure_ascii=False)}: "
                         f"{json.dumps(val, ensure_ascii=False)}{comma}{tail}")
    return lines


def build(notes) -> str:
    body = dump(DEFAULTS, notes)
    return "{\n" + "\n".join(body) + "\n}"


def replace_block(text: str, new_body: str) -> str:
    """替换"完整配置"那一段（含 capture 与 api 的那个块）。"""
    pat = re.compile(re.escape(FENCE) + r"jsonc\n(.*?)\n" + re.escape(FENCE), re.S)
    blocks = list(pat.finditer(text))
    target = None
    for m in blocks:
        if re.search(r'"(capture|api)"\s*:', m.group(1)) and len(m.group(1)) > 600:
            target = m
            break
    if target is None and blocks:
        target = blocks[-1]
    if target is None:
        return text
    return text[:target.start(1)] + new_body + text[target.end(1):]


def strip_comments(text: str) -> str:
    """去掉 jsonc 的注释，用于校验。

    注意：**不能用 `//[^\\n]*`** —— 它会把 URL 里的 `//` 也当注释，
    `"https://api.deepseek.com"` 会被截成 `"https:`，于是"校验失败"。
    实测被这个假失败绕了好几轮：错的不是文档，是校验方法。
    只把"行首或空白之后"的 `//` 当注释。
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)(^|\s)//(?!/)[^\n]*", r"\1", text)


for name, notes in (("README.zh-CN.md", ZH), ("README.md", EN)):
    p = ROOT / name
    body = build(notes)
    t = replace_block(p.read_text(encoding="utf-8"), body)
    p.write_text(t, encoding="utf-8")

    # 验证 1：去注释后严格解析
    s = strip_comments(body)
    try:
        parsed = json.loads(s)
        # 验证 2：键集与 DEFAULTS 完全一致
        def keys(d, pre=""):
            out = set()
            for k, v in d.items():
                out.add(pre + k)
                if isinstance(v, dict):
                    out |= keys(v, pre + k + ".")
            return out
        da, db = keys(parsed), keys(DEFAULTS)
        same = da == db
        print(f"  {name}: JSON 解析通过｜键集与 DEFAULTS "
              + ("完全一致 OK" if same else f"不一致！多 {da-db} 少 {db-da}"))
    except Exception as e:
        print(f"  {name}: 解析失败 -> {e}")
