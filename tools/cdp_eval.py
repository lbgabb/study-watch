"""交互式调试：连上浏览器，执行几个表达式并打印结果。

用法：python tools/cdp_eval.py <URL> "<JS表达式>" ["<JS表达式>" ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp_check import CDP, launch  # noqa: E402


def main() -> int:
    url = sys.argv[1]
    exprs = sys.argv[2:]
    proc, profile, ws_url = launch(url)
    try:
        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        import time
        time.sleep(3)
        for e in exprs:
            try:
                v = cdp.eval_js(e)
                print(f"  {e}\n    => {json.dumps(v, ensure_ascii=False)[:400]}")
            except Exception as ex:
                print(f"  {e}\n    !! {ex}")
    finally:
        import shutil
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
