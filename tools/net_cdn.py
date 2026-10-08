"""CDN 节点逐个测速：拿到多个备用地址，分别测吞吐，找出哪个节点快。

B 站网页播放器默认挑一个节点；如果它挑的那个恰好很慢，就会一直缓冲，
而你手动换成快的节点就正常——这种问题在校园网里很常见。
"""
import json
import sys
import time
import urllib.request

BV = sys.argv[1] if len(sys.argv) > 1 else "BV1U6T7zeEAA"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}


def get_json(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDRS), timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def measure(url: str, seconds: float = 6.0) -> tuple[float, float, float]:
    """返回 (首字节ms, 稳态MB/s, 下载MB)。"""
    req = urllib.request.Request(url, headers=HDRS)
    t0 = time.perf_counter()
    first = None
    total = 0
    samples = []
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            buf = bytearray(1 << 20)
            while True:
                n = resp.readinto(buf)
                now = time.perf_counter() - t0
                if n <= 0:
                    break
                if first is None:
                    first = now
                total += n
                samples.append((now, total))
                if now >= seconds:
                    break
    except Exception as e:
        return (-1.0, -1.0, 0.0)
    if len(samples) < 3:
        # 文件太小，用整体速度
        el = samples[-1][0] if samples else 1
        return ((first or 0) * 1000, total / el / 1024 / 1024 if el else 0, total / 1024 / 1024)

    # 稳态：中间 60% 窗口
    lo = samples[0][0] + (samples[-1][0] - samples[0][0]) * 0.2
    hi = samples[0][0] + (samples[-1][0] - samples[0][0]) * 0.8
    mid = [s for s in samples if lo <= s[0] <= hi] or samples
    dt = mid[-1][0] - mid[0][0]
    db = mid[-1][1] - mid[0][1]
    return ((first or 0) * 1000, (db / dt / 1024 / 1024) if dt > 0 else 0, total / 1024 / 1024)


def main() -> int:
    info = get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={BV}")
    cid = info["data"]["cid"]
    print(f"视频：{info['data']['title'][:40]}")

    # 不加 platform=html5，让它返回完整的备用节点列表（1080P，qn=80）
    play = get_json(f"https://api.bilibili.com/x/player/playurl?bvid={BV}&cid={cid}"
                    f"&qn=80&fnval=1&fourk=1")
    if play.get("code") != 0:
        print(f"playurl 失败：{play.get('message')}")
        return 1
    durl = play["data"]["durl"][0]
    urls = [durl["url"]] + list(durl.get("backup_url") or [])
    accept = play["data"].get("accept_quality")
    print(f"分片 {durl['size'] / 1024 / 1024:.1f} MB｜可选清晰度 {accept}")
    print(f"共 {len(urls)} 个节点：\n")

    results = []
    for i, u in enumerate(urls):
        host = u.split("/")[2]
        ttfb, speed, got = measure(u, seconds=6)
        results.append((host, ttfb, speed, got))
        flag = "失败" if speed < 0 else ""
        print(f"  [{i}] {host[:40]:<40} 首字节 {ttfb:7.0f} ms｜稳态 {speed:6.2f} MB/s｜"
              f"下了 {got:5.1f} MB {flag}")

    ok = [r for r in results if r[2] > 0]
    if ok:
        ok.sort(key=lambda r: -r[2])
        print()
        print(f"  最快节点：{ok[0][0]}  {ok[0][2]:.2f} MB/s")
        print(f"  最慢节点：{ok[-1][0]}  {ok[-1][2]:.2f} MB/s")
        if ok[0][2] > ok[-1][2] * 3:
            print("  => 节点之间差距超过 3 倍，说明播放器可能挑到了慢节点")
            print("     这种可以靠换 DNS（让解析落到别的节点）或手动换线缓解")
        else:
            print("  => 各节点速度接近，问题不在节点选择")
    return 0


if __name__ == "__main__":
    sys.exit(main())
