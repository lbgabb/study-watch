"""反复跑自测直到复现偶发失败，把失败细节留档。

用来定位"大部分时候全绿、偶尔红一项"的问题——
这类问题如果不抓到具体是哪条断言，只靠看汇总永远查不出来。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "data" / "_flaky"
LOG_DIR.mkdir(parents=True, exist_ok=True)

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def main() -> int:
    failures = []
    for i in range(1, ROUNDS + 1):
        print(f"--- 第 {i}/{ROUNDS} 轮 ---", flush=True)
        p = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(ROOT / "selftest.ps1")],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=1800,
        )
        out = (p.stdout or "") + (p.stderr or "")
        failed_steps = re.findall(r"\[失败\]\s*(.+)", out)
        if failed_steps:
            print("  失败项: " + "；".join(failed_steps))
            log = LOG_DIR / f"round{i}.log"
            log.write_text(out, encoding="utf-8")
            for name in failed_steps:
                failures.append((i, name.strip(), log))
            # 把该轮里失败前后的上下文也打出来
            lines = out.splitlines()
            for idx, line in enumerate(lines):
                if "[失败]" in line:
                    print("    上下文:")
                    for ctx in lines[max(0, idx - 6):idx + 4]:
                        print("      " + ctx.rstrip())
        else:
            print("  全绿")

    print()
    print(f"{ROUNDS} 轮里失败 {len(failures)} 次")
    for rnd, name, log in failures:
        print(f"  第{rnd}轮：{name}  （完整日志 {log.name}）")
    if not failures:
        print("  未复现——说明偶发概率很低，或已被之前的加固消除")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
