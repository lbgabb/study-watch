"""提醒文案与配图映射：一处定义，界面、卡片、双语都由它驱动。

设计说明（为什么是这些语气）：

  · 分心类用"拆台/自嘲"的语气，不是命令式。被骂会让人关掉工具，
    被戳穿才会笑一下然后回去干活。
  · 正反馈类（回来啦、该休息、完成）跟分心类同等重要。只有吐槽没有夸奖，
    用两天就烦了。
  · 每句话都尽量指向"具体动作"（关掉、静音、去倒水），而不是空泛的
    "要努力"。人执行具体动作比执行态度容易。
  · 文案里不放 emoji：卡片用微软雅黑渲染，emoji 在不同机器上会变方块。

字段：
    file    素材文件名（assets/_reminder_src/ 下）
    tone    warn 分心 / good 鼓励 / praise 完成 / rest 休息 —— 决定标题配色
    meta    可选，卡片底部的小字
    zh/en   {"title": ..., "body": ...}
"""

CARDS: dict[str, dict] = {
    "general": {
        "file": "08-general.png",
        "tone": "warn",
        "zh": {"title": "哎呀呀，又在开小差呢",
               "body": "我只是个看屏幕的，可我都看出来了。关掉这个窗口，回去干正事。"},
        "en": {"title": "Caught you wandering",
               "body": "I only look at screens, and even I noticed. Close this and get back to it."},
        "meta": {"zh": "点「知道了」我不会再念；点「安静」我闭嘴一阵子",
                 "en": "Acknowledge to continue, or mute me for a while"},
    },
    "shortvideo": {
        "file": "07-shortvideo.png",
        "tone": "warn",
        "zh": {"title": "再刷一个就学习？",
               "body": "你上一个「再刷一个」是二十分钟前说的。这条也不会有尽头。"},
        "en": {"title": '"Just one more"?',
               "body": 'Your last "just one more" was twenty minutes ago. This feed has no end.'},
    },
    "gaming": {
        "file": "02-gaming.png",
        "tone": "warn",
        "zh": {"title": "这局不算，那下一局呢",
               "body": "存档不会跑，作业会。玩可以，但先跟自己说好什么时候停。"},
        "en": {"title": "One more round?",
               "body": "Your save file will wait. Your deadline will not."},
    },
    "social": {
        "file": "06-social.png",
        "tone": "warn",
        "zh": {"title": "回完这条就学习——真的吗",
               "body": "聊天框永远有人在说话。把它放一边，等休息时再一次性回。"},
        "en": {"title": "Replying to just one message?",
               "body": "There is always one more message. Put it aside and answer them all at the break."},
    },
    "sleepy": {
        "file": "01-sleepy.jpg",
        "tone": "rest",
        "zh": {"title": "困了就别硬撑",
               "body": "盯着屏幕发呆不算学习，也不算休息。起身走两步，或者干脆睡二十分钟。"},
        "en": {"title": "Tired is tired",
               "body": "Staring blankly is neither studying nor resting. Stand up, or take a 20-minute nap."},
    },
    "thumbsup": {
        "file": "03-thumbsup.png",
        "tone": "good",
        "zh": {"title": "这就对了",
               "body": "刚才还在别处，现在回来了。回来这件事本身比一直不跑神更现实。"},
        "en": {"title": "That's the way",
               "body": "You were elsewhere a minute ago and now you're back. Coming back matters more than never drifting."},
    },
    "relax": {
        "file": "04-relax.png",
        "tone": "rest",
        "zh": {"title": "这轮结束了，去休息",
               "body": "这一段的判定不计入统计，你安心离开屏幕。倒杯水，看看远处。"},
        "en": {"title": "Round done — go rest",
               "body": "Checks during the break don't count against you. Get some water, look out a window."},
    },
    "celebrate": {
        "file": "05-celebrate.png",
        "tone": "praise",
        "zh": {"title": "计划完成，干得漂亮",
               "body": "说好的轮数一轮没落。休息够了再来，或者今天就到这儿。"},
        "en": {"title": "Plan complete. Nice work.",
               "body": "Every round you planned, done. Rest up, or call it a day."},
    },
}

# 界面里给用户挑选 / 映射用的顺序
ORDER = ["general", "shortvideo", "gaming", "social", "sleepy",
         "thumbsup", "relax", "celebrate"]


def card_order() -> list[str]:
    return ORDER


# 判定类别 -> 配图。找不到就用 general。
CATEGORY_CARD = {
    "游戏": "gaming",
    "Gaming": "gaming",
    "社交": "social",
    "Social": "social",
    "闲置": "sleepy",
    "Idle": "sleepy",
}


def pick_card(category: str = "", *, returning: bool = False, phase: str = "",
              event: str = "", process: str = "", title: str = "") -> str:
    """决定这次该用哪张图与哪句文案。

    优先级（越靠前越具体）：
      1. event        计划完成 / 进入休息 这类明确事件
      2. returning    分心之后回到正轨
      3. 短视频特征    进程或标题命中短视频站点（比"娱乐"这个粗类别准得多）
      4. category     类别直接映射
      5. general      兜底
    """
    if event in ("plan_done",):
        return "celebrate"
    if event in ("break_start", "rest"):
        return "relax"
    if returning:
        return "thumbsup"
    if event in ("phase_focus", "resume"):
        return "thumbsup"

    blob = f"{process} {title}".lower()
    if any(k in blob for k in ("douyin", "tiktok", "kuaishou", "shorts", "reels",
                               "bilibili", "youtube", "抖音", "快手", "小红书")):
        return "shortvideo"

    return CATEGORY_CARD.get(category, "general")


def text_for(card_key: str, lang: str = "zh") -> dict:
    info = CARDS.get(card_key) or CARDS["general"]
    return info.get(lang) or info["zh"]
