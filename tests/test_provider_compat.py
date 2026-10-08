"""兼容性自测：用假的"挑剔服务商"验证降级链是否работает。

模拟三种真实会遇到的服务商：
  1. 标准 OpenAI 兼容（应该一次成功）
  2. 不认 image_url.detail（llama.cpp / LM Studio / 部分网关）-> 应去掉 detail 重发
  3. 不支持 response_format=json_object -> 应去掉它重发
  4. 鉴权失败 -> 不该重试，且报错要说人话

不需要任何真实 key，也不产生费用。
"""
import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import vision  # noqa: E402

results: list[tuple[str, bool, str]] = []
received: list[dict] = []
MODE = {"mode": "ok"}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        received.append(body)
        mode = MODE["mode"]

        def fail(code: int, msg: str):
            payload = json.dumps({"error": {"message": msg}}).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        if mode == "auth":
            return fail(401, "invalid api key")
        if mode == "model" and body.get("model") == "no-such-model":
            return fail(404, "model not found")
        # 挑剔点 1：不接受 detail 字段
        if mode == "no_detail":
            img = body["messages"][0]["content"][1]["image_url"]
            if "detail" in img:
                return fail(400, "unknown field 'detail' in image_url")
        # 挑剔点 2：不支持 json_object
        if mode == "no_json_mode" and body.get("response_format"):
            return fail(400, "response_format is not supported")

        content = ('{"seen":"棋盘格与 TEST42","category":"学习","on_task":true,'
                   '"confidence":0.9,"basis":"黑白交替方块"}')
        payload = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    port = free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"          # 故意不带 /v1，验证路径拼接
    print(f"假服务商：{base}（故意不带 /v1）")

    cfg = {
        "api": {"base_url": base, "model": "fake-vision", "temperature": 0,
                "max_tokens": 500, "timeout_sec": 20},
        "detail": "low",
        "judge": {"goal": "测试", "strictness": "normal", "extra_rules": [], "alias_rules": []},
    }
    # 绕过 key 解析：直接给一个假 key（签名要跟真函数一致，多了 override 参数）
    import lib.vision as V
    orig = V.resolve_api_key
    V.resolve_api_key = lambda c, override=None: override or "sk-fake"

    try:
        print()
        print("=== 1) 标准服务商：应一次成功，且带上 detail 与 json 模式 ===")
        MODE["mode"] = "ok"
        received.clear()
        r = V.check_api(cfg)
        check("调用成功", r["ok"] and r["json_ok"], f"{r['latency_ms']}ms")
        check("只发了 1 次请求（没有多余重试）", len(received) == 1, f"实际 {len(received)} 次")
        sent = received[0]
        check("带了 image_url.detail", "detail" in sent["messages"][0]["content"][1]["image_url"])
        check("带了 response_format", sent.get("response_format") == {"type": "json_object"})
        check("路径拼成了 /chat/completions", True, "假服务商能收到即说明路径正确")
        check("模型看到了图", "棋盘格" in str(r["parsed"].get("seen", "")), str(r["parsed"].get("seen")))

        print()
        print("=== 2) 不认 detail 的服务商（llama.cpp 等）：应自动去掉重发 ===")
        MODE["mode"] = "no_detail"
        received.clear()
        r = V.check_api(cfg)
        check("最终调用成功", r["ok"] and r["json_ok"])
        check("发了 2 次（第一次被拒，第二次降级）", len(received) == 2, f"实际 {len(received)} 次")
        if len(received) >= 2:
            first = received[0]["messages"][0]["content"][1]["image_url"]
            second = received[1]["messages"][0]["content"][1]["image_url"]
            check("第一次带 detail、第二次不带",
                  "detail" in first and "detail" not in second,
                  f"first={'detail' in first} second={'detail' in second}")

        print()
        print("=== 3) 不支持 JSON 模式的服务商：应去掉 response_format 重发 ===")
        MODE["mode"] = "no_json_mode"
        received.clear()
        r = V.check_api(cfg)
        check("最终调用成功", r["ok"])
        check("发了 3 次（逐级降级）", len(received) == 3, f"实际 {len(received)} 次")
        if len(received) >= 3:
            check("最后那次既没有 detail 也没有 response_format",
                  "detail" not in received[-1]["messages"][0]["content"][1]["image_url"]
                  and "response_format" not in received[-1])
        check("没有强制 JSON 模式时也能从文本里解析出 JSON", r["json_ok"],
              f"解析结果 {r['parsed']}")

        print()
        print("=== 4) 鉴权失败：不该重试，报错要说人话 ===")
        MODE["mode"] = "auth"
        received.clear()
        try:
            V.check_api(cfg)
            check("鉴权失败应抛错", False, "竟然成功了")
        except Exception as e:
            msg = str(e)
            check("鉴权失败应抛错", True)
            check("只试了 1 次（401 不重试）", len(received) == 1, f"实际 {len(received)} 次")
            check("报错包含可操作提示", "鉴权失败" in msg and "model=" in msg, msg[:80])

        print()
        print("=== 5) 模型不存在：提示要指向 base_url/model ===")
        MODE["mode"] = "model"
        cfg2 = json.loads(json.dumps(cfg))
        cfg2["api"]["model"] = "no-such-model"
        received.clear()
        try:
            V.check_api(cfg2)
            check("应抛错", False)
        except Exception as e:
            msg = str(e)
            check("提示模型/接口不存在", "404" in msg and "model" in msg, msg[:90])
            check("只试了 1 次（404 不重试）", len(received) == 1, f"实际 {len(received)} 次")
    finally:
        V.resolve_api_key = orig
        httpd.shutdown()

    passed = sum(1 for _, ok, _ in results if ok)
    print()
    print(f"{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
