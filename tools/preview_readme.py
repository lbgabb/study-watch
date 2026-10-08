"""用无头浏览器渲染 README 并截图，检查 Markdown 格式有没有问题。

为什么需要：Markdown 表格错位、代码块没闭合、锚点链接失效这类问题，
光看源码很难发现，渲染出来一眼就能看到。

用法：python tools/preview_readme.py [输出图片路径]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp_check import CDP, launch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "_readme.png"

    # 把 README 包成一个最简 HTML：样式贴近 GitHub，便于看排版
    md = (ROOT / "README.md").read_text(encoding="utf-8")
    # 做一层"够用"的 Markdown -> HTML 转换（只为本预览服务，不追求完备）
    import html
    import re

    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    lines = md.splitlines()
    body: list[str] = []
    in_code = False
    in_table = False
    for ln in lines:
        if ln.startswith("```"):
            if in_code:
                body.append("</pre>")
            else:
                body.append("<pre>")
            in_code = not in_code
            continue
        if in_code:
            body.append(html.escape(ln))
            continue
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells if c):
                continue                     # 分隔行
            if not in_table:
                body.append("<table>")
                in_table = True
            tag = "th" if not any("<table>" in b for b in body[:-1]) and len(body) and body[-1] == "<table>" else "td"
            body.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        elif in_table:
            body.append("</table>")
            in_table = False
        if ln.startswith("#"):
            lvl = len(ln) - len(ln.lstrip("#"))
            body.append(f"<h{lvl}>{inline(ln[lvl:].strip())}</h{lvl}>")
        elif ln.strip() in ("---", "***"):
            body.append("<hr>")
        elif ln.startswith("- ") or ln.startswith("* "):
            body.append(f"<li>{inline(ln[2:])}</li>")
        elif ln.strip() == "":
            body.append("")
        else:
            body.append(f"<p>{inline(ln)}</p>")
    if in_table:
        body.append("</table>")
    if in_code:
        body.append("</pre>")

    doc = f"""<!doctype html><meta charset="utf-8">
<style>
body{{background:#fff;color:#1f2328;font:16px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
     max-width:900px;margin:0 auto;padding:32px}}
h1{{font-size:2em;border-bottom:1px solid #d8dee4;padding-bottom:.3em}}
h2{{font-size:1.5em;border-bottom:1px solid #d8dee4;padding-bottom:.3em;margin-top:1.6em}}
h3{{font-size:1.2em;margin-top:1.4em}}
code{{background:#f6f8fa;padding:.2em .4em;border-radius:6px;font-size:85%;
      font-family:Consolas,monospace}}
pre{{background:#f6f8fa;padding:14px;border-radius:8px;overflow-x:auto;font-size:13px;white-space:pre-wrap}}
pre code{{background:none;padding:0}}
table{{border-collapse:collapse;margin:12px 0;display:block;overflow-x:auto;max-width:100%}}
th,td{{border:1px solid #d0d7de;padding:6px 13px;font-size:14px;text-align:left}}
th{{background:#f6f8fa}}
blockquote{{border-left:4px solid #d0d7de;color:#57606a;margin:0;padding:0 1em}}
hr{{border:none;border-top:1px solid #d8dee4;margin:24px 0}}
li{{margin:.25em 0}}
img{{max-width:100%}}
</style>
{chr(10).join(body)}
"""
    tmp = ROOT / "data" / "_readme_preview.html"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(doc, encoding="utf-8")

    proc, profile, ws_url = launch(tmp.as_uri())
    try:
        cdp = CDP(ws_url)
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        time.sleep(2.5)

        # 格式自检
        stats = cdp.eval_js("""(() => {
            const tables = document.querySelectorAll('table').length;
            const pres = document.querySelectorAll('pre').length;
            const hs = document.querySelectorAll('h1,h2,h3').length;
            // 表格列数是否一致（错位检查）
            let ragged = 0;
            document.querySelectorAll('table').forEach(t => {
                const counts = new Set(Array.from(t.rows).map(r => r.cells.length));
                if (counts.size > 1) ragged++;
            });
            // 代码块里是否还残留未闭合的 ``` （说明解析漏了）
            let strayFence = 0;
            document.querySelectorAll('pre').forEach(p => {
                if (p.textContent.indexOf('```') >= 0) strayFence++;
            });
            // 是否有内联的 ** 没被转成 <strong>
            const bodyText = document.body.innerText;
            const strayBold = (bodyText.match(/\\*\\*/g) || []).length;
            return {tables, pres, hs, ragged, strayFence, strayBold,
                    height: document.body.scrollHeight};
        })()""")

        ok = True
        def check(name, cond, detail=""):
            nonlocal ok
            if not cond:
                ok = False
            print(f"  [{'通过' if cond else '失败'}] {name}" + (f" -> {detail}" if detail else ""))

        print("=== README 渲染检查 ===")
        check("表格都渲染出来了", stats["tables"] >= 8, f"{stats['tables']} 个表格")
        check("表格列数一致（没写错 | 分隔）", stats["ragged"] == 0, f"{stats['ragged']} 个错位")
        check("代码块已闭合", stats["pres"] >= 8 and stats["strayFence"] == 0,
              f"{stats['pres']} 个代码块，{stats['strayFence']} 个残留 ```")
        check("加粗语法都转成了 strong（没有裸露的 **）",
              stats["strayBold"] == 0, f"{stats['strayBold']} 处残留")
        check("标题层级正常", stats["hs"] >= 15, f"{stats['hs']} 个标题")
        check("页面有内容", stats["height"] > 3000, f"高度 {stats['height']}px")

        # 全页截图（按内容高度设窗口）
        h = min(int(stats["height"]) + 60, 12000)
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": 1000, "height": h, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(1)
        n = cdp.screenshot(out)
        print(f"\n已截图：{out}（{n} 字节，{h}px 高）")
        print(f"预览用 HTML：{tmp}")
        return 0 if ok else 1
    finally:
        import shutil
        try:
            proc.terminate(); proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
