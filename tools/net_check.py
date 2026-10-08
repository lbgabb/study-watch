"""真实网络诊断：取一条 B 站视频的播放地址，用 curl 实测吞吐，并对比不同清晰度/CDN。

只读取公开 API + 下载少量数据用于测速，不写入任何文件（curl 输出到 NUL）。
"""
import json
import re
import subprocess
import sys
import urllib.request

BV = sys.argv[1] if len(sys.argv) > 1 else "BV1U6T7zeEAA"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def curl_probe(url: str, label: str, seconds: int = 20, max_bytes: int = 40 * 1024 * 1024) -> dict:
    """用 curl 断点下载一段，读它的性能统计。"""
    fmt = ("HTTP %{http_code}|bytes %{size_download}|time %{time_total}|"
           "speed %{speed_download}|connect %{time_connect}|ttfb %{time_starttransfer}")
    cmd = [
        "curl.exe", "-s", "-o", "NUL", "-w", fmt,
        "--max-time", str(seconds), "--max-filesize", str(max_bytes),
        "-A", UA, "-e", "https://www.bilibili.com/", "-r", f"0-{max_bytes}", url,
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + 25).stdout.strip()
    d = {}
    for part in out.split("|"):
        if " " in part:
            k, v = part.split(" ", 1)
            d[k] = v
    try:
        speed = float(d.get("speed", 0)) / 1024 / 1024   # MB/s
    except ValueError:
        speed = 0.0
    try:
        mb = float(d.get("bytes", 0)) / 1024 / 1024
    except ValueError:
        mb = 0.0
    print(f"  {label:<28} HTTP {d.get('http')}｜下载 {mb:.1f} MB｜{d.get('time')}s｜"
          f"{speed:.2f} MB/s｜建连 {d.get('connect')}s｜首字节 {d.get('ttfb')}s")
    return {"speed_mbps": speed, "bytes": mb, "raw": d}


def main() -> int:
    print(f"=== 视频信息 {BV} ===")
    info = get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={BV}")
    if info.get("code") != 0:
        print(f"  接口返回 code={info.get('code')} msg={info.get('message')}")
        return 1
    data = info["data"]
    cid, aid = data["cid"], data["aid"]
    print(f"  {data['title']}")
    print(f"  时长 {data['duration'] // 60} 分 {data['duration'] % 60} 秒｜cid={cid} aid={aid}")
    print(f"  分P数 {len(data.get('pages', []))}｜UP {data['owner']['name']}")

    print()
    print("=== 取播放地址 ===")
    play = get_json(
        f"https://api.bilibili.com/x/player/playurl?bvid={BV}&cid={cid}&qn=32"
        f"&fnval=1&platform=html5&high_quality=1"
    )
    if play.get("code") != 0:
        print(f"  playurl 失败 code={play.get('code')} msg={play.get('message')}"
              f"（通常需要登录 cookie）")
        return 2
    durl = play["data"]["durl"][0]
    url = durl["url"]
    print(f"  清晰度 {play['data'].get('quality')}｜分片 {durl['size'] / 1024 / 1024:.1f} MB")
    m = re.search(r"https://([^/]+)/", url)
    print(f"  CDN 主机 {m.group(1) if m else '?'}")

    print()
    print("=== 实测下载（20 秒上限，最多 40MB）===")
    main_probe = curl_probe(url, "主播放地址")

    print()
    print("=== 备用 CDN 对比 ===")
    for i, u in enumerate(durl.get("backup_url") or [], 1):
        host = re.search(r"https://([^/]+)/", u)
        curl_probe(u, f"备用 {i} {host.group(1)[:24] if host else ''}", seconds=12,
                   max_bytes=20 * 1024 * 1024)

    print()
    print("=== 结论参考 ===")
    s = main_probe["speed_mbps"]
    if s >= 3:
        print(f"  当前下载 {s:.2f} MB/s，对 1080P（约 0.4-0.8 MB/s 码率）绰绰有余")
        print("  -> 卡缓冲多半不是带宽问题，往下查播放器/解码/单线程分片")
    elif s >= 0.8:
        print(f"  当前下载 {s:.2f} MB/s，勉强够 1080P，4K 会卡")
        print(f"  -> 带宽偏紧，也可能被其它程序占用（建议边播放边跑一次本脚本看抖动）")
    else:
        print(f"  当前下载只有 {s:.2f} MB/s，这就是卡缓冲的直接原因")
    return 0


if __name__ == "__main__":
    sys.exit(main())
