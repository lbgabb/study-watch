"""检查当前能否拿到高清晰度：先看登录态，再列出可选清晰度。

未登录时 B 站网页版通常只给到 480P（qn=32），这既影响画质也可能让人误判"卡"。
"""
import json
import sys
import urllib.request

BV = sys.argv[1] if len(sys.argv) > 1 else "BV1U6T7zeEAA"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}

QN_NAME = {6: "240P", 16: "360P", 32: "480P", 64: "720P", 74: "720P60",
           80: "1080P", 112: "1080P+", 116: "1080P60", 120: "4K", 125: "HDR", 127: "8K"}


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    print("=== 登录态 ===")
    nav = get_json("https://api.bilibili.com/x/web-interface/nav")
    logged = nav.get("data", {}).get("isLogin")
    print(f"  isLogin = {logged}")
    if logged:
        d = nav["data"]
        print(f"  用户名 {d.get('uname')}｜大会员 {d.get('vipStatus') == 1}｜等级 {d.get('level_info', {}).get('current_level')}")
    else:
        print("  （匿名会话：网页版通常只给到 480P）")

    print()
    print("=== 该视频可选的清晰度（匿名会话）===")
    info = get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={BV}")
    cid = info["data"]["cid"]
    play = get_json(f"https://api.bilibili.com/x/player/playurl?bvid={BV}&cid={cid}"
                    f"&qn=120&fnval=1&fourk=1")
    data = play.get("data", {})
    accept = data.get("accept_quality") or []
    desc = data.get("accept_description") or []
    print(f"  accept_quality = {accept}")
    print(f"  含义 = {[QN_NAME.get(q, str(q)) for q in accept]}")
    print(f"  服务端描述 = {desc}")
    print(f"  本次返回清晰度 = {data.get('quality')}（{QN_NAME.get(data.get('quality'), '?')}）")
    if accept and max(accept) <= 32:
        print("  => 匿名会话只能到 480P。登录后一般可解锁 1080P（更高需要大会员）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
