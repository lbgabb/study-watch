"""配置接口自测：读写、校验、白名单、重启提示、key 保存。

安全要求：测试会真的改 config.json，所以先备份、跑完必须还原
（并且逐字节校验还原成功）。
"""
import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.config import CONFIG_PATH, ROOT  # noqa: E402

SECRETS = ROOT / "data" / "secrets.json"
results: list[tuple[str, bool, str]] = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(path: str, method: str = "GET", body: dict | None = None,
         base: str = "", timeout: int = 120) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'通过' if ok else '失败'}] {name}" + (f" -> {detail}" if detail else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    port = args.port or free_port()
    base = f"http://127.0.0.1:{port}"

    backup = CONFIG_PATH.with_suffix(".json.testbak")
    secrets_backup = SECRETS.read_bytes() if SECRETS.exists() else None
    shutil.copy2(CONFIG_PATH, backup)
    original_bytes = CONFIG_PATH.read_bytes()

    own = subprocess.Popen(
        [sys.executable, str(ROOT / "lib" / "server.py"), "--port", str(port), "--no-open"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
    )
    try:
        for _ in range(40):
            time.sleep(0.25)
            try:
                call("/api/config", base=base, timeout=5)
                break
            except Exception:
                continue

        print("=== 读取 ===")
        d = call("/api/config", base=base)
        check("能读出配置", "values" in d and len(d["values"]) > 20, f"{len(d['values'])} 项")
        check("key 只回显掩码", "…" in (d["key"].get("masked") or "")
              and "sk-3562" not in json.dumps(d), str(d["key"].get("masked")))
        check("给出配置文件路径", bool(d.get("config_path")))
        check("标出需重启生效的项", len(d.get("restart_keys") or {}) > 0)

        print()
        print("=== 写入合法值（应下一轮生效）===")
        before = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        r = call("/api/config", "POST", {"edits": {"interval_sec": 234, "reminder.sound": False}}, base=base)
        check("保存成功", r.get("ok") is True, r.get("message", ""))
        after = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        check("interval_sec 真的写进文件了", after["interval_sec"] == 234, str(after["interval_sec"]))
        check("reminder.sound 写进去了", after["reminder"]["sound"] is False)
        check("其他项没被动过", after["api"]["model"] == before["api"]["model"]
              and len(after["capture"]["rules"]) == len(before["capture"]["rules"]),
              f"规则数 {len(after['capture']['rules'])}")
        check("提示了生效时机", "生效" in (r.get("message") or ""), r.get("message", ""))

        print()
        print("=== 写入需要重启的项（应明确提示）===")
        r = call("/api/config", "POST", {"edits": {"api.model": "some-vision-model"}}, base=base)
        check("保存成功并提示需重启", r.get("ok") and r.get("need_restart"),
              f"{r.get('message', '')}｜need_restart={r.get('need_restart')}")

        print()
        print("=== 非法输入必须被拒绝且不落盘 ===")
        cases = [
            ("不在白名单的项", {"edits": {"__import__": "evil"}}),
            ("base_url 不是 URL", {"edits": {"api.base_url": "not-a-url"}}),
            ("detail 取值非法", {"edits": {"detail": "super"}}),
            ("strictness 取值非法", {"edits": {"judge.strictness": "very"}}),
            ("类型不对", {"edits": {"interval_sec": "abc"}}),
            ("布尔项传字符串", {"edits": {"reminder.sound": "yes"}}),
            ("空字符串", {"edits": {"api.model": "   "}}),
        ]
        for name, body in cases:
            r = call("/api/config", "POST", body, base=base)
            check(f"拒绝：{name}", r.get("ok") is False, (r.get("message") or "")[:60])

        now = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        check("被拒的输入没有污染配置",
              now["api"]["base_url"] == before["api"]["base_url"]
              and now["detail"] == before["detail"]
              and now["judge"]["strictness"] == before["judge"]["strictness"]
              and now["interval_sec"] == 234,   # 只有前面合法的改动留着
              f"base_url={now['api']['base_url']} detail={now['detail']}")

        print()
        print("=== 面板里填 key 并保存 ===")
        r = call("/api/config", "POST",
                 {"edits": {"api.api_key_env": "STUDY_WATCH_TEST_KEY"},
                  "api_key": "FAKE-KEY-NOT-REAL-0001"}, base=base)
        check("保存 key 成功", r.get("ok") and r.get("key_saved"), r.get("message", ""))
        check("secrets.json 里写进去了",
              SECRETS.exists() and "FAKE-KEY-NOT-REAL-0001" in SECRETS.read_text(encoding="utf-8"))
        d2 = call("/api/config", base=base)
        check("接口仍只回掩码", "FAKE-KEY-NOT-REAL-0001" not in json.dumps(d2),
              str(d2["key"].get("masked")))
        check("key 来源变成面板保存", d2["key"].get("source") == "面板保存", str(d2["key"]))

        print()
        print("=== 用面板里的值直接测连通（不落盘）===")
        # 指向本地假服务商，避免真花钱
        fake_port = free_port()
        fake = subprocess.Popen(
            [sys.executable, "-c", (
                "import json,threading;from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer\n"
                "class H(BaseHTTPRequestHandler):\n"
                "    protocol_version='HTTP/1.1'\n"
                "    def do_POST(self):\n"
                "        n=int(self.headers.get('Content-Length',0));self.rfile.read(n)\n"
                "        p=json.dumps({'choices':[{'message':{'content':"
                "'{\"seen\":\"测试通过\",\"category\":\"学习\",\"on_task\":true,\"confidence\":0.9,"
                "\"basis\":\"x\"}'}}],'usage':{'prompt_tokens':1,'completion_tokens':1}}).encode()\n"
                "        self.send_response(200);self.send_header('Content-Type','application/json')\n"
                "        self.send_header('Content-Length',str(len(p)));self.end_headers();self.wfile.write(p)\n"
                "    def log_message(self,*a):pass\n"
                f"ThreadingHTTPServer(('127.0.0.1',{fake_port}),H).serve_forever()"
            )],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000,
        )
        time.sleep(1.2)
        try:
            r = call("/api/check-api", "POST",
                     {"edits": {"api.base_url": f"http://127.0.0.1:{fake_port}",
                                "api.model": "fake"},
                      "api_key": "sk-whatever"}, base=base)
            check("能连通并给出结论", r.get("ok") is True, r.get("message", "")[:70])
            check("把模型看到的内容带回来了", "测试通过" in (r.get("seen") or ""), r.get("seen", ""))
        finally:
            fake.terminate()

        r = call("/api/check-api", "POST",
                 {"edits": {"api.base_url": "http://127.0.0.1:1"}, "api_key": "sk-x"}, base=base)
        check("连不通时给出失败原因", r.get("ok") is False, (r.get("message") or "")[:70])
    finally:
        own.terminate()
        try:
            own.wait(timeout=10)
        except subprocess.TimeoutExpired:
            own.kill()
        # 还原配置与 secrets
        shutil.copy2(backup, CONFIG_PATH)
        backup.unlink(missing_ok=True)
        if secrets_backup is None:
            SECRETS.unlink(missing_ok=True)
        else:
            SECRETS.write_bytes(secrets_backup)

    restored = CONFIG_PATH.read_bytes()
    check("测试结束后配置文件已逐字节还原", restored == original_bytes,
          f"{len(restored)} vs {len(original_bytes)} 字节")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 项通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
