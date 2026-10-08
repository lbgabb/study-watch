"""解析健壮性自测：把模型可能吐出的畸形 JSON 全部覆盖一遍。

每项都做两件事：能解析出结果，且关键字段没错位。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.vision import _as_bool, _as_float, _extract_json, _repair_json

VALID = ('{"activity":"在看课程视频","category":"学习","on_task":true,'
         '"confidence":0.9,"basis":"屏幕上是课件"}')

# 本次真实故障形态：字符串内部有未转义的裸引号
UNESCAPED = ('{"activity":"在B站看《理论力学期末急救》讲解","category":"娱乐","on_task":false,'
             '"confidence":0.9,"basis":"导航"首页 番剧"与弹幕功能入口"}')

FENCED = "```json\n" + VALID + "\n```"
WITH_PROSE = "好的，判断如下：\n" + VALID + "\n希望有帮助。"

CASES = [
    # (名称, 输入, 期望能解析, 期望字段检查)
    ("标准 JSON", VALID, True, {"category": "学习", "on_task": True}),
    ("markdown 代码块", FENCED, True, {"category": "学习"}),
    ("前后夹带解释", WITH_PROSE, True, {"category": "学习"}),
    ("裸引号（真实故障）", UNESCAPED, True, {"category": "娱乐", "on_task": False}),
    ("嵌套对象", '{"activity":"x","meta":{"a":1},"on_task":true}', True, {"on_task": True}),
    ("数组值", '{"activity":"x","tags":["a","b"],"on_task":false}', True, {"on_task": False}),
    ("缺逗号", '{"activity":"x" "category":"学习"}', True, {"category": "学习"}),
    ("键值间裸引号", '{"activity":"看了"高数"第十八讲","category":"学习"}', True, {"category": "学习"}),
    ("已转义引号不应被破坏", '{"activity":"他说\\"好的\\"","category":"学习"}', True, {"category": "学习"}),
    ("尾部多余逗号", '{"activity":"x","category":"学习",}', True, {"category": "学习"}),
    ("纯文本兜底", "抱歉我无法判断", True, None),
    ("数组不是对象", "[1,2,3]", False, None),
]


def run() -> int:
    passed = failed = 0
    for name, raw, should_parse, expect in CASES:
        try:
            data = _extract_json(raw)
            ok, detail = True, str({k: data.get(k) for k in (expect or {})})
            if expect:
                for k, v in expect.items():
                    if data.get(k) != v:
                        ok, detail = False, f"{k}={data.get(k)!r} 期望 {v!r}"
        except Exception as e:
            ok, detail = False, f"{type(e).__name__}: {e}"

        if ok == should_parse:
            passed += 1
            print(f"[通过] {name}" + (f" -> {detail}" if expect else ""))
        else:
            failed += 1
            print(f"[失败] {name} -> {detail}")
            print(f"        修补结果：{_repair_json(raw)[:200]}")

    # 宽容解析
    coerced = (
        _as_bool("true") is True and _as_bool("否") is False
        and _as_bool(1) is True and _as_bool(0) is False
        and _as_float("0.75") == 0.75 and _as_float("abc") == 0.0
        and _as_float(3) == 1.0 and _as_float(-1) == 0.0
    )
    if coerced:
        passed += 1
        print("[通过] on_task / confidence 宽容解析")
    else:
        failed += 1
        print("[失败] on_task / confidence 宽容解析")

    print(f"\n{passed} 通过 / {failed} 失败")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
