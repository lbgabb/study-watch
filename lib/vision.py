"""截屏 + 调用视觉模型（deepseek-flash）判断用户在做什么。"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import ImageGrab

from . import winapi
from .config import ROOT

CATEGORIES = ["学习", "工作", "娱乐", "社交", "游戏", "购物", "闲置", "其他"]

# deepseek-flash 参考价（美元 / 1M tokens）：高峰 输入0.30 输出1.20；低谷减半
PRICE_IN_PEAK = 0.30 / 1_000_000
PRICE_OUT_PEAK = 1.20 / 1_000_000

_RESPONSE_SCHEMA_HINT = (
    '{"activity":"一句话中文描述此刻在做什么",'
    '"category":"学习|工作|娱乐|社交|游戏|购物|闲置|其他",'
    '"on_task":true或false,'
    '"confidence":0到1的小数,'
    '"basis":"引用屏幕上实际看到的具体文字或界面元素作为依据"}'
)

_PREAMBLE = """你是"学习监督助手"的视觉判定模块。你会看到用户电脑屏幕的一张截图，以及当前前台窗口的程序名和标题。

你的任务：判断用户此刻是在学习，还是在分心做别的事。

用户设定的学习目标：{goal}

判定原则：
1. 以截图里实际显示的画面为准。窗口标题/程序名只是线索，可能与实际内容不符，不得仅凭标题下结论。
2. 学习包括：在看课程/讲座/公开课视频、看教材或论文 PDF、做网课题库或试卷、写代码或跑实验、背单词/学外语、整理笔记与作业。
3. 娱乐包括：刷短视频、看影视剧或动漫、看直播、玩游戏、看网络小说、听歌刷歌单、逛购物网站。
4. 特别注意"伪装成学习"的情况：只要是短视频/推荐流形态（一屏一视频、有点赞评论弹幕等互动元素、标题党式标题），即使内容看起来是知识科普，也算娱乐。
5. 社交包括即时通讯聊天、社交平台、论坛灌水。
6. 闲置包括锁屏、纯桌面、屏保，或屏幕上几乎没有变化、看不出正在使用电脑。
7. 只有截图证据不足以判断时，confidence 才给低值；证据明确时给高值。

严格只输出一个 JSON 对象，不要解释文字，不要 markdown 代码块，格式：
{schema}"""

_STRICTNESS = {
    "loose": "\n额外放宽：只要是在获取知识信息（含知识类视频、技术文章、科普内容），都可以算作学习。",
    "normal": "",
    "strict": "\n额外收紧：只有明确在做题、读教材、写代码、记笔记、上课这类强投入行为才算学习；被动看视频、浏览资讯、查资料都算分心。",
}


def local_secrets_path() -> Path:
    return ROOT / "data" / "secrets.json"


def read_local_secrets() -> dict:
    """data/secrets.json：面板里保存的凭据（gitignore 掉了，不随代码走）。"""
    p = local_secrets_path()
    if not p.is_file():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_local_secrets(data: dict) -> None:
    p = local_secrets_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def key_status(cfg: dict[str, Any]) -> dict[str, Any]:
    """当前 key 从哪来、长什么样（只回显掩码，绝不返回完整 key）。"""
    api = cfg["api"]
    env_name = api.get("api_key_env") or "DEEPSEEK_API_KEY"

    if os.environ.get(env_name):
        raw, source = os.environ[env_name].strip(), "环境变量"
    else:
        raw = read_local_secrets().get(env_name, "")
        source = "面板保存" if raw else ""
        if not raw:
            cred = Path(os.path.expanduser(api.get("credentials_file") or "")).resolve()
            if cred.is_file():
                text = cred.read_text(encoding="utf-8", errors="ignore")
                m = re.search(rf"^\s*{re.escape(env_name)}:\s*(\S+)\s*$", text, re.M)
                if m:
                    raw, source = m.group(1).strip(), f"{cred.name}"

    if not raw:
        return {"ok": False, "source": "", "masked": "", "env_name": env_name}
    masked = raw[:6] + "…" + raw[-4:] if len(raw) > 12 else raw[:3] + "…"
    return {"ok": True, "source": source, "masked": masked, "env_name": env_name}


def resolve_api_key(cfg: dict[str, Any], override: str | None = None) -> str:
    """依次尝试：显式传入 -> 环境变量 -> 面板保存的 secrets.json -> DSH 凭据文件。"""
    api = cfg["api"]
    env_name = api.get("api_key_env") or "DEEPSEEK_API_KEY"

    if override and override.strip():
        return override.strip()
    if os.environ.get(env_name):
        return os.environ[env_name].strip()

    saved = read_local_secrets().get(env_name, "")
    if saved.strip():
        return saved.strip()

    cred = Path(os.path.expanduser(api.get("credentials_file") or "")).resolve()
    if cred.is_file():
        text = cred.read_text(encoding="utf-8", errors="ignore")
        m = re.search(rf"^\s*{re.escape(env_name)}:\s*(\S+)\s*$", text, re.M)
        if m:
            return m.group(1).strip()

    raise RuntimeError(
        f"找不到 API key：可以在仪表盘「控制面板 → 设置 → API」里填写，"
        f"或设置环境变量 {env_name}，或在 {cred} 中写入 {env_name}: sk-xxxx"
    )


def _tiny_test_image() -> str:
    """内置一张小测试图（棋盘格），不截屏也能验证服务商是否支持视觉输入。"""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (256, 256), (250, 250, 250))
    d = ImageDraw.Draw(im)
    for y in range(0, 256, 32):
        for x in range(0, 256, 32):
            if (x // 32 + y // 32) % 2 == 0:
                d.rectangle([x, y, x + 31, y + 31], fill=(30, 40, 55))
    d.text((70, 118), "TEST 42", fill=(255, 90, 90))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def check_api(cfg: dict[str, Any], key_override: str | None = None) -> dict[str, Any]:
    """自检当前服务商/模型是否可用：发一张内置小图，问它看到了什么。

    用来在换服务商、换模型之后先确认配置对不对，不必浪费真实截图。
    key_override 用于"面板里刚填了 key、还没保存就想先测一下"的场景。
    """
    api = cfg["api"]
    base = api.get("base_url", "https://api.deepseek.com").rstrip("/")
    model = api.get("model", "deepseek-flash")
    key = resolve_api_key(cfg, override=key_override)

    prompt = ("这是一张测试图。请只输出 JSON："
              '{"seen":"一句话描述你看到的图案与文字","category":"学习","on_task":true,'
              '"confidence":0.9,"basis":"你依据哪些画面特征判断"}')
    shot = {"b64": _tiny_test_image(), "raw_size": (256, 256), "sent_size": (256, 256), "bytes": 0}

    t0 = time.time()
    content, usage, latency = _call_api(cfg, key, model, prompt, shot["b64"])
    try:
        data = _extract_json(content)
        parsed = True
    except Exception:
        data = {"raw": content[:200]}
        parsed = False

    return {
        "ok": True,
        "base_url": base,
        "model": model,
        "latency_ms": int(latency * 1000),
        "tokens_in": int(usage.get("prompt_tokens") or 0),
        "tokens_out": int(usage.get("completion_tokens") or 0),
        "json_ok": parsed,
        "parsed": data,
        "raw": content[:300],
    }


def build_prompt(cfg: dict[str, Any]) -> str:
    judge = cfg.get("judge", {})
    prompt = _PREAMBLE.format(goal=judge.get("goal", "学习"), schema=_RESPONSE_SCHEMA_HINT)
    prompt += _STRICTNESS.get(judge.get("strictness", "normal"), "")
    for rule in judge.get("extra_rules") or []:
        prompt += f"\n额外规则：{rule}"
    for alias in judge.get("alias_rules") or []:
        prompt += f"\n归类约定：{alias}"
    return prompt


def capture(cfg: dict[str, Any], save_dir: Path | None = None) -> dict[str, Any]:
    """截取整个虚拟桌面，缩放并编码为 JPEG base64。"""
    left, top, width, height = winapi.virtual_screen()
    if width <= 0 or height <= 0:  # 极端情况回退到主屏
        im = ImageGrab.grab()
        left = top = 0
    else:
        im = ImageGrab.grab(bbox=(left, top, left + width, top + height))

    raw_size = im.size
    max_width = int(cfg.get("max_width", 1600))
    if im.width > max_width:
        h = max(1, round(im.height * max_width / im.width))
        im = im.resize((max_width, h), 1)  # 1 = LANCZOS

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=int(cfg.get("jpeg_quality", 85)), optimize=True)
    data = buf.getvalue()

    shot_path = ""
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
        shot_path = str(save_dir / f"{datetime.now():%Y%m%d-%H%M%S}.jpg")
        Path(shot_path).write_bytes(data)

    return {
        "b64": base64.b64encode(data).decode(),
        "raw_size": raw_size,
        "sent_size": im.size,
        "bytes": len(data),
        "shot_path": shot_path,
    }


def _ends_with_comma(out: list[str]) -> bool:
    """忽略尾部空白，判断已输出内容是否以逗号结尾（用于避免补出重复逗号）。"""
    for chunk in reversed(out):
        for ch in reversed(chunk):
            if ch.isspace():
                continue
            return ch == ","
    return False


def _repair_json(text: str) -> str:
    """把模型写坏的 JSON 尽量修回可解析：漏转义的裸引号、缺失的逗号、光秃秃的字符串。

    用单一状态变量 expect 跟踪"下一个字符串应该是键名还是值"，遇到不合语法的引号就当内容替换。
    """
    stripped = text.strip()
    if stripped and stripped[0] not in "{[":
        # 模型直接把一句话当答案返回，包成对象好让上层继续走
        return json.dumps({"activity": stripped}, ensure_ascii=False)

    out: list[str] = []
    stack: list[str] = []          # 期待的闭合符
    in_string = False
    result = "value"               # 当前字符串的身份：key 或 value
    expect = "key"                 # 下一个字符串的身份：key 或 value
    last = ""                      # 上一个有意义的结构字符
    closed_value = False           # 刚刚闭合的是一个值（用于补漏逗号）
    i, n = 0, len(text)

    while i < n:
        ch = text[i]

        if in_string:
            if ch == "\\":
                out.append(text[i:i + 2])
                i += 2
                continue
            if ch == '"':
                # 预读下一个有意义的字符，判断这个引号能不能合法收尾
                j = i + 1
                while j < n and text[j] in " \t\r\n":
                    j += 1
                nxt = text[j] if j < n else ""
                legal = (nxt == ":") if result == "key" else (nxt in ",}]" or nxt == "")
                if legal:
                    out.append('"')
                    in_string = False
                    expect = "colon" if result == "key" else "comma"
                    closed_value = result == "value"
                else:
                    # 这个引号其实是内容里的裸引号
                    if nxt == '"' and result == "value":
                        # 形如 "值" "键": ... ——补上漏掉的逗号，再正常收尾
                        if not _ends_with_comma(out):
                            out.append(",")
                        out.append('"')
                        in_string = False
                        expect = "comma"
                        closed_value = True
                    else:
                        out.append("\u201d")   # 替换为右双引号，保持可读
                i += 1
                continue
            out.append(ch)
            i += 1
            continue

        # ---- 字符串外部 ----
        if ch == '"':
            if expect == "colon":
                out.append(":")                      # 键名后漏了冒号
            elif expect == "comma" and closed_value:
                out.append(",")                      # 值后漏了逗号（此时原文确实没有逗号）
            if stack and stack[-1] == "]":
                result = "value"                     # 数组里只可能是值
            elif expect == "value":
                result = "value"
            else:
                result = "key"                       # 对象里逗号之后是键名
            in_string = True
            closed_value = False
            out.append('"')
            i += 1
            continue

        if ch == "{":
            stack.append("}")
            expect = "key"
            closed_value = False
        elif ch == "[":
            stack.append("]")
            expect = "value"
            closed_value = False
        elif ch in "}]":
            if stack:
                stack.pop()
            if out and out[-1] == ",":
                out.pop()                            # 去掉闭合符前的多余逗号
            closed_value = False
        elif ch == ":":
            expect = "value"
            closed_value = False
        elif ch == ",":
            if out and out[-1] == ",":
                pass                                 # 连续逗号，丢掉一个
            else:
                out.append(ch)
            # 对象里逗号之后是键名，数组里逗号之后是值
            expect = "value" if (stack and stack[-1] == "]") else "key"
            closed_value = False
            if not ch.isspace():
                last = ch
            i += 1
            continue
        if not ch.isspace():
            last = ch
        out.append(ch)
        i += 1

    return "".join(out)


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        candidate = m.group(0) if m else text
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            data = json.loads(_repair_json(candidate))
    if not isinstance(data, dict):
        raise ValueError("模型返回的 JSON 不是对象")
    return data


def _post_json(url: str, api_key: str, body: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")[:500]
        raise _HttpError(e.code, detail) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络错误：{e.reason}") from None


class _HttpError(RuntimeError):
    def __init__(self, code: int, detail: str):
        super().__init__(f"HTTP {code}: {detail}")
        self.code = code
        self.detail = detail


def _friendly_http_error(e: _HttpError, base_url: str, model: str) -> str:
    """把服务商的报错翻译成能照着做的提示。"""
    d = (e.detail or "").lower()
    if e.code == 401 or e.code == 403:
        return (f"鉴权失败（HTTP {e.code}）：key 不对、没权限、或该模型未开通。\n"
                f"  当前 base_url={base_url}｜model={model}\n"
                f"  服务商原文：{e.detail[:200]}")
    if e.code == 404:
        return (f"接口或模型不存在（HTTP 404）：检查 base_url 是否需要 /v1，以及 model 名字。\n"
                f"  当前 base_url={base_url}｜model={model}\n"
                f"  服务商原文：{e.detail[:200]}")
    if e.code == 429:
        return f"被限流（HTTP 429）：降低判定频率或换 key。服务商原文：{e.detail[:200]}"
    if e.code == 400 and ("image" in d or "vision" in d or "modality" in d or "multimodal" in d):
        return (f"这个模型不接受图片输入（HTTP 400）：换一个支持视觉的模型。\n"
                f"  当前 model={model}\n  服务商原文：{e.detail[:200]}")
    return f"HTTP {e.code}: {e.detail[:300]}"


def _call_api(cfg: dict, api_key: str, model: str, user_text: str, b64: str) -> tuple[str, dict, float]:
    """发一次请求，返回 (正文, usage, 延迟秒)。

    为了兼容各家（也包括本地模型），这里做两级自动降级：
      1. 先带上 image_url.detail —— 多数云端服务商支持，可以省 token
      2. 被拒绝就去掉 detail 重发（llama.cpp / LM Studio / 部分网关不认这个字段）
      3. response_format 被拒绝也去掉重发（有些服务商不支持强制 JSON 模式）
    整个过程对上层透明，判定逻辑不用关心用的是谁。
    """
    api = cfg["api"]
    base = api.get("base_url", "https://api.deepseek.com").rstrip("/")
    url = base + "/chat/completions"
    timeout = api.get("timeout_sec", 90)

    def build(with_detail: bool, with_json_mode: bool) -> dict:
        image_url: dict[str, Any] = {"url": f"data:image/jpeg;base64,{b64}"}
        if with_detail and cfg.get("detail"):
            image_url["detail"] = cfg["detail"]
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": image_url},
            ]}],
            "temperature": api.get("temperature", 0),
            "max_tokens": api.get("max_tokens", 900),
        }
        if with_json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    started = time.time()
    attempts = [(True, True), (False, True), (False, False)]
    last_err: Exception | None = None
    payload = None
    for i, (with_detail, with_json) in enumerate(attempts):
        try:
            payload = _post_json(url, api_key, build(with_detail, with_json), timeout)
            break
        except _HttpError as e:
            last_err = e
            # 只在"参数不被支持"时降级重试；鉴权/限流/模型不存在重试没意义
            if e.code != 400 or i == len(attempts) - 1:
                raise RuntimeError(_friendly_http_error(e, base, model)) from None
            continue
    latency = time.time() - started
    if payload is None:
        raise RuntimeError(f"请求失败：{last_err}")

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"服务商返回结构异常（{type(e).__name__}）：{json.dumps(payload)[:300]}") from None

    if isinstance(content, list):
        # 有些网关把正文放在 content 数组里
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        raise RuntimeError(f"模型返回了非文本内容：{type(content).__name__}")
    return content, payload.get("usage") or {}, latency


def judge(cfg: dict[str, Any], api_key: str, shot: dict[str, Any], context: dict) -> dict[str, Any]:
    """把截图交给视觉模型判定，返回结构化 verdict。

    模型偶尔会吐出不合法 JSON（例如字符串里漏转义引号），这里做两级兜底：
    宽容解析 -> 带"严格 JSON"提示重发一次。
    """
    model = cfg["api"].get("model", "deepseek-flash")
    prompt = build_prompt(cfg)
    ctx_lines = [
        f"前台程序：{context.get('process') or '未知'}",
        f"窗口标题：{context.get('title') or '（无标题）'}",
    ]
    user_text = prompt + "\n\n--- 当前前台窗口信息（仅作线索）---\n" + "\n".join(ctx_lines)

    tin = tout = 0
    latency = 0.0
    attempts: list[str] = []

    for attempt in range(2):
        text, usage, dt = _call_api(cfg, api_key, model, user_text, shot["b64"])
        tin += int(usage.get("prompt_tokens") or 0)
        tout += int(usage.get("completion_tokens") or 0)
        latency += dt
        try:
            data = _extract_json(text)
            break
        except (json.JSONDecodeError, ValueError) as e:
            attempts.append(f"第 {attempt + 1} 次: {e}")
            if attempt == 1:
                raise RuntimeError("两次返回都不是合法 JSON → " + "；".join(attempts)) from None
            # 重发一次，并明确提醒必须转义引号
            user_text = (
                prompt
                + "\n\n--- 当前前台窗口信息（仅作线索）---\n" + "\n".join(ctx_lines)
                + "\n\n注意：上一次输出不是合法 JSON。这次请务必输出合法 JSON："
                  "字符串内部的引号必须写成 \\\"，不要换行，不要任何额外文字。"
            )

    cost = tin * PRICE_IN_PEAK + tout * PRICE_OUT_PEAK
    category = str(data.get("category") or "其他").strip()
    if category not in CATEGORIES:
        category = "其他"

    return {
        "activity": str(data.get("activity") or "").strip(),
        "category": category,
        "on_task": _as_bool(data.get("on_task")),
        "confidence": _as_float(data.get("confidence")),
        "basis": str(data.get("basis") or data.get("evidence") or "").strip(),
        "latency_ms": int(latency * 1000),
        "tokens_in": tin,
        "tokens_out": tout,
        "cost_usd": round(cost, 6),
        "model": model,
        "retried": len(attempts) > 0,
        "raw": text,
    }


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", "是", "对")
    if isinstance(v, (int, float)):
        return bool(v)
    return False


def _as_float(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))
