"""把 DS鲸鱼娘 Live2D 模型整理进仓库，并生成漫画3.json。

为什么要生成 model3.json：
  原包是 VTube Studio 用的，靠**文件名**加载动作与表情，model3.json 里
  既没有 Motions 也没有 Expressions。而 Web 端渲染器（pixi-live2d-display）
  按 model3.json 的声明加载，所以必须补上这两段——参考实现也做了这一步。

许可证（重要）：
  模型素材是 CC BY-NC-SA 4.0（非商业），代码是 MIT。两者分层声明，
  见仓库根的 NOTICE.md 与 PROVENANCE.md。本脚本只是格式转换，不改变许可。

用法：
    python tools/build_live2d_model.py --src "E:/ds/_l2d_model"
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "live2d"

# 动作组：组名 -> (文件名, FadeIn, FadeOut)
# 组名用英文，避免前端调用时写中文；idle 是必须的（不播动作时用）
MOTIONS = {
    "idle": [("motions/idle.motion3.json", 0.8, 0.8)],
    "bubble": [("motions/chuipaopao.motion3.json", 0.35, 0.5)],
    "splash": [("motions/喷水.motion3.json", 0.35, 0.5)],
    "selfie": [("motions/自拍.motion3.json", 0.35, 0.5)],
    "selfieQuick": [("motions/自拍简单.motion3.json", 0.35, 0.5)],
    "ketchup": [("motions/番茄酱.motion3.json", 0.35, 0.5)],
    "openLid": [("motions/开盖.motion3.json", 0.35, 0.5)],
    "aidale": [("aidale.motion3.json", 0.35, 0.5)],
}

# 只带我们真正会用到的表情，控制体积。键是前端用的英文 id，值是原文件名。
EXPRESSIONS = {
    "normal": None,                 # 无表情（复位）
    "star": "星星眼",               # 在状态 / 夸奖
    "heart": "爱心眼",              # 计划完成
    "excited": "开心兴奋",          # 番茄钟做完
    "tease": "调皮",                # 吐槽
    "tongue": "吐舌",               # 吐槽（更欠）
    "dizzy": "晕晕",                # 刷太久 / 发呆
    "sleepy": "闭眼口水",           # 犯困
    "cry": "哭",                    # 连续分心
    "sad": "悲伤",                  # 长时间跑神
    "angry": "生气",                # 屡教不改
    "sweat": "流汗",                # 刚回到正轨
    "question": "问号",             # 判定不确定
    "blank": "呆呆眼",              # 闲置
    "dark": "阴暗",                 # 深夜
    "blush": "脸红",                # 被夸
}

SKIP_NAMES = {"c_0120.model3.json", "icon.png", "c_0120.vtube.json",
              "items_pinned_to_model.json"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="解包后的模型目录")
    ap.add_argument("--clean", action="store_true", help="先清空目标目录")
    args = ap.parse_args()

    src = Path(args.src)
    if not (src / "c_0120.moc3").is_file():
        print(f"  找不到 c_0120.moc3（{src}）")
        return 1

    if args.clean and OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "motions").mkdir(parents=True, exist_ok=True)
    (OUT / "expressions").mkdir(parents=True, exist_ok=True)

    # 1) 核心文件
    copied = {"core": 0, "motions": 0, "expressions": 0}
    for name in ("c_0120.moc3", "c_0120.physics3.json", "c_0120.cdi3.json"):
        shutil.copy(src / name, OUT / name)
        copied["core"] += 1
    tex_src = src / "c_0120.2048"
    if tex_src.is_dir():
        shutil.copytree(tex_src, OUT / "c_0120.2048", dirs_exist_ok=True)
        copied["core"] += len(list(tex_src.glob("*.png")))

    # 2) 动作（文件重命名成英文，避免 URL 里出现中文）
    motion_refs: dict[str, list[dict]] = {}
    for group, items in MOTIONS.items():
        refs = []
        for rel, fin, fout in items:
            s = src / rel
            if not s.is_file():
                print(f"  跳过缺失的动作：{rel}")
                continue
            dst_name = f"{group}.motion3.json"
            shutil.copy(s, OUT / "motions" / dst_name)
            copied["motions"] += 1
            refs.append({"File": f"motions/{dst_name}",
                         "FadeInTime": fin, "FadeOutTime": fout})
        if refs:
            motion_refs[group] = refs

    # 3) 表情（同样重命名）
    expr_refs = []
    for eid, fname in EXPRESSIONS.items():
        if fname is None:
            continue
        s = src / f"{fname}.exp3.json"
        if not s.is_file():
            print(f"  跳过缺失的表情：{fname}")
            continue
        shutil.copy(s, OUT / "expressions" / f"{eid}.exp3.json")
        copied["expressions"] += 1
        expr_refs.append({"Name": eid, "File": f"expressions/{eid}.exp3.json"})

    # 4) 生成 model3.json
    model3 = {
        "Version": 3,
        "FileReferences": {
            "Moc": "c_0120.moc3",
            "Textures": ["c_0120.2048/texture_00.png",
                         "c_0120.2048/texture_01.png"],
            "Physics": "c_0120.physics3.json",
            "DisplayInfo": "c_0120.cdi3.json",
            "Motions": motion_refs,
            "Expressions": expr_refs,
        },
        "Groups": [
            {"Target": "Parameter", "Name": "EyeBlink",
             "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]},
            {"Target": "Parameter", "Name": "LipSync", "Ids": []},
        ],
        "HitAreas": [
            {"Id": "Head", "Name": "头"},
            {"Id": "Body", "Name": "身体"},
        ],
    }
    (OUT / "c_0120.model3.json").write_text(
        json.dumps(model3, ensure_ascii=False, indent=2), encoding="utf-8")

    # 5) 前端用的表情 id -> 语义 映射（与 lib/reminder_copy 的状态对齐）
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"  输出目录：{OUT}")
    print(f"    核心文件 {copied['core']} 个｜动作 {copied['motions']} 个"
          f"｜表情 {copied['expressions']} 个")
    print(f"    动作组：{list(motion_refs)}")
    print(f"    表情 id：{[e['Name'] for e in expr_refs]}")
    print(f"    合计体积：{size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
