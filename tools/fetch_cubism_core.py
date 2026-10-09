"""找一个能下载 Live2D Cubism Core 的源，并做多源重试。

Cubism Core 是渲染 Live2D 必需的专有运行时（Live2D Inc. 版权所有，
按 Cubism SDK 的 Redistributable Code 条款允许随作品分发）。
官方 CDN 在国内网络/沙箱里可能解析不了，所以这里按优先级挨个试。

**版本必须对上**（踩过一次）：
    模型是 .moc3  -> 需要 Cubism 3/4/5 的 Cubism Core（live2dcubismcore.min.js）
    模型是 .moc   -> 才是 Cubism 2.x 的 live2d.min.js
两者互不兼容。live2d.min.js 里只有 Live2DModelWebGL，喂 .moc3 会直接加载失败。
所以校验条件盯的是 CubismCore / moc3 这些 3.x+ 的特征串，而不是笼统的 "live2d"。
"""
import hashlib
import socket
import time
import urllib.request
from pathlib import Path

OUT = Path("E:/ds/_l2d_vendor")
OUT.mkdir(parents=True, exist_ok=True)
NAME = "live2dcubismcore.min.js"

SOURCES = [
    "https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js",
    "https://registry.npmmirror.com/live2dcubismcore/latest/files/live2dcubismcore.min.js",
    "https://registry.npmmirror.com/-/binary/live2dcubismcore/live2dcubismcore.min.js",
    "https://unpkg.com/live2dcubismcore@1.0.2/live2dcubismcore.min.js",
    "https://cdn.jsdelivr.net/npm/live2dcubismcore@1.0.2/live2dcubismcore.min.js",
    "https://fastly.jsdelivr.net/npm/live2dcubismcore@1.0.2/live2dcubismcore.min.js",
    "https://gcore.jsdelivr.net/npm/live2dcubismcore@1.0.2/live2dcubismcore.min.js",
]


def dns_ok(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def is_cubism_core(data: bytes) -> tuple[bool, str]:
    """判断是不是 Cubism 3/4/5 的 Core。返回 (是否符合, 说明)。

    注意：**不要用 "moc3" 当判据**。Cubism Core 4 是 WebAssembly 加载器，
    里面没有明文 "moc3" 字符串（踩过这个坑，把官方文件误判成错的）。
    真正的判据是 CubismCore + WebAssembly，以及"不是 2.x"。
    """
    if len(data) < 50_000:
        return False, f"只有 {len(data):,} 字节，太小"
    head = data[:200_000]
    if b"Live2DModelWebGL" in head:
        return False, "这是 Cubism 2.x 的 live2d.min.js，不能加载 .moc3"
    if b"CubismCore" not in head:
        return False, "没有 CubismCore 标识"
    if b"WebAssembly" not in head:
        return False, "没有 WebAssembly（Cubism 4 Core 应该有）"
    if b"Redistributable Code" not in head and b"Live2D Inc" not in head:
        return False, "没有 Live2D 许可头，来源可疑"
    return True, "Cubism Core（含官方许可头，WASM 版）"


def main() -> int:
    for url in SOURCES:
        host = url.split("/")[2]
        if not dns_ok(host):
            print(f"  跳过（解析不了域名）{host}")
            continue
        for attempt in range(1, 4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = urllib.request.urlopen(req, timeout=60).read()
                ok, why = is_cubism_core(data)
                if not ok:
                    print(f"  {host}：{why}（换源）")
                    break
                p = OUT / NAME
                p.write_bytes(data)
                print(f"  [成功] {url}")
                print(f"          {len(data):,} 字节｜sha256 {hashlib.sha256(data).hexdigest()[:16]}")
                print(f"          {why}")
                return 0
            except Exception as e:
                print(f"  {host} 第{attempt}次失败：{type(e).__name__}: {e}")
                time.sleep(2)
    print("  所有源都失败。Cubism Core 需要你手动下载后放到 assets/vendor/：")
    print("    官方地址：https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

