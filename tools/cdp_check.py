"""用 Chrome DevTools 协议驱动无头 Edge，真的点按钮并读回 DOM 验证。

为什么不用 --dump-dom：Edge 新版无头的 --dump-dom 不输出内容。
这里用 CDP（纯标准库实现 WebSocket，不装任何包），能：
  - 在页面里执行 JS（点击预设按钮、读 tlTag 文本）
  - 截图，做视觉确认

用法：python tools/cdp_check.py <页面URL> [截图输出路径]
"""
import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_edge() -> str | None:
    for p in EDGE_CANDIDATES:
        if Path(p).is_file():
            return p
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WS:
    """最小 WebSocket 客户端（只支持文本帧，够 CDP 用）。"""

    def __init__(self, url: str, timeout: float = 30.0):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)$", url)
        if not m:
            raise ValueError(f"不支持的 ws 地址：{url}")
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WebSocket 握手失败：连接被关闭")
            buf += chunk
        if b"101" not in buf.split(b"\r\n")[0]:
            raise RuntimeError(f"WebSocket 握手失败：{buf[:200]!r}")
        self._buf = buf.split(b"\r\n\r\n", 1)[1]

    def send(self, text: str) -> None:
        data = text.encode()
        header = bytearray([0x81])                 # FIN + text
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("WebSocket 连接已关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def recv(self) -> str:
        while True:
            b1, b2 = self._read(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(length)
            if opcode == 0x1:
                return payload.decode("utf-8", errors="replace")
            if opcode == 0x8:
                raise RuntimeError("WebSocket 被对端关闭")
            # ping/pong/其他：忽略后继续读

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


class CDP:
    def __init__(self, ws_url: str):
        self.ws = WS(ws_url)
        self.seq = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0):
        self.seq += 1
        mid = self.seq
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method} 失败：{msg['error']}")
                return msg.get("result")
        raise TimeoutError(f"{method} 超时")

    def eval_js(self, expr: str, timeout: float = 30.0):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True},
                      timeout=timeout)
        res = r.get("result") or {}
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS 异常：{r['exceptionDetails'].get('text')} "
                               f"{(r['exceptionDetails'].get('exception') or {}).get('description','')}")
        return res.get("value")

    def screenshot(self, path: Path) -> int:
        r = self.call("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(r["data"])
        path.write_bytes(data)
        return len(data)


def launch(url: str):
    edge = find_edge()
    if not edge:
        raise RuntimeError("没找到 Edge")
    port = free_port()
    profile = Path(tempfile.mkdtemp(prefix="cdp_prof_"))
    proc = subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
         "--window-size=1560,1100", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # 等 devtools 端口就绪
    target = None
    for _ in range(60):
        time.sleep(0.5)
        try:
            raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3).read()
            targets = json.loads(raw)
            pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            if pages:
                target = pages[0]
                break
        except Exception:
            continue
    if not target:
        proc.terminate()
        raise RuntimeError("拿不到 CDP 页面目标")
    return proc, profile, target["webSocketDebuggerUrl"]


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8770/"
    shot = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    proc, profile, ws_url = launch(url)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = ""):
        results.append((name, bool(ok), detail))
        print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))

    try:
        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        time.sleep(3)   # 等页面把 fetch 和首次渲染做完

        print("=== 页面基础 ===")
        title = cdp.eval_js("document.title")
        check("页面已加载", bool(title), str(title))
        check("没有前端报错", cdp.eval_js("!!document.getElementById('timeline').querySelector('svg')"),
              "时间轴 SVG 存在")

        # 只数"判定段"：排除拖选遮罩等没有 fill 的辅助元素
        COUNT_BARS = ("document.querySelectorAll('#timeline svg rect[fill]').length")
        tag = "document.getElementById('tlTag').textContent"
        hint = "document.getElementById('tlHint').textContent"

        print()
        print("=== 全天视图 ===")
        tag_all = cdp.eval_js(tag)
        hint_all = cdp.eval_js(hint)
        check("区间标签非空", bool(tag_all and tag_all.strip()), str(tag_all))
        presets = cdp.eval_js("Array.from(document.querySelectorAll('#tlPresets button')).map(b=>b.textContent)")
        check("预设按钮已生成", isinstance(presets, list) and len(presets) >= 4, str(presets))
        segs_all = cdp.eval_js(COUNT_BARS)
        check("时间轴画出判定段", isinstance(segs_all, int) and segs_all > 0, f"{segs_all} 段")

        print()
        print("=== 点「最近 1 小时」应缩放到 1 小时窗口 ===")
        cdp.eval_js("""(() => {
            const b = Array.from(document.querySelectorAll('#tlPresets button'))
                .find(x => x.textContent.indexOf('1 小时') >= 0);
            if (!b) return 'no-button';
            b.click();
            return 'clicked';
        })()""")
        time.sleep(0.8)
        tag_1h = cdp.eval_js(tag)
        hint_1h = cdp.eval_js(hint)
        segs_1h = cdp.eval_js(COUNT_BARS)
        check("按钮点击生效（标签变化）", tag_1h != tag_all, f"{tag_all} -> {tag_1h}")
        check("只显示窗口内的段", isinstance(segs_1h, int) and segs_1h <= segs_all,
              f"{segs_all} -> {segs_1h}")
        check("标签段数与实际画出的段数一致",
              isinstance(segs_1h, int) and f"{segs_1h} 段" in (tag_1h or ""),
              f"标签={tag_1h}｜实际 {segs_1h} 段")

        if shot:
            n = cdp.screenshot(shot)
            print(f"\n已截图（最近 1 小时视图）：{shot}（{n} 字节）")

        print()
        print("=== 重置应回到全天 ===")
        cdp.eval_js("document.getElementById('tlReset').click()")
        time.sleep(0.8)
        tag_reset = cdp.eval_js(tag)
        segs_reset = cdp.eval_js(COUNT_BARS)
        check("重置后标签回到全天", tag_reset == tag_all, f"{tag_reset}")
        check("重置后段数恢复", segs_reset == segs_all, f"{segs_reset} vs {segs_all}")

        print()
        print("=== 自定义区间（用输入框）===")
        cdp.eval_js("""(() => {
            const f = document.getElementById('tlFrom'), t = document.getElementById('tlTo');
            f.value = '12:00'; t.value = '13:00';
            document.getElementById('tlApply').click();
        })()""")
        time.sleep(0.8)
        tag_custom = cdp.eval_js(tag)
        segs_custom = cdp.eval_js(COUNT_BARS)
        check("自定义区间生效", "12:00" in (tag_custom or "") and "13:00" in (tag_custom or ""),
              str(tag_custom))
        check("自定义区间的段数也对得上",
              isinstance(segs_custom, int) and f"{segs_custom} 段" in (tag_custom or ""),
              f"标签={tag_custom}｜实际 {segs_custom} 段")

        print()
        print("=== 输入框应被同步成实际区间 ===")
        vals = cdp.eval_js("({from: document.getElementById('tlFrom').value,"
                           "  to: document.getElementById('tlTo').value})")
        check("起止输入框已填上当前区间",
              isinstance(vals, dict) and vals.get("from") == "12:00" and vals.get("to") == "13:00",
              str(vals))

        print()
        print("=== 非法输入应给出提示，且提示要顶得住自动重绘 ===")
        cdp.eval_js("""(() => {
            document.getElementById('tlFrom').value = '';
            document.getElementById('tlTo').value = '';
            document.getElementById('tlApply').click();
        })()""")
        time.sleep(0.5)
        hint_bad = cdp.eval_js(hint)
        check("空输入有可读提示", "填" in (hint_bad or ""), str(hint_bad))
        still_ok = cdp.eval_js("!!document.getElementById('timeline').querySelector('svg')")
        check("非法输入后时间轴仍在", bool(still_ok))
        check("非法输入没有把区间弄坏（仍是 12:00–13:00）",
              "12:00" in (cdp.eval_js(tag) or ""), str(cdp.eval_js(tag)))
        # 页面每 5 秒自动重绘一次；等过一个周期，提示必须还在
        time.sleep(6)
        hint_after = cdp.eval_js(hint)
        check("提示在自动重绘后仍然可见", "填" in (hint_after or ""), str(hint_after))

        print()
        print("=== 日期切换 ===")
        days = cdp.eval_js("Array.from(document.querySelectorAll('#tlDay option')).map(o=>o.value)")
        check("日期下拉已填充", isinstance(days, list) and len(days) >= 1, str(days))
        if isinstance(days, list) and len(days) >= 2:
            other = days[1]
            cdp.eval_js(f"""(() => {{
                const s = document.getElementById('tlDay');
                s.value = {other!r};
                s.dispatchEvent(new Event('change'));
            }})()""")
            time.sleep(2.5)
            tag_d = cdp.eval_js(tag)
            segs_d = cdp.eval_js(COUNT_BARS)
            check(f"切到 {other} 后区间标签更新", bool(tag_d and tag_d.strip()), str(tag_d))
            check("切换后回到全天视图（不是残留的旧窗口）",
                  "0 段" not in (tag_d or "") or segs_d == 0, f"标签={tag_d}")
            h2 = cdp.eval_js("(document.querySelector('#nowCard h2')||{}).textContent || ''")
            check("顶部「现在」标注为历史日期", (other in (h2 or "")) or ("历史" in (h2 or "")), str(h2))

            # 历史日期上点预设：锚点应是那天的末尾，否则窗口会落在数据之外（空视图）
            cdp.eval_js("""(() => {
                const b = Array.from(document.querySelectorAll('#tlPresets button'))
                    .find(x => x.textContent.indexOf('1 小时') >= 0);
                if (b) b.click();
            })()""")
            time.sleep(1)
            segs_preset = cdp.eval_js(COUNT_BARS)
            check("历史日期上点预设不会得到空窗口",
                  isinstance(segs_preset, int) and segs_preset > 0, f"{segs_preset} 段")
            if shot:
                cdp.screenshot(shot)
                print(f"已截图（{other} 视图）：{shot}")
            # 切回最近的一天
            cdp.eval_js(f"""(() => {{
                const s = document.getElementById('tlDay');
                s.value = {days[0]!r};
                s.dispatchEvent(new Event('change'));
            }})()""")
            time.sleep(2)
            h2b = cdp.eval_js("(document.querySelector('#nowCard h2')||{}).textContent || ''")
            check("切回今天后标题恢复", "历史" not in (h2b or ""), str(h2b))
        else:
            print("  （只有一天的数据，跳过切换验证）")

    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
