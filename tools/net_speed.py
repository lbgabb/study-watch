"""更准的吞吐测试：固定抓一大段字节，算稳态速度；同时看 Wi-Fi 信号质量。

curl 的 speed_download 在小文件上会被首字节延迟严重稀释，所以这里自己计时、
从响应里连续读，并按"去掉前 1 秒"的稳态速度报数。
"""
import json
import subprocess
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


def sustained_speed(url: str, seconds: float = 15.0) -> dict:
    """连续下载 seconds 秒，返回首秒速度与稳态速度（去掉前 1 秒）。"""
    req = urllib.request.Request(url, headers=HDRS)
    t0 = time.perf_counter()
    first_byte_at = None
    samples = []      # (相对时间, 累计字节)
    total = 0
    with urllib.request.urlopen(req, timeout=30) as resp:
        buf = bytearray(1 << 20)
        while True:
            n = resp.readinto(buf)
            now = time.perf_counter() - t0
            if n <= 0:
                break
            if first_byte_at is None:
                first_byte_at = now
            total += n
            samples.append((now, total))
            if now >= seconds:
                break
    elapsed = time.perf_counter() - t0

    def speed_between(t_from: float, t_to: float) -> float:
        pts = [(t, b) for t, b in samples if t >= t_from]
        if len(pts) < 2:
            return 0.0
        pts = [p for p in pts if p[0] <= t_to] or pts
        dt = pts[-1][0] - pts[0][0]
        db = pts[-1][1] - pts[0][1]
        return (db / dt / 1024 / 1024) if dt > 0 else 0.0

    # 稳态：取中间 60% 的时间窗
    mid_from = elapsed * 0.2
    mid_to = elapsed * 0.8
    return {
        "total_mb": total / 1024 / 1024,
        "elapsed": elapsed,
        "ttfb": (first_byte_at or 0) * 1000,
        "avg_mbps": (total / elapsed / 1024 / 1024) if elapsed else 0,
        "steady_mbps": speed_between(mid_from, mid_to),
    }


def wifi_info() -> list[str]:
    out = []
    try:
        r = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=0x08000000)
        for line in (r.stdout or "").splitlines():
            s = line.strip()
            for key in ("信号", "接收速率", "传输速率", "信道", "无线电类型", "SSID", "Signal",
                        "Receive rate", "Transmit rate", "Channel", "Radio type"):
                if s.startswith(key):
                    out.append("  " + s)
    except Exception as e:
        out.append(f"  读取失败：{e}")
    return out


def main() -> int:
    print("=== Wi-Fi 链路状态 ===")
    for line in wifi_info():
        print(line)

    print()
    print("=== 取播放地址 ===")
    info = get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={BV}")
    if info.get("code") != 0:
        print(f"  失败：{info.get('message')}")
        return 1
    cid = info["data"]["cid"]
    play = get_json(f"https://api.bilibili.com/x/player/playurl?bvid={BV}&cid={cid}"
                    f"&qn=32&fnval=1&platform=html5&high_quality=1")
    durl = play["data"]["durl"][0]
    urls = [durl["url"]] + list(durl.get("backup_url") or [])
    print(f"  共 {len(urls)} 个地址（1 主 + {len(urls) - 1} 备）")

    print()
    print("=== 连续下载 15 秒测稳态速度 ===")
    best = 0.0
    for i, u in enumerate(urls):
        host = u.split("/")[2]
        try:
            st = sustained_speed(u, seconds=15)
        except Exception as e:
            print(f"  [{i}] {host[:34]:<34} 失败：{type(e).__name__}: {e}")
            continue
        tag = "主" if i == 0 else f"备{i}"
        print(f"  [{tag}] {host[:34]:<34} 下了 {st['total_mb']:6.1f} MB / {st['elapsed']:.1f}s｜"
              f"首字节 {st['ttfb']:6.0f} ms｜平均 {st['avg_mbps']:5.2f} MB/s｜"
              f"稳态 {st['steady_mbps']:5.2f} MB/s")
        best = max(best, st["steady_mbps"])

    print()
    print("=== 判读 ===")
    print(f"  本次测到的最好稳态速度：{best:.2f} MB/s")
    need = {"480P": 0.15, "1080P": 0.5, "1080P高码率": 1.0, "4K": 2.5}
    for name, mb in need.items():
        print(f"    {name:<12} 约需 {mb:>4.2f} MB/s  -> {'够' if best >= mb * 1.5 else '偏紧' if best >= mb else '不够'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
